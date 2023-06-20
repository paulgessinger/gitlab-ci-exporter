import typer

from .gitlab import cli as gitlab_cli

cli = typer.Typer()
cli.add_typer(gitlab_cli, name="gitlab")
