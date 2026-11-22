"""Append-only journal with explicit source identity, clocks, and outcome routing."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from ..stage1.model import business_date, is_utc, midnight
from ..stage1.provenance import sha256, canonical, stable_id
from ..stage1.soh import calendar_days

TICK = timedelta(microseconds=1)


class Account(StrEnum):
    WAREHOUSE = "1100"
    RECOVERY = "1110"
    WIP = "1200"
    RECEIVABLE = "1300"
    FEED_RECEIPT = "2100"
    ACQUISITION = "2110"
    YARDAGE = "2120"
    VET = "2130"
    INVOICE = "2140"
    MIX = "2200"
    DISTRIBUTION = "2210"
    NORMAL = "2220"
    PENDING = "2230"
    OPENING = "3100"
    REVENUE = "4100"
    PACKER = "4110"
    COGS = "5100"
    MORTALITY = "5200"
    ABNORMAL = "5300"
    STOCK_COUNT = "5310"
    SPOILAGE = "5320"
    OTHER_VARIANCE = "5330"
    WAREHOUSE_SHRINK = "5340"
    WAREHOUSE_DAMAGE = "5350"


CLEARING = {Account.MIX, Account.DISTRIBUTION, Account.NORMAL, Account.PENDING}
VARIANCES = {Account.ABNORMAL, Account.STOCK_COUNT, Account.SPOILAGE,
             Account.OTHER_VARIANCE, Account.WAREHOUSE_SHRINK, Account.WAREHOUSE_DAMAGE}
OUTCOMES = {Account.COGS, Account.MORTALITY}
CATTLE_COST = OUTCOMES | {Account.WIP}


@dataclass(frozen=True)
class Source:
    source_id: str
    system: str
    document_id: str
    line_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    payload_sha256: str
    source_snapshot_id: str
    event_kind: str | None


@dataclass(frozen=True)
class Link:
    source_id: str
    parent_id: str


class Sources:
    def __init__(self):
        self.rows = {}
        self.links = set()
        self.parents = {}

    def add(self, system, document, line, effective, posted, available, payload, parents=(), *, event_kind=None):
        if (not all(key and key.strip() for key in (system, document, line))
                or not all(is_utc(point) for point in (effective, posted, available))
                or not effective <= posted <= available):
            raise ValueError(f"invalid source identity or clocks: {document}/{line}")
        key = stable_id("FIN-SOURCE", [system, document, line])
        parents = set(parents)
        if key in parents:
            raise ValueError(f"missing or cyclic source lineage: {line}")
        rows = self.rows
        parent_rows = []
        for parent in parents:
            try:
                prow = rows[parent]
            except KeyError:
                raise ValueError(f"missing or cyclic source lineage: {line}") from None
            if prow.available_at > available:
                raise ValueError(f"future source lineage: {line}")
            parent_rows.append(prow)
        digest = sha256(canonical(payload))
        vintage = stable_id("FIN-VINTAGE", [key, digest, effective, posted, available,
                                             sorted(prow.source_snapshot_id for prow in parent_rows)])
        row = Source(key, system, document, line, effective, posted, available, digest, vintage, event_kind)
        if key in rows:
            if rows[key] != row or parents != self.parents[key]:
                raise ValueError(f"conflicting source retry: {line}")
        else:
            rows[key] = row
            self.parents[key] = parents
            self.links.update(Link(key, parent) for parent in parents)
        return key


@dataclass(frozen=True)
class Period:
    month: str
    start: date
    end: date
    locked_at: datetime

    @property
    def effective_before(self):
        return midnight(self.end + timedelta(days=1))


def periods(start, end):
    bounds = {}
    for day in calendar_days(start, end):
        month = day.isoformat()[:7]
        bounds.setdefault(month, [day, day])[1] = day
    return tuple(Period(month, first, last, midnight(last + timedelta(days=1)))
                 for month, (first, last) in bounds.items())


def accounting_month(effective_at, posted_at, calendar):
    service = max(business_date(effective_at), calendar[0].start).isoformat()[:7]
    lock = next((row.locked_at for row in calendar if row.month == service), None)
    if lock is None or posted_at <= lock:
        return service
    current = business_date(posted_at).isoformat()[:7]
    if current == service:
        raise ValueError(f"posting after partial-period lock requires a successor period: {service}")
    posting_lock = next((row.locked_at for row in calendar if row.month == current), None)
    if posting_lock is not None and posted_at > posting_lock:
        raise ValueError(f"posting month already locked: {current}")
    return current


@dataclass(frozen=True)
class Action:
    key: str
    source_id: str
    effective_at: datetime
    component: str
    debit: Account
    credit: Account
    cents: int
    animal_id: str | None = None
    lot_id: str | None = None
    location_id: str | None = None
    pool_id: str | None = None
    approval_id: str | None = None
    reverses: str | None = None
    route_cost: bool = False
    release: bool = False
    restate_at: datetime | None = None


@dataclass(frozen=True)
class Journal:
    journal_id: str
    source_id: str
    source_system: str
    document_id: str
    line_id: str
    animal_id: str | None
    lot_id: str | None
    location_id: str | None
    yard_id: str
    service_date: date
    effective_at: datetime
    source_posted_at: datetime
    posted_at: datetime
    available_at: datetime
    accounting_month: str
    period_routing_at: datetime
    debit_account: Account
    credit_account: Account
    amount_cents: int
    component: str
    pool_id: str | None
    source_snapshot_id: str
    ledger_version: str
    policy_version: str
    approval_id: str | None
    restatement_approval_id: str | None
    reverses_journal_id: str | None
    outcome_event_id: str | None
    principal_release: bool


class Book:
    def __init__(self, sources, calendar, *, version, policy, yard, restatement=None):
        self.sources = sources
        self.calendar = calendar
        self._lock_by_month = {row.month: row.locked_at for row in calendar}
        self._first_start = calendar[0].start
        self.version = version
        self.policy = policy
        self.yard = yard
        self.restatement = restatement
        self._actions = {}
        self._journals = {}
        self._wip = Counter()
        self._exits = {}
        self._entries = set()
        self._reversed = set()
        self._watermark = None

    def _accounting_month(self, effective_at, posted_at):
        service = max(business_date(effective_at), self._first_start).isoformat()[:7]
        lock = self._lock_by_month.get(service)
        if lock is None or posted_at <= lock:
            return service
        current = business_date(posted_at).isoformat()[:7]
        if current == service:
            raise ValueError(f"posting after partial-period lock requires a successor period: {service}")
        posting_lock = self._lock_by_month.get(current)
        if posting_lock is not None and posted_at > posting_lock:
            raise ValueError(f"posting month already locked: {current}")
        return current

    def run(self, actions, cutoff):
        if not is_utc(cutoff):
            raise ValueError("journal cutoff requires UTC")
        if self.restatement:
            has_approval = getattr(self.sources, "has_approval", None)
            ok = (has_approval(self.restatement, cutoff) if has_approval is not None else any(
                row.system == "stage4/approvals" and row.document_id == self.restatement
                and row.available_at <= cutoff for row in self.sources.rows.values()
            ))
            if not ok:
                raise ValueError("restatement requires an available controller approval")
        ready = {}
        for action in actions:
            if ready.setdefault(action.key, action) != action:
                raise ValueError(f"conflicting journal retry: {action.key}")
        rows = self.sources.rows
        restatement = self.restatement
        ordered = []
        for action in ready.values():
            source = rows[action.source_id]
            if source.available_at <= cutoff:
                when = action.restate_at if restatement and action.restate_at else source.available_at
                priority = 0 if action.component in {"opening_wip", "acquisition"} else 2 if action.release else 1
                ordered.append(((when, priority, action.effective_at, action.key), action, source))
        ordered.sort(key=lambda item: item[0])
        for stamp, action, source in ordered:
            if action.key in self._actions:
                if self._actions[action.key] != action:
                    raise ValueError(f"conflicting journal retry: {action.key}")
                continue
            if self._watermark is not None and stamp < self._watermark:
                raise ValueError("append requires a source available after the journal frontier")
            self._post(action, stamp[0], source=source)
            self._watermark = stamp
        return tuple(self._journals.values())

    def _post(self, action, routing_at, *, source=None):
        if source is None:
            source = self.sources.rows[action.source_id]
        if (not action.key or not action.component or type(action.cents) is not int
                or not is_utc(action.effective_at)
                or action.effective_at > source.available_at
                or not isinstance(action.debit, Account) or not isinstance(action.credit, Account)
                or action.debit == action.credit
                or (action.animal_id is not None and not action.lot_id)
                or ((action.route_cost or action.release or Account.WIP in {action.debit, action.credit})
                    and not action.animal_id)):
            raise ValueError(f"invalid journal action: {action.key}")
        if action.approval_id and not any(
            self.sources.rows[parent].document_id == action.approval_id
            and self.sources.rows[parent].system == "stage4/approvals"
            for parent in self.sources.parents[action.source_id]
        ):
            raise ValueError(f"posting requires source-linked approval: {action.key}")
        if self.restatement and action.restate_at and (
                not action.approval_id or not action.effective_at <= routing_at <= source.available_at):
            raise ValueError(f"invalid historical restatement routing: {action.key}")
        animal = action.animal_id
        debit, credit, amount = action.debit, action.credit, action.cents
        exit_event = self._exits.get(animal)
        acquiring = action.component in {"opening_wip", "acquisition"}
        if acquiring and (animal in self._entries or debit != Account.WIP or amount <= 0):
            raise ValueError(f"invalid or duplicate cattle acquisition: {animal}")
        if animal and not acquiring and (action.release or Account.WIP in {debit, credit}) and animal not in self._entries:
            raise ValueError(f"cattle cost has no known opening or receipt: {animal}")
        if action.release:
            expected_kind = "sale" if debit == Account.COGS else "death"
            if (exit_event or debit not in OUTCOMES or credit != Account.WIP or amount != 0
                    or source.system != "livestock/movement_events" or source.event_kind != expected_kind
                    or self._wip[animal] < 0):
                raise ValueError(f"invalid or duplicate principal release: {animal}")
            amount = self._wip[animal]
            exit_event = debit, source.source_id
        elif animal and Account.WIP in {debit, credit}:
            if action.route_cost and exit_event:
                if action.effective_at > self.sources.rows[exit_event[1]].effective_at:
                    raise ValueError(f"cost service after exit: {action.key}")
                if debit == Account.WIP:
                    debit = exit_event[0]
                else:
                    credit = exit_event[0]
            elif exit_event:
                raise ValueError(f"posting would reopen exited cattle WIP: {animal}")
        if amount < 0:
            debit, credit, amount = credit, debit, -amount
        reversed_row = self._journals.get(action.reverses)
        if action.reverses:
            original = self._actions.get(action.reverses)
            if (not action.approval_id or not reversed_row or not original
                    or action.reverses in self._reversed or original.release
                    or original.source_id not in self.sources.parents[action.source_id]
                    or (action.debit, action.credit, action.cents, animal, action.component, action.pool_id,
                        action.effective_at, action.lot_id, action.location_id, action.route_cost)
                    != (original.debit, original.credit, -original.cents, original.animal_id,
                        original.component, original.pool_id, original.effective_at,
                        original.lot_id, original.location_id, original.route_cost)):
                raise ValueError(f"invalid reversal: {action.key}")
        month = self._accounting_month(action.effective_at, routing_at)
        if acquiring:
            self._entries.add(animal)
        if action.release:
            self._exits[animal] = exit_event
        self._wip[animal] += amount * ((debit == Account.WIP) - (credit == Account.WIP))
        self._actions[action.key] = action
        if action.reverses:
            self._reversed.add(action.reverses)
        if not amount and not action.release:
            return
        self._journals[action.key] = Journal(
            stable_id("JOURNAL", [self.version, self.policy, action.key]), source.source_id,
            source.system, source.document_id, source.line_id, animal, action.lot_id, action.location_id,
            self.yard, business_date(action.effective_at), action.effective_at, source.posted_at,
            source.available_at, source.available_at, month, routing_at, debit, credit, amount, action.component,
            action.pool_id, source.source_snapshot_id, self.version, self.policy, action.approval_id,
            self.restatement if action.restate_at else None,
            reversed_row.journal_id if reversed_row else None, exit_event[1] if exit_event else None,
            action.release)


@dataclass(frozen=True)
class JournalLine:
    journal_id: str
    line_number: int
    account: Account
    signed_cents: int


def journal_lines(journals):
    for row in journals:
        yield JournalLine(row.journal_id, 1, row.debit_account, row.amount_cents)
        yield JournalLine(row.journal_id, 2, row.credit_account, -row.amount_cents)


def balance(journals, account):
    return sum(row.amount_cents * ((row.debit_account == account) - (row.credit_account == account))
               for row in journals)
