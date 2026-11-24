"""账户日封顶额度计划。

规则：
- 同一账户按自然日共用一个日封顶额度；跨日骑行每天额度分开计算。
- 签发认收以额度账本剩余额度为限，实扣中超出部分列为待退。
- 本模块只做计划，不触碰账本；账本占用在签发事务内完成，保证并发与幂等。
"""
from datetime import datetime, timedelta

from app.catalog import SPEC
from app.domain.helpers import largest_remainder


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def daily_debits(item):
    """把一笔实扣（wallet_debit，分）按各自然日应扣车费占比分摊到天。"""
    day_fares = list(item.get("day_fares") or [])
    total = sum(day_fares)
    debit = int(item["wallet_debit"])
    if total <= 0 or debit <= 0:
        return [0] * len(day_fares)
    if debit == total:
        return list(day_fares)
    return largest_remainder(debit, day_fares)


def trip_day_entries(item):
    """生成一笔骑行在每个自然日上的实扣分摊条目。"""
    start = _as_datetime(item["start_at"])
    debits = daily_debits(item)
    entries = []
    for offset, amount in enumerate(debits):
        day = (start + timedelta(days=offset)).date()
        entries.append({
            "trip_id": item.get(SPEC["key"], ""),
            "account_id": item.get("account_id", ""),
            "day": day.isoformat(),
            "debit_cents": amount,
        })
    return entries


def plan_quota(results, ledger_balance, cap_cents=None):
    """根据账本已占用额度，为批次内每条骑行生成认收/待退计划。

    ledger_balance: {(account_id, 'YYYY-MM-DD'): 已占用分}
    返回 (row_plans, account_days)，两者均按稳定顺序排列。
    """
    cap = SPEC["daily_cap_cents"] if cap_cents is None else int(cap_cents)
    used = {key: int(value) for key, value in (ledger_balance or {}).items()}
    # 行按来源行号、主键稳定排序，保证先到先认收的确定性
    ordered = sorted(results, key=lambda item: (item.get("_line", 0), str(item.get(SPEC["key"], ""))))
    row_plans = []
    for item in ordered:
        per_day = trip_day_entries(item)
        recognized_days = []
        recognized_total = 0
        for entry in per_day:
            key = (entry["account_id"], entry["day"])
            remaining = max(0, cap - used.get(key, 0))
            debit = entry["debit_cents"]
            take = min(debit, remaining)
            refund = debit - take
            used[key] = used.get(key, 0) + take
            recognized_total += take
            recognized_days.append({"day": entry["day"], "debit_cents": debit,
                                    "recognized_cents": take, "refund_cents": refund,
                                    "remaining_after": max(0, cap - used[key])})
        debit_total = int(item["wallet_debit"])
        refund_total = debit_total - recognized_total
        row_plans.append({
            "trip_id": item.get(SPEC["key"], ""),
            "account_id": item.get("account_id", ""),
            "debit_cents": debit_total,
            "recognized_cents": recognized_total,
            "refund_cents": refund_total,
            "days": recognized_days,
        })
    account_days = []
    for (account_id, day), amount in sorted(used.items()):
        if amount <= 0 and (account_id, day) not in (ledger_balance or {}):
            continue
        account_days.append({"account_id": account_id, "day": day,
                             "cap_cents": cap, "used_cents": amount,
                             "remaining_cents": max(0, cap - amount)})
    return row_plans, account_days


def summarize(row_plans, account_days):
    return {
        "daily_cap_cents": SPEC["daily_cap_cents"],
        "recognized_total": sum(plan["recognized_cents"] for plan in row_plans),
        "refund_total": sum(plan["refund_cents"] for plan in row_plans),
        "debit_total": sum(plan["debit_cents"] for plan in row_plans),
        "capped_account_days": [item for item in account_days
                                if item["used_cents"] >= item["cap_cents"]],
        "account_days": account_days,
        "rows": row_plans,
    }
