import pytest

from .helpers import ContractCase, assert_contract_case


CATALOG_CASES = [
    ContractCase("databases list", "GET", "/databases", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases filter", "GET", "/databases?datname=$eq.prest", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases order", "GET", "/databases?_order=datname", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases invalid order", "GET", "/databases?_order=$eq.prest", 400, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases pagination", "GET", "/databases?datname=$eq.prest&_page=1&_page_size=20", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases count", "GET", "/databases?_count=*", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases invalid where identifier", "GET", "/databases?0datname=prest", 400, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases invalid pagination", "GET", "/databases?datname=$eq.prest&_page=A", 400, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases unknown column", "GET", "/databases?datatata=$eq.test", 400, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases distinct", "GET", "/databases?_distinct=true", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("databases empty distinct tolerated", "GET", "/databases?_distinct", 200, source_ref="integration/controllers/catalog_test.go:TestGetDatabases"),
    ContractCase("schemas list", "GET", "/schemas", 200, body_contains=("public",), source_ref="integration/controllers/catalog_test.go:TestGetSchemas"),
    ContractCase("schemas filter", "GET", "/schemas?schema_name=$eq.public", 200, body_contains=("public",), source_ref="integration/controllers/catalog_test.go:TestGetSchemas"),
    ContractCase("schemas invalid order", "GET", "/schemas?schema_name=$eq.public&_order=$eq.schema_name", 400, body_contains=("invalid identifier",), source_ref="integration/controllers/catalog_test.go:TestGetSchemas"),
    ContractCase("schemas count", "GET", "/schemas?_count=*", 200, body_contains=('"count"',), source_ref="integration/controllers/catalog_test.go:TestGetSchemas"),
    ContractCase("schemas invalid where identifier", "GET", "/schemas?0schema_name=$eq.public", 400, body_contains=("invalid identifier",), source_ref="integration/controllers/catalog_test.go:TestGetSchemas"),
    ContractCase("schemas unknown column", "GET", "/schemas?schematame=$eq.test", 400, body_contains=("does not exist",), source_ref="integration/controllers/catalog_test.go:TestGetSchemas"),
    ContractCase("tables list", "GET", "/tables", 200, source_ref="integration/controllers/crud_test.go:TestGetTables"),
    ContractCase("tables filter", "GET", "/tables?c.relname=$eq.test", 200, source_ref="integration/controllers/crud_test.go:TestGetTables"),
    ContractCase("tables invalid where identifier", "GET", "/tables?0c.relname=$eq.test", 400, source_ref="integration/controllers/crud_test.go:TestGetTables"),
    ContractCase("tables invalid order identifier", "GET", "/tables?_order=0c.relname", 400, source_ref="integration/controllers/crud_test.go:TestGetTables"),
]


@pytest.mark.parametrize("case", CATALOG_CASES, ids=[case.id for case in CATALOG_CASES])
def test_catalog_contract(base_url_for, run_destructive_contract, case):
    assert_contract_case(base_url_for, run_destructive_contract, case)
