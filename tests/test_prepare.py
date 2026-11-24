from app.catalog import SPEC
from app.domain.prepare import prepare_rows
from tests.domain_cases import CLEAN, row


def test_clean_sample_prepares():
    items, issues = prepare_rows(CLEAN)
    assert len(items) == 5
    assert issues == []


def test_blank_key_is_isolated():
    items, issues = prepare_rows([row(**{SPEC["key"]: ""})])
    assert not items
    assert issues[0]["code"] == "KEY_MISSING"


def test_bad_number_is_isolated():
    item = row(**{"paused_minutes": "abc"})
    items, issues = prepare_rows([item])
    assert not items
    assert issues[0]["code"].startswith("INVALID_")


def test_domain_invalid_rows_are_isolated():
    item = row(**{'end_at': '2026-11-20 07:00'})
    items, issues = prepare_rows([item])
    assert not items
    assert issues


def test_normalization_row_is_accepted():
    item = row(**{'start_at': '2026-11-20 23:50', 'end_at': '2026-11-21 00:20', 'paused_minutes': '0', 'distance_m': '1000', 'wallet_debit': '2.50'})
    items, issues = prepare_rows([item])
    assert len(items) == 1
    assert issues == []


def test_issue_keeps_line_and_key():
    key = CLEAN[0][SPEC["key"]]
    item = row(**{"paused_minutes": "abc"})
    item["_line"] = 77
    _, issues = prepare_rows([item])
    assert issues[0]["line"] == 77
    assert issues[0]["key"] == key
