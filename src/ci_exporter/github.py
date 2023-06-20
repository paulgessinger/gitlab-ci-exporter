import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
from pathlib import Path
import tempfile

from prometheus_client import (
    CollectorRegistry,
    generate_latest,
    start_http_server,
    Gauge,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiohttp
from gidgethub.aiohttp import GitHubAPI
import asyncstdlib
import typer
import more_itertools
import peewee

from .update import Updater
from .db import Job, prepare_database, Status


class GithubUpdater(Updater):
    def __init__(self, token: str):
        self.registry = CollectorRegistry()
        self._token = token

        self.job_count = Gauge(
            name="github_ci_job_count",
            documentation="The total number of jobs running for various categories",
            labelnames=["status", "job_name"],
            registry=self.registry,
        )

        self.job_latency = Gauge(
            name="github_ci_job_latency",
            documentation="Time of most recent finished job spent in queue",
            registry=self.registry,
        )

    @staticmethod
    def _map_status_conclusion(status:str, conclusion:str)-> Status:
        if status == "queued":
            return Status.pending
        elif status == "in_progress":
            return Status.running
        elif status == "completed":
            if conclusion == "success":
                return Status.success
            elif conclusion == "failure":
                return Status.failed
            elif conclusion == "cancelled":
                return Status.canceled
            elif conclusion == "skipped":
                return Status.skipped
            else:
                raise ValueError(f"Invalid conclusion {conclusion}")
        else:
            raise ValueError(f"Invalid status {status}")


    async def tick(self, projects: List[str]):
        async with aiohttp.ClientSession() as session:
            gh = GitHubAPI(session, requester="ci_exporter", oauth_token=self._token)
            since = datetime.now() - timedelta(hours=3)
            for project in projects:
                runs = gh.getiter(
                    f"/repos/{project}/actions/runs?created=:>{since.strftime('%Y-%m-%dT%H:%M:%S')}",
                    iterable_key="workflow_runs",
                )


                runs = [r async for r in runs]
                async def get_jobs(url):
                    return [j async for j in gh.getiter(url, iterable_key="jobs")]


                for outer_chunk in more_itertools.chunked(runs, 100):
                    batch = []
                    for chunk in more_itertools.chunked(outer_chunk, 10):
                        chunk_jobs = await asyncio.gather(*[get_jobs(r["jobs_url"]) for r in chunk])

                        datefmt = "%Y-%m-%dT%H:%M:%SZ"
                        parse = lambda d: datetime.strptime(d, datefmt) if d is not None else None
                        for run, jobs in zip(chunk, chunk_jobs):
                            for job in jobs:
                                batch.append({
                                    "id": job["id"],
                                    "project": project,
                                    "commit_sha": job["head_sha"],
                                    "name": f"{run['name']} / {job['name']}",
                                    "ref": run["head_branch"],
                                    "status": self._map_status_conclusion(job["status"], job["conclusion"]).name,
                                    "created_at": parse(job["created_at"]),
                                    "started_at": parse(job["started_at"]),
                                    "finished_at": parse(job["completed_at"]),
                                })
                    Job.insert_many(batch).on_conflict_replace().execute()

            self.job_count.clear()
            for job in Job.select(
                peewee.fn.COUNT().alias("count"), Job.name, Job.status
            ).group_by(Job.name, Job.status):
                self.job_count.labels(status=job.status, job_name=job.name).inc(
                    job.count
                )

            latest = (
                Job.select()
                .where(Job.finished_at is not None)
                .order_by(Job.finished_at.desc())
                .get()
            )
            if latest is not None:
                queued_duration = latest.started_at - latest.created_at
                self.job_latency.set(queued_duration.total_seconds())


cli = typer.Typer()


@cli.command()
def serve(
    token: str = typer.Option(..., envvar="GHE_TOKEN"),
    projects: List[str] = typer.Option(..., envvar="GHE_PROJECTS"),
    interval: int = typer.Option(30, envvar="GHE_INTERVAL"),
    port: int = typer.Option(8000, envvar="PORT"),
):
    with tempfile.NamedTemporaryFile() as t:
        prepare_database(Path(t.name))
        updater = GithubUpdater(token=token)
        start_http_server(port, registry=updater.registry)

        scheduler = AsyncIOScheduler()

        scheduler.add_job(
            updater.tick, "interval", seconds=interval, kwargs={"projects": projects}
        ).modify(next_run_time=datetime.now())

        try:
            print("Starting scheduler")
            scheduler.start()
            asyncio.get_event_loop().run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass


@cli.command()
def tick(
    token: str = typer.Option(..., envvar="GHE_TOKEN"),
    projects: List[str] = typer.Option(..., envvar="GHE_PROJECTS"),
    dbfile: Optional[Path] = None,
):
    context = tempfile.NamedTemporaryFile if dbfile is None else contextlib.nullcontext

    with context() as t:
        assert t is not None or dbfile is not None
        prepare_database(dbfile or Path(t.name))
        updater = GithubUpdater(token=token)
        asyncio.run(updater.tick(projects))

    print(generate_latest(updater.registry).decode())
