from pathlib import Path
import tempfile

import typer
from prometheus_client import generate_latest, start_http_server
from apscheduler.schedulers.blocking import BlockingScheduler

from gitlab_ci_exporter.db import prepare_database

from .update import Updater
from .db import database

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
        updater = Updater(host=host, token=token)
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
):
    with tempfile.NamedTemporaryFile() as t:
        prepare_database(Path(t.name))
        updater = Updater(host=host, token=token)
        updater.tick(project)

    print(generate_latest().decode())
