import asyncio
from datetime import datetime
from typing import Optional, List
import tempfile
import contextlib
from pathlib import Path

from gidgetlab.aiohttp import GitLabAPI
import aiohttp
import peewee
from prometheus_client import (
    CollectorRegistry,
    generate_latest,
    start_http_server,
    Gauge,
    Histogram,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import typer
import asyncstdlib

from . import LATENCY_BUCKETS
from .db import Job, prepare_database
from .update import Updater


class GitlabUpdater(Updater):
    def __init__(self, host: str, token: str):
        self._host = host
        self._token = token
        self.registry = CollectorRegistry()

        self.job_count = Gauge(
            name="gitlab_ci_job_count",
            documentation="The total number of jobs running for various categories",
            labelnames=["status", "job_name"],
            registry=self.registry,
        )

        self.job_latency = Histogram(
            name="gitlab_ci_job_latency",
            documentation="Time of most recent finished job spent in queue",
            registry=self.registry,
            buckets=LATENCY_BUCKETS,
        )

    def _adapt(self, jobs, project):
        for i, job in enumerate(jobs):
            row = {"commit_sha": job["commit"]["id"], "project": project}

            for k in [
                "id",
                "name",
                "ref",
                "status",
                "queued_duration",
            ]:
                row[k] = job[k]

            for k in [
                "created_at",
                "started_at",
                "finished_at",
            ]:
                if job[k] is None:
                    row[k] = None
                    continue
                row[k] = datetime.fromisoformat(job[k]).replace(tzinfo=None)

            yield row

    async def tick(self, projects: List[str]):
        async with aiohttp.ClientSession() as session:
            gl = GitLabAPI(
                session,
                url=self._host,
                requester="ci_exporter",
                access_token=self._token,
            )

            # get jobs we did not have queued duration for
            queued = [
                q.id
                for q in Job.select(Job.id)
                .where(Job.queued_duration.is_null())
                .execute()
            ]

            for project in projects:
                jobs = gl.getiter(
                    f"/projects/{project.replace('/', '%2F')}/jobs?per_page=250&order_by=id&sort=desc"
                )

                g = self._adapt(
                    [j async for _, j in asyncstdlib.zip(range(1000), jobs)], project
                )
                Job.insert_many(g).on_conflict_replace().execute()

            # update latency
            queued_updated = list(
                Job.select(Job.queued_duration)
                .where(
                    Job.id.in_(queued),
                )
                .execute()
            )

            for j in queued_updated:
                if j.queued_duration is None:
                    continue
                self.job_latency.observe(j.queued_duration)

            self.job_count.clear()
            for job in Job.select(
                peewee.fn.COUNT().alias("count"), Job.name, Job.status
            ).group_by(Job.name, Job.status):
                self.job_count.labels(status=job.status, job_name=job.name).inc(
                    job.count
                )


cli = typer.Typer()


@cli.command()
def serve(
    host: str = typer.Option(..., envvar="GLE_HOST"),
    token: str = typer.Option(..., envvar="GLE_TOKEN"),
    projects: List[str] = typer.Option(..., envvar="GLE_PROJECTS"),
    interval: int = typer.Option(30, envvar="GLE_INTERVAL"),
    port: int = typer.Option(8000, envvar="PORT"),
):
    with tempfile.NamedTemporaryFile() as t:
        prepare_database(Path(t.name))
        updater = GitlabUpdater(host=host, token=token)
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
    host: str = typer.Option(..., envvar="GLE_HOST"),
    token: str = typer.Option(..., envvar="GLE_TOKEN"),
    projects: List[str] = typer.Option(..., envvar="GLE_PROJECTS"),
    dbfile: Optional[Path] = None,
):
    context = tempfile.NamedTemporaryFile if dbfile is None else contextlib.nullcontext

    with context() as t:
        assert t is not None or dbfile is not None
        prepare_database(dbfile or Path(t.name))
        updater = GitlabUpdater(host=host, token=token)
        asyncio.run(updater.tick(projects))

    print(generate_latest(updater.registry).decode())
