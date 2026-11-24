from app.catalog import SPEC
from app.domain.calculate import calculate_rows
from app.domain.decision import decide_rows
from app.domain.prepare import prepare_rows
from app.intake.service import load

CLEAN = [{'trip_id': 'T1',
  'bike_id': 'B1',
  'start_at': '2026-11-20 08:00',
  'end_at': '2026-11-20 08:20',
  'paused_minutes': '0',
  'distance_m': '3200',
  'wallet_debit': '1.50',
  'plan': 'standard'},
 {'trip_id': 'T2',
  'bike_id': 'B2',
  'start_at': '2026-11-20 23:50',
  'end_at': '2026-11-21 00:20',
  'paused_minutes': '0',
  'distance_m': '5400',
  'wallet_debit': '2.50',
  'plan': 'standard'},
 {'trip_id': 'T3',
  'bike_id': 'B3',
  'start_at': '2026-11-20 09:00',
  'end_at': '2026-11-20 09:10',
  'paused_minutes': '5',
  'distance_m': '800',
  'wallet_debit': '1.00',
  'plan': 'standard'},
 {'trip_id': 'T4',
  'bike_id': 'B4',
  'start_at': '2026-11-20 18:00',
  'end_at': '2026-11-20 18:20',
  'paused_minutes': '0',
  'distance_m': '2800',
  'wallet_debit': '1.50',
  'plan': 'standard'},
 {'trip_id': 'T5',
  'bike_id': 'B5',
  'start_at': '2026-11-20 07:00',
  'end_at': '2026-11-20 08:30',
  'paused_minutes': '0',
  'distance_m': '12000',
  'wallet_debit': '4.00',
  'plan': 'standard'}]


def row(**changes):
    item = dict(CLEAN[0])
    item.update(changes)
    return item


def calc(rows):
    items, issues = prepare_rows(rows)
    return calculate_rows(items), issues


def run(rows):
    items, issues = prepare_rows(rows)
    return decide_rows(calculate_rows(items)), issues


def run_profile(profile):
    return run(load(profile)["rows"])
