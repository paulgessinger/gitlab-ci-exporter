import typer

from .gitlab import cli as gitlab_cli
from .github import cli as github_cli

cli = typer.Typer()
cli.add_typer(gitlab_cli, name="gitlab")
cli.add_typer(github_cli, name="github")
