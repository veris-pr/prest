import pytest

from .helpers import ContractCase, assert_contract_case


SCRIPT_CASES = [
    ContractCase("script get", "GET", "/_QUERIES/fulltable/get_all?field1=gopher", 200, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script funcs", "GET", "/_QUERIES/fulltable/funcs", 200, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script get header", "GET", "/_QUERIES/fulltable/get_header", 200, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script missing folder", "DELETE", "/_QUERIES/fullnon/delete_all?field1=trump", 400, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script missing file", "DELETE", "/_QUERIES/fulltable/some_com_all?field1=trump", 400, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script invalid sql", "POST", "/_QUERIES/fulltable/create_table?field1=test7", 400, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script post", "POST", "/_QUERIES/fulltable/write_all?field1=gopherzin&field2=pereira", 200, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script put", "PUT", "/_QUERIES/fulltable/put_all?field1=trump&field2=pereira", 200, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script patch", "PATCH", "/_QUERIES/fulltable/patch_all?field1=temer&field2=trump", 200, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script delete", "DELETE", "/_QUERIES/fulltable/delete_all?field1=trump", 200, destructive=True, source_ref="integration/controllers/scripts_test.go:TestExecuteFromScripts"),
    ContractCase("script database prefix", "GET", "/_QUERIES/prest-test/fulltable/get_all?field1=gopher", 200, source_ref="integration/controllers/ready_test.go:TestReadyWithScriptRoute"),
    ContractCase("xml renderer", "GET", "/schemas?_count=*&_renderer=xml", 200, body_contains=("<objects><object><count>", "</count></object></objects>"), source_ref="integration/controllers/scripts_test.go:TestRenderWithXML"),
]


@pytest.mark.parametrize("case", SCRIPT_CASES, ids=[case.id for case in SCRIPT_CASES])
def test_scripts_contract(base_url_for, run_destructive_contract, case):
    assert_contract_case(base_url_for, run_destructive_contract, case)
