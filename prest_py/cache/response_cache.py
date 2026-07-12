"""In-memory TTL response cache for pREST.

Approved default: in-memory TTL cache first, Redis optional later.

Mirrors Go behavior:
- `EndpointRules(uri)` — determine if URI should be cached and for how long
- `get(key)` — return cached value if not expired
- `set(key, value, ttl)` — store value with TTL in minutes
- Only GET responses are cached

Safety: the cache is bounded and sweeps expired entries on write so query-string
churn cannot grow memory without bound.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

DEFAULT_MAX_ENTRIES = 1000


@dataclass
class CacheEntry:
    value: str
    expires_at: float


class ResponseCache:
    """In-memory TTL cache keyed by URL string.

    Uses simple dict storage with lazy expiry. Entries are removed on access if
    expired, and a sweep runs on write when the store exceeds ``max_entries``.
    """

    def __init__(
        self,
        enabled: bool = False,
        default_ttl_minutes: int = 10,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.enabled = enabled
        self.default_ttl_minutes = default_ttl_minutes
        self.max_entries = max_entries
        self._store: dict[str, CacheEntry] = {}

    def endpoint_rules(self, uri: str, endpoints: list[dict] | None = None) -> tuple[bool, int]:
        """Determine if URI should be cached and for how long.

        Matches Go `Config.EndpointRules`:
        - If disabled -> (False, ttl)
        - If enabled and no endpoints -> (True, default_ttl)
        - If enabled and endpoints -> only matching enabled endpoints
        """
        if not self.enabled:
            return False, self.default_ttl_minutes

        if not endpoints:
            return True, self.default_ttl_minutes

        for endpoint in endpoints:
            ep_uri = endpoint.get("endpoint", "")
            ep_enabled = endpoint.get("enabled", False)
            ep_time = endpoint.get("time", self.default_ttl_minutes)
            if ep_uri == uri and ep_enabled:
                return True, ep_time

        return False, self.default_ttl_minutes

    def get(self, key: str) -> str | None:
        """Return cached value if exists and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None

        if time.time() > entry.expires_at:
            del self._store[key]
            return None

        return entry.value

    def set(self, key: str, value: str, ttl_minutes: int) -> None:
        """Store value with TTL in minutes."""
        if not self.enabled or ttl_minutes <= 0:
            return

        if len(self._store) >= self.max_entries:
            self._sweep_expired()
            # If still at capacity after sweeping expired entries, drop the
            # oldest remaining entry to make room.
            if len(self._store) >= self.max_entries and self._store:
                oldest = min(self._store, key=lambda k: self._store[k].expires_at)
                del self._store[oldest]

        expires_at = time.time() + (ttl_minutes * 60)
        self._store[key] = CacheEntry(value=value, expires_at=expires_at)

    def _sweep_expired(self) -> None:
        now = time.time()
        expired = [k for k, e in self._store.items() if now > e.expires_at]
        for k in expired:
            del self._store[k]

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)