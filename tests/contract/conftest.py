import os
from urllib.parse import urlparse

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--target",
        action="store",
        default=os.environ.get("PREST_CONTRACT_TARGET", "go"),
        choices=("go", "python"),
        help="Contract target to test: go or python.",
    )
    parser.addoption(
        "--run-destructive-contract",
        action="store_true",
        default=False,
        help="Run contract cases that mutate seeded PostgreSQL state.",
    )


@pytest.fixture(scope="session")
def contract_target(request):
    return request.config.getoption("--target")


@pytest.fixture(scope="session")
def run_destructive_contract(request):
    return request.config.getoption("--run-destructive-contract")


def _env_for(target: str, server: str) -> str:
    env = {
        "go": {
            "default": "PREST_TEST_URL",
            "multicluster": "PREST_MULTICLUSTER_TEST_URL",
            "auth": "PREST_AUTH_TEST_URL",
        },
        "python": {
            "default": "PY_PREST_TEST_URL",
            "multicluster": "PY_PREST_MULTICLUSTER_TEST_URL",
            "auth": "PY_PREST_AUTH_TEST_URL",
        },
    }[target][server]
    return env


@pytest.fixture(scope="session")
def base_url_for(contract_target):
    def resolve(server: str = "default") -> str:
        env = _env_for(contract_target, server)
        value = os.environ.get(env, "").strip().rstrip("/")
        if not value:
            pytest.skip(f"{env} not set for {contract_target} {server} contract target")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            pytest.fail(f"{env} must be an absolute HTTP URL, got {value!r}")
        return value

    return resolve
