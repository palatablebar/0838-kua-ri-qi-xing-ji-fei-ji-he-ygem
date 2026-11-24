import sqlite3
import threading

from app.review.store import Store


def create(client, profile):
    response = client.post("/api/runs", json={"profile": profile})
    assert response.status_code == 200
    return response.get_json()


def approve(client, run, comment="签发"):
    return client.post(f"/api/runs/{run['run_id']}/review",
                       json={"decision": "APPROVED", "comment": comment,
                             "expected_revision": run["revision"]})


def test_first_batch_issues_on_time_within_cap(client):
    run = create(client, "shared_a")
    response = approve(client, run)
    assert response.status_code == 200
    quota = response.get_json()["quota"]
    assert quota["refund_total"] == 0
    assert quota["recognized_total"] == 300
    ledger = client.get("/api/quota/ledger").get_json()
    a100 = next(item for item in ledger["entries"] if item["account_id"] == "A100")
    assert a100["used_cents"] == 300
    assert a100["remaining_cents"] == 100


def test_second_batch_cannot_overcollect_and_marks_refund(client):
    approve(client, create(client, "shared_a"))
    run_b = create(client, "shared_b")
    response = approve(client, run_b)
    assert response.status_code == 200
    quota = response.get_json()["quota"]
    # A100 只剩 100：S3 实扣 150，认收 100，待退 50
    s3 = next(row for row in quota["rows"] if row["account_id"] == "A100")
    assert s3["recognized_cents"] == 100
    assert s3["refund_cents"] == 50
    # A200 跨日两天各自 250，均不触顶
    assert quota["refund_total"] == 50
    ledger = client.get("/api/quota/ledger").get_json()
    a100 = next(item for item in ledger["entries"] if item["account_id"] == "A100")
    assert a100["used_cents"] == 400
    assert a100["remaining_cents"] == 0


def test_daily_ledger_never_exceeds_cap_across_batches(client):
    approve(client, create(client, "shared_a"))
    approve(client, create(client, "shared_b"))
    entries = client.get("/api/quota/ledger").get_json()["entries"]
    for item in entries:
        assert item["used_cents"] <= item["cap_cents"]


def test_cross_day_quota_is_split_per_natural_day(client):
    approve(client, create(client, "shared_a"))
    approve(client, create(client, "shared_b"))
    entries = client.get("/api/quota/ledger").get_json()["entries"]
    a200 = {(item["day"]): item for item in entries if item["account_id"] == "A200"}
    assert set(a200) == {"2026-11-20", "2026-11-21"}
    assert all(item["used_cents"] == 250 for item in a200.values())


def test_retry_approval_does_not_double_reserve_quota(client):
    run = create(client, "shared_a")
    first = approve(client, run)
    assert first.status_code == 200
    revision = first.get_json()["revision"]
    # 同版本重试：版本已陈旧应被拒绝，且额度不重复占用
    retry = client.post(f"/api/runs/{run['run_id']}/review",
                        json={"decision": "APPROVED", "comment": "重试",
                              "expected_revision": run["revision"]})
    assert retry.status_code == 409
    entries = client.get("/api/quota/ledger").get_json()["entries"]
    assert sum(item["used_cents"] for item in entries) == 300
    # 用新版本再次确认（HOLD 后再签发），账本仍不翻倍
    held = client.post(f"/api/runs/{run['run_id']}/review",
                       json={"decision": "HELD", "comment": "暂缓", "expected_revision": revision})
    assert held.status_code == 200
    approve(client, held.get_json())
    entries = client.get("/api/quota/ledger").get_json()["entries"]
    assert sum(item["used_cents"] for item in entries) == 300


def test_concurrent_approvals_of_same_account_never_overflow(client, tmp_path):
    store = Store(str(tmp_path / "concurrent.sqlite3"))
    results = []
    errors = []

    def worker(profile):
        app = client.application
        with app.app_context():
            try:
                from app.service import pipeline
                from app.review.service import approve as do_approve, create_run
                payload = pipeline(profile)
                run = create_run(store, payload)
                do_approve(store, run["run_id"], "APPROVED", "并发", run["revision"])
                results.append(profile)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
    threads = [threading.Thread(target=worker, args=("shared_a",)),
               threading.Thread(target=worker, args=("shared_b",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    for item in store.quota_ledger_entries():
        assert item["used_cents"] <= item["cap_cents"]
    a100 = next(item for item in store.quota_ledger_entries() if item["account_id"] == "A100")
    assert a100["used_cents"] == 400


def test_same_batch_submitted_concurrently_reserves_once(client, tmp_path):
    from app.domain.quota import plan_quota, summarize
    store = Store(str(tmp_path / "once.sqlite3"))
    app = client.application
    with app.app_context():
        from app.service import pipeline
        from app.review.service import create_run
        payload = pipeline("shared_a")
        run = create_run(store, payload)
    run_id, revision = run["run_id"], run["revision"]

    def planner_for(planner_payload):
        def planner(balance):
            row_plans, account_days = plan_quota(planner_payload["results"], balance)
            return row_plans, account_days, summarize(row_plans, account_days)
        return planner

    outcomes = []

    def worker():
        try:
            # 两个线程基于同一个 rev 0 并发提交，写锁内重新读版本后必有一个陈旧
            _, problem, _ = store.approve_with_quota(
                run_id, "APPROVED", "并发", revision, planner_for(payload))
            outcomes.append(problem or "approved")
        except sqlite3.OperationalError as exc:
            outcomes.append("locked:" + str(exc))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("approved") == 1
    assert all(item == "approved" or item == "stale" or item.startswith("locked:")
               for item in outcomes)
    entries = store.quota_ledger_entries()
    assert sum(item["used_cents"] for item in entries) == 300
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM quota_reservations").fetchone()[0] == 1


def test_evidence_contains_recognized_and_refund(client):
    approve(client, create(client, "shared_a"))
    run_b = create(client, "shared_b")
    approved = approve(client, run_b).get_json()
    artifact = client.get(f"/api/runs/{approved['run_id']}/evidence").get_json()
    assert artifact["quota"]["refund_total"] == 50
    assert artifact["quota"]["recognized_total"] == 600


def test_pipeline_quota_preview_is_present_before_approval(client):
    run = create(client, "shared_b")
    assert run["status"] == "DRAFT"
    assert run["quota"]["daily_cap_cents"] == 400
    # 预演按空余额，不反映账本，只用于工作台展示本批结构
    assert run["quota"]["debit_total"] == 650


def test_quota_ledger_endpoint_reports_remaining(client):
    ledger = client.get("/api/quota/ledger").get_json()
    assert ledger["daily_cap_cents"] == 400
    assert ledger["entries"] == []
    approve(client, create(client, "shared_a"))
    entries = client.get("/api/quota/ledger").get_json()["entries"]
    assert len(entries) == 1
    assert entries[0]["account_id"] == "A100"
    assert entries[0]["day"] == "2026-11-20"
    assert entries[0]["used_cents"] + entries[0]["remaining_cents"] == entries[0]["cap_cents"]


def test_dirty_batch_with_blocker_never_touches_quota(client):
    run = create(client, "dirty")
    response = client.post(f"/api/runs/{run['run_id']}/review",
                           json={"decision": "APPROVED", "comment": "x", "expected_revision": 0})
    assert response.status_code == 409
    assert client.get("/api/quota/ledger").get_json()["entries"] == []
