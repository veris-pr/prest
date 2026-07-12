from __future__ import annotations

from urllib.parse import parse_qs

import pytest

from prest_py.postgres.query_builder import (
    BodyEmpty,
    InvalidGroupFunction,
    InvalidIdentifier,
    InvalidJoinClause,
    InvalidOperator,
    MustSelectOneField,
    QueryBuilderError,
    count_by_request,
    delete_sql,
    distinct_clause,
    get_query_operator,
    group_by_clause,
    insert_sql,
    join_by_request,
    normalize_group_function,
    order_by_request,
    paginate_if_possible,
    parse_batch_insert_request,
    parse_insert_request,
    returning_by_request,
    select_fields,
    select_sql,
    set_by_request,
    table_reference,
    update_sql,
    where_by_request,
)


def _p(qs: str) -> dict[str, list[str]]:
    """Helper: parse a query string into the dict[str, list[str]] shape used by the builder."""
    return parse_qs(qs, keep_blank_values=True)


# ---------------------------------------------------------------------------
# get_query_operator
# ---------------------------------------------------------------------------


def test_get_query_operator_known():
    assert get_query_operator("$eq") == "="
    assert get_query_operator("$gt") == ">"
    assert get_query_operator("$in") == "IN"
    assert get_query_operator("$like") == "LIKE"
    assert get_query_operator("$null") == "IS NULL"


def test_get_query_operator_unknown():
    with pytest.raises(InvalidOperator):
        get_query_operator("$bogus")


# ---------------------------------------------------------------------------
# where_by_request
# ---------------------------------------------------------------------------


def test_where_simple_eq():
    result = where_by_request(_p("name=$eq.test"))
    assert result.sql == '"name" = $1'
    assert result.values == ["test"]


def test_where_implicit_eq():
    result = where_by_request(_p("name=test"))
    assert result.sql == '"name" = $1'
    assert result.values == ["test"]


def test_where_gt():
    result = where_by_request(_p("age=$gt.18"))
    assert result.sql == '"age" > $1'
    assert result.values == ["18"]


def test_where_in():
    result = where_by_request(_p("id=$in.1,2,3"))
    assert result.sql == '"id" IN ($1, $2, $3)'
    assert result.values == ["1", "2", "3"]


def test_where_null():
    result = where_by_request(_p("name=$null"))
    assert result.sql == '"name" IS NULL'
    assert result.values == []


def test_where_dotted_identifier():
    result = where_by_request(_p("c.relname=$eq.test"))
    assert result.sql == '"c"."relname" = $1'
    assert result.values == ["test"]


def test_where_invalid_identifier():
    with pytest.raises(InvalidIdentifier):
        where_by_request(_p("0name=$eq.test"))


def test_where_multiple_params():
    result = where_by_request(_p("name=$eq.test&age=$gt.18"))
    assert '"name" = $1' in result.sql
    assert '"age" > $2' in result.sql
    assert result.values == ["test", "18"]


def test_where_skips_reserved_params():
    result = where_by_request(_p("_page=1&name=$eq.test"))
    assert result.sql == '"name" = $1'
    assert result.values == ["test"]


# ---------------------------------------------------------------------------
# order_by_request
# ---------------------------------------------------------------------------


def test_order_by_ascending():
    result = order_by_request(_p("_order=name"))
    assert result == ' ORDER BY "name"'


def test_order_by_descending():
    result = order_by_request(_p("_order=-name"))
    assert result == ' ORDER BY "name" DESC'


def test_order_by_multiple():
    result = order_by_request(_p("_order=name,age"))
    assert '"name"' in result
    assert '"age"' in result


def test_order_by_invalid():
    with pytest.raises(InvalidIdentifier):
        order_by_request(_p("_order=0name"))


def test_order_by_empty():
    assert order_by_request(_p("_order=")) == ""


def test_order_by_absent():
    assert order_by_request(_p("")) == ""


# ---------------------------------------------------------------------------
# paginate_if_possible
# ---------------------------------------------------------------------------


def test_paginate_basic():
    result = paginate_if_possible(_p("_page=1&_page_size=10"))
    assert result == "LIMIT 10 OFFSET(1 - 1) * 10"


def test_paginate_default_size():
    result = paginate_if_possible(_p("_page=2"))
    assert result == "LIMIT 10 OFFSET(2 - 1) * 10"


def test_paginate_absent():
    assert paginate_if_possible(_p("")) == ""


