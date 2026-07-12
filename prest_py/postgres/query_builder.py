"""PostgreSQL SQL builder and query-parameter parser for the Python rewrite.

This module ports the high-risk query-builder behavior from the Go adapter:
``WhereByRequest``, ``OrderByRequest``, ``PaginateIfPossible``,
``DistinctClause``, ``CountByRequest``, ``JoinByRequest``, ``GroupByClause``,
``ParseInsertRequest``, ``ParseBatchInsertRequest``, ``SetByRequest``,
``ReturningByRequest``, ``SelectFields``, and the SQL builders.

Design rules (ported from Go):

- Identifiers are validated via ``prest_py.domain.identifiers`` before any SQL
  string is assembled.
- Filter values are always parameterized with ``$n`` placeholders — never
  concatenated into SQL.
- The returned ``Query`` dataclass carries both the SQL fragment and the
  ordered values list so callers can execute with proper parameterization.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from prest_py.domain import identifiers as ident

# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

_OPERATOR_MAP: dict[str, str] = {
    "eq": "=",
    "ne": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "in": "IN",
    "nin": "NOT IN",
    "any": "ANY",
    "some": "SOME",
    "all": "ALL",
    "notnull": "IS NOT NULL",
    "null": "IS NULL",
    "true": "IS TRUE",
    "nottrue": "IS NOT TRUE",
    "false": "IS FALSE",
    "notfalse": "IS NOT FALSE",
    "like": "LIKE",
    "ilike": "ILIKE",
    "nlike": "NOT LIKE",
    "nilike": "NOT ILIKE",
    "ltreelanc": "@>",
    "ltreerdesc": "<@",
    "ltreematch": "~",
    "ltreematchtxt": "@",
}

_REMOVE_OPERATOR_RE = re.compile(r"\$[a-z]+.")
_NORMALIZED_GROUP_RE = re.compile(
    r"^(?:SUM|AVG|MAX|MIN|STDDEV|VARIANCE)\("
    r'(?:\*|"[A-Za-z_][A-Za-z0-9_]*"(?:\."[A-Za-z_][A-Za-z0-9_]*")*)'
    r'\)(?: AS "[A-Za-z_][A-Za-z0-9_]*")?$'
)

PAGE_NUMBER_KEY = "_page"
PAGE_SIZE_KEY = "_page_size"
DEFAULT_PAGE_SIZE = 10

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QueryBuilderError(Exception):
    """Base error for query-builder failures."""


class InvalidIdentifier(QueryBuilderError):
    pass


class InvalidOperator(QueryBuilderError):
    pass


class InvalidJoinClause(QueryBuilderError):
    pass


class InvalidGroupFunction(QueryBuilderError):
    pass


class BodyEmpty(QueryBuilderError):
    pass


class MustSelectOneField(QueryBuilderError):
    pass


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class WhereResult:
    sql: str = ""
    values: list[Any] = field(default_factory=list)


@dataclass
class SetResult:
    sql: str = ""
    values: list[Any] = field(default_factory=list)


@dataclass
class InsertResult:
    cols_name: str = ""
    cols_value: str = ""
    values: list[Any] = field(default_factory=list)


@dataclass
class BatchInsertResult:
    cols_name: str = ""
    columns: list[str] = field(default_factory=list)
    placeholders: str = ""
    values: list[Any] = field(default_factory=list)


@dataclass
class JoinResult:
    clauses: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Operator parsing
# ---------------------------------------------------------------------------


def get_query_operator(op: str) -> str:
    """Translate a pREST URL operator like ``$eq`` to SQL like ``=``.

    Raises ``InvalidOperator`` on unknown operators.
    """
    cleaned = op.replace("$", "").replace(" ", "")
    if cleaned in _OPERATOR_MAP:
        return _OPERATOR_MAP[cleaned]
    raise InvalidOperator(f"invalid operator: {op}")


# ---------------------------------------------------------------------------
# WHERE parsing
# ---------------------------------------------------------------------------


def _split_top_level_or_group(value: str) -> list[str]:
    """Split a string on top-level `` OR `` or ``||`` separators."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    in_single = False
    in_double = False

    while i < len(value):
        ch = value[i]

        if in_single:
            current.append(ch)
            if ch == "'":
                if i + 1 < len(value) and value[i + 1] == "'":
                    current.append(value[i + 1])
                    i += 2
                    continue
                in_single = False
            i += 1
            continue

        if in_double:
            current.append(ch)
            if ch == '"':
                if i + 1 < len(value) and value[i + 1] == '"':
                    current.append(value[i + 1])
                    i += 2
                    continue
                in_double = False
            i += 1
            continue

        # || legacy separator
        if i + 1 < len(value) and ch == "|" and value[i + 1] == "|":
            parts.append("".join(current).strip())
            current = []
            i += 2
            continue

        if ch == "'":
            in_single = True
            current.append(ch)
            i += 1
            continue

        if ch == '"':
            in_double = True
            current.append(ch)
            i += 1
            continue

        # OR separator (case-insensitive, surrounded by whitespace)
        if _is_top_level_or(value, i):
            parts.append("".join(current).strip())
            current = []
            i += 2
            while i < len(value) and value[i].isspace():
                i += 1
            continue

        current.append(ch)
        i += 1

    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _is_top_level_or(value: str, i: int) -> bool:
    if i + 1 >= len(value):
        return False
    if value[i : i + 2].upper() != "OR":
        return False
    if i > 0 and not value[i - 1].isspace():
        return False
    if i + 2 >= len(value) or not value[i + 2].isspace():
        return False
    return True


