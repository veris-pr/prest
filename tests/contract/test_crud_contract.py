import pytest

from .helpers import ContractCase, assert_contract_case

DATABASES = ("prest-test", "secondary-db")


def _for_databases(name, method, path_template, status, **kwargs):
    return [
        ContractCase(
            f"{name} ({database})",
            method,
            path_template.format(database=database),
            status,
            **kwargs,
        )
        for database in DATABASES
    ]


READ_CASES = [
    *_for_databases("schema table listing", "GET", "/{database}/public", 200, source_ref="integration/controllers/crud_test.go:TestGetTablesByDatabaseAndSchema"),
    *_for_databases("schema table listing invalid where", "GET", "/{database}/public?0t.tablename=$eq.test", 400, source_ref="integration/controllers/crud_test.go:TestGetTablesByDatabaseAndSchema"),
    *_for_databases("select array table", "GET", "/{database}/public/testarray", 200, body_contains=("Gohan", "Goten"), source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select case-sensitive table", "GET", "/{database}/public/Reply", 200, body_contains=("prest tester",), source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select count list", "GET", "/{database}/public/view_test?_count=player", 200, body_contains=('"count"',), source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select count first", "GET", "/{database}/public/view_test?_count=player&_count_first=true", 200, body_contains=('"count":1',), source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select join", "GET", "/{database}/public/test?_join=inner:test8:test8.nameforjoin:$eq:test.name", 200, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select group by having", "GET", "/{database}/public/test_group_by_table?_select=age,sum:salary&_groupby=age->>having:sum:salary:$gt:3000", 200, body_contains=('"age": 19', '"sum": 7997'), source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select invalid join", "GET", "/{database}/public/test?_join=inner:test2:test2.name", 400, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select invalid where identifier", "GET", "/{database}/public/test?0name=$eq.test", 400, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select invalid order", "GET", "/{database}/public/test?_order=0name", 400, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select invalid pagination", "GET", "/{database}/public/test?name=$eq.test&_page=A", 400, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    *_for_databases("select invalid count", "GET", "/{database}/public/test?_count=0name", 400, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    ContractCase("select invalid configured db", "GET", "/invalid/public/view_test?_count=0celphone", 400, source_ref="integration/controllers/crud_test.go:TestSelectFromTables"),
    ContractCase("show table", "GET", "/show/prest-test/public/test", 200, source_ref="integration/controllers/crud_test.go:TestShowTable"),
    ContractCase("show invalid db", "GET", "/show/invalid/public/test2", 400, source_ref="integration/controllers/crud_test.go:TestShowTable"),
]

WRITE_CASES = [
    ContractCase("insert row", "POST", "/prest-test/public/test", 201, json_body={"name": "prest-test"}, destructive=True, source_ref="integration/controllers/crud_test.go:TestInsertInTables"),
    ContractCase("insert invalid database identifier", "POST", "/0prest-test/public/test", 400, json_body={"name": "prest-test"}, destructive=True, source_ref="integration/controllers/crud_test.go:TestInsertInTables"),
    ContractCase("insert invalid schema", "POST", "/prest-test/0public/test", 404, json_body={"name": "prest-test"}, destructive=True, source_ref="integration/controllers/crud_test.go:TestInsertInTables"),
    ContractCase("batch insert", "POST", "/batch/prest-test/public/test", 201, json_body=[{"name": "bprest"}, {"name": "aprest"}], destructive=True, source_ref="integration/controllers/crud_test.go:TestBatchInsertInTables"),
    ContractCase("batch insert copy", "POST", "/batch/prest-test/public/test", 201, json_body=[{"name": "cprest"}, {"name": "dprest"}], headers={"Prest-Batch-Method": "copy"}, body_exact="", destructive=True, source_ref="integration/controllers/crud_test.go:TestBatchInsertInTables"),
    ContractCase("update with returning", "PUT", "/prest-test/public/test?id=1&_returning=*", 200, json_body={"name": "prest"}, destructive=True, source_ref="integration/controllers/crud_test.go:TestUpdateFromTable"),
    ContractCase("patch with returning", "PATCH", "/prest-test/public/test?id=2&_returning=name", 200, json_body={"name": "prest"}, destructive=True, source_ref="integration/controllers/crud_test.go:TestUpdateFromTable"),
    ContractCase("delete with where", "DELETE", "/prest-test/public/test?name=$eq.test", 200, destructive=True, source_ref="integration/controllers/crud_test.go:TestDeleteFromTable"),
]


@pytest.mark.parametrize("case", READ_CASES, ids=[case.id for case in READ_CASES])
def test_crud_read_contract(base_url_for, run_destructive_contract, case):
    assert_contract_case(base_url_for, run_destructive_contract, case)


@pytest.mark.parametrize("case", WRITE_CASES, ids=[case.id for case in WRITE_CASES])
def test_crud_write_contract(base_url_for, run_destructive_contract, case):
    assert_contract_case(base_url_for, run_destructive_contract, case)