def test_paginate_invalid_page():
    with pytest.raises(ValueError):
        paginate_if_possible(_p("_page=A"))


# ---------------------------------------------------------------------------
# distinct_clause
# ---------------------------------------------------------------------------


def test_distinct_true():
    assert distinct_clause(_p("_distinct=true")) == "SELECT DISTINCT"


def test_distinct_empty():
    assert distinct_clause(_p("_distinct=")) == ""


def test_distinct_absent():
    assert distinct_clause(_p("")) == ""


# ---------------------------------------------------------------------------
# count_by_request
# ---------------------------------------------------------------------------


def test_count_star():
    result = count_by_request(_p("_count=*"))
    assert "COUNT(*)" in result


def test_count_field():
    result = count_by_request(_p("_count=name"))
    assert 'COUNT("name")' in result


def test_count_invalid():
    with pytest.raises(InvalidIdentifier):
        count_by_request(_p("_count=0name"))


def test_count_absent():
    assert count_by_request(_p("")) == ""


# ---------------------------------------------------------------------------
# join_by_request
# ---------------------------------------------------------------------------


def test_join_valid():
    result = join_by_request(_p("_join=inner:test2:test2.name:$eq:test.name"))
    assert len(result.clauses) == 1
    clause = result.clauses[0]
    assert "INNER JOIN" in clause
    assert '"test2"' in clause
    assert "=" in clause
    assert '"test2"."name"' in clause
    assert '"test"."name"' in clause


def test_join_with_schema():
    result = join_by_request(_p("_join=inner:public.test2:test2.name:$eq:test.name"))
    assert len(result.clauses) == 1
    assert '"public"."test2"' in result.clauses[0]


def test_join_wrong_args():
    with pytest.raises(InvalidJoinClause):
        join_by_request(_p("_join=inner:test2:test2.name"))


def test_join_invalid_type():
    with pytest.raises(InvalidJoinClause):
        join_by_request(_p("_join=weird:test2:test2.name:$eq:test.name"))


def test_join_invalid_identifier():
    with pytest.raises(InvalidIdentifier):
        join_by_request(_p("_join=inner:0test2:test2.name:$eq:test.name"))


def test_join_absent():
    assert join_by_request(_p("")).clauses == []


# ---------------------------------------------------------------------------
# group_by_clause
# ---------------------------------------------------------------------------


def test_group_by_simple():
    result = group_by_clause(_p("_groupby=age"))
    assert result == 'GROUP BY "age"'


def test_group_by_multiple():
    result = group_by_clause(_p("_groupby=age,salary"))
    assert '"age"' in result
    assert '"salary"' in result


def test_group_by_with_having():
    result = group_by_clause(_p("_groupby=age->>having:sum:salary:$gt:3000"))
    assert 'GROUP BY "age"' in result
    assert "HAVING" in result
    assert "SUM" in result
    assert ">" in result
    assert "3000" in result


def test_group_by_invalid_returns_empty():
    result = group_by_clause(_p("_groupby=0name"))
    assert result == ""


def test_group_by_absent():
    assert group_by_clause(_p("")) == ""


# ---------------------------------------------------------------------------
# normalize_group_function
# ---------------------------------------------------------------------------


def test_normalize_sum():
    result = normalize_group_function("sum:salary")
    assert result == 'SUM("salary")'


def test_normalize_sum_with_alias():
    result = normalize_group_function("sum:salary:total")
    assert result == 'SUM("salary") AS "total"'


def test_normalize_invalid_func():
    with pytest.raises(InvalidGroupFunction):
        normalize_group_function("bogus:salary")


# ---------------------------------------------------------------------------
# returning_by_request
# ---------------------------------------------------------------------------


def test_returning_star():
    result = returning_by_request(_p("_returning=*"))
    assert result == "*"


def test_returning_fields():
    result = returning_by_request(_p("_returning=id&_returning=name"))
    assert '"id"' in result
    assert '"name"' in result


def test_returning_invalid():
    with pytest.raises(InvalidIdentifier):
        returning_by_request(_p("_returning=0bad"))


def test_returning_absent():
    assert returning_by_request(_p("")) == ""


# ---------------------------------------------------------------------------
# select_fields
# ---------------------------------------------------------------------------


def test_select_fields_simple():
    result = select_fields(["name", "age"])
    assert "SELECT" in result
    assert '"name"' in result
    assert '"age"' in result
    assert "FROM" in result


def test_select_fields_star():
    result = select_fields(["*"])
    assert "SELECT * FROM" == result


