from __future__ import annotations

import re

_VALID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_valid(identifier: str) -> bool:
    """Return True if *identifier* is a valid SQL identifier or dotted path."""
    if not _VALID_RE.match(identifier):
        return False
    return all(0 < len(part) <= 63 for part in identifier.split("."))


def is_safe_segment(segment: str) -> bool:
    """Return True if *segment* is a safe single identifier for path params."""
    if not segment or len(segment) > 63:
        return False
    return bool(_SAFE_SEGMENT_RE.fullmatch(segment))


def quote(identifier: str) -> str:
    """Validate and return a safely quoted identifier path like ``"a"."b"``.

    Raises ``ValueError`` when the identifier is invalid.
    """
    if not is_valid(identifier):
        raise ValueError(f"invalid identifier: {identifier}")
    parts = identifier.split(".")
    quoted = [f'"{part.replace(chr(34), chr(34) * 2)}"' for part in parts]
    return ".".join(quoted)


def split_and_validate_csv(csv: str) -> list[str]:
    """Split a comma-separated list and validate each identifier.

    Returns an empty list for empty input. Raises ``ValueError`` on any
    invalid identifier.
    """
    if not csv:
        return []
    parts = csv.split(",")
    for part in parts:
        if not is_valid(part):
            raise ValueError(f"invalid identifier: {part}")
    return parts