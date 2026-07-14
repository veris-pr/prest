from __future__ import annotations

import pytest

from prest_py.domain.identifiers import is_safe_segment, is_valid, quote, split_and_validate_csv


def test_is_valid_simple():
    assert is_valid("name") is True
    assert is_valid("test") is True


def test_is_valid_dotted():
    assert is_valid("c.relname") is True
    assert is_valid("t.tablename") is True


def test_is_valid_rejects_digit_start():
    assert is_valid("0name") is False
    assert is_valid("0c.relname") is False


def test_is_valid_rejects_special_chars():
    assert is_valid("name;drop") is False
    assert is_valid("bad@schema") is False


def test_is_valid_rejects_too_long():
    assert is_valid("a" * 64) is False
    assert is_valid("a" * 63) is True


def test_is_safe_segment_basic():
    assert is_safe_segment("prest-test") is True
    assert is_safe_segment("tenant_a") is True
    assert is_safe_segment("0prest-test") is True  # digits allowed for segments


def test_is_safe_segment_rejects_dots():
    assert is_safe_segment("a.b") is False


def test_is_safe_segment_rejects_empty():
    assert is_safe_segment("") is False


def test_quote_simple():
    assert quote("name") == '"name"'


def test_quote_dotted():
    assert quote("c.relname") == '"c"."relname"'


def test_quote_rejects_invalid():
    with pytest.raises(ValueError, match="invalid identifier"):
        quote("0name")


def test_split_and_validate_csv():
    result = split_and_validate_csv("name,age,salary")
    assert result == ["name", "age", "salary"]


def test_split_and_validate_csv_empty():
    assert split_and_validate_csv("") == []


def test_split_and_validate_csv_invalid():
    with pytest.raises(ValueError, match="invalid identifier"):
        split_and_validate_csv("name,0bad")