import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY,
              request_key TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL,
              profile TEXT NOT NULL,
              status TEXT NOT NULL,
              revision INTEGER NOT NULL,
              payload TEXT NOT NULL,
              comment TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS quota_ledger(
              account_id TEXT NOT NULL,
              day TEXT NOT NULL,
              cap_cents INTEGER NOT NULL,
              used_cents INTEGER NOT NULL,
              PRIMARY KEY (account_id, day)
            );
            CREATE TABLE IF NOT EXISTS quota_reservations(
              run_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quota_entries(
              run_id TEXT NOT NULL,
              trip_id TEXT NOT NULL,
              account_id TEXT NOT NULL,
              day TEXT NOT NULL,
              debit_cents INTEGER NOT NULL,
              recognized_cents INTEGER NOT NULL,
              refund_cents INTEGER NOT NULL
            );
            ''')

    def find_by_request(self, request_key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE request_key=?", (request_key,)).fetchone()
        return dict(row) if row else None

    def create(self, request_key, profile, payload):
        run_id = uuid.uuid4().hex[:12]
        with self.connect() as db:
            # INSERT OR IGNORE 保证并发提交同一 run_key 时只有一条批次，且不抛 UNIQUE 异常
            db.execute("INSERT OR IGNORE INTO runs(id,request_key,created_at,profile,status,revision,payload) "
                       "VALUES(?,?,?,?,?,?,?)",
                       (run_id, request_key, datetime.now(timezone.utc).isoformat(), profile, "DRAFT", 0,
                        json.dumps(payload, ensure_ascii=False)))
        return self.get(run_id) or self.find_by_request(request_key)

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def quota_balance(self, db=None):
        """返回 {(account_id, day): used_cents}，可在事务连接内调用。"""
        own = db is None
        if own:
            db = self.connect()
        rows = db.execute("SELECT account_id, day, used_cents FROM quota_ledger").fetchall()
        if own:
            db.close()
        return {(item["account_id"], item["day"]): item["used_cents"] for item in rows}

    def quota_ledger_entries(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT account_id, day, cap_cents, used_cents "
                "FROM quota_ledger ORDER BY account_id, day").fetchall()
        return [dict(item, remaining_cents=max(0, item["cap_cents"] - item["used_cents"]))
                for item in rows]

    def has_reservation(self, db, run_id):
        return db.execute("SELECT 1 FROM quota_reservations WHERE run_id=?",
                          (run_id,)).fetchone() is not None

    def _write_quota(self, db, run_id, row_plans, account_days):
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO quota_reservations(run_id, created_at) VALUES(?,?)", (run_id, now))
        for bucket in account_days:
            db.execute('''INSERT INTO quota_ledger(account_id, day, cap_cents, used_cents)
                          VALUES(?,?,?,?)
                          ON CONFLICT(account_id, day) DO UPDATE SET
                            cap_cents=excluded.cap_cents,
                            used_cents=excluded.used_cents''',
                       (bucket["account_id"], bucket["day"], bucket["cap_cents"], bucket["used_cents"]))
        for plan in row_plans:
            for day in plan["days"]:
                db.execute('''INSERT INTO quota_entries
                              (run_id, trip_id, account_id, day, debit_cents, recognized_cents, refund_cents)
                              VALUES(?,?,?,?,?,?,?)''',
                           (run_id, plan["trip_id"], plan["account_id"], day["day"], day["debit_cents"],
                            day["recognized_cents"], day["refund_cents"]))

    def approve_with_quota(self, run_id, decision, comment, expected_revision, plan_builder):
        """单事务完成版本校验、额度预留与签发。

        plan_builder(balance) -> (row_plans, account_days, quota_summary)
        已预留的批次重试时直接复用原预留，不重复占用额度。
        返回 (row, problem, quota_summary)；quota_summary 同时在事务内写入 payload。
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None, "missing", None
            if row["revision"] != expected_revision:
                return None, "stale", None
            quota_summary = None
            if decision == "APPROVED":
                if self.has_reservation(db, run_id):
                    quota_summary = self._snapshot(db, run_id)
                else:
                    row_plans, account_days, quota_summary = plan_builder(self.quota_balance(db))
                    self._write_quota(db, run_id, row_plans, account_days)
                payload = json.loads(row["payload"])
                payload["quota"] = quota_summary
                db.execute("UPDATE runs SET payload=? WHERE id=?",
                           (json.dumps(payload, ensure_ascii=False), run_id))
            db.execute("UPDATE runs SET status=?, revision=revision+1, comment=? WHERE id=?",
                       (decision, comment, run_id))
        return self.get(run_id), None, quota_summary

    def _snapshot(self, db, run_id):
        from app.catalog import SPEC
        entries = db.execute(
            "SELECT trip_id, account_id, day, debit_cents, recognized_cents, refund_cents "
            "FROM quota_entries WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        row_index = {}
        row_plans = []
        for entry in entries:
            if entry["trip_id"] not in row_index:
                plan = {"trip_id": entry["trip_id"], "account_id": entry["account_id"],
                        "debit_cents": 0, "recognized_cents": 0, "refund_cents": 0, "days": []}
                row_index[entry["trip_id"]] = plan
                row_plans.append(plan)
            plan = row_index[entry["trip_id"]]
            day = {"day": entry["day"], "debit_cents": entry["debit_cents"],
                   "recognized_cents": entry["recognized_cents"], "refund_cents": entry["refund_cents"]}
            plan["days"].append(day)
            plan["debit_cents"] += entry["debit_cents"]
            plan["recognized_cents"] += entry["recognized_cents"]
            plan["refund_cents"] += entry["refund_cents"]
        ledger = db.execute("SELECT account_id, day, cap_cents, used_cents FROM quota_ledger").fetchall()
        account_days = [{"account_id": item["account_id"], "day": item["day"],
                         "cap_cents": item["cap_cents"], "used_cents": item["used_cents"],
                         "remaining_cents": max(0, item["cap_cents"] - item["used_cents"])}
                        for item in ledger]
        return {
            "daily_cap_cents": SPEC["daily_cap_cents"],
            "debit_total": sum(plan["debit_cents"] for plan in row_plans),
            "recognized_total": sum(plan["recognized_cents"] for plan in row_plans),
            "refund_total": sum(plan["refund_cents"] for plan in row_plans),
            "capped_account_days": [item for item in account_days
                                    if item["used_cents"] >= item["cap_cents"]],
            "account_days": account_days,
            "rows": row_plans,
        }

    def get_quota_snapshot(self, run_id):
        with self.connect() as db:
            if not self.has_reservation(db, run_id):
                return None
            return self._snapshot(db, run_id)
