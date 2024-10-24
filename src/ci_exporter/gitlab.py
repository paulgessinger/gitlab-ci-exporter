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
            labelnames=["status", "job_name", "project"],
            registry=self.registry,
        )

        self.job_latency = Histogram(
            name="gitlab_ci_job_latency",
            documentation="Time jobs spent in queue",
            labelnames=["status", "job_name", "project"],
            registry=self.registry,
            buckets=LATENCY_BUCKETS,
        )

        self.job_duration = Histogram(
            name="gitlab_ci_job_duration",
            documentation="Time that jobs took to execute",
            labelnames=["status", "job_name", "project"],
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

            for project in projects:
                jobs = gl.getiter(
                    f"/projects/{project.replace('/', '%2F')}/jobs?per_page=250&order_by=id&sort=desc"
                )

                g = self._adapt(
                    [j async for _, j in asyncstdlib.zip(range(1000), jobs)], project
                )
                Job.insert_many(g).on_conflict_replace().execute()

            jobs = list(
                Job.select(
                    peewee.fn.COUNT().alias("count"), Job.name, Job.status, Job.project
                ).group_by(Job.name, Job.status, Job.project)
            )
            self.job_count.clear()
            for job in jobs:
                print(job)
                self.job_count.labels(
                    status=job.status, job_name=job.name, project=job.project
                ).inc(job.count)

            jobs = []
            for job in Job.select(
                Job.name,
                Job.status,
                Job.finished_at,
                Job.created_at,
                Job.started_at,
                Job.project,
            ).where(Job.started_at.is_null(False)):
                jobs.append(
                    (
                        job.status,
                        job.name,
                        job.project,
                        (job.started_at - job.created_at).total_seconds(),
                        (
                            (job.finished_at - job.started_at).total_seconds()
                            if job.finished_at is not None
                            else None
                        ),
                    )
                )

            self.job_latency.clear()
            self.job_duration.clear()
            for status, name, project, latency, duration in jobs:
                self.job_latency.labels(
                    status=status, job_name=name, project=project
                ).observe(latency)

                if duration is not None:
                    self.job_duration.labels(
                        status=status, job_name=name, project=project
                    ).observe(duration)


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
