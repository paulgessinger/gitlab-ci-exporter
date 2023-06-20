from typing import Optional
import tempfile
import contextlib
from pathlib import Path

import gitlab
import peewee
from prometheus_client import generate_latest, start_http_server, Gauge
from apscheduler.schedulers.blocking import BlockingScheduler
import typer

from .db import Job, database, prepare_database
from .update import Updater

gitlab_ci_job_count = Gauge(
    name="gitlab_ci_job_count",
    documentation="The total number of jobs running for various categories",
    labelnames=["status", "job_name"],
)

gitlab_ci_job_latency = Gauge(
    name="gitlab_ci_job_latency",
    documentation="Time of most recent finished job spent in queue",
)

class GitlabUpdater(Updater):
    def __init__(self, host: str, token: str):
        self.gl = gitlab.Gitlab(url=host, private_token=token)

    def _adapt(self, jobs):
        for i, job in enumerate(jobs):
            row = {
                "commit_sha": job.commit["id"],
            }

            for k in [
                "id",
                "created_at",
                "started_at",
                "finished_at",
                "duration",
                "queued_duration",
                "name",
                "ref",
                "status",
            ]:
                row[k] = getattr(job, k)

            yield row

    def tick(self, project: str):
        project = self.gl.projects.get(project)
        jobs = project.jobs.list(
            #  scope=[
            #  "pending",
            #  "created",
            #  "running",
            #  ],
            iterator=True,
            per_page=250,
            order_by="id",
            sort="desc",
        )

        g = (j for _, j in zip(range(1000), self._adapt(jobs)))
        Job.insert_many(g).on_conflict_replace().execute()

        gitlab_ci_job_count.clear()
        for job in Job.select(
            peewee.fn.COUNT().alias("count"), Job.name, Job.status
        ).group_by(Job.name, Job.status):
            gitlab_ci_job_count.labels(status=job.status, job_name=job.name).inc(
                job.count
            )

        latest = Job.select().order_by(Job.finished_at.desc()).get()
        gitlab_ci_job_latency.set(latest.queued_duration)

cli = typer.Typer()

@cli.command()
def serve(
    host: str = typer.Option(..., envvar="GLE_HOST"),
    token: str = typer.Option(..., envvar="GLE_TOKEN"),
    project: str = typer.Option(..., envvar="GLE_PROJECT"),
    interval: int = typer.Option(30, envvar="GLE_INTERVAL"),
    port: int = typer.Option(8000, envvar="PORT"),
):
    with tempfile.NamedTemporaryFile() as t:
        prepare_database(Path(t.name))
        updater = GitlabUpdater(host=host, token=token)
        start_http_server(port)

        scheduler = BlockingScheduler()
        scheduler.add_executor("threadpool")

        scheduler.add_job(
            updater.tick, "interval", seconds=interval, kwargs={"project": project}
        )

        try:
            print("Starting scheduler")
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass


@cli.command()
def tick(
    host: str = typer.Option(..., envvar="GLE_HOST"),
    token: str = typer.Option(..., envvar="GLE_TOKEN"),
    project: str = typer.Option(..., envvar="GLE_PROJECT"),
    interval: int = typer.Option(30, envvar="GLE_INTERVAL"),
    port: int = typer.Option(8000, envvar="PORT"),
    dbfile: Optional[Path] = None,
):
    context = tempfile.NamedTemporaryFile if dbfile is None else contextlib.nullcontext

    with context() as t:
        assert t is not None or dbfile is not None
        prepare_database(dbfile or Path(t.name))
        updater = GitlabUpdater(host=host, token=token)
        updater.tick(project)

    print(generate_latest().decode())

