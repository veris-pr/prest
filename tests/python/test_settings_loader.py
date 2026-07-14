from pathlib import Path

import pytest

from prest_py.settings import load_settings

EMPTY_ENV = {"PATH": ""}


def test_load_settings_uses_defaults_when_config_missing(tmp_path):
    missing = tmp_path / "missing.toml"

    settings = load_settings(missing, env=EMPTY_ENV)

    assert settings.config_path == str(missing)
    assert settings.http.port == 3000
    assert settings.pg.host == "127.0.0.1"
    assert settings.pg.database == "prest"
    assert settings.pg.single is True
    assert settings.cache.enabled is False


def test_explicit_empty_env_does_not_read_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PREST_HTTP_PORT", "23456")

    settings = load_settings(tmp_path / "missing.toml", env={})

    assert settings.http.port == 3000


def test_malformed_toml_uses_defaults(tmp_path):
    config = tmp_path / "broken.toml"
    config.write_text("[http\nport = ???", encoding="utf-8")

    settings = load_settings(config, env={})

    assert settings.http.port == 3000
    assert settings.config_path == str(config)


def test_invalid_toml_field_restores_only_that_default(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text(
        '[http]\nport = 70000\n[pg]\nhost = "kept-host"\n',
        encoding="utf-8",
    )

    settings = load_settings(config, env={})

    assert settings.http.port == 3000
    assert settings.pg.host == "kept-host"


def test_invalid_env_cast_is_ignored(tmp_path):
    settings = load_settings(
        tmp_path / "missing.toml",
        env={"PREST_HTTP_PORT": "not-an-int"},
    )

    assert settings.http.port == 3000


def test_plugin_entries_load_from_toml(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text(
        '[plugins]\nentries = ["package.one:register", "package.two:register"]\n',
        encoding="utf-8",
    )

    settings = load_settings(config, env={})

    assert settings.plugins.entries == ["package.one:register", "package.two:register"]


def test_plugin_entries_env_accepts_json_or_csv(tmp_path):
    missing = tmp_path / "missing.toml"

    json_settings = load_settings(
        missing,
        env={"PREST_PLUGIN_ENTRIES": '["package.one:register", "package.two:register"]'},
    )
    csv_settings = load_settings(
        missing,
        env={"PREST_PLUGIN_ENTRIES": "package.one:register, package.two:register"},
    )

    assert json_settings.plugins.entries == ["package.one:register", "package.two:register"]
    assert csv_settings.plugins.entries == json_settings.plugins.entries


def test_invalid_plugin_toml_does_not_silently_disable_plugins(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text("[plugins]\nentries = [123]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid plugins configuration"):
        load_settings(config, env={})


def test_invalid_plugin_env_does_not_silently_disable_plugins(tmp_path):
    with pytest.raises(ValueError, match="invalid PREST_PLUGIN_ENTRIES"):
        load_settings(
            tmp_path / "missing.toml",
            env={"PREST_PLUGIN_ENTRIES": '["valid:register", 123]'},
        )


def test_load_settings_reads_existing_toml_fixture():
    settings = load_settings(Path("testdata/prest_multicluster.toml"), env=EMPTY_ENV)

    assert settings.http.port == 3000
    assert settings.pg.host == "postgres"
    assert settings.pg.database == "prest-test"
    assert settings.pg.single is False
    assert settings.access.restrict is False
    assert [db.alias for db in settings.databases] == ["prest-test", "secondary-db"]
    secondary = settings.profile_by_alias("secondary-db")
    assert secondary is not None
    assert secondary.host == "postgres-b"
    assert secondary.database == "secondary-cluster"
    assert secondary.ssl.mode == "disable"


def test_load_settings_reads_access_and_cache_toml():
    settings = load_settings(Path("testdata/prest.toml"), env=EMPTY_ENV)

    assert settings.auth.table == "prest_users"
    assert settings.auth.username == "username"
    assert settings.cache.enabled is True
    assert settings.cache.endpoints[0].endpoint == "/prest/public/test"
    assert settings.access.restrict is True
    assert any(
        table.name == "test" and "read" in table.permissions for table in settings.access.tables
    )
    assert any(user.name == "foo_read" for user in settings.access.users)


def test_prest_conf_env_selects_config(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text('[http]\nport = 2345\n[pg]\ndatabase = "from-conf"\n')

    settings = load_settings(env={"PREST_CONF": str(config)})

    assert settings.config_path == str(config)
    assert settings.http.port == 2345
    assert settings.pg.database == "from-conf"


def test_env_overrides_toml_values(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text('[http]\nport = 3000\n[pg]\nhost = "toml-host"\nsingle = true\n')

    settings = load_settings(
        config,
        env={
            "PREST_HTTP_PORT": "24000",
            "PREST_PG_HOST": "env-host",
            "PREST_PG_SINGLE": "false",
            "PREST_CACHE_ENABLED": "true",
        },
    )

    assert settings.http.port == 24000
    assert settings.pg.host == "env-host"
    assert settings.pg.single is False
    assert settings.cache.enabled is True


def test_port_env_overrides_prest_http_port(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text("[http]\nport = 3000\n")

    settings = load_settings(config, env={"PREST_HTTP_PORT": "24000", "PORT": "25000"})

    assert settings.http.port == 25000


def test_database_url_overrides_pg_connection_fields():
    settings = load_settings(
        env={
            "DATABASE_URL": "postgres://user:secret@db.example:6543/app?sslmode=require",
        },
    )

    assert settings.pg.url == "postgres://user:secret@db.example:6543/app?sslmode=require"
    assert settings.pg.host == "db.example"
    assert settings.pg.port == 6543
    assert settings.pg.user == "user"
    assert settings.pg.pass_ == "secret"
    assert settings.pg.database == "app"
    assert settings.pg.ssl.mode == "require"


def test_database_registry_env_pairs_win_over_toml(tmp_path):
    config = tmp_path / "prest.toml"
    config.write_text(
        '[pg]\nhost = "default-host"\nuser = "default-user"\n'
        'pass = "default-pass"\ndatabase = "default-db"\n'
        '[[databases]]\nalias = "tenant-a"\nhost = "toml-host"\ndatabase = "toml-db"\n'
        '[[databases]]\nalias = "tenant-b"\nhost = "toml-b"\ndatabase = "toml-b"\n'
    )

    settings = load_settings(
        config,
        env={
            "DATABASE_ALIAS_1": "tenant-a",
            "DATABASE_URL_1": "postgres://env-user:env-pass@env-host:5439/env-db?sslmode=require",
        },
    )

    assert [db.alias for db in settings.databases] == ["tenant-a", "tenant-b"]
    tenant_a = settings.profile_by_alias("tenant-a")
    assert tenant_a is not None
    assert tenant_a.host == "env-host"
    assert tenant_a.user == "env-user"
    assert tenant_a.pass_ == "env-pass"
    assert tenant_a.database == "env-db"
    assert tenant_a.ssl.mode == "require"

    tenant_b = settings.profile_by_alias("tenant-b")
    assert tenant_b is not None
    assert tenant_b.host == "toml-b"
    assert tenant_b.user == "default-user"
    assert tenant_b.pass_ == "default-pass"


def test_invalid_registry_aliases_are_skipped():
    settings = load_settings(
        env={
            "DATABASE_ALIAS_1": "bad/alias",
            "DATABASE_URL_1": "postgres://user:pass@host:5432/db?sslmode=disable",
            "DATABASE_ALIAS_2": "good-alias",
            "DATABASE_URL_2": "postgres://user:pass@host:5432/db?sslmode=disable",
        },
    )

    assert [db.alias for db in settings.databases] == ["good-alias"]


def test_invalid_registry_url_is_skipped():
    settings = load_settings(
        env={
            "DATABASE_ALIAS_1": "bad-port",
            "DATABASE_URL_1": "postgres://user:pass@host:not-a-port/db",
            "DATABASE_ALIAS_2": "good-alias",
            "DATABASE_URL_2": "postgres://user:pass@host:5432/db",
        },
    )

    assert [db.alias for db in settings.databases] == ["good-alias"]


def test_invalid_database_url_log_redacts_credentials(caplog):
    load_settings(
        env={
            "DATABASE_URL": "postgres://user:super-secret@host:not-a-port/db",
        }
    )

    assert "invalid database URL" in caplog.text
    assert "super-secret" not in caplog.text
