from datetime import date, timedelta
from app.catalog import SPEC
from app.domain.helpers import *  # noqa: F401,F403


def calculate_rows(items):
    out = []
    rows = items
    for item in items:
        start, end = item["start_at"], item["end_at"]
        cursor = start
        pause_seconds = item["paused_minutes"] * 60
        day_fares = []
        while cursor < end:
            midnight = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            boundary = min(midnight, end)
            seconds = int((boundary - cursor).total_seconds())
            consumed = min(pause_seconds, seconds)
            pause_seconds -= consumed
            minutes = (seconds - consumed + 59) // 60
            day_fares.append(min(100 + max(0, minutes - 15) * 10, 400) if minutes else 0)
            cursor = boundary
        fare = sum(day_fares)
        item["fare"] = fare
        item["split_days"] = len(day_fares)
        item["metric"] = D(str(fare), "CALC")
        item["limit"] = D(str(item["wallet_debit"]), "LIMIT")
        item["day_fares"] = day_fares
        item["breakdown"] = [f'{start.date() + timedelta(days=index)} · {part} 分'
                             for index, part in enumerate(day_fares)]
        out.append(item)
    for item in out:
        item.setdefault("label", str(item.get(SPEC["key"], "")))
    return out
