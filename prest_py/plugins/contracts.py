"""Public contracts for Python-native pREST plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter


@dataclass(frozen=True)
class PluginRegistration:
    """Transport extensions returned by one plugin registration callable.

    Routers are included before pREST's broad dynamic catalog/CRUD routes so
    exact plugin paths remain reachable, matching Go route ordering. Middleware
    classes run inside built-in XML, global security/exposure, and cache policy
    boundaries.
    """

    routers: tuple[APIRouter, ...] = ()
    middleware: tuple[type[Any], ...] = ()
