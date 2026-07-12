"""Fail-fast import-string loader for trusted Python plugins."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from fastapi import APIRouter

from prest_py.plugins.contracts import PluginRegistration


class PluginLoadError(RuntimeError):
    """Raised when configured plugin code cannot be loaded or validated."""


@dataclass(frozen=True)
class LoadedPlugin:
    entry: str
    registration: PluginRegistration


def load_plugins(entries: list[str]) -> tuple[LoadedPlugin, ...]:
    """Resolve and invoke configured ``module:callable`` plugin entries.

    Plugins are trusted application code and load once during app creation.
    Configuration errors fail startup; silently dropping a security or routing
    extension would leave the runtime in an unknown state.
    """
    loaded: list[LoadedPlugin] = []
    seen: set[str] = set()

    for raw_entry in entries:
        entry = raw_entry.strip()
        if not entry:
            raise PluginLoadError("plugin entry cannot be empty")
        if entry in seen:
            raise PluginLoadError(f"duplicate plugin entry: {entry}")
        seen.add(entry)

        register = _resolve_callable(entry)
        try:
            registration = register()
        except Exception as exc:
            raise PluginLoadError(f"plugin {entry!r} registration failed: {exc}") from exc

        loaded.append(
            LoadedPlugin(
                entry=entry,
                registration=_validate_registration(entry, registration),
            )
        )

    return tuple(loaded)


def _resolve_callable(entry: str):
    module_name, separator, attribute_path = entry.partition(":")
    if not separator or not module_name or not attribute_path:
        raise PluginLoadError(
            f"invalid plugin entry {entry!r}; expected 'package.module:register'"
        )

    try:
        target: Any = import_module(module_name)
    except Exception as exc:
        raise PluginLoadError(f"could not import plugin module {module_name!r}: {exc}") from exc

    try:
        for attribute in attribute_path.split("."):
            target = getattr(target, attribute)
    except AttributeError as exc:
        raise PluginLoadError(f"plugin callable not found: {entry}") from exc

    if not callable(target):
        raise PluginLoadError(f"plugin target is not callable: {entry}")
    return target


def _validate_registration(entry: str, value: object) -> PluginRegistration:
    if not isinstance(value, PluginRegistration):
        raise PluginLoadError(
            f"plugin {entry!r} must return PluginRegistration, got {type(value).__name__}"
        )
    if not value.routers and not value.middleware:
        raise PluginLoadError(f"plugin {entry!r} returned an empty registration")

    for router in value.routers:
        if not isinstance(router, APIRouter):
            raise PluginLoadError(f"plugin {entry!r} contains a non-APIRouter router")
    for middleware in value.middleware:
        if not isinstance(middleware, type):
            raise PluginLoadError(f"plugin {entry!r} contains a non-class middleware")

    return value