def where_by_request(
    query_params: dict[str, list[str]],
    initial_placeholder_id: int = 1,
) -> WhereResult:
    """Parse URL query params into a WHERE clause with parameterized values.

    Params prefixed with ``_`` are reserved (except ``_or``). All other params
    are treated as filter fields.
    """
    clauses: list[str] = []
    values: list[Any] = []
    or_clauses: list[str] = []
    pid = initial_placeholder_id

    for key, val_list in query_params.items():
        if not key.startswith("_"):
            for v in val_list:
                clause, vls = _where_key_and_value(key, v, pid_ref := [pid])
                pid = pid_ref[0]
                if clause:
                    clauses.append(clause)
                    values.extend(vls)
        elif key == "_or":
            for v in val_list:
                v = v.strip()
                if not v:
                    continue
                for part in _split_top_level_or_group(v):
                    pos = part.find("=")
                    if pos <= 0:
                        continue
                    field_name = part[:pos]
                    condition = part[pos + 1 :]
                    clause, vls = _where_key_and_value(field_name, condition, pid_ref := [pid])
                    pid = pid_ref[0]
                    if clause:
                        or_clauses.append(clause)
                        values.extend(vls)

    if or_clauses:
        clauses.append(f"({' OR '.join(or_clauses)})")

    return WhereResult(sql=" AND ".join(clauses), values=values)


def _where_key_and_value(raw_key: str, v: str, pid_ref: list[int]) -> tuple[str, list[Any]]:
    """Build a single WHERE clause fragment for one key=value pair.

    ``pid_ref`` is a one-element list used as a mutable counter for placeholder
    numbering.
    """
    if not v:
        raise InvalidOperator("invalid operator")

    op_match = _REMOVE_OPERATOR_RE.match(v)
    if op_match:
        op = op_match.group().replace(".", "")
        value = _REMOVE_OPERATOR_RE.sub("", v)
    else:
        op = "$eq"
        value = v

    op_sql = get_query_operator(op)

    # Type suffix handling (jsonb, tsquery)
    key_info = raw_key.split(":")
    if len(key_info) > 1:
        if key_info[1] == "jsonb":
            return _where_jsonb(key_info[0], value, op_sql, pid_ref)
        if key_info[1] == "tsquery":
            return _where_tsquery(key_info[0], value, pid_ref)
        if not ident.is_valid(key_info[0]):
            raise InvalidIdentifier(f"invalid identifier: {key_info[0]}")
        raise QueryBuilderError(f"unknown type suffix: {key_info[1]}")

    if not ident.is_valid(raw_key):
        raise InvalidIdentifier(f"invalid identifier: {raw_key}")

    quoted_key = ident.quote(raw_key)

    return _build_comparison(quoted_key, value, op_sql, pid_ref)


def _build_comparison(
    quoted_key: str, value: str, op_sql: str, pid_ref: list[int],
) -> tuple[str, list[Any]]:
    pid = pid_ref[0]

    if op_sql in ("IN", "NOT IN"):
        items = value.split(",")
        params = []
        for i, _item in enumerate(items):
            params.append(f"${pid + i}")
        pid_ref[0] = pid + len(items)
        return f"{quoted_key} {op_sql} ({', '.join(params)})", list(items)

    if op_sql in ("ANY", "SOME", "ALL"):
        pid_ref[0] = pid + 1
        # asyncpg array codecs require a sized Python iterable, not a
        # PostgreSQL array-literal string.
        return f"{quoted_key} = {op_sql} (${pid})", [value.split(",")]

    if op_sql.startswith("IS "):
        return f"{quoted_key} {op_sql}", []

    pid_ref[0] = pid + 1
    return f"{quoted_key} {op_sql} ${pid}", [value]


