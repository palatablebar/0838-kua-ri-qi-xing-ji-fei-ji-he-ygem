from app.domain.decision import decide_rows
from tests.domain_cases import calc, run, run_profile


def test_clean_sample_has_no_blocker():
    results, _ = run_profile("clean")
    assert sum(1 for item in results if item["verdict"] == "REJECT") == 0


def test_dirty_sample_has_blocker():
    results, _ = run_profile("dirty")
    assert any(item["verdict"] == "REJECT" for item in results)


def test_each_result_has_reason():
    results, _ = run_profile("dirty")
    assert all(item.get("reason") for item in results)


def test_boundary_case_one():
    results, issues = run([{'trip_id': 'A1', 'bike_id': 'B', 'start_at': '2026-11-20 08:00', 'end_at': '2026-11-20 08:15', 'paused_minutes': '0', 'distance_m': '100', 'wallet_debit': '1.00', 'plan': 'standard'}])
    assert not issues
    assert results[0]["verdict"] == "PASS"
    assert results[0]["reason"] == "FARE_MATCH"


def test_boundary_case_two():
    results, issues = run([{'trip_id': 'A2', 'bike_id': 'B', 'start_at': '2026-11-20 08:00', 'end_at': '2026-11-20 08:20', 'paused_minutes': '0', 'distance_m': '100', 'wallet_debit': '1.00', 'plan': 'standard'}])
    assert not issues
    assert results[0]["verdict"] == "REVIEW"


def test_verdict_counts_match_rows():
    from app.service import pipeline
    payload = pipeline("clean")
    assert sum(payload["summary"].values()) == payload["counts"]["computed"]
    assert set(payload["summary"]) == {"PASS", "REVIEW", "REJECT"}
