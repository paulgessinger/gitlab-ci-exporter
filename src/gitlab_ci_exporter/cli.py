import typer
from prometheus_client import start_http_server
from apscheduler.schedulers.blocking import BlockingScheduler

from .update import Updater

cli = typer.Typer()


@cli.command()
def serve(
    host: str = typer.Option(..., envvar="GLE_HOST"),
    token: str = typer.Option(..., envvar="GLE_TOKEN"),
    project: str = typer.Option(..., envvar="GLE_PROJECT"),
    interval: int = typer.Option(30, envvar="GLE_INTERVAL"),
    port: int = typer.Option(8000, envvar="PORT"),
):

    updater = Updater(host=host, token=token)
    #  updater.tick(project)
    #  return
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
def tick():
    tick()