def test_select_fields_empty():
    with pytest.raises(MustSelectOneField):
        select_fields([])


def test_select_fields_with_group_function():
    result = select_fields(["sum:salary"])
    assert 'SUM("salary")' in result


def test_select_fields_accepts_pre_normalized_group_function():
    assert select_fields(['age', 'SUM("salary")']) == 'SELECT "age",SUM("salary") FROM'


# ---------------------------------------------------------------------------
# parse_insert_request
# ---------------------------------------------------------------------------


def test_parse_insert_simple():
    result = parse_insert_request({"name": "test"})
    assert result.cols_name == '"name"'
    assert result.cols_value == "($1)"
    assert result.values == ["test"]


def test_parse_insert_multiple():
    result = parse_insert_request({"name": "test", "age": 30})
    assert '"name"' in result.cols_name
    assert '"age"' in result.cols_name
    assert result.cols_value == "($1,$2)"
    assert "test" in result.values
    assert 30 in result.values


def test_parse_insert_array():
    result = parse_insert_request({"data": ["a", "b", "c"]})
    assert result.values == [["a", "b", "c"]]


def test_parse_insert_empty():
    with pytest.raises(BodyEmpty):
        parse_insert_request({})


def test_parse_insert_invalid_key():
    with pytest.raises(InvalidIdentifier):
        parse_insert_request({"0bad": "test"})


# ---------------------------------------------------------------------------
# parse_batch_insert_request
# ---------------------------------------------------------------------------


def test_parse_batch_insert_simple():
    result = parse_batch_insert_request([{"name": "a"}, {"name": "b"}])
    assert result.cols_name == '"name"'
    assert result.columns == ["name"]
    assert "($1)" in result.placeholders
    assert "($2)" in result.placeholders
    assert result.values == ["a", "b"]


def test_parse_batch_insert_empty():
    with pytest.raises(BodyEmpty):
        parse_batch_insert_request([])


def test_parse_batch_insert_invalid_key():
    with pytest.raises(InvalidIdentifier):
        parse_batch_insert_request([{"0bad": "a"}])


def test_parse_batch_insert_non_object_record():
    with pytest.raises(QueryBuilderError, match="list of objects"):
        parse_batch_insert_request(["not-an-object"])


def test_parse_batch_insert_heterogeneous_keys():
    with pytest.raises(QueryBuilderError, match="same fields"):
        parse_batch_insert_request([{"a": 1}, {"b": 2}])


def test_parse_batch_insert_array_value():
    result = parse_batch_insert_request([{"data": ["a", "b"]}])
    assert result.values == [["a", "b"]]


# ---------------------------------------------------------------------------
# set_by_request
# ---------------------------------------------------------------------------


def test_set_by_request_simple():
    result = set_by_request({"name": "test"})
    assert result.sql == '"name"=$1'
    assert result.values == ["test"]


def test_set_by_request_multiple():
    result = set_by_request({"name": "test", "age": 30})
    assert '"name"=$1' in result.sql
    assert '"age"=$2' in result.sql
    assert result.values == ["test", 30]


def test_set_by_request_empty():
    with pytest.raises(BodyEmpty):
        set_by_request({})


def test_set_by_request_invalid_key():
    with pytest.raises(InvalidIdentifier):
        set_by_request({"0bad": "test"})


def test_set_by_request_dict_value():
    result = set_by_request({"data": {"key": "val"}})
    assert result.values == ['{"key": "val"}']


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------


def test_table_reference_legacy():
    result = table_reference("prest-test", "public", "test", has_registry=False)
    assert result == '"prest-test"."public"."test"'


def test_table_reference_registry():
    result = table_reference("prest-test", "public", "test", has_registry=True)
    assert result == '"public"."test"'


def test_select_sql():
    result = select_sql('SELECT "name" FROM', "prest-test", "public", "test")
    assert result == 'SELECT "name" FROM "prest-test"."public"."test"'


def test_insert_sql():
    result = insert_sql("prest-test", "public", "test", '"name"', "($1)")
    assert result == 'INSERT INTO "prest-test"."public"."test"("name") VALUES($1)'


def test_delete_sql():
    result = delete_sql("prest-test", "public", "test")
    assert result == 'DELETE FROM "prest-test"."public"."test"'


def test_update_sql():
    result = update_sql("prest-test", "public", "test", '"name"=$1')
    assert result == 'UPDATE "prest-test"."public"."test" SET "name"=$1'