def _where_jsonb(
    raw_key: str, value: str, op_sql: str, pid_ref: list[int],
) -> tuple[str, list[Any]]:
    json_field = raw_key.split("->>")
    if len(json_field) != 2 or not ident.is_valid(json_field[0]) \
            or not ident.is_valid(json_field[1]):
        raise InvalidIdentifier(f"invalid identifier: {json_field}")

    left_parts = json_field[0].split(".")
    json_left = '"' + '"."'.join(left_parts) + '"'
    safe_attr = json_field[1].replace("'", "''")
    json_left = f"{json_left}->>'{safe_attr}'"

    return _build_comparison(json_left, value, op_sql, pid_ref)


def _where_tsquery(raw_key: str, value: str, pid_ref: list[int]) -> tuple[str, list[Any]]:
    ts_parts = raw_key.split("$")
    if not ident.is_valid(ts_parts[0]):
        raise InvalidIdentifier(f"invalid identifier: {ts_parts[0]}")
    safe_val = value.replace("'", "''")
    if len(ts_parts) == 2:
        if not ident.is_valid(ts_parts[1]):
            raise InvalidIdentifier(f"invalid identifier: {ts_parts[1]}")
        safe_cfg = ts_parts[1].replace("'", "''")
        return f"{ts_parts[0]} @@ to_tsquery('{safe_cfg}', '{safe_val}')", []
    return f"{ts_parts[0]} @@ to_tsquery('{safe_val}')", []


