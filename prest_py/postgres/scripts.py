"""SQL script template parser for pREST _QUERIES endpoint.

Ports Go ``text/template`` behavior for the subset of template syntax used
by pREST scripts. Supports:

- ``{{.key}}`` — variable substitution from template data
- ``{{index .header "Key"}}`` — nested map access (headers)
- ``{{funcName "arg1" "arg2"}}`` — function call (defaultOrValue, inFormat,
  limitOffset, sqlVal, sqlList, ident, split, isSet, unEscape)

``sqlVal`` and ``sqlList`` are stateful — they collect parameter values and
generate ``$n`` placeholders for parameterized query execution.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from prest_py.domain.identifiers import quote as ident_quote

_TEMPLATE_BLOCK_RE = re.compile(r"\{\{(.*?)\}\}")
_FUNC_RE = re.compile(r'^(\w+)\s+(.*)$')
_STRING_ARG_RE = re.compile(r'"([^"]*)"')
_VAR_RE = re.compile(r"^\.(\w+)$")
_INDEX_RE = re.compile(r'^index\s+\.(\w+)\s+"([^"]*)"$')

_SAFE_PARAM_RE = re.compile(r"^[a-zA-Z0-9_.:@/\\ -]+$")


class ScriptParser:
    """Parse Go-style template syntax for pREST SQL scripts.

    Stateful: ``sqlVal`` and ``sqlList`` accumulate values and placeholder IDs.
    """

    def __init__(self, template_data: dict[str, Any]) -> None:
        self.template_data = template_data
        self.args: list[Any] = []
        self._next_placeholder = 0

    def parse(self, template_str: str) -> tuple[str, list[Any]]:
        """Parse template string, returning SQL and ordered parameter values."""
        self.args = []
        self._next_placeholder = 0

        def replacer(match: re.Match[str]) -> str:
            block = match.group(1).strip()
            return self._eval_block(block)

        sql = _TEMPLATE_BLOCK_RE.sub(replacer, template_str)
        return sql, self.args

    def _eval_block(self, block: str) -> str:
        # Variable access: .key
        var_match = _VAR_RE.match(block)
        if var_match:
            key = var_match.group(1)
            return str(self.template_data.get(key, ""))

        # Index access: index .header "Key"
        index_match = _INDEX_RE.match(block)
        if index_match:
            map_key = index_match.group(1)
            sub_key = index_match.group(2)
            container = self.template_data.get(map_key, {})
            if isinstance(container, dict):
                if sub_key in container:
                    return str(container[sub_key])
                # HTTP header names are case-insensitive. Starlette normalizes
                # them to lowercase, while existing Go templates often use
                # canonical names such as `X-Application`.
                if map_key == "header":
                    folded = sub_key.casefold()
                    for key, value in container.items():
                        if str(key).casefold() == folded:
                            return str(value)
            return ""

        # Function call: funcName "arg1" "arg2"
        func_match = _FUNC_RE.match(block)
        if func_match:
            func_name = func_match.group(1)
            args_str = func_match.group(2)
            args = _STRING_ARG_RE.findall(args_str)
            return self._call_function(func_name, args)

        # Literal
        return block

    def _call_function(self, name: str, args: list[str]) -> str:
        if name == "sqlVal":
            return self._sql_val(args[0] if args else "")
        if name == "sqlList":
            return self._sql_list(args[0] if args else "")
        if name == "ident":
            key = args[0] if args else ""
            val = str(self.template_data.get(key, ""))
            return ident_quote(val)
        if name == "defaultOrValue":
            key = args[0] if args else ""
            default = args[1] if len(args) > 1 else ""
            if key not in self.template_data:
                self.template_data[key] = default
            return str(self.template_data[key])
        if name == "inFormat":
            key = args[0] if args else ""
            val = self.template_data.get(key)
            if isinstance(val, list):
                joined = "', '".join(str(v) for v in val)
                return f"('{joined}')"
            return f"('{val}')"
        if name == "limitOffset":
            page_str = args[0] if args else "1"
            size_str = args[1] if len(args) > 1 else "10"
            return _limit_offset(page_str, size_str)
        if name == "isSet":
            key = args[0] if args else ""
            return "true" if key in self.template_data else "false"
        if name == "unEscape":
            return unquote(args[0] if args else "")
        if name == "split":
            orig = args[0] if args else ""
            sep = args[1] if len(args) > 1 else ","
            # Go's split operates on the literal first argument; it does not
            # look that string up in TemplateData.
            return "[" + " ".join(orig.split(sep)) + "]"
        return ""

    def _sql_val(self, key: str) -> str:
        val = self.template_data.get(key)
        self.args.append(val)
        self._next_placeholder += 1
        return f"${self._next_placeholder}"

    def _sql_list(self, key: str) -> str:
        val = self.template_data.get(key)
        if isinstance(val, list):
            ph = []
            for v in val:
                self.args.append(v)
                self._next_placeholder += 1
                ph.append(f"${self._next_placeholder}")
            return f"({', '.join(ph)})"
        self.args.append(val)
        self._next_placeholder += 1
        return f"(${self._next_placeholder})"


def _limit_offset(page_str: str, size_str: str) -> str:
    try:
        page_num = int(page_str)
        page_size = int(size_str)
    except ValueError:
        return ""
    if page_num - 1 < 0:
        page_num = 1
    return f"LIMIT {page_size} OFFSET({page_num} - 1) * {page_size}"


def sanitize_param(value: str) -> str:
    """Sanitize script parameter value to prevent injection.

    Only allows alphanumeric, underscore, dots, colons, at signs, slashes,
    backslashes, spaces, and hyphens — matching Go's safeScriptParamRegex.
    """
    if _SAFE_PARAM_RE.match(value):
        return value
    return ""


# Script method → suffix mapping
METHOD_SUFFIXES = {
    "GET": ".read.sql",
    "POST": ".write.sql",
    "PUT": ".update.sql",
    "PATCH": ".update.sql",
    "DELETE": ".delete.sql",
}


def resolve_script_path(
    method: str,
    queries_location: str,
    script_name: str,
    base_path: str,
) -> str | None:
    """Resolve script file path for the given HTTP method.

    Returns the full path if the file exists, or None if not found.
    Raises ValueError for unsupported methods.
    """
    suffix = METHOD_SUFFIXES.get(method.upper())
    if not suffix:
        raise ValueError(f"invalid http method {method}")

    base = Path(base_path).resolve()
    target = (base / queries_location / f"{script_name}{suffix}").resolve()

    # `Path.is_relative_to` enforces path-component containment, unlike string
    # prefix checks (`queries_evil` must not be accepted as inside `queries`).
    if not target.is_relative_to(base):
        raise ValueError("path traversal detected")

    if not target.is_file():
        return None

    return str(target)