
import typer
from prometheus_client import generate_latest, start_http_server
from apscheduler.schedulers.blocking import BlockingScheduler

from .gitlab import cli as gitlab_cli
from .db import database, prepare_database

cli = typer.Typer()
cli.add_typer(gitlab_cli, name="gitlab")
