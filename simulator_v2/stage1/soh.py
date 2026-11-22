"""Daily and monthly stock bridges for the yard, physical locations, and lots."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby

from .model import AnimalStatus, EventKind, business_date, midnight
from .replay import replay
from .validation import Check, require

YARD = ("yard", "SYN-YARD")
FLOWS = ("receipts", "sales", "deaths", "transfers_in", "transfers_out")
EVENT_FLOW = {EventKind.RECEIPT: "receipts", EventKind.SALE: "sales", EventKind.DEATH: "deaths"}


@dataclass(frozen=True)
class StockRow:
    scope_type: str
    scope_id: str
    period_start: date
    period_end: date
    opening_head: int
    receipts: int
    sales: int
    deaths: int
    transfers_in: int
    transfers_out: int
    closing_head: int
    animal_days: int
    synthetic: bool = True


def calendar_days(start, end):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def stock_rows(result, start, end):
    animal_lots = {animal.animal_id: animal.lot_id for animal in result.animals}
    scopes = [YARD, *(("location", key) for key in sorted({
        version.location_id for version in result.location_versions
    })), *(("lot", lot.lot_id) for lot in result.lots)]
    events_by_day = defaultdict(list)
    for event in result.events:
        events_by_day[business_date(event.effective_at)].append(event)
    active = {}
    for day, events in events_by_day.items():
        if day >= start:
            break
        for event in events:
            update_roster(active, event)

    def counts():
        totals = Counter({YARD: len(active)})
        for animal_id, location_id in active.items():
            totals["location", location_id] += 1
            totals["lot", animal_lots[animal_id]] += 1
        return totals

    rows = []
    for day in calendar_days(start, end):
        opening = counts()
        seen = defaultdict(set)
        seen[YARD].update(active)
        for animal_id, location_id in active.items():
            seen["location", location_id].add(animal_id)
            seen["lot", animal_lots[animal_id]].add(animal_id)
        flows = defaultdict(Counter)
        for event in events_by_day[day]:
            animal_id = event.animal_id
            lot = ("lot", animal_lots[animal_id])
            source = ("location", event.from_location_id)
            target = ("location", event.to_location_id)
            if event.kind == EventKind.TRANSFER:
                flows[source]["transfers_out"] += 1
                flows[target]["transfers_in"] += 1
            else:
                field = EVENT_FLOW[event.kind]
                for scope in (YARD, lot, target if event.kind == EventKind.RECEIPT else source):
                    flows[scope][field] += 1
            if event.to_location_id is not None:
                for scope in (YARD, lot, target):
                    seen[scope].add(animal_id)
            update_roster(active, event)

        closing = counts()
        for scope in scopes:
            rows.append(StockRow(*scope, day, day, opening[scope],
                                 *(flows[scope][field] for field in FLOWS),
                                 closing[scope], len(seen[scope])))
    return tuple(rows)


def update_roster(active, event):
    if event.to_location_id is None:
        del active[event.animal_id]
    else:
        active[event.animal_id] = event.to_location_id


def monthly_rows(daily):
    buckets = defaultdict(list)
    for row in daily:
        key = row.period_end.year, row.period_end.month, row.scope_type, row.scope_id
        buckets[key].append(row)
    return tuple(
        StockRow(first.scope_type, first.scope_id, first.period_start, last.period_end,
                 first.opening_head, *(sum(getattr(row, field) for row in rows) for field in FLOWS),
                 last.closing_head, sum(row.animal_days for row in rows))
        for rows in buckets.values() for first, last in [(rows[0], rows[-1])]
    )


def reconcile(rows, grain):
    drift = []
    continuity = []
    scope_ties = []
    transfers = []
    prior = {}
    for day, group in groupby(rows, key=lambda row: row.period_end):
        by_scope = defaultdict(list)
        for row in group:
            scope = (row.scope_type, row.scope_id)
            by_scope[row.scope_type].append(row)
            row_id = f"{day}/{row.scope_id}"
            computed = (row.opening_head + row.receipts - row.sales - row.deaths
                        + row.transfers_in - row.transfers_out)
            if computed != row.closing_head or min(row.opening_head, row.closing_head) < 0:
                drift.append(row_id)
            if scope in prior and prior[scope] != row.opening_head:
                continuity.append(row_id)
            prior[scope] = row.closing_head
        yard, = by_scope["yard"]
        for kind in ("location", "lot"):
            comparable = ("opening_head", "closing_head", "receipts", "sales", "deaths")
            if kind == "lot":
                comparable += ("animal_days",)
            for field in comparable:
                if sum(getattr(row, field) for row in by_scope[kind]) != getattr(yard, field):
                    scope_ties.append(f"{day}/{kind}/{field}")
        locations = by_scope["location"]
        if (sum(row.transfers_in - row.transfers_out for row in locations) != 0
                or any(row.transfers_in or row.transfers_out for row in [yard, *by_scope["lot"]])):
            transfers.append(str(day))
    return tuple(Check(check_id, grain, 0, len(bad), len(bad), tuple(bad[:10]))
                 for check_id, bad in (("STOCK_BRIDGE", drift), ("STOCK_CONTINUITY", continuity),
                                       ("SCOPE_TIE", scope_ties), ("TRANSFER_NET_ZERO", transfers)))


def check_intervals(result):
    prior = {}
    open_at_end = {}
    bad = set()
    for row in result.intervals:
        if row.animal_id in prior:
            previous = prior[row.animal_id]
            if previous.end_at is None or previous.end_at > row.start_at:
                bad.add(row.animal_id)
        if row.end_at is None:
            open_at_end[row.animal_id] = row.location_id
        elif row.end_at < row.start_at:
            bad.add(row.animal_id)
        prior[row.animal_id] = row
    for state in result.states:
        if (state.location_id != open_at_end.get(state.animal_id)
                or (state.status == AnimalStatus.ACTIVE) != (state.location_id is not None)):
            bad.add(state.animal_id)
    return Check("INTERVAL_STATE", "animal", 0, len(bad), len(bad), tuple(sorted(bad)[:10]))


def calculate_soh(ledger, start, end, knowledge_cutoff):
    config = ledger.config
    require(type(start) is date and type(end) is date and config.start_date <= start <= end <= config.end_date,
            "REPORTING_PERIOD", "snapshot", "nonempty subset of run horizon", (str(start), str(end)))
    result = replay(ledger, midnight(end + timedelta(days=1)), knowledge_cutoff)
    daily = stock_rows(result, start, end)
    monthly = monthly_rows(daily)
    checks = (*result.checks, check_intervals(result), *reconcile(daily, "day"),
              *reconcile(monthly, "month"))
    return result, daily, monthly, checks