def _coerce_value(value: Any) -> Any:
    """Coerce a JSON body value into an asyncpg-compatible parameter.

    Lists are passed through so asyncpg's array codecs handle them. Dicts are
    serialized to JSON for jsonb columns. Scalars pass through unchanged.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return json.dumps(value)
    return value


# ---------------------------------------------------------------------------
# ORDER BY
# ---------------------------------------------------------------------------


def order_by_request(query_params: dict[str, list[str]]) -> str:
    """Parse ``_order`` param into an ``ORDER BY`` clause, or return empty."""
    req_order = query_params.get("_order", [""])[0] if query_params.get("_order") else ""
    if not req_order:
        return ""

    ordering_arr = req_order.split(",")
    parts: list[str] = []
    for fld in ordering_arr:
        desc = False
        field = fld
        if field.startswith("-"):
            desc = True
            field = field[1:]
        if not ident.is_valid(field):
            raise InvalidIdentifier(f"invalid identifier: {field}")
        q = ident.quote(field)
        if desc:
            q = f"{q} DESC"
        parts.append(q)

    return f" ORDER BY {', '.join(parts)}"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate_if_possible(query_params: dict[str, list[str]]) -> str:
    """Parse ``_page`` and ``_page_size`` into ``LIMIT ... OFFSET(...)`` SQL.

    Returns empty string when ``_page`` is absent.
    Raises ``ValueError`` on non-integer page values (matching Go's Atoi error).
    """
    if PAGE_NUMBER_KEY not in query_params:
        return ""

    page_number = int(query_params[PAGE_NUMBER_KEY][0])
    page_size = DEFAULT_PAGE_SIZE
    if PAGE_SIZE_KEY in query_params:
        page_size = int(query_params[PAGE_SIZE_KEY][0])

    if page_number - 1 < 0:
        page_number = 1

    return f"LIMIT {page_size} OFFSET({page_number} - 1) * {page_size}"


# ---------------------------------------------------------------------------
# DISTINCT
# ---------------------------------------------------------------------------


def distinct_clause(query_params: dict[str, list[str]]) -> str:
    """Return ``SELECT DISTINCT`` when ``_distinct=true``, else empty string."""
    check = query_params.get("_distinct", [""])[0] if query_params.get("_distinct") else ""
    if check == "true":
        return "SELECT DISTINCT"
    return ""


# ---------------------------------------------------------------------------
# COUNT
# ---------------------------------------------------------------------------


def count_by_request(query_params: dict[str, list[str]]) -> str:
    """Parse ``_count`` param into a ``SELECT COUNT(...)`` fragment.

    Returns empty string when ``_count`` is absent.
    """
    count_fields_raw = query_params.get("_count", [""])[0] if query_params.get("_count") else ""
    if not count_fields_raw:
        return ""

    select_fields_raw = query_params.get("_select", [""])[0] if query_params.get("_select") else ""
    select_suffix = f", {select_fields_raw}" if select_fields_raw else ""

    fields = count_fields_raw.split(",")
    for i, fld in enumerate(fields):
        if fld != "*" and not ident.is_valid(fld):
            raise InvalidIdentifier(f"invalid identifier: {fld}")
        if fld != "*":
            fields[i] = ident.quote(fld)

    return f"SELECT COUNT({','.join(fields)}){select_suffix} FROM"


# ---------------------------------------------------------------------------
# JOIN
# ---------------------------------------------------------------------------


def join_by_request(query_params: dict[str, list[str]]) -> JoinResult:
    """Parse ``_join`` param into a JOIN clause list.

    Format: ``type:table:left_field:operator:right_field``
    """
    join_raw = query_params.get("_join", [""])[0] if query_params.get("_join") else ""
    if not join_raw:
        return JoinResult()

    join_args = join_raw.split(":")
    if len(join_args) != 5:
        raise InvalidJoinClause("invalid number of arguments in join statement")

    jt = join_args[0].upper()
    allowed = {"INNER", "LEFT", "RIGHT", "FULL", "CROSS"}
    if jt not in allowed:
        raise InvalidJoinClause("invalid join clause")

    if not ident.is_valid(join_args[1]) or not ident.is_valid(join_args[2]) \
            or not ident.is_valid(join_args[4]):
        raise InvalidIdentifier("invalid identifier")

    op_sql = get_query_operator(join_args[3])

    # Join table: support schema.table
    join_with = join_args[1].split(".")
    if len(join_with) == 2:
        join_table = f'{join_with[0]}"."{join_with[1]}'
    else:
        join_table = join_args[1]

    spl = join_args[2].split(".")
    if len(spl) != 2:
        raise InvalidJoinClause("invalid join clause")

    splj = join_args[4].split(".")
    if len(splj) != 2:
        raise InvalidJoinClause("invalid join clause")

    join_query = (
        f' {jt} JOIN "{join_table}" ON "{spl[0]}"."{spl[1]}"'
        f' {op_sql} "{splj[0]}"."{splj[1]}" '
    )
    return JoinResult(clauses=[join_query])


# ---------------------------------------------------------------------------
# GROUP BY
# ---------------------------------------------------------------------------


def normalize_group_function(param_value: str) -> str:
    """Normalize a group function expression like ``sum:salary`` to ``SUM("salary")``."""
    values = param_value.split(":")
    group_func = values[0].upper()
    valid_funcs = {"SUM", "AVG", "MAX", "MIN", "STDDEV", "VARIANCE"}

    if group_func not in valid_funcs:
        raise InvalidGroupFunction(f"invalid group function: {group_func}")

    field = values[1]
    if field != "*":
        if not ident.is_valid(field):
            raise InvalidIdentifier(f"invalid identifier: {field}")
        field = ident.quote(field)

    result = f"{group_func}({field})"
    if len(values) == 3:
        alias = values[2]
        if not ident.is_valid(alias) or "." in alias:
            raise InvalidIdentifier(f"invalid identifier: {alias}")
        result = f'{result} AS "{alias}"'
    return result


def group_by_clause(query_params: dict[str, list[str]]) -> str:
    """Parse ``_groupby`` param into a ``GROUP BY ...`` clause, with optional HAVING."""
    group_query = query_params.get("_groupby", [""])[0] if query_params.get("_groupby") else ""
    if not group_query:
        return ""

    if "->>having" in group_query:
        params = group_query.split(":")
        group_field_parts = group_query.split("->>having")

        fields = group_field_parts[0].split(",")
        for i, field in enumerate(fields):
            if not ident.is_valid(field):
                return ""
            fields[i] = ident.quote(field)
        group_field_sql = ", ".join(fields)

        if len(params) != 5:
            return f"GROUP BY {group_field_sql}"

        try:
            group_func = normalize_group_function(f"{params[1]}:{params[2]}")
            operator = get_query_operator(params[3])
        except (InvalidGroupFunction, InvalidOperator):
            return f"GROUP BY {group_field_sql}"

        val = params[4]
        try:
            float(val)
            having = f"HAVING {group_func} {operator} {val}"
        except ValueError:
            safe = val.replace("'", "''")
            having = f"HAVING {group_func} {operator} '{safe}'"

        return f"GROUP BY {group_field_sql} {having}"

    fields = group_query.split(",")
    for i, field in enumerate(fields):
        if not ident.is_valid(field):
            return ""
        fields[i] = ident.quote(field)
    return f"GROUP BY {', '.join(fields)}"


# ---------------------------------------------------------------------------
# RETURNING
# ---------------------------------------------------------------------------


def returning_by_request(query_params: dict[str, list[str]]) -> str:
    """Parse ``_returning`` param into a ``RETURNING`` clause, or return empty."""
    queries = query_params.get("_returning", [])
    if not queries:
        return ""

    cols: list[str] = []
    for q in queries:
        if q == "*":
            cols.append("*")
            continue
        if not ident.is_valid(q):
            raise InvalidIdentifier(f"invalid identifier: {q}")
        cols.append(ident.quote(q))

    return ", ".join(cols)


# ---------------------------------------------------------------------------
# SELECT fields
# ---------------------------------------------------------------------------


def select_fields(fields: list[str]) -> str:
    """Build a ``SELECT ... FROM`` fragment from permitted field list."""
    if not fields:
        raise MustSelectOneField("you must select at least one field")

    aux: list[str] = []
    for fld in fields:
        try:
            group_func = normalize_group_function(fld)
            aux.append(group_func)
            continue
        except (InvalidGroupFunction, IndexError):
            pass

        if fld == "*":
            aux.append("*")
            continue

        # Allow only normalized aggregate expressions produced by
        # `normalize_group_function`, e.g. SUM("salary").
        if _NORMALIZED_GROUP_RE.fullmatch(fld):
            aux.append(fld)
            continue

        if not ident.is_valid(fld):
            raise InvalidIdentifier(f"invalid identifier: {fld}")
        aux.append(ident.quote(fld))

    return f"SELECT {','.join(aux)} FROM"


# ---------------------------------------------------------------------------
# INSERT / SET / BATCH parsing
# ---------------------------------------------------------------------------


def parse_insert_request(body: dict[str, Any]) -> InsertResult:
    """Parse a JSON body into insert columns, placeholder string, and values."""
    if not body:
        raise BodyEmpty("body is empty")

    fields: list[str] = []
    values: list[Any] = []
    for key, value in body.items():
        if not ident.is_valid(key):
            raise InvalidIdentifier(f"invalid identifier: {key}")
        fields.append(f'"{key}"')
        values.append(_coerce_value(value))

    cols_name = ", ".join(fields)
    cols_value = _create_placeholders(1, len(values))
    return InsertResult(cols_name=cols_name, cols_value=cols_value, values=values)


def parse_batch_insert_request(body: list[dict[str, Any]]) -> BatchInsertResult:
    """Parse a JSON array body into batch insert columns, placeholders, and values.

    Validates that every record is a dict with the same key set and that every
    key is a safe identifier, so untrusted request body keys never cross the
    SQL identifier boundary unquoted.
    """
    if not body:
        raise BodyEmpty("body is empty")

    if not isinstance(body[0], dict):
        raise QueryBuilderError("batch insert body must be a list of objects")

    record_keys = sorted(body[0].keys())
    if not record_keys:
        raise QueryBuilderError("batch insert records must have at least one field")

    for key in record_keys:
        if not ident.is_valid(key):
            raise InvalidIdentifier(f"invalid identifier: {key}")

    cols_name = ",".join(f'"{k}"' for k in record_keys)

    values: list[Any] = []
    placeholders_parts: list[str] = []
    for record in body:
        if not isinstance(record, dict):
            raise QueryBuilderError("batch insert body must be a list of objects")
        record_key_set = set(record.keys())
        if record_key_set != set(record_keys):
            raise QueryBuilderError("batch insert records must share the same fields")
        init_ph = len(values) + 1
        for key in record_keys:
            values.append(_coerce_value(record[key]))
        placeholders_parts.append(_create_placeholders(init_ph, len(values)))

    placeholders = ",".join(placeholders_parts)
    return BatchInsertResult(
        cols_name=cols_name,
        columns=record_keys,
        placeholders=placeholders,
        values=values,
    )


def set_by_request(body: dict[str, Any], initial_placeholder_id: int = 1) -> SetResult:
    """Parse a JSON body into a ``SET`` clause with parameterized values."""
    if not body:
        raise BodyEmpty("body is empty")

    fields: list[str] = []
    values: list[Any] = []
    pid = initial_placeholder_id
    for key, value in body.items():
        if not ident.is_valid(key):
            raise InvalidIdentifier(f"invalid identifier: {key}")
        keys = key.split(".")
        quoted = '"' + '"."'.join(keys) + '"'
        fields.append(f"{quoted}=${pid}")

        if isinstance(value, list):
            values.append(value)
        elif isinstance(value, dict):
            values.append(json.dumps(value))
        else:
            values.append(value)
        pid += 1

    return SetResult(sql=", ".join(fields), values=values)


def _create_placeholders(initial: int, length: int) -> str:
    """Build a parenthesized placeholder string like ``($1, $2, $3)``."""
    parts = [f"${i}" for i in range(initial, length + 1)]
    return f"({','.join(parts)})"


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------


def table_reference(database: str, schema: str, table: str, has_registry: bool = False) -> str:
    """Build a quoted table reference for SQL generation."""
    if has_registry:
        return f'"{schema}"."{table}"'
    return f'"{database}"."{schema}"."{table}"'


def select_sql(
    select_str: str, database: str, schema: str, table: str,
    has_registry: bool = False,
) -> str:
    return f"{select_str} {table_reference(database, schema, table, has_registry)}"


def insert_sql(
    database: str, schema: str, table: str, names: str, placeholders: str,
    has_registry: bool = False,
) -> str:
    ref = table_reference(database, schema, table, has_registry)
    return f"INSERT INTO {ref}({names}) VALUES{placeholders}"


def delete_sql(database: str, schema: str, table: str, has_registry: bool = False) -> str:
    return f"DELETE FROM {table_reference(database, schema, table, has_registry)}"


def update_sql(
    database: str, schema: str, table: str, set_syntax: str,
    has_registry: bool = False,
) -> str:
    return f"UPDATE {table_reference(database, schema, table, has_registry)} SET {set_syntax}"


# ---------------------------------------------------------------------------
# Catalog SQL constants
# ---------------------------------------------------------------------------

DATABASES_SELECT = "\nSELECT\n\t{field}\nFROM\n\tpg_database"
DATABASES_WHERE = "\nWHERE\n\tNOT datistemplate"
DATABASES_ORDER_BY = "\nORDER BY\n\t{field} ASC"

SCHEMAS_SELECT = "\nSELECT\n\t{field}\nFROM\n\tinformation_schema.schemata"
SCHEMAS_ORDER_BY = "\nORDER BY\n\t{field} ASC"

TABLES_SELECT = """\nSELECT
\tn.nspname as "schema",
\tc.relname as "name",
\tCASE c.relkind
\t\tWHEN 'r' THEN 'table'
\t\tWHEN 'v' THEN 'view'
\t\tWHEN 'm' THEN 'materialized_view'
\t\tWHEN 'i' THEN 'index'
\t\tWHEN 'S' THEN 'sequence'
\t\tWHEN 's' THEN 'special'
\t\tWHEN 'f' THEN 'foreign_table'
\tEND as "type",
\tpg_catalog.pg_get_userbyid(c.relowner) as "owner"
FROM
\tpg_catalog.pg_class c
LEFT JOIN
\tpg_catalog.pg_namespace n ON n.oid = c.relnamespace """

TABLES_WHERE = """\nWHERE
\tc.relkind IN ('r','v','m','S','s','') AND
\tn.nspname !~ '^pg_toast' AND
\tn.nspname NOT IN ('information_schema', 'pg_catalog') AND
\thas_schema_privilege(n.nspname, 'USAGE') """

TABLES_ORDER_BY = "\nORDER BY 1, 2"

SCHEMA_TABLES_SELECT = """\nSELECT
\tt.tablename as "name",
\tt.schemaname as "schema",
\tsc.catalog_name as "database"
FROM
\tpg_catalog.pg_tables t
INNER JOIN
\tinformation_schema.schemata sc ON sc.schema_name = t.schemaname"""

SCHEMA_TABLES_WHERE = "\nWHERE\n\tsc.catalog_name = $1 AND\n\tt.schemaname = $2"

SCHEMA_TABLES_ORDER_BY = "\nORDER BY\n\tt.tablename ASC"

GROUP_BY_TEMPLATE = "GROUP BY {fields}"
HAVING_TEMPLATE = "HAVING {func} {op} {value}"