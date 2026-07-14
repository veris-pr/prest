import pytest

from .helpers import ContractCase, assert_contract_case


PLATFORM_CASES = [
    ContractCase("health", "GET", "/_health", 200, source_ref="integration/controllers/health_test.go:TestCheckDBHealth"),
    ContractCase("ready", "GET", "/_ready", 200, source_ref="integration/controllers/ready_test.go:TestReadyEndpoint"),
    ContractCase("auth disabled", "POST", "/auth", 404, source_ref="integration/controllers/auth_test.go:TestAuthDisable"),
    ContractCase("auth enabled get", "GET", "/auth", 405, server="auth", source_ref="integration/controllers/auth_test.go:TestAuthEnable"),
    ContractCase("auth enabled missing credentials", "POST", "/auth", 401, server="auth", source_ref="integration/controllers/auth_test.go:TestAuthEnable"),
    ContractCase("multicluster default alias", "GET", "/prest-test/public/test", 200, server="multicluster", source_ref="integration/controllers/multicluster_test.go:TestMultiClusterSelect"),
    ContractCase("multicluster secondary alias", "GET", "/secondary-db/public/test", 200, server="multicluster", source_ref="integration/controllers/multicluster_test.go:TestMultiClusterSelect"),
]


@pytest.mark.parametrize("case", PLATFORM_CASES, ids=[case.id for case in PLATFORM_CASES])
def test_platform_contract(base_url_for, run_destructive_contract, case):
    assert_contract_case(base_url_for, run_destructive_contract, case)
