import json

from app.domain.quota import plan_quota, summarize
from app.errors import DomainIssue
from app.review.policy import approval_allowed


def create_run(store, payload):
    row = store.create(payload["run_key"], payload["profile"], payload)
    return serialize(row)


def _build_planner(payload):
    results = payload.get("results", [])

    def planner(balance):
        row_plans, account_days = plan_quota(results, balance)
        return row_plans, account_days, summarize(row_plans, account_days)

    return planner


def approve(store, run_id, decision, comment, expected_revision):
    row = store.get(run_id)
    if row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    payload = json.loads(row["payload"])
    if decision not in {"APPROVED", "HELD"}:
        raise DomainIssue("BAD_REQUEST")
    if decision == "APPROVED" and not approval_allowed(payload):
        raise DomainIssue("GATE_BLOCKED", 409)
    planner = _build_planner(payload)
    row, problem, _ = store.approve_with_quota(
        run_id, decision, comment.strip(), expected_revision, planner)
    if problem == "missing":
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if problem == "stale":
        raise DomainIssue("STALE_REVIEW", 409)
    return serialize(row)


def serialize(row):
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload.update(run_id=row["id"], status=row["status"], revision=row["revision"],
                   comment=row["comment"], created_at=row["created_at"])
    return payload
