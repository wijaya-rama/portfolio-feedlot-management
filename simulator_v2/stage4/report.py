"""Financial summaries and publication gates for the Stage 4 fixture."""

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime

from ..stage1.fixture import FINAL_CUTOFF
from ..stage1.model import business_date, midnight
from ..stage1.provenance import canonical, sha256
from ..stage1.validation import Check, reject_failures
from ..stage3.reconciliation import wip_candidates
from ..stage3.warehouse import bridges
from ..stage3_5.reconciliation import StockDMBridge, dm_bridges
from .chart import CHART
from .close import close_month, compare_closes
from .feed import CONSUMED, NORMAL_COMPONENTS
from .ledger import Account, Book, CATTLE_COST, TICK, balance, journal_lines
from .recovery import RecoveryLot

BASELINE = (161646, 1605, 771, 13028, 2, 146240, 4882099, 2924400)


@dataclass(frozen=True)
class FeedBridge:
    period: str
    policy_version: str
    gross_issue_cents: int
    mix_loss_cents: int
    distribution_loss_cents: int
    refusal_cents: int
    bunk_loss_cents: int
    consumption_base_cents: int
    normal_mix_cents: int
    normal_distribution_cents: int
    normal_refusal_cents: int
    absorbed_normal_cents: int
    wip_and_released_feed_cents: int
    recoverable_cents: int
    abnormal_process_cents: int
    other_warehouse_variance_cents: int
    pending_cents: int
    original_consumed_g_af: int
    original_consumed_g_dm: int


@dataclass(frozen=True)
class Sensitivity:
    month: str
    policy_version: str
    booked_absorption_cents: int
    ending_absorption_in_wip_cents: int
    closing_wip_cents: int
    recoverable_cents: int
    clearing_cents: int
    net_sales_cents: int
    sales_cogs_cents: int
    sales_gross_margin_cents: int
    mortality_writeoff_cents: int
    operating_feed_variance_cents: int
    modeled_yard_contribution_cents: int
    cumulative_accounted_cost_cents: int


@dataclass(frozen=True)
class InvoiceRoute:
    journal_id: str
    invoice_split_id: str
    invoice_document_id: str
    layer_id: str
    historical_entry_id: str | None
    inventory_entry_id: str | None
    delivery_or_mix_id: str | None
    animal_id: str | None
    component: str
    accounting_month: str
    destination_account: Account
    signed_cents: int


@dataclass(frozen=True)
class InvoiceImpact:
    invoice_split_id: str
    animal_id: str | None
    horizon_account: Account
    net_cents: int


@dataclass(frozen=True)
class WarehouseVintage:
    snapshot_id: str
    effective_before: datetime
    knowledge_cutoff: datetime
    revises_snapshot_id: str | None
    approval_id: str | None
    g_af: int
    cents: int


@dataclass(frozen=True)
class MonthlyWarehouseDM(StockDMBridge):
    close_id: str


def feed_bridge(fixture):
    monthly = defaultdict(list)
    for row in fixture.active_feed:
        day = business_date(row.service_at).isoformat()[:7]
        monthly[day].append(row)
        monthly["horizon"].append(row)
    stock = defaultdict(int)
    for row in fixture.warehouse:
        if row.kind in {"adjustment", "spoilage"}:
            stock[row.accounting_month] -= row.cents
            stock["horizon"] -= row.cents
    for period, rows in sorted(monthly.items()):
        def column(name):
            return sum(getattr(row, name) for row in rows)
        mix, distribution, refusal, bunk, consumed = map(
            column, ("mix_loss_cents", "distribution_loss_cents", "refusal_cents",
                     "bunk_loss_cents", "consumption_cents"))
        normal_mix, normal_distribution, normal_refusal = map(
            column, ("normal_mix_cents", "normal_distribution_cents", "normal_refusal_cents"))
        absorbed = normal_mix + normal_distribution + normal_refusal
        yield FeedBridge(
            period, fixture.feed.policy.version, mix + distribution + refusal + bunk + consumed,
            mix, distribution, refusal, bunk, consumed, normal_mix, normal_distribution,
            normal_refusal, absorbed, consumed + absorbed, column("recoverable_cents"),
            column("abnormal_cents"), stock[period], column("pending_cents"),
            column("consumed_g_af"), column("consumed_g_dm"))


def journal_sets(fixture, *, corrected=False, cutoff=FINAL_CUTOFF):
    return Book(fixture.sources, fixture.calendar, version="restated" if corrected else "booked",
                policy=fixture.feed.policy.version, yard=fixture.config["yard_id"],
                restatement=fixture.restated if corrected else None).run(fixture.actions, cutoff)


def close_series(fixture, journals, *, originals=()):
    previous = None
    all_closes = []
    for index, period in enumerate(fixture.calendar):
        original = originals[index][0] if originals else None
        # Publication of the corrected series follows the lock on the last partial month.
        knowledge = FINAL_CUTOFF + TICK if original else None
        result = close_month(fixture, period, journals, prior=previous, original=original, knowledge=knowledge)
        if previous:
            before = all_closes[-1][6]
            current = result[6]
            previous_trial = {row.account: row.closing_signed_cents for row in all_closes[-1][4]}
            if (before.closing_wip_cents != current.opening_wip_cents
                    or any(previous_trial[row.account] != row.opening_signed_cents for row in result[4])
                    or before.inventory_cents != sum(row.opening_cents for row in result[3])
                    or before.inventory_g_af != sum(row.opening_g_af for row in result[3])):
                raise ValueError(f"monthly opening does not match preceding close: {period.month}")
        all_closes.append(result)
        previous = result[0]
    return tuple(all_closes)


def dry_matter(fixture, closes):
    for summary in closes:
        close = summary[0]
        snapshot = fixture.operations.warehouse.snapshot(close.effective_before, close.knowledge_cutoff)
        period = next(period for period in fixture.calendar if period.month == close.month)
        stock = tuple(bridges(snapshot, (midnight(period.start), close.effective_before)))
        basis = replace(fixture.operations, warehouse_snapshots=(snapshot,), stock_bridges=stock)
        for row in dm_bridges(basis):
            if (row.opening_g_dm + row.receipts_g_dm + row.transfers_g_dm
                    + row.issues_g_dm + row.adjustments_g_dm + row.spoilage_g_dm
                    + row.returns_g_dm + row.assay_revaluation_g_dm + row.rounding_g_dm != row.closing_g_dm):
                raise ValueError(f"invalid monthly DM bridge: {close.month}/{row.layer_id}")
            yield MonthlyWarehouseDM(**asdict(row), close_id=close.close_id)


def invoice_routes(fixture, journals):
    splits = fixture.operations.warehouse_snapshots[0].invoice_splits
    by_source = {fixture.refs[row.split_id]: row for row in splits}
    inventory_sources = {fixture.refs[row.inventory_entry_id]: row for row in splits if row.inventory_entry_id}
    for journal in journals:
        if Account.INVOICE not in {journal.debit_account, journal.credit_account}:
            continue
        direct = [by_source[key] for key in fixture.sources.parents[journal.source_id] | {journal.source_id}
                  if key in by_source]
        split = inventory_sources[journal.source_id] if not direct else direct[0]
        cents = -balance((journal,), Account.INVOICE)
        yield InvoiceRoute(
            journal.journal_id, split.split_id, split.invoice_transaction_id, split.layer_id,
            split.historical_entry_id, split.inventory_entry_id, journal.pool_id, journal.animal_id,
            journal.component, journal.accounting_month,
            journal.debit_account if cents > 0 else journal.credit_account, cents)


def invoice_impact(invoices, journals):
    exits = {row.animal_id: row.debit_account for row in journals if row.principal_release}
    totals = defaultdict(int)
    for row in invoices:
        account = row.destination_account
        if account == Account.WIP:
            account = exits.get(row.animal_id, account)
        totals[row.invoice_split_id, row.animal_id, account] += row.signed_cents
    for (split, animal, account), cents in sorted(totals.items(),
                                                 key=lambda item: (item[0][0], item[0][1] or "", item[0][2])):
        if cents:
            yield InvoiceImpact(split, animal, account, cents)


def warehouse_vintages(fixture):
    for row in fixture.operations.warehouse_snapshots:
        yield WarehouseVintage(row.snapshot_id, row.effective_before, row.knowledge_cutoff,
                               row.revises_snapshot_id, row.approval_id,
                               sum(item.g_af for item in row.balances),
                               sum(item.cents for item in row.balances))


def recoverable(fixture, invoices):
    for row in fixture.active_feed:
        if not row.recoverable_g_af:
            continue
        delivery_id = row.delivery_id
        delivery = fixture.feed.deliveries[delivery_id]
        ticket = next(version.row.bunk_ticket_id for version in fixture.feed.by_delivery[delivery_id]
                      if version.row.settlement_id == row.settlement_id)
        yield RecoveryLot(ticket, delivery_id, ticket, row.settlement_id, delivery.pen_id,
                          row.available_at, row.recoverable_g_af, row.recoverable_g_dm,
                          row.recoverable_cents,
                          sum(item.signed_cents for item in invoices if item.destination_account == Account.RECOVERY
                              and item.delivery_or_mix_id == delivery_id))


def sensitivity(fixture, journals, summaries):
    horizon = defaultdict(int)
    for batch in summaries:
        month = batch[0].month
        totals = batch[6]
        current = [row for row in journals if row.accounting_month == month]
        absorbed = sum(sum(balance((row,), account) for account in CATTLE_COST)
                       for row in current if row.component.removeprefix("invoice_") in NORMAL_COMPONENTS)
        values = {
            "booked_absorption_cents": absorbed,
            "ending_absorption_in_wip_cents": totals.retained_absorbed_cents,
            "closing_wip_cents": totals.closing_wip_cents,
            "recoverable_cents": totals.recoverable_cents,
            "clearing_cents": totals.clearing_cents,
            "net_sales_cents": totals.net_sales_cents,
            "sales_cogs_cents": totals.sales_cogs_cents,
            "sales_gross_margin_cents": totals.sales_gross_margin_cents,
            "mortality_writeoff_cents": totals.mortality_burden_cents,
            "operating_feed_variance_cents": totals.feed_operating_variance_cents,
            "modeled_yard_contribution_cents": totals.modeled_yard_contribution_cents,
        }
        for key, value in values.items():
            if key in {"ending_absorption_in_wip_cents", "closing_wip_cents",
                       "recoverable_cents", "clearing_cents"}:
                horizon[key] = value
            else:
                horizon[key] += value
        accumulated = sum(horizon[key] for key in (
            "closing_wip_cents", "recoverable_cents", "sales_cogs_cents",
            "mortality_writeoff_cents", "operating_feed_variance_cents", "clearing_cents"))
        yield Sensitivity(month, fixture.feed.policy.version, **values,
                          cumulative_accounted_cost_cents=accumulated)
    yield Sensitivity("horizon", fixture.feed.policy.version, **horizon,
                      cumulative_accounted_cost_cents=accumulated)


def validation(fixture, journals, original, revised, feed, invoices, recovery):
    errors = []
    def check(label, expected, actual):
        errors.append(Check(label, "stage4/fixture", expected, actual, int(expected != actual)))

    ids = {row.journal_id: row for row in journals}
    keys = {row.account for row in CHART}
    check("DOUBLE_ENTRY_AND_IDENTIFIERS", (len(journals), set(Account) == keys, 0),
          (len(ids), True, sum(row.debit_account == row.credit_account or row.amount_cents < 0
                              or type(row.amount_cents) is not int or
                              (not row.amount_cents and not row.principal_release) for row in journals)))
    lines = defaultdict(list)
    for line in journal_lines(journals):
        lines[line.journal_id].append(line.signed_cents)
    check("BALANCED_BOOK", (len(journals), 0, 0),
          (len(lines), sum(sum(amounts) != 0 or len(amounts) != 2 for amounts in lines.values()),
           sum(balance(journals, account) for account in Account)))
    check("NO_FUTURE_SOURCE", 0, sum(
        row.available_at != fixture.sources.rows[row.source_id].available_at
        or row.posted_at < row.available_at or row.effective_at > row.available_at
        or row.source_snapshot_id != fixture.sources.rows[row.source_id].source_snapshot_id
        or (row.reverses_journal_id is not None
            and ids[row.reverses_journal_id].available_at > row.available_at)
        for row in journals))
    check("SOURCE_LINEAGE", 0, sum(
        link.parent_id not in fixture.sources.rows or
        fixture.sources.rows[link.parent_id].available_at > fixture.sources.rows[link.source_id].available_at
        for link in fixture.sources.links))
    check("NORMAL_AND_CONSUMPTION_RECOGNIZED_ONCE", 0, sum(
        b.gross_issue_cents != b.wip_and_released_feed_cents + b.recoverable_cents
        + b.abnormal_process_cents + b.pending_cents for b in feed))
    horizon = next(row for row in feed if row.period == "horizon")
    check("STAGE35_INDEPENDENT_FEED_TOTALS", BASELINE, (
        horizon.gross_issue_cents, horizon.mix_loss_cents, horizon.distribution_loss_cents,
        horizon.refusal_cents, horizon.bunk_loss_cents, horizon.consumption_base_cents,
        horizon.original_consumed_g_af, horizon.original_consumed_g_dm))
    candidates = wip_candidates(fixture.operations)
    check("SINGLE_ALLOCATION_METHOD_AND_INTAKE", (3336, 146240, 2924400), (
        len(candidates), sum(row.provisional_cents for row in candidates), sum(row.g_dm for row in candidates)))
    recognized = sum(sum(balance((row,), account) for account in CATTLE_COST) for row in journals
                     if row.component in NORMAL_COMPONENTS | {CONSUMED})
    check("LEDGER_VERSUS_PHYSICAL_FEED_COST", horizon.wip_and_released_feed_cents, recognized)
    check("WAREHOUSE_FIFO_ONCE", horizon.gross_issue_cents, sum(
        row.amount_cents for row in journals if row.component == "warehouse_issue"))
    check("FEED_INVOICE_ROUTED", 25, sum(row.signed_cents for row in invoices))
    check("RECOVERY_CONTROL", balance(journals, Account.RECOVERY),
          sum(row.provisional_cents + row.invoice_cents for row in recovery))
    check("MONTH_LOCK_IMMUTABLE", tuple(row[0].close_id for row in original), tuple(
        close_month(fixture, period, journal_sets(fixture, cutoff=period.locked_at),
                    prior=original[index - 1][0] if index else None)[0].close_id
        for index, period in enumerate(fixture.calendar)))
    check("RESTATEMENT_LINEAGE", tuple(row[0].close_id for row in original),
          tuple(row[0].replaces_close_id for row in revised))
    check("DAILY_YARDAGE", (338, 338), (
        len(fixture.yardage), len({(row.date, row.animal_id) for row in fixture.yardage})))
    check("FIXTURE_ONLY", 12, len(fixture.operations.timeline.animals))
    for close in (*original, *revised):
        errors.extend(close[7])
    reject_failures(errors)
    return tuple(errors)


def reconciliation(fixture, journals, original, revised, invoices, feed):
    invoices_by_sink = defaultdict(int)
    for row in invoices:
        invoices_by_sink[row.destination_account.name] += row.signed_cents
    invoice_total = {key: value for key, value in invoices_by_sink.items() if value}
    terminal = defaultdict(int)
    for row in invoice_impact(invoices, journals):
        terminal[row.horizon_account.name] += row.net_cents
    month_ends = [row[6] for row in original]
    return {
        "source_scenario": fixture.operations.scenario["version"],
        "allocation_method": fixture.config["method"],
        "policy": fixture.feed.policy.version,
        "feed_cost_bridge": feed,
        "monthly_as_known": month_ends,
        "monthly_restated": [row[6] for row in revised],
        "restatement_deltas": [delta for parent, child in zip(original, revised, strict=True)
                               for delta in compare_closes(parent, child) if delta.delta],
        "invoice_net_posting_accounts_cents": invoice_total,
        "invoice_horizon_destination_cents": terminal,
        "animal_wip_at_horizon": original[-1][1],
        "trial_balance_signed_cents": {account.name: balance(journals, account) for account in Account},
        "trial_balance_debits_cents": sum(max(0, balance(journals, account)) for account in Account),
        "trial_balance_credits_cents": sum(max(0, -balance(journals, account)) for account in Account),
        "snapshot_chain_sha256": sha256(canonical(tuple(row[0] for row in (*original, *revised)))),
    }
