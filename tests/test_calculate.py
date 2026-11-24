from decimal import Decimal

from app.catalog import SPEC
from app.domain.calculate import calculate_rows
from app.domain.prepare import prepare_rows
from tests.domain_cases import CLEAN, calc

# TRAP-19 TRAP-20 TRAP-24 的边界由本文件的跨日、合并与单位用例固定。


def clean_results():
    items, issues = prepare_rows(CLEAN)
    assert issues == []
    return calculate_rows(items)


def test_clean_result_count():
    assert len(clean_results()) == 5


def test_metric_total_is_reconciled():
    total = sum((item["metric"] for item in clean_results()), Decimal("0"))
    assert total == Decimal("1050")


def test_first_result_matches_expected():
    item = clean_results()[0]
    assert item["label"] == "T1"
    assert abs(float(item["fare"]) - float("150")) < 0.011


def test_core_boundary_case():
    results, issues = calc([{'trip_id': 'T9', 'bike_id': 'B9', 'start_at': '2026-11-20 08:00', 'end_at': '2026-11-20 08:16', 'paused_minutes': '0', 'distance_m': '1000', 'wallet_debit': '1.10', 'plan': 'standard'}])
    assert issues == []
    value = results[0]["fare"]
    expected = '110'
    if expected in {"True", "False"}:
        assert bool(value) is (expected == "True")
    elif isinstance(expected, bool):
        assert bool(value) is expected
    elif expected.startswith("20") and len(expected) == 10:
        assert value.isoformat() == expected
    elif expected.replace(".", "", 1).replace("-", "", 1).isdigit():
        assert abs(float(value) - float(expected)) < 0.001
    else:
        assert value == expected


def test_result_labels_are_unique():
    labels = [item["label"] for item in clean_results()]
    assert len(labels) == len(set(labels))


def test_every_result_has_metric():
    assert all(item.get("metric") is not None for item in clean_results())


def test_trip_ending_at_midnight_does_not_charge_an_empty_day():
    ended_at_midnight = dict(CLEAN[0], start_at="2026-11-20 23:45", end_at="2026-11-21 00:00")
    results, issues = calc([ended_at_midnight])
    assert issues == []
    assert results[0]["day_fares"] == [100]


def test_fully_paused_first_day_has_no_base_fare():
    crossed_midnight = dict(CLEAN[0], start_at="2026-11-20 23:45", end_at="2026-11-21 00:10", paused_minutes="15")
    results, issues = calc([crossed_midnight])
    assert issues == []
    assert results[0]["day_fares"] == [0, 100]
