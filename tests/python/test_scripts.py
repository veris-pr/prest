from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.postgres.scripts import ScriptParser, resolve_script_path, sanitize_param
from prest_py.settings.models import Settings


def _settings(**overrides) -> Settings:
    defaults = {
        "app_name": "test-prest",
        "debug": True,
        "http": {"host": "0.0.0.0", "port": 3000, "timeout": 60},
        "pg": {
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest-test",
        },
        "queries": {"location": str(Path("testdata/queries"))},
    }
    defaults.update(overrides)
    return Settings.model_validate(defaults)


# ---------------------------------------------------------------------------
# ScriptParser
# ---------------------------------------------------------------------------


def test_parser_simple_variable():
    parser = ScriptParser({"field1": "gopher"})
    sql, values = parser.parse("SELECT * FROM test7 WHERE name = '{{.field1}}'")
    assert sql == "SELECT * FROM test7 WHERE name = 'gopher'"
    assert values == []


def test_parser_sqlval_generates_placeholder():
    parser = ScriptParser({"field1": "gopher"})
    sql, values = parser.parse("SELECT * FROM test7 WHERE name = {{sqlVal \"field1\"}}")
    assert sql == "SELECT * FROM test7 WHERE name = $1"
    assert values == ["gopher"]


def test_parser_default_or_value():
    parser = ScriptParser({})
    sql, values = parser.parse(
        "SELECT * FROM test7 WHERE name = '{{defaultOrValue \"field1\" \"gopher\"}}'"
    )
    assert sql == "SELECT * FROM test7 WHERE name = 'gopher'"


def test_parser_default_or_value_existing():
    parser = ScriptParser({"field1": "existing"})
    sql, _ = parser.parse(
        "SELECT * FROM test7 WHERE name = '{{defaultOrValue \"field1\" \"default\"}}'"
    )
    assert sql == "SELECT * FROM test7 WHERE name = 'existing'"


def test_parser_in_format_single():
    parser = ScriptParser({"field1": "gopher"})
    sql, _ = parser.parse("SELECT * FROM test7 WHERE name IN {{inFormat \"field1\"}}")
    assert sql == "SELECT * FROM test7 WHERE name IN ('gopher')"


def test_parser_in_format_list():
    parser = ScriptParser({"field1": ["a", "b", "c"]})
    sql, _ = parser.parse("SELECT * FROM test7 WHERE name IN {{inFormat \"field1\"}}")
    assert sql == "SELECT * FROM test7 WHERE name IN ('a', 'b', 'c')"


def test_parser_limit_offset():
    parser = ScriptParser({})
    sql, _ = parser.parse("SELECT * FROM test7 {{limitOffset \"1\" \"10\"}}")
    assert sql == "SELECT * FROM test7 LIMIT 10 OFFSET(1 - 1) * 10"


def test_parser_index_header():
    parser = ScriptParser({"header": {"X-Application": "myapp"}})
    sql, _ = parser.parse("SELECT '{{index .header \"X-Application\"}}'")
    assert sql == "SELECT 'myapp'"


def test_parser_header_lookup_is_case_insensitive():
    parser = ScriptParser({"header": {"x-application": "myapp"}})
    sql, _ = parser.parse("SELECT '{{index .header \"X-Application\"}}'")
    assert sql == "SELECT 'myapp'"


def test_parser_is_set_uses_go_boolean_format():
    parser = ScriptParser({"field1": "value"})
    sql, _ = parser.parse('{{isSet "field1"}} {{isSet "missing"}}')
    assert sql == "true false"


def test_parser_split_uses_literal_argument():
    parser = ScriptParser({"a,b": "must-not-be-used"})
    sql, _ = parser.parse('{{split "a,b" ","}}')
    assert sql == "[a b]"


def test_parser_sqllist():
    parser = ScriptParser({"items": ["a", "b"]})
    sql, values = parser.parse("SELECT * FROM t WHERE x IN {{sqlList \"items\"}}")
    assert sql == "SELECT * FROM t WHERE x IN ($1, $2)"
    assert values == ["a", "b"]


def test_parser_sqlval_multiple():
    parser = ScriptParser({"f1": "a", "f2": "b"})
    sql, values = parser.parse(
        "SELECT * FROM t WHERE x = {{sqlVal \"f1\"}} AND y = {{sqlVal \"f2\"}}"
    )
    assert sql == "SELECT * FROM t WHERE x = $1 AND y = $2"
    assert values == ["a", "b"]


# ---------------------------------------------------------------------------
# sanitize_param
# ---------------------------------------------------------------------------


def test_sanitize_param_safe():
    assert sanitize_param("hello.world") == "hello.world"
    assert sanitize_param("user@example") == "user@example"


def test_sanitize_param_unsafe():
    assert sanitize_param("'; DROP TABLE--") == ""


# ---------------------------------------------------------------------------
# resolve_script_path
# ---------------------------------------------------------------------------


def test_resolve_script_get():
    path = resolve_script_path("GET", "fulltable", "get_all", str(Path("testdata/queries")))
    assert path is not None
    assert path.endswith("get_all.read.sql")


def test_resolve_script_post():
    path = resolve_script_path("POST", "fulltable", "write_all", str(Path("testdata/queries")))
    assert path is not None
    assert path.endswith("write_all.write.sql")


def test_resolve_script_delete():
    path = resolve_script_path("DELETE", "fulltable", "delete_all", str(Path("testdata/queries")))
    assert path is not None
    assert path.endswith("delete_all.delete.sql")


def test_resolve_script_missing():
    path = resolve_script_path("GET", "fulltable", "nonexistent", str(Path("testdata/queries")))
    assert path is None


def test_resolve_script_invalid_method():
    import pytest

    with pytest.raises(ValueError, match="invalid http method"):
        resolve_script_path("OPTIONS", "fulltable", "get_all", str(Path("testdata/queries")))


def test_resolve_script_path_traversal():
    import pytest

    with pytest.raises(ValueError, match="path traversal"):
        resolve_script_path("GET", "../../etc/passwd", "get_all", str(Path("testdata/queries")))


def test_resolve_script_path_blocks_sibling_prefix(tmp_path):
    import pytest

    base = tmp_path / "queries"
    sibling = tmp_path / "queries_evil"
    base.mkdir()
    sibling.mkdir()
    (sibling / "steal.read.sql").write_text("SELECT 1", encoding="utf-8")

    with pytest.raises(ValueError, match="path traversal"):
        resolve_script_path("GET", "../queries_evil", "steal", str(base))


def test_resolve_script_path_rejects_directory(tmp_path):
    base = tmp_path / "queries"
    target = base / "fulltable" / "folder.read.sql"
    target.mkdir(parents=True)

    assert resolve_script_path("GET", "fulltable", "folder", str(base)) is None


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_script_get_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/_QUERIES/fulltable/get_all?field1=gopher")

    assert response.status_code == 503


def test_script_missing_script():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/_QUERIES/fulltable/nonexistent?field1=x")

    assert response.status_code == 400
    assert "could not get script" in response.json()["error"].lower()


def test_script_missing_folder():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/_QUERIES/nonexistent/get_all?field1=x")

    assert response.status_code == 400


def test_script_database_prefix_unregistered():
    settings = _settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest-test",
            "single": False,
        },
        databases=[{"alias": "known-db", "host": "host-a", "database": "db_a"}],
        queries={"location": str(Path("testdata/queries"))},
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/_QUERIES/unknown-db/fulltable/get_all?field1=x")

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()