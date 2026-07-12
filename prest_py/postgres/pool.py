from __future__ import annotations

import asyncio
import logging
import ssl as ssl_module
from urllib.parse import quote as urlquote
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from prest_py.settings.models import DatabaseSettings, Settings

logger = logging.getLogger(__name__)


class PoolManager:
    """Async connection-pool manager keyed by connection URI.

    Mirrors the Go `connection.Manager` contract:

    - pools are keyed by connection URI; aliases sharing a URI share a pool
    - pools are created lazily on first request (single-flight guarded)
    - `pg.single` rejects non-default aliases when a registry is active
    - readiness pings the default DB and every registered alias
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pools: dict[str, asyncpg.Pool] = {}
        self._create_lock = asyncio.Lock()

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        """Open the default database pool and verify connectivity."""
        pool = await self.get(self._settings.pg.database)
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")

    async def close(self) -> None:
        """Close all pools and reset state."""
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()

    # -- accessors -----------------------------------------------------------

    def registered_aliases(self) -> list[str]:
        if not self._settings.has_database_registry:
            return []
        return [db.alias for db in self._settings.databases]

    # -- routing -------------------------------------------------------------

    def is_registered(self, alias: str) -> bool:
        if not self._settings.has_database_registry:
            return True
        return self._settings.profile_by_alias(alias) is not None

    def physical_name(self, alias: str) -> str:
        profile = self._settings.profile_by_alias(alias)
        if profile and profile.database:
            return profile.database
        if alias == "":
            return self._settings.pg.database
        return alias

    def _validate_alias(self, alias: str) -> str:
        """Resolve alias to physical DB name, enforcing pg.single."""
        if self._settings.has_database_registry:
            if alias == "" or alias == self._settings.pg.database:
                return self._settings.pg.database
            if self._settings.pg.single:
                raise ValueError(f"pg.single is true; alias {alias!r} not allowed")
            if not self.is_registered(alias):
                raise ValueError(f"database alias {alias!r} is not registered")
            return self.physical_name(alias)
        if alias == "":
            return self._settings.pg.database
        return alias

    # -- URI building --------------------------------------------------------

    def _uri_for(self, alias: str) -> str:
        profile = self._settings.profile_by_alias(alias)
        if profile and profile.url:
            return profile.url
        if profile:
            return _build_uri(profile, self._settings)
        database = alias or self._settings.pg.database
        if self._settings.pg.url:
            return _uri_with_database(self._settings.pg.url, database)
        return _build_default_uri(self._settings, database)

    def _pool_limits_for(self, alias: str) -> tuple[int, int]:
        max_idle = self._settings.pg.maxidleconn
        max_open = self._settings.pg.maxopenconn
        profile = self._settings.profile_by_alias(alias)
        if profile:
            if profile.maxidleconn:
                max_idle = profile.maxidleconn
            if profile.maxopenconn:
                max_open = profile.maxopenconn
        return max_idle, max_open

    def _ssl_kwargs_for(self, alias: str) -> dict:
        """Build asyncpg ssl kwargs when cert/key/rootcert are configured.

        When only sslmode is set, it travels via the DSN query string and no
        ssl kwarg is needed. Cert-based SSL requires an explicit SSLContext.
        """
        profile = self._settings.profile_by_alias(alias)
        ssl = profile.ssl if profile else self._settings.pg.ssl
        mode = (ssl.mode or "disable").lower()
        if mode == "disable" or not (ssl.cert or ssl.key or ssl.rootcert):
            return {}
        ctx = ssl_module.create_default_context(cafile=ssl.rootcert or None)
        if ssl.cert:
            ctx.load_cert_chain(certfile=ssl.cert, keyfile=ssl.key or None)
        if mode in ("allow", "prefer", "require"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl_module.CERT_NONE
        elif mode == "verify-ca":
            ctx.check_hostname = False
            ctx.verify_mode = ssl_module.CERT_REQUIRED
        else:  # verify-full
            ctx.check_hostname = True
            ctx.verify_mode = ssl_module.CERT_REQUIRED
        return {"ssl": ctx}

    # -- pool access ---------------------------------------------------------

    async def get(self, alias: str = "") -> asyncpg.Pool:
        """Get or lazily create the pool for alias.

        Single-flight: a shared lock guards creation so concurrent first
        requests for the same alias do not create duplicate pools.
        """
        self._validate_alias(alias)  # raises early on invalid alias
        uri = self._uri_for(alias or self._settings.pg.database)
        if uri in self._pools:
            return self._pools[uri]
        async with self._create_lock:
            if uri in self._pools:  # double-check after acquiring lock
                return self._pools[uri]
            return await self._add_to_pool(alias or self._settings.pg.database, uri)

    async def _add_to_pool(self, alias: str, uri: str) -> asyncpg.Pool:
        max_idle, max_open = self._pool_limits_for(alias)
        max_open = max(max_open, 1)
        min_idle = min(max_idle, max_open)
        connect_timeout = max(self._settings.pg.conntimeout, 1)
        pool = await asyncpg.create_pool(
            dsn=uri,
            min_size=min_idle,
            max_size=max_open,
            timeout=connect_timeout,
            **self._ssl_kwargs_for(alias),
        )
        self._pools[uri] = pool
        return pool

    # -- health --------------------------------------------------------------

    async def ping(self, alias: str = "") -> bool:
        """Ping a single alias/default DB. Returns True on success."""
        try:
            pool = await self.get(alias)
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            logger.exception("ping failed for alias=%r", alias)
            return False

    async def ping_all(self) -> bool:
        """Ping default + every registered alias. Returns True only if all succeed."""
        if not await self.ping():
            return False
        if not self._settings.has_database_registry:
            return True
        for db in self._settings.databases:
            if not await self.ping(db.alias):
                return False
        return True


def _encode(value: str) -> str:
    """Percent-encode a URI credentials component."""
    return urlquote(value, safe="")


def _uri_with_database(uri: str, database: str) -> str:
    """Replace only the database path, preserving all connection options."""
    parsed = urlsplit(uri)
    return urlunsplit(parsed._replace(path=f"/{database}"))


def _build_uri(profile: DatabaseSettings, defaults: Settings) -> str:
    database = profile.database or defaults.pg.database
    port = profile.port or defaults.pg.port
    ssl_mode = profile.ssl.mode or defaults.pg.ssl.mode
    user = profile.user or defaults.pg.user
    host = profile.host or defaults.pg.host
    password = profile.pass_ or defaults.pg.pass_
    return f"postgres://{_encode(user)}:{_encode(password)}@{host}:{port}/{database}?sslmode={ssl_mode}"


def _build_default_uri(settings: Settings, database: str) -> str:
    pg = settings.pg
    return (
        f"postgres://{_encode(pg.user)}:{_encode(pg.pass_)}@{pg.host}:{pg.port}/{database}"
        f"?sslmode={pg.ssl.mode}"
    )
