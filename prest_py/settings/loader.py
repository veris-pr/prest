from __future__ import annotations

import copy
import json
import logging
import os
import re
import tomllib
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from pydantic import ValidationError

from prest_py.settings.models import DatabaseSettings, Settings

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "./prest.toml"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def load_settings(
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Load pREST settings from defaults, TOML, then environment overrides.

    This intentionally mirrors the Go loader's priority for the Phase 2 slice:
    defaults < TOML < env. Missing config files are tolerated.
    """

    environ = os.environ if env is None else env
    path = str(config_path or environ.get("PREST_CONF") or DEFAULT_CONFIG_PATH)
    data: dict = {}
    if Path(path).exists():
        try:
            with Path(path).open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            logger.warning("could not load config %s; using defaults: %s", path, exc)

    defaults = Settings().model_dump(by_alias=True)
    merged = _merge_dict(defaults, data)
    # Handle flat json_agg_type from TOML's nested json.agg.type
    json_section = merged.get("json", {})
    if isinstance(json_section, dict):
        agg_section = json_section.get("agg", {})
        if isinstance(agg_section, dict) and "type" in agg_section:
            merged["json_agg_type"] = agg_section["type"]
    merged["config_path"] = path
    _apply_env_overrides(merged, environ)
    settings = _validate_settings_lenient(merged, defaults)
    _validate_json_agg_type(settings)
    _apply_pg_url(settings, environ)
    settings.databases = _merge_database_registry(settings, data.get("databases"), environ)
    return settings


def _merge_dict(base: dict, overlay: Mapping) -> dict:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), MutableMapping):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _validate_settings_lenient(data: dict, defaults: dict) -> Settings:
    """Validate settings while restoring only invalid values to defaults.

    Pydantic gives an exact location for each invalid value. Scalar errors are
    reset to the matching default; invalid list entries (for example one bad
    access-table object) are removed. This preserves unrelated valid config.
    """
    candidate = copy.deepcopy(data)
    for _attempt in range(100):
        try:
            return Settings.model_validate(candidate)
        except ValidationError as exc:
            error = exc.errors()[0]
            location = tuple(error.get("loc", ()))
            if location and location[0] == "plugins":
                raise ValueError(
                    f"invalid plugins configuration at "
                    f"{'.'.join(str(part) for part in location)}: {error.get('msg')}"
                ) from exc
            logger.warning(
                "ignoring invalid config value at %s: %s",
                ".".join(str(part) for part in location),
                error.get("msg", "validation error"),
            )
            if not _restore_invalid_value(candidate, defaults, location):
                logger.warning("could not isolate invalid config; using defaults")
                return Settings()
    logger.warning("too many invalid config values; using defaults")
    return Settings()


def _restore_invalid_value(candidate: object, defaults: object, location: tuple) -> bool:
    if not location:
        return False

    current = candidate
    default_current = defaults
    for position, token in enumerate(location):
        is_last = position == len(location) - 1

        if isinstance(token, int):
            if not isinstance(current, list) or not 0 <= token < len(current):
                return False
            # Invalid structured list item: skip that item, matching Go's
            # registry/config-list leniency.
            current.pop(token)
            return True

        if not isinstance(current, dict):
            return False
        key = str(token)
        if key not in current and f"{key}_" in current:
            key = f"{key}_"
        if key not in current:
            return False

        default_value = default_current.get(key) if isinstance(default_current, dict) else None
        if is_last:
            if isinstance(default_current, dict) and key in default_current:
                current[key] = copy.deepcopy(default_value)
            else:
                current.pop(key, None)
            return True

        next_value = current[key]
        next_token = location[position + 1]
        if isinstance(next_token, int) and isinstance(next_value, list):
            current = next_value
            default_current = default_value
            continue
        if not isinstance(next_value, (dict, list)):
            if isinstance(default_current, dict) and key in default_current:
                current[key] = copy.deepcopy(default_value)
                return True
            current.pop(key, None)
            return True
        current = next_value
        default_current = default_value

    return False


def _apply_env_overrides(data: dict, env: Mapping[str, str]) -> None:
    env_map = {
        "PREST_DEBUG": ("debug", _to_bool),
        "PREST_CONTEXT": ("context", str),
        "PREST_AUTH_ENABLED": ("auth.enabled", _to_bool),
        "PREST_AUTH_USERNAME": ("auth.username", str),
        "PREST_AUTH_PASSWORD": ("auth.password", str),
        "PREST_AUTH_SCHEMA": ("auth.schema", str),
        "PREST_AUTH_TABLE": ("auth.table", str),
        "PREST_AUTH_ENCRYPT": ("auth.encrypt", str),
        "PREST_AUTH_TYPE": ("auth.type", str),
        "PREST_HTTP_HOST": ("http.host", str),
        "PREST_HTTP_PORT": ("http.port", int),
        "PREST_HTTP_TIMEOUT": ("http.timeout", int),
        "PORT": ("http.port", int),
        "PREST_PG_URL": ("pg.url", str),
        "DATABASE_URL": ("pg.url", str),
        "PREST_PG_HOST": ("pg.host", str),
        "PREST_PG_PORT": ("pg.port", int),
        "PREST_PG_USER": ("pg.user", str),
        "PREST_PG_PASS": ("pg.pass", str),
        "PREST_PG_DATABASE": ("pg.database", str),
        "PREST_PG_SSL_MODE": ("pg.ssl.mode", str),
        "PREST_PG_SSL_CERT": ("pg.ssl.cert", str),
        "PREST_PG_SSL_KEY": ("pg.ssl.key", str),
        "PREST_PG_SSL_ROOTCERT": ("pg.ssl.rootcert", str),
        "PREST_PG_MAXIDLECONN": ("pg.maxidleconn", int),
        "PREST_PG_MAXOPENCONN": ("pg.maxopenconn", int),
        "PREST_PG_CONNTIMEOUT": ("pg.conntimeout", int),
        "PREST_PG_SINGLE": ("pg.single", _to_bool),
        "PREST_PG_CACHE": ("pg.cache", _to_bool),
        "PREST_CACHE_ENABLED": ("cache.enabled", _to_bool),
        "PREST_CACHE_TIME": ("cache.time", int),
        "PREST_CACHE_STORAGEPATH": ("cache.storagepath", str),
        "PREST_CACHE_SUFIXFILE": ("cache.sufixfile", str),
        "PREST_ACCESS_RESTRICT": ("access.restrict", _to_bool),
        "PREST_EXPOSE_ENABLED": ("expose.enabled", _to_bool),
        "PREST_EXPOSE_TABLES": ("expose.tables", _to_bool),
        "PREST_EXPOSE_SCHEMAS": ("expose.schemas", _to_bool),
        "PREST_EXPOSE_DATABASES": ("expose.databases", _to_bool),
        "PREST_JWT_DEFAULT": ("jwt.default", _to_bool),
        "PREST_JWT_KEY": ("jwt.key", str),
        "PREST_JWT_ALGO": ("jwt.algo", str),
        "PREST_JWT_WELLKNOWNURL": ("jwt.wellknownurl", str),
        "PREST_JWT_JWKS": ("jwt.jwks", str),
        "PREST_JSON_AGG_TYPE": ("json_agg_type", str),
        "PREST_QUERIES_LOCATION": ("queries.location", str),
        "PREST_PLUGIN_ENTRIES": ("plugins.entries", _to_string_list),
    }
    for key, (path, cast) in env_map.items():
        if key not in env or env[key] == "":
            continue
        try:
            value = cast(env[key])
        except (TypeError, ValueError) as exc:
            if key == "PREST_PLUGIN_ENTRIES":
                raise ValueError("invalid PREST_PLUGIN_ENTRIES") from exc
            logger.warning("ignoring invalid environment value %s=%r: %s", key, env[key], exc)
            continue
        _set_path(data, path, value)


def _set_path(data: dict, dotted_path: str, value: object) -> None:
    current = data
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


VALID_JSON_AGG_TYPES = frozenset({"jsonb_agg", "json_agg"})


def _validate_json_agg_type(settings: Settings) -> None:
    """Validate json_agg_type, falling back to jsonb_agg on invalid values."""
    if settings.json_agg_type not in VALID_JSON_AGG_TYPES:
        logger.warning(
            "json_agg_type %r is invalid, using jsonb_agg",
            settings.json_agg_type,
        )
        settings.json_agg_type = "jsonb_agg"


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "t", "true", "yes", "y", "on"}


def _to_string_list(value: str) -> list[str]:
    text = value.strip()
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("expected a JSON array of strings")
        return [item.strip() for item in parsed if item.strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _parse_database_url(value: str) -> ParseResult | None:
    try:
        parsed = urlparse(value)
        # Accessing `.port` performs URL port validation.
        _ = parsed.port
    except ValueError as exc:
        # Do not echo a DSN: it can contain database credentials.
        logger.warning("ignoring invalid database URL: %s", exc)
        return None
    return parsed


def _apply_pg_url(settings: Settings, env: Mapping[str, str]) -> None:
    # DATABASE_URL wins over PREST_PG_URL and TOML pg.url, matching Go behavior.
    pg_url = env.get("DATABASE_URL") or settings.pg.url
    if not pg_url:
        return
    parsed = _parse_database_url(pg_url)
    if parsed is None:
        settings.pg.url = ""
        return
    settings.pg.url = pg_url
    if parsed.hostname:
        settings.pg.host = parsed.hostname
    if parsed.port:
        settings.pg.port = parsed.port
    if parsed.username:
        settings.pg.user = parsed.username
    if parsed.password:
        settings.pg.pass_ = parsed.password
    if parsed.path and parsed.path != "/":
        settings.pg.database = parsed.path.lstrip("/")
    sslmode = _query_value(parsed.query, "sslmode")
    if sslmode:
        settings.pg.ssl.mode = sslmode


def _merge_database_registry(
    settings: Settings,
    toml_databases: object,
    env: Mapping[str, str],
) -> list[DatabaseSettings]:
    merged: dict[str, DatabaseSettings] = {}
    env_aliases: set[str] = set()

    for db in _database_registry_from_env(env):
        merged[db.alias] = db
        env_aliases.add(db.alias)

    if isinstance(toml_databases, list):
        for raw in toml_databases:
            if not isinstance(raw, Mapping):
                continue
            alias = str(raw.get("alias", ""))
            if not _is_safe_segment(alias) or alias in env_aliases or alias in merged:
                continue
            try:
                db = DatabaseSettings.model_validate(raw)
            except ValidationError as exc:
                logger.warning("ignoring invalid database profile %r: %s", alias, exc)
                continue
            _fill_database_defaults(db, settings)
            if db.url and not _apply_url_to_database(db):
                continue
            merged[db.alias] = db

    return [merged[alias] for alias in sorted(merged)]


def _database_registry_from_env(env: Mapping[str, str]) -> list[DatabaseSettings]:
    out: list[DatabaseSettings] = []
    index = 1
    while True:
        alias = env.get(f"DATABASE_ALIAS_{index}") or env.get(f"PREST_DATABASE_ALIAS_{index}") or ""
        url = env.get(f"DATABASE_URL_{index}") or env.get(f"PREST_DATABASE_URL_{index}") or ""
        if not alias and not url:
            break
        if alias and url and _is_safe_segment(alias):
            db = DatabaseSettings(alias=alias, url=url)
            if _apply_url_to_database(db):
                out.append(db)
        index += 1
    return out


def _fill_database_defaults(db: DatabaseSettings, settings: Settings) -> None:
    if not db.host:
        db.host = settings.pg.host
    if not db.port:
        db.port = settings.pg.port
    if not db.user:
        db.user = settings.pg.user
    if not db.pass_:
        db.pass_ = settings.pg.pass_
    if not db.database:
        db.database = settings.pg.database
    if not db.ssl.mode:
        db.ssl.mode = settings.pg.ssl.mode
    if not db.ssl.cert:
        db.ssl.cert = settings.pg.ssl.cert
    if not db.ssl.key:
        db.ssl.key = settings.pg.ssl.key
    if not db.ssl.rootcert:
        db.ssl.rootcert = settings.pg.ssl.rootcert
    if not db.maxopenconn:
        db.maxopenconn = settings.pg.maxopenconn
    if not db.maxidleconn:
        db.maxidleconn = settings.pg.maxidleconn


def _apply_url_to_database(db: DatabaseSettings) -> bool:
    parsed = _parse_database_url(db.url)
    if parsed is None:
        return False
    if parsed.hostname:
        db.host = parsed.hostname
    if parsed.port:
        db.port = parsed.port
    if parsed.username:
        db.user = parsed.username
    if parsed.password:
        db.pass_ = parsed.password
    if parsed.path and parsed.path != "/":
        db.database = parsed.path.lstrip("/")
    sslmode = _query_value(parsed.query, "sslmode")
    if sslmode:
        db.ssl.mode = sslmode
    return True


def _query_value(query: str, key: str) -> str:
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if name == key:
            return value
    return ""


def _is_safe_segment(value: str) -> bool:
    return bool(value and _SAFE_SEGMENT.fullmatch(value))
