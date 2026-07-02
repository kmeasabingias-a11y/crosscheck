"""CrossCheck command-line interface (Typer)."""

from pathlib import Path
from typing import Annotated

import typer

from crosscheck import __version__
from crosscheck.config import get_settings
from crosscheck.logging_config import configure_logging

app = typer.Typer(
    name="crosscheck",
    help="Cross-document contradiction detection.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the version and exit when ``--version`` is given."""
    if value:
        typer.echo(f"crosscheck {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Audit a corpus for cross-document contradictions."""
    configure_logging(get_settings())


@app.command()
def audit(
    corpus: Annotated[Path, typer.Argument(help="Path to the corpus directory to audit.")],
) -> None:
    """Audit a corpus directory for contradictions (not yet implemented)."""
    typer.echo(f"'audit' is not implemented yet — coming in Phase 3. Requested corpus: {corpus}")
    raise typer.Exit(code=1)
