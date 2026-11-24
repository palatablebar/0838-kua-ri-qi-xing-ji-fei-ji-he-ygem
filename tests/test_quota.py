from app.catalog import SPEC
from app.domain.quota import daily_debits, plan_quota, summarize
from tests.domain_cases import calc


def results(rows):
    items, issues = calc(rows)
    assert issues == []
    return items


def trip(**changes):
    base = {'trip_id': 'Q1', 'account_id': 'ACC1', 'bike_id': 'B',
            'start_at': '2026-11-20 08:00', 'end_at': '2026-11-20 08:20',
            'paused_minutes': '0', 'distance_m': '1000',
            'wallet_debit': '2.00', 'plan': 'standard'}
    base.update(changes)
    return base


def test_single_batch_under_cap_recognizes_full_debit():
    rows = results([trip()])
    plans, days = plan_quota(rows, {})
    assert plans[0]["recognized_cents"] == 200
    assert plans[0]["refund_cents"] == 0
    assert days[0]["remaining_cents"] == 200


def test_two_rows_separately_fit_but_jointly_exceed_cap():
    rows = results([
        trip(trip_id="Q1", wallet_debit="2.00"),
        trip(trip_id="Q2", wallet_debit="1.00"),
        trip(trip_id="Q3", wallet_debit="1.50"),
    ])
    plans, days = plan_quota(rows, {})
    # 前两笔合计 300，第三笔只能认收剩余 100，多收 50 列待退
    assert [(p["trip_id"], p["recognized_cents"], p["refund_cents"]) for p in plans] == [
        ("Q1", 200, 0), ("Q2", 100, 0), ("Q3", 100, 50)]
    assert days[0]["used_cents"] == SPEC["daily_cap_cents"]
    assert days[0]["remaining_cents"] == 0
    summary = summarize(plans, days)
    assert summary["recognized_total"] == 400
    assert summary["refund_total"] == 50
    assert summary["debit_total"] == 450
    assert summary["capped_account_days"][0]["account_id"] == "ACC1"


def test_second_batch_uses_remaining_quota_from_ledger():
    first = results([trip(trip_id="Q1", wallet_debit="3.00")])
    _, days_first = plan_quota(first, {})
    balance = {(d["account_id"], d["day"]): d["used_cents"] for d in days_first}
    assert balance[("ACC1", "2026-11-20")] == 300

    second = results([trip(trip_id="Q2", wallet_debit="2.00")])
    plans, _ = plan_quota(second, balance)
    assert plans[0]["recognized_cents"] == 100
    assert plans[0]["refund_cents"] == 100


def test_accounts_have_independent_caps():
    rows = results([
        trip(trip_id="Q1", account_id="ACC1", wallet_debit="4.00"),
        trip(trip_id="Q2", account_id="ACC2", wallet_debit="4.00"),
    ])
    plans, days = plan_quota(rows, {})
    assert all(p["refund_cents"] == 0 for p in plans)
    assert {d["account_id"] for d in days} == {"ACC1", "ACC2"}
    assert all(d["used_cents"] == 400 for d in days)


def test_cross_day_trip_uses_separate_daily_quota():
    rows = results([trip(trip_id="Q4", start_at="2026-11-20 23:40",
                         end_at="2026-11-21 00:20", wallet_debit="5.00")])
    plans, days = plan_quota(rows, {})
    plan = plans[0]
    assert plan["refund_cents"] == 0
    assert [d["day"] for d in plan["days"]] == ["2026-11-20", "2026-11-21"]
    assert sum(d["recognized_cents"] for d in plan["days"]) == 500
    # 两天额度各自独立，互不挤占
    assert all(d["remaining_cents"] == 150 for d in days)


def test_cross_day_trip_second_day_hits_remaining_cap():
    rows = results([trip(trip_id="Q4", start_at="2026-11-20 23:40",
                         end_at="2026-11-21 00:20", wallet_debit="5.00")])
    balance = {("ACC1", "2026-11-21"): 300}
    plans, _ = plan_quota(rows, balance)
    day_map = {d["day"]: d for d in plans[0]["days"]}
    assert day_map["2026-11-20"]["recognized_cents"] == 250
    assert day_map["2026-11-21"]["recognized_cents"] == 100
    assert day_map["2026-11-21"]["refund_cents"] == 150
    assert plans[0]["refund_cents"] == 150


def test_daily_debit_split_keeps_total_and_largest_remainder():
    item = results([trip(trip_id="Q4", start_at="2026-11-20 23:40",
                         end_at="2026-11-21 00:20", wallet_debit="5.01")])[0]
    split = daily_debits(item)
    assert sum(split) == 501
    assert split == [251, 250]


def test_zero_debit_needs_no_quota():
    rows = results([trip(wallet_debit="0")])
    plans, days = plan_quota(rows, {})
    assert plans[0]["recognized_cents"] == 0
    assert plans[0]["refund_cents"] == 0
    assert days == []
