from app.domain.helpers import D


def decide_rows(items):
    for item in items:
        if item["wallet_debit"] == 0 and item["fare"] > 0:
            item["verdict"] = "REJECT"
            item["reason"] = "UNPAID"
        elif item["wallet_debit"] != item["fare"]:
            item["verdict"] = "REVIEW"
            item["reason"] = "WALLET_MISMATCH"
        elif any(part == 400 for part in item["day_fares"]) and item["fare"] == 400 * item["split_days"]:
            item["verdict"] = "REVIEW"
            item["reason"] = "DAILY_CAP_APPLIED"
        else:
            item["verdict"] = "PASS"
            item["reason"] = "FARE_MATCH"
        item.setdefault("verdict", "PASS")
        item.setdefault("reason", "OK")
    return items
