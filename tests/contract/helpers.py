from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


@dataclass(frozen=True)
class ContractCase:
    name: str
    method: str
    path: str
    status: int
    server: str = "default"
    json_body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body_contains: tuple[str, ...] = ()
    body_exact: str | None = None
    destructive: bool = False
    source_ref: str = ""

    @property
    def id(self) -> str:
        return self.name


def request_case(base_url: str, case: ContractCase) -> tuple[int, str, Mapping[str, str]]:
    data = None
    headers = dict(case.headers)
    if case.json_body is not None:
        data = json.dumps(case.json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = Request(
        f"{base_url}{case.path}",
        data=data,
        headers=headers,
        method=case.method,
    )

    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310 - contract target is caller-supplied test URL
            body = resp.read().decode("utf-8")
            return resp.status, body, dict(resp.headers)
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, body, dict(exc.headers)


def assert_contract_case(base_url_for, run_destructive_contract: bool, case: ContractCase) -> None:
    if case.destructive and not run_destructive_contract:
        pytest.skip("destructive contract case; pass --run-destructive-contract to run")

    base_url = base_url_for(case.server)
    status, body, _headers = request_case(base_url, case)

    assert status == case.status, _failure_context(case, body)
    if case.body_exact is not None:
        assert body == case.body_exact, _failure_context(case, body)
    for expected in case.body_contains:
        assert expected in body, _failure_context(case, body)


def _failure_context(case: ContractCase, body: str) -> str:
    ref = f" source={case.source_ref}" if case.source_ref else ""
    return f"case={case.name!r} {case.method} {case.path}{ref}\nbody={body[:1000]}"
