from __future__ import annotations

import re

from prest_py.settings.models import Settings


def table_permissions(
    settings: Settings,
    database: str,
    schema: str,
    table: str,
    op: str,
    username: str = "",
) -> bool:
    """Check if *op* is permitted on the given table.

    When ``access.restrict`` is False, everything is permitted.
    """
    if not settings.access.restrict:
        return True

    if table in settings.access.ignore_table:
        return True

    conf = _match_table_conf(settings.access.tables, database, schema, table)
    access = op in conf.permissions if conf else False

    if not username:
        return access

    for user in settings.access.users:
        if user.name != username:
            continue
        user_conf = _match_table_conf(user.tables, database, schema, table)
        if user_conf:
            return op in user_conf.permissions

    return access


def fields_by_permission(
    settings: Settings,
    database: str,
    schema: str,
    table: str,
    op: str,
    username: str = "",
) -> list[str]:
    """Return permitted field list. Defaults to ``["*"]`` when unrestricted."""
    fields = ["*"]

    conf = _match_table_conf(settings.access.tables, database, schema, table)
    if conf and op in conf.permissions:
        fields = conf.fields

    if not username:
        return fields

    for user in settings.access.users:
        if user.name != username:
            continue
        user_conf = _match_table_conf(user.tables, database, schema, table)
        if user_conf and op in user_conf.permissions:
            fields = user_conf.fields

    return fields


def fields_permissions(
    settings: Settings,
    requested_cols: list[str],
    database: str,
    schema: str,
    table: str,
    op: str,
    username: str = "",
) -> list[str]:
    """Resolve the effective field list for a read request.

    When ``access.restrict`` is False, return requested cols or ``["*"]``.
    When restricted, intersect requested cols with allowed fields.
    """
    if not settings.access.restrict or op == "delete":
        return requested_cols if requested_cols else ["*"]

    allowed = fields_by_permission(settings, database, schema, table, op, username)
    if "*" in allowed:
        return requested_cols if requested_cols else ["*"]

    if not requested_cols:
        return allowed if allowed else ["*"]

    return _intersection(requested_cols, allowed)


def _intersection(cols: list[str], allowed: list[str]) -> list[str]:
    result: list[str] = []
    for col in cols:
        if _check_field(col, allowed):
            result.append(col)
    return result


def _check_field(col: str, fields: list[str]) -> str | None:
    group_match = re.search(r'"(.+?)"', col)
    if group_match:
        inner = group_match.group(1)
        if inner in fields:
            return col
    if col in fields:
        return col
    return None


def _match_table_conf(tables, database: str, schema: str, table: str):
    """Find the best-matching table config by specificity: full > schema > name-only."""
    table_only = None
    schema_table = None
    full = None

    for t in tables:
        if t.name != table:
            continue
        if t.database == database and t.schema_ == schema:
            full = t
        elif t.database == "" and t.schema_ == schema:
            schema_table = t
        elif t.database == "" and t.schema_ == "":
            table_only = t

    return full or schema_table or table_only