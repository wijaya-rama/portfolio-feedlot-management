"""Period activation and exact ordered fingerprints for the Stage 4 close."""

from bisect import bisect_left
from collections import Counter
from datetime import date, datetime, timedelta
from hashlib import sha256
from json.encoder import encode_basestring as _quote

from ..stage1.model import UTC, business_date
from ..stage1.provenance import canonical
from ..stage3.warehouse import Balance
from ..stage4.close import JournalSummary
from ..stage4.ledger import Journal

_EPOCH_DATE = date(1970, 1, 1)
_EPOCH_DT = datetime(1970, 1, 1, tzinfo=UTC)
_DT_ISO_CACHE = {}
_US_ISO_CACHE = {}
_DATE_ISO_CACHE = {}
_DAYS_ISO_CACHE = {}


def _fmt_dt(value):
    cached = _DT_ISO_CACHE.get(value)
    if cached is not None:
        return cached
    text = (value.isoformat()[:-6] + "Z") if value.tzinfo is UTC else value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    quoted = f'"{text}"'
    if len(_DT_ISO_CACHE) > 65536:
        _DT_ISO_CACHE.clear()
    _DT_ISO_CACHE[value] = quoted
    return quoted


def _fmt_date(value):
    cached = _DATE_ISO_CACHE.get(value)
    if cached is not None:
        return cached
    quoted = f'"{value.isoformat()}"'
    if len(_DATE_ISO_CACHE) > 4096:
        _DATE_ISO_CACHE.clear()
    _DATE_ISO_CACHE[value] = quoted
    return quoted


def _fmt_us(us):
    cached = _US_ISO_CACHE.get(us)
    if cached is not None:
        return cached
    dt = _EPOCH_DT + timedelta(microseconds=us)
    quoted = f'"{dt.isoformat()[:-6]}Z"'
    if len(_US_ISO_CACHE) > 65536:
        _US_ISO_CACHE.clear()
    _US_ISO_CACHE[us] = quoted
    return quoted


def _fmt_days(days):
    cached = _DAYS_ISO_CACHE.get(days)
    if cached is not None:
        return cached
    quoted = f'"{(_EPOCH_DATE + timedelta(days=days)).isoformat()}"'
    if len(_DAYS_ISO_CACHE) > 4096:
        _DAYS_ISO_CACHE.clear()
    _DAYS_ISO_CACHE[days] = quoted
    return quoted


def _qopt(value):
    return "null" if value is None else _quote(value)


def canonical_journal_bytes(row):
    """Exact byte-identical equivalent of canonical(vars(row))[:-1] for Stage 4 Journal rows."""
    return (
        f'{{"accounting_month":{_quote(row.accounting_month)},'
        f'"amount_cents":{row.amount_cents},'
        f'"animal_id":{_qopt(row.animal_id)},'
        f'"approval_id":{_qopt(row.approval_id)},'
        f'"available_at":{_fmt_dt(row.available_at)},'
        f'"component":{_quote(row.component)},'
        f'"credit_account":{_quote(row.credit_account)},'
        f'"debit_account":{_quote(row.debit_account)},'
        f'"document_id":{_quote(row.document_id)},'
        f'"effective_at":{_fmt_dt(row.effective_at)},'
        f'"journal_id":{_quote(row.journal_id)},'
        f'"ledger_version":{_quote(row.ledger_version)},'
        f'"line_id":{_quote(row.line_id)},'
        f'"location_id":{_qopt(row.location_id)},'
        f'"lot_id":{_qopt(row.lot_id)},'
        f'"outcome_event_id":{_qopt(row.outcome_event_id)},'
        f'"period_routing_at":{_fmt_dt(row.period_routing_at)},'
        f'"policy_version":{_quote(row.policy_version)},'
        f'"pool_id":{_qopt(row.pool_id)},'
        f'"posted_at":{_fmt_dt(row.posted_at)},'
        f'"principal_release":{"true" if row.principal_release else "false"},'
        f'"restatement_approval_id":{_qopt(row.restatement_approval_id)},'
        f'"reverses_journal_id":{_qopt(row.reverses_journal_id)},'
        f'"service_date":{_fmt_date(row.service_date)},'
        f'"source_id":{_quote(row.source_id)},'
        f'"source_posted_at":{_fmt_dt(row.source_posted_at)},'
        f'"source_snapshot_id":{_quote(row.source_snapshot_id)},'
        f'"source_system":{_quote(row.source_system)},'
        f'"yard_id":{_quote(row.yard_id)}}}'
    ).encode("utf-8")


def canonical_journal_from_columns(
    accounting_month, amount_cents, animal_id, approval_id, available_us, component,
    credit_account, debit_account, document_id, effective_us, journal_id, ledger_version,
    line_id, location_id, lot_id, outcome_event_id, period_routing_us, policy_version,
    pool_id, posted_us, principal_release, restatement_approval_id, reverses_journal_id,
    service_days, source_id, source_posted_us, source_snapshot_id, source_system, yard_id,
):
    """Exact byte-identical canonical Journal JSON from Parquet columnar values (UTC us / epoch days)."""
    return (
        f'{{"accounting_month":{_quote(accounting_month)},'
        f'"amount_cents":{amount_cents},'
        f'"animal_id":{_qopt(animal_id)},'
        f'"approval_id":{_qopt(approval_id)},'
        f'"available_at":{_fmt_us(available_us)},'
        f'"component":{_quote(component)},'
        f'"credit_account":{_quote(credit_account)},'
        f'"debit_account":{_quote(debit_account)},'
        f'"document_id":{_quote(document_id)},'
        f'"effective_at":{_fmt_us(effective_us)},'
        f'"journal_id":{_quote(journal_id)},'
        f'"ledger_version":{_quote(ledger_version)},'
        f'"line_id":{_quote(line_id)},'
        f'"location_id":{_qopt(location_id)},'
        f'"lot_id":{_qopt(lot_id)},'
        f'"outcome_event_id":{_qopt(outcome_event_id)},'
        f'"period_routing_at":{_fmt_us(period_routing_us)},'
        f'"policy_version":{_quote(policy_version)},'
        f'"pool_id":{_qopt(pool_id)},'
        f'"posted_at":{_fmt_us(posted_us)},'
        f'"principal_release":{"true" if principal_release else "false"},'
        f'"restatement_approval_id":{_qopt(restatement_approval_id)},'
        f'"reverses_journal_id":{_qopt(reverses_journal_id)},'
        f'"service_date":{_fmt_days(service_days)},'
        f'"source_id":{_quote(source_id)},'
        f'"source_posted_at":{_fmt_us(source_posted_us)},'
        f'"source_snapshot_id":{_quote(source_snapshot_id)},'
        f'"source_system":{_quote(source_system)},'
        f'"yard_id":{_quote(yard_id)}}}'
    ).encode("utf-8")


class JournalVisibility:
    def __init__(self, periods, cutoffs):
        self.months = tuple(period.month for period in periods)
        self.cutoffs = tuple(cutoffs)
        if len(self.months) != len(self.cutoffs) or tuple(sorted(self.cutoffs)) != self.cutoffs:
            raise ValueError("close visibility requires a nondecreasing cutoff by month")

    def first(self, month, available_at):
        return max(bisect_left(self.months, month), bisect_left(self.cutoffs, available_at))


class OrderedFingerprints:
    """Share SHA-256 state while ordered journal prefixes are identical."""

    def __init__(self, size):
        self.size = size
        self.starts = [0]
        self.groups = [(sha256(b"["), 0)]

    def add(self, first, encoded):
        index = bisect_left(self.starts, first)
        if index == len(self.starts) or self.starts[index] != first:
            digest, count = self.groups[index - 1]
            self.starts.insert(index, first)
            self.groups.insert(index, (digest.copy(), count))
        for i in range(index, len(self.groups)):
            digest, count = self.groups[i]
            if count:
                digest.update(b",")
            digest.update(encoded)
            self.groups[i] = digest, count + 1

    def results(self):
        for i, (digest, count) in enumerate(self.groups):
            finalized = digest.copy()
            finalized.update(b"]\n")
            result = finalized.hexdigest(), count
            stop = self.starts[i + 1] if i + 1 < len(self.starts) else self.size
            yield from (result for _ in range(self.starts[i], stop))


class CloseIndex:
    def __init__(self, periods, cutoffs):
        self.visibility = JournalVisibility(periods, cutoffs)
        self.moves = [JournalSummary() for _ in periods]
        self.fingerprints = OrderedFingerprints(len(periods))

    def add(self, journals):
        visible = []
        for row in journals:
            first = self.visibility.first(row.accounting_month, row.available_at)
            if first < len(self.moves):
                self.moves[first].add(row, self.visibility.months[first])
                visible.append((first, row))
        self.add_fingerprints(visible)

    def add_fingerprints(self, visible):
        for first, row in visible:
            encoded = canonical_journal_bytes(row) if isinstance(row, Journal) else canonical(vars(row))[:-1]
            self.fingerprints.add(first, encoded)

    def checkpoints(self):
        rolling = JournalSummary()
        for index, (digest, count) in enumerate(self.fingerprints.results()):
            rolling.roll_forward(self.moves[index])
            self.moves[index] = None
            yield rolling, digest, count


def immediate_warehouse_closes(snapshot, periods):
    """Reduce independently replayed FIFO entries at month end for immediate feeds."""
    if any(row.effective_at != row.available_at for row in snapshot.entries):
        return {}
    if any(previous.effective_at > row.effective_at for previous, row in zip(snapshot.entries, snapshot.entries[1:])):
        return {}
    entries = iter(snapshot.entries)
    row = next(entries, None)
    balances = {}
    closes = {}
    for period in periods:
        while row is not None and row.effective_at < period.effective_before:
            key = row.bin_id, row.layer_id
            grams, cents = balances.get(key, (0, 0))
            grams, cents = grams + row.g_af, cents + row.cents
            if grams or cents:
                balances[key] = grams, cents
            else:
                balances.pop(key, None)
            row = next(entries, None)
        closes[period.month] = tuple(Balance(*key, *amounts) for key, amounts in sorted(balances.items()))
    return closes


def yardage_by_month(rows):
    return Counter(business_date(row.service_at).strftime("%Y-%m") for row in rows)
