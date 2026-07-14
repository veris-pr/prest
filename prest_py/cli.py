"""pREST Python CLI.

Mirrors the Go ``prestd`` command surface that this rewrite supports:

- ``prestd`` (no args) and ``prestd serve`` start the API server.
- ``prestd version`` prints the release version.
- ``prestd migrate ...`` is a stub that points operators to the Go binary,
  which remains the migration tool (see docs/python-migrations.md).

Migration commands are intentionally not reimplemented in Python.
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import Annotated

import typer

from prest_py.app import create_app
from prest_py.settings import load_settings

cli = typer.Typer(
    name="prestd",
    add_completion=False,
    no_args_is_help=False,
    help="Serve a RESTful API from any PostgreSQL database.",
    context_settings={"help_option_names": ["-h", "--help"]},
)

migrate_app = typer.Typer(
    name="migrate",
    help="Migration operations (handled by the Go pREST binary).",
    no_args_is_help=False,
)

cli.add_typer(migrate_app, name="migrate")

_TAGLINE = (
    "Simplify and accelerate development, ⚡ instant, realtime, "
    "high-performance on any Postgres application, existing or new"
)

_MIGRATE_POINTER = (
    "Migrations are handled by the Go pREST binary, not this Python server.\n"
    "Install/Run: prestd migrate {subcommand} --path <dir> --url <postgres-url>\n"
    "See: docs/python-migrations.md"
)


def _package_version() -> str:
    try:
        return pkg_version("prest-py")
    except PackageNotFoundError:
        return "0.1.0+local"


def _run_server(host: str | None, port: int | None, config: str | None, reload: bool) -> None:
    settings = load_settings(config_path=config)
    bind_host = host or settings.http.host
    bind_port = port if port is not None else settings.http.port

    try:
        app = create_app(settings)
    except Exception as exc:
        typer.echo(f"failed to initialize app: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not settings.auth.enabled:
        typer.echo("warning: running prestd in public mode (auth.enabled=false)", err=True)
    if settings.debug:
        typer.echo("warning: running prestd in debug mode", err=True)

    # Imported here so `prestd version` does not require uvicorn at import time.
    import uvicorn

    typer.echo(f"listening and serving on {bind_host}:{bind_port}", err=True)
    uvicorn.run(app, host=bind_host, port=bind_port, reload=reload, log_config=None)


@cli.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option("--host", help="Bind host.")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Bind port.")] = None,
    config: Annotated[str | None, typer.Option("--config", help="Path to prest.toml.")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Enable auto-reload (dev).")] = False,
) -> None:
    """pREST — start the server when no subcommand is given."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if ctx.invoked_subcommand is None:
        _run_server(host, port, config, reload)


@cli.command("version")
def version_command() -> None:
    """Print the pREST version."""
    typer.echo(f"{_TAGLINE} {_package_version()}")


@migrate_app.callback(invoke_without_command=True)
def _migrate_root(ctx: typer.Context) -> None:
    """Point operators to the Go binary for migrations."""
    if ctx.invoked_subcommand is None:
        typer.echo(_MIGRATE_POINTER.format(subcommand="<command>"), err=True)
        raise typer.Exit(code=2)


def _migrate_stub(subcommand: str) -> None:
    typer.echo(_MIGRATE_POINTER.format(subcommand=subcommand), err=True)
    raise typer.Exit(code=2)


@migrate_app.command("up")
def migrate_up() -> None:
    """Apply all available migrations (use Go binary)."""
    _migrate_stub("up")


@migrate_app.command("down")
def migrate_down() -> None:
    """Roll back all migrations (use Go binary)."""
    _migrate_stub("down")


@migrate_app.command("redo")
def migrate_redo() -> None:
    """Roll back the latest migration, then re-apply (use Go binary)."""
    _migrate_stub("redo")


@migrate_app.command("reset")
def migrate_reset() -> None:
    """Run down then up (use Go binary)."""
    _migrate_stub("reset")


@migrate_app.command("next")
def migrate_next() -> None:
    """Apply the next N migrations (use Go binary)."""
    _migrate_stub("next")


@migrate_app.command("version")
def migrate_version() -> None:
    """Show migration status (use Go binary)."""
    _migrate_stub("version")


def main() -> None:
    """Entry point for the ``prestd`` console script."""
    cli()


if __name__ == "__main__":
    main()
