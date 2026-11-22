"""Monthly inventory, account and animal reconciliations at explicit knowledge cutoffs."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from ..stage1.model import AnimalStatus
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.soh import calculate_soh
from ..stage1.validation import Check, reject_failures
from ..stage3.warehouse import Kind
from .feed import CONSUMED, NORMAL_COMPONENTS
from .ledger import Account, CATTLE_COST, CLEARING, OUTCOMES, VARIANCES, balance


@dataclass(frozen=True)
class Close:
    close_id: str
    month: str
    start_date: date
    end_date: date
    effective_before: datetime
    knowledge_cutoff: datetime
    locked_at: datetime
    view: str
    policy_version: str
    journal_sha256: str
    source_journal_count: int
    replaces_close_id: str | None
    prior_month_close_id: str | None
    approval_id: str | None


@dataclass(frozen=True)
class AnimalWip:
    close_id: str
    month: str
    animal_id: str
    lot_id: str
    yard_id: str
    closing_location_id: str | None
    status: str
    opening_cents: int
    acquisition_cents: int
    feed_consumption_cents: int
    feed_absorbed_cents: int
    yardage_cents: int
    veterinary_cents: int
    veterinary_overhead_cents: int
    adjustments_cents: int
    sales_release_cents: int
    mortality_release_cents: int
    closing_cents: int
    late_cogs_cents: int
    late_mortality_cents: int


@dataclass(frozen=True)
class AnimalComponent:
    close_id: str
    month: str
    animal_id: str
    lot_id: str
    yard_id: str
    closing_location_id: str | None
    component: str
    ending_wip_cents: int
    cumulative_cogs_cents: int
    cumulative_mortality_cents: int


def animal_components(batch, journals):
    close, animals = batch[:2]
    ledger = defaultdict(Counter)
    for row in journals:
        if (row.animal_id and not row.principal_release and row.accounting_month <= close.month
                and row.available_at <= close.knowledge_cutoff):
            signed = sum(balance((row,), account) for account in CATTLE_COST)
            if signed:
                ledger[row.animal_id][row.component] += signed
    destinations = {AnimalStatus.ACTIVE: 0, AnimalStatus.SOLD: 1, AnimalStatus.DEAD: 2}
    for animal in animals:
        costs = ledger[animal.animal_id]
        index = destinations.get(animal.status)
        if index is None and costs:
            raise ValueError(f"cattle cost before receipt: {animal.animal_id}")
        if index == 0 and sum(costs.values()) != animal.closing_cents:
            raise ValueError(f"cattle cost components disagree with WIP: {animal.animal_id}")
        for component, cents in sorted(costs.items()):
            if cents:
                amounts = [0, 0, 0]
                amounts[index] = cents
                yield AnimalComponent(close.close_id, close.month, animal.animal_id, animal.lot_id,
                                      animal.yard_id, animal.closing_location_id, component, *amounts)


@dataclass(frozen=True)
class Stock:
    close_id: str
    month: str
    scope_type: str
    scope_id: str
    opening_head: int
    receipts: int
    sales: int
    deaths: int
    transfers_in: int
    transfers_out: int
    closing_head: int
    animal_days: int


@dataclass(frozen=True)
class Trial:
    close_id: str
    month: str
    account: Account
    opening_signed_cents: int
    debit_cents: int
    credit_cents: int
    closing_signed_cents: int


@dataclass(frozen=True)
class Warehouse:
    close_id: str
    month: str
    bin_id: str
    layer_id: str
    ingredient_id: str
    opening_g_af: int
    opening_cents: int
    receipts_g_af: int
    receipts_cents: int
    issues_g_af: int
    issues_cents: int
    transfers_g_af: int
    transfers_cents: int
    stock_count_g_af: int
    stock_count_cents: int
    spoilage_g_af: int
    spoilage_cents: int
    returns_g_af: int
    returns_cents: int
    invoice_cents: int
    closing_g_af: int
    closing_cents: int


@dataclass(frozen=True)
class ExceptionRow:
    close_id: str
    month: str
    account: Account
    pool_id: str
    as_of: datetime
    first_effective_at: datetime
    reason: str
    open_cents: int


@dataclass(frozen=True)
class Monthly:
    close_id: str
    month: str
    view: str
    opening_wip_cents: int
    acquisition_cents: int
    consumption_to_wip_cents: int
    loss_to_wip_cents: int
    yardage_to_wip_cents: int
    vet_to_wip_cents: int
    vet_overhead_to_wip_cents: int
    wip_adjustments_cents: int
    sale_release_cents: int
    death_release_cents: int
    closing_wip_cents: int
    retained_absorbed_cents: int
    inventory_cents: int
    inventory_g_af: int
    recoverable_cents: int
    clearing_cents: int
    provisional_revenue_cents: int
    packer_adjustments_cents: int
    net_sales_cents: int
    sales_cogs_cents: int
    sales_gross_margin_cents: int
    mortality_burden_cents: int
    feed_operating_variance_cents: int
    modeled_yard_contribution_cents: int


WIP_FIELDS = {
    "acquisition": "acquisition_cents", CONSUMED: "feed_consumption_cents",
    "yardage": "yardage_cents", "vet_direct": "veterinary_cents",
    "vet_overhead": "veterinary_overhead_cents",
    **{component: "feed_absorbed_cents" for component in NORMAL_COMPONENTS},
}
WAREHOUSE_FIELDS = (Kind.RECEIPT, Kind.ISSUE, "transfer", Kind.ADJUST, Kind.SPOILAGE, Kind.RETURN)


def _wip_rows(close, fixture, journals, states):
    by_animal = defaultdict(list)
    for journal in journals:
        if journal.animal_id:
            by_animal[journal.animal_id].append(journal)
    entries = fixture.operations.timeline.entries
    for state in sorted(states, key=lambda row: row.animal_id):
        animal = state.animal_id
        relevant = by_animal[animal]
        before = [row for row in relevant if row.accounting_month < close.month or row.component == "opening_wip"]
        current = [row for row in relevant if row.accounting_month == close.month and row.component != "opening_wip"]
        costs = Counter()
        for row in current:
            wip = balance((row,), Account.WIP)
            if row.principal_release:
                field = "sales_release_cents" if row.debit_account == Account.COGS else "mortality_release_cents"
                costs[field] += -wip
            elif wip:
                field = WIP_FIELDS.get(row.component, "adjustments_cents")
                if row.approval_id and row.component != "yardage_correction":
                    field = "adjustments_cents"
                costs[field] += wip
            elif row.debit_account in OUTCOMES or row.credit_account in OUTCOMES:
                costs["late_cogs_cents"] += balance((row,), Account.COGS)
                costs["late_mortality_cents"] += balance((row,), Account.MORTALITY)
        if entries[animal].available_at > close.knowledge_cutoff:
            raise ValueError("future entry in animal WIP cutoff")
        yield AnimalWip(close.close_id, close.month, animal, state.lot_id, fixture.config["yard_id"],
                        state.location_id, state.status, balance(before, Account.WIP),
                        *(costs[field] for field in ("acquisition_cents", "feed_consumption_cents",
                                                      "feed_absorbed_cents", "yardage_cents",
                                                      "veterinary_cents", "veterinary_overhead_cents",
                                                      "adjustments_cents",
                                                      "sales_release_cents", "mortality_release_cents")),
                        balance(relevant, Account.WIP),
                        costs["late_cogs_cents"], costs["late_mortality_cents"])


def _warehouse_rows(close, fixture):
    by_layer = defaultdict(list)
    for row in fixture.warehouse:
        if row.available_at <= close.knowledge_cutoff and row.accounting_month <= close.month:
            by_layer[row.bin_id, row.layer_id, row.ingredient_id].append(row)
    for key, lines in sorted(by_layer.items()):
        prior, values = Counter(), defaultdict(Counter)
        for row in lines:
            kind = "transfer" if row.kind in {"transfer_in", "transfer_out"} else row.kind
            amounts = prior if row.accounting_month < close.month or row.kind == Kind.OPENING else values[kind]
            amounts.update({"g_af": row.g_af, "cents": row.cents})
        yield Warehouse(close.close_id, close.month, *key, prior["g_af"], prior["cents"],
                        *(values[kind][unit] for kind in WAREHOUSE_FIELDS for unit in ("g_af", "cents")),
                        values[Kind.INVOICE]["cents"], sum(row.g_af for row in lines),
                        sum(row.cents for row in lines))


def _clearing_pool(row, account):
    if row.component == "distribution_load" and account == Account.DISTRIBUTION:
        return row.document_id
    if row.component == "mix_loss_transfer" and account == Account.NORMAL:
        return row.document_id
    return row.pool_id


def _exceptions(close, fixture, journals):
    buckets = defaultdict(list)
    for row in journals:
        for account in {row.debit_account, row.credit_account} & CLEARING:
            buckets[account, _clearing_pool(row, account)].append(row)
    for (account, pool), group in sorted(buckets.items()):
        cents = balance(group, account)
        if not cents:
            continue
        delivery = fixture.feed.deliveries.get(pool)
        seen_settlement = any(
            version.row.available_at <= close.knowledge_cutoff
            for version in fixture.feed.by_delivery.get(pool, ())[:1])
        future_settlement = (delivery and delivery.effective_at < close.effective_before
                             and not seen_settlement)
        reason = None
        if account == Account.PENDING and cents > 0:
            reason = "Refusal classification evidence missing"
        elif future_settlement and account in {Account.NORMAL, Account.DISTRIBUTION} and cents > 0:
            reason = "Initial settlement unavailable at the knowledge cutoff"
        if reason is None:
            raise ValueError(f"unexplained clearing balance at {close.month}: {account}/{pool}/{cents}")
        yield ExceptionRow(close.close_id, close.month, account, pool, close.knowledge_cutoff,
                           min(row.effective_at for row in group), reason, cents)


def _totals(close, rows, warehouse, relevant, current, exceptions):
    def sum_wip(field):
        return sum(getattr(row, field) for row in rows)

    def retained_absorption(row):
        return ((row.component.removeprefix("invoice_") in NORMAL_COMPONENTS)
                and (row.debit_account == Account.WIP or row.credit_account == Account.WIP)
                and row.animal_id in active)

    active = {row.animal_id for row in rows if row.status == AnimalStatus.ACTIVE}
    retained = sum(balance((row,), Account.WIP) for row in relevant if retained_absorption(row))
    revenue = -balance(current, Account.REVENUE)
    packer = -balance(current, Account.PACKER)
    cogs = balance(current, Account.COGS)
    mortality = balance(current, Account.MORTALITY)
    variance = sum(balance(current, account) for account in VARIANCES)
    return Monthly(
        close.close_id, close.month, close.view, sum_wip("opening_cents"), sum_wip("acquisition_cents"),
        sum_wip("feed_consumption_cents"), sum_wip("feed_absorbed_cents"), sum_wip("yardage_cents"),
        sum_wip("veterinary_cents"), sum_wip("veterinary_overhead_cents"),
        sum_wip("adjustments_cents"), sum_wip("sales_release_cents"),
        sum_wip("mortality_release_cents"), sum_wip("closing_cents"), retained,
        sum(row.closing_cents for row in warehouse), sum(row.closing_g_af for row in warehouse),
        balance(relevant, Account.RECOVERY), sum(row.open_cents for row in exceptions),
        revenue, packer, revenue + packer, cogs, revenue + packer - cogs, mortality, variance,
        revenue + packer - cogs - mortality - variance)


def close_month(fixture, period, journals, *, prior=None, original=None, knowledge=None):
    knowledge = period.locked_at if knowledge is None else knowledge
    revised = original is not None
    approval = fixture.restated if revised else None
    registered = fixture.sources.rows[fixture.refs[approval]] if revised else None
    if (revised and (original.month != period.month or knowledge <= original.knowledge_cutoff
                     or registered.available_at > knowledge)):
        raise ValueError("restatement requires same month, later knowledge and approved source")
    if not revised and knowledge != period.locked_at:
        raise ValueError("original close must use the immutable period lock")
    relevant = [row for row in journals
                if row.accounting_month <= period.month and row.available_at <= knowledge]
    current = [row for row in relevant if row.accounting_month == period.month]
    historical = [row for row in relevant if row.accounting_month < period.month]
    replay, _, monthly, stock_checks = calculate_soh(
        fixture.operations.ledger, period.start, period.end, knowledge)
    reject_failures(stock_checks)
    view = "restated" if revised else "as_known"
    digest = sha256(canonical(relevant))
    identifier = stable_id("MONTHLY-CLOSE", [period, knowledge, view, digest, replay.states, monthly,
                                             approval, original.close_id if revised else None,
                                             prior.close_id if prior else None])
    close = Close(identifier, period.month, period.start, period.end, period.effective_before,
                  knowledge, period.locked_at, view, fixture.feed.policy.version, digest, len(relevant),
                  original.close_id if revised else None, prior.close_id if prior else None, approval)
    wip = tuple(_wip_rows(close, fixture, relevant, replay.states))
    stock = tuple(Stock(close.close_id, close.month, row.scope_type, row.scope_id, row.opening_head,
                        row.receipts, row.sales, row.deaths, row.transfers_in, row.transfers_out,
                        row.closing_head, row.animal_days) for row in monthly)
    warehouse = tuple(_warehouse_rows(close, fixture))
    exceptions = tuple(_exceptions(close, fixture, relevant))
    opening_entries = [row for row in current if row.component in {"opening_wip", "warehouse_opening"}]
    activity = [row for row in current if row not in opening_entries]
    trial = tuple(Trial(close.close_id, close.month, account, balance(historical + opening_entries, account),
                        sum(row.amount_cents for row in activity if row.debit_account == account),
                        sum(row.amount_cents for row in activity if row.credit_account == account),
                        balance(relevant, account)) for account in Account)
    total = _totals(close, wip, warehouse, relevant, current, exceptions)
    expected_exits = {state.animal_id for state in replay.states
                      if state.status in {AnimalStatus.DEAD, AnimalStatus.SOLD}}
    actual_exits = Counter(row.animal_id for row in relevant if row.principal_release)
    warehouse_listing = fixture.operations.warehouse.snapshot(period.effective_before, knowledge)
    expected_layers = {(row.bin_id, row.layer_id): (row.g_af, row.cents)
                       for row in warehouse_listing.balances}
    actual_layers = {(row.bin_id, row.layer_id): (row.closing_g_af, row.closing_cents)
                     for row in warehouse if row.closing_g_af or row.closing_cents}
    checks = [
        ("TRIAL_BALANCE", sum(row.closing_signed_cents for row in trial) == 0
         and sum(row.debit_cents - row.credit_cents for row in trial) == 0
         and all(row.opening_signed_cents + row.debit_cents - row.credit_cents
                 == row.closing_signed_cents for row in trial)),
        ("WAREHOUSE_CONTROL", balance(relevant, Account.WAREHOUSE) == total.inventory_cents
         and actual_layers == expected_layers),
        ("OPENING_CONTROL", sum(row.opening_cents for row in warehouse)
         == next(row.opening_signed_cents for row in trial if row.account == Account.WAREHOUSE)
         and total.opening_wip_cents == next(row.opening_signed_cents for row in trial
                                             if row.account == Account.WIP)),
        ("WIP_CONTROL", balance(relevant, Account.WIP) == total.closing_wip_cents
         and all(row.opening_cents + row.acquisition_cents + row.feed_consumption_cents
                 + row.feed_absorbed_cents + row.yardage_cents + row.veterinary_cents
                 + row.veterinary_overhead_cents
                 + row.adjustments_cents - row.sales_release_cents - row.mortality_release_cents
                 == row.closing_cents >= 0 for row in wip)),
        ("EXIT_WIP", actual_exits == Counter(dict.fromkeys(expected_exits, 1))
         and all(row.status == AnimalStatus.ACTIVE or not row.closing_cents for row in wip)),
        ("RELEASE_AND_LATE_COST", total.sales_cogs_cents == sum(row.sales_release_cents + row.late_cogs_cents
                                                               for row in wip)
         and total.mortality_burden_cents == sum(row.mortality_release_cents + row.late_mortality_cents
                                                for row in wip)),
        ("CLEARING", sum(balance(relevant, account) for account in CLEARING) == total.clearing_cents),
        ("RECEIVABLE", balance(relevant, Account.RECEIVABLE)
         == -balance(relevant, Account.REVENUE) - balance(relevant, Account.PACKER)),
        ("YARDAGE_ELIGIBILITY", sum(period.start <= row.date <= period.end for row in fixture.yardage)
         == next(row.animal_days for row in stock if row.scope_type == "yard")),
    ]
    checks = tuple(Check(label, f"{period.month}/{view}", True, passed, int(not passed))
                   for label, passed in checks)
    reject_failures(checks)
    return close, wip, stock, warehouse, trial, exceptions, total, checks


@dataclass(frozen=True)
class CloseDelta:
    month: str
    original_close_id: str
    corrected_close_id: str
    measure: str
    original: int
    corrected: int
    delta: int


def compare_closes(original, corrected):
    first, second = original[6], corrected[6]
    for name in Monthly.__dataclass_fields__:
        old, new = getattr(first, name), getattr(second, name)
        if type(old) is int:
            yield CloseDelta(first.month, first.close_id, second.close_id, name, old, new, new - old)
    before = {(row.scope_type, row.scope_id): row for row in original[2]}
    after = {(row.scope_type, row.scope_id): row for row in corrected[2]}
    for scope in sorted(before.keys() | after.keys()):
        for field in ("closing_head", "animal_days", "transfers_in", "transfers_out"):
            old, new = getattr(before.get(scope), field, 0), getattr(after.get(scope), field, 0)
            if old != new:
                yield CloseDelta(first.month, first.close_id, second.close_id, "/".join((*scope, field)),
                                 old, new, new - old)
