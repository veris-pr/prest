from __future__ import annotations

from typer.testing import CliRunner

from prest_py.cli import cli

runner = CliRunner()


def test_version_command_prints_tagline_and_version():
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    out = result.stdout.strip()
    assert "instant, realtime, high-performance" in out
    # package version is present (0.1.0 in dev, metadata-driven otherwise)
    assert out.split()[-1].count(".") >= 2


def test_help_lists_commands():
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "version" in result.stdout
    assert "migrate" in result.stdout


def test_migrate_help_lists_subcommands():
    result = runner.invoke(cli, ["migrate", "--help"])

    assert result.exit_code == 0
    for name in ["up", "down", "redo", "reset", "next", "version"]:
        assert name in result.stdout


def test_migrate_no_subcommand_exits_nonzero_with_pointer():
    result = runner.invoke(cli, ["migrate"])

    assert result.exit_code == 2
    assert "Go pREST binary" in result.stderr
    assert "docs/python-migrations.md" in result.stderr


def test_migrate_up_stub_points_to_go_binary():
    result = runner.invoke(cli, ["migrate", "up"])

    assert result.exit_code == 2
    assert "prestd migrate up" in result.stderr


def test_migrate_down_stub_points_to_go_binary():
    result = runner.invoke(cli, ["migrate", "down"])

    assert result.exit_code == 2
    assert "prestd migrate down" in result.stderr


def test_migrate_version_stub_points_to_go_binary():
    result = runner.invoke(cli, ["migrate", "version"])

    assert result.exit_code == 2
    assert "prestd migrate version" in result.stderr


def test_root_no_subcommand_attempts_server(monkeypatch):
    """Bare ``prestd`` routes to the server. We stub uvicorn to avoid binding."""
    called = {}

    def fake_run(app, host, port, reload, log_config):
        called["host"] = host
        called["port"] = port
        called["reload"] = reload

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = runner.invoke(cli, ["--host", "127.0.0.1", "--port", "21999"])

    assert result.exit_code == 0, result.stderr
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 21999


def test_root_invalid_port_fails():
    result = runner.invoke(cli, ["--port", "not-a-port"])

    assert result.exit_code != 0
