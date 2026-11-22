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
    yield from _animal_component_rows(close, animals, ledger)


def _animal_component_rows(close, animals, ledger):
    destinations = {AnimalStatus.ACTIVE: 0, AnimalStatus.SOLD: 1, AnimalStatus.DEAD: 2}
    for animal in animals:
        costs = ledger.get(animal.animal_id, {})
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


class JournalSummary:
    """Additive close controls for eligible Stage 4 journals."""
    def __init__(self):
        self.balances = Counter()
        self.current_balances = Counter()
        self.debits, self.credits = Counter(), Counter()
        self.wip = Counter()
        self.current_wip = Counter()
        self.costs = defaultdict(Counter)
        self.components = defaultdict(Counter)
        self.absorption = Counter()
        self.releases = Counter()
        self.clearing = Counter()
        self.clearing_first = {}

    def add(self, row, month):
        debit, credit, amount = row.debit_account, row.credit_account, row.amount_cents
        self.balances[debit] += amount
        self.balances[credit] -= amount
        current = row.accounting_month == month
        component = row.component
        if current:
            self.current_balances[debit] += amount
            self.current_balances[credit] -= amount
            if component not in {"opening_wip", "warehouse_opening"}:
                self.debits[debit] += amount
                self.credits[credit] += amount
        if debit in CLEARING:
            self.add_clearing(debit, row, amount)
        if credit in CLEARING:
            self.add_clearing(credit, row, -amount)
        animal = row.animal_id
        if not animal:
            return
        wip = amount * ((debit == Account.WIP) - (credit == Account.WIP))
        if wip:
            self.wip[animal] += wip
            if component.removeprefix("invoice_") in NORMAL_COMPONENTS:
                self.absorption[animal] += wip
        if row.principal_release:
            self.releases[animal] += 1
        else:
            signed = amount * ((debit in CATTLE_COST) - (credit in CATTLE_COST))
            if signed:
                self.components[animal][component] += signed
        if current and component != "opening_wip":
            if row.principal_release:
                field = "sales_release_cents" if debit == Account.COGS else "mortality_release_cents"
                self.costs[animal][field] -= wip
            elif wip:
                field = WIP_FIELDS.get(component, "adjustments_cents")
                if row.approval_id and component != "yardage_correction":
                    field = "adjustments_cents"
                self.costs[animal][field] += wip
            elif debit in OUTCOMES or credit in OUTCOMES:
                self.costs[animal]["late_cogs_cents"] += amount * ((debit == Account.COGS) - (credit == Account.COGS))
                self.costs[animal]["late_mortality_cents"] += amount * (
                    (debit == Account.MORTALITY) - (credit == Account.MORTALITY))
            if wip:
                self.current_wip[animal] += wip

    def add_clearing(self, account, row, amount):
        key = account, _clearing_pool(row, account)
        self.clearing[key] += amount
        earlier = self.clearing_first.setdefault(key, row.effective_at)
        if row.effective_at < earlier:
            self.clearing_first[key] = row.effective_at

    def roll_forward(self, movement):
        # Advance cumulative controls and retain only this month's activity.
        for field in ("balances", "wip", "absorption", "releases", "clearing"):
            getattr(self, field).update(getattr(movement, field))
        for animal, costs in movement.components.items():
            self.components[animal].update(costs)
        for key, first in movement.clearing_first.items():
            if first < self.clearing_first.setdefault(key, first):
                self.clearing_first[key] = first
        for field in ("current_balances", "debits", "credits", "current_wip", "costs"):
            setattr(self, field, getattr(movement, field))

    def animal_components(self, batch):
        return _animal_component_rows(*batch[:2], self.components)


def _wip_rows(close, fixture, summary, states):
    entries = fixture.operations.timeline.entries
    for state in sorted(states, key=lambda row: row.animal_id):
        animal = state.animal_id
        costs = summary.costs.get(animal, Counter())
        if entries[animal].available_at > close.knowledge_cutoff:
            raise ValueError("future entry in animal WIP cutoff")
        ending = summary.wip[animal]
        yield AnimalWip(close.close_id, close.month, animal, state.lot_id, fixture.config["yard_id"],
                        state.location_id, state.status, ending - summary.current_wip[animal],
                        *(costs[field] for field in ("acquisition_cents", "feed_consumption_cents",
                                                      "feed_absorbed_cents", "yardage_cents",
                                                      "veterinary_cents", "veterinary_overhead_cents",
                                                      "adjustments_cents",
                                                      "sales_release_cents", "mortality_release_cents")),
                        ending, costs["late_cogs_cents"], costs["late_mortality_cents"])


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


def _exceptions(close, fixture, summary):
    for account, pool in sorted(key for key, cents in summary.clearing.items() if cents):
        cents = summary.clearing[account, pool]
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
                           summary.clearing_first[account, pool], reason, cents)


def _totals(close, rows, warehouse, summary, exceptions):
    def sum_wip(field):
        return sum(getattr(row, field) for row in rows)

    retained = sum(summary.absorption[row.animal_id] for row in rows if row.status == AnimalStatus.ACTIVE)
    current = summary.current_balances
    revenue, packer = -current[Account.REVENUE], -current[Account.PACKER]
    cogs, mortality = current[Account.COGS], current[Account.MORTALITY]
    variance = sum(current[account] for account in VARIANCES)
    return Monthly(
        close.close_id, close.month, close.view, sum_wip("opening_cents"), sum_wip("acquisition_cents"),
        sum_wip("feed_consumption_cents"), sum_wip("feed_absorbed_cents"), sum_wip("yardage_cents"),
        sum_wip("veterinary_cents"), sum_wip("veterinary_overhead_cents"),
        sum_wip("adjustments_cents"), sum_wip("sales_release_cents"),
        sum_wip("mortality_release_cents"), sum_wip("closing_cents"), retained,
        sum(row.closing_cents for row in warehouse), sum(row.closing_g_af for row in warehouse),
        summary.balances[Account.RECOVERY], sum(row.open_cents for row in exceptions),
        revenue, packer, revenue + packer, cogs, revenue + packer - cogs, mortality, variance,
        revenue + packer - cogs - mortality - variance)


def close_month(fixture, period, journals, *, prior=None, original=None, knowledge=None,
                journal_checkpoint=None, warehouse_balances=None, yardage_days=None):
    knowledge = period.locked_at if knowledge is None else knowledge
    revised = original is not None
    approval = fixture.restated if revised else None
    registered = fixture.sources.rows[fixture.refs[approval]] if revised else None
    if (revised and (original.month != period.month or knowledge <= original.knowledge_cutoff
                     or registered.available_at > knowledge)):
        raise ValueError("restatement requires same month, later knowledge and approved source")
    if not revised and knowledge != period.locked_at:
        raise ValueError("original close must use the immutable period lock")
    if journal_checkpoint is None:
        relevant = [row for row in journals if row.accounting_month <= period.month and row.available_at <= knowledge]
        summary = JournalSummary()
        for row in relevant:
            summary.add(row, period.month)
        digest, count = sha256(canonical(relevant)), len(relevant)
    else:
        summary, digest, count = journal_checkpoint
    replay, _, monthly, stock_checks = calculate_soh(
        fixture.operations.ledger, period.start, period.end, knowledge)
    reject_failures(stock_checks)
    view = "restated" if revised else "as_known"
    identifier = stable_id("MONTHLY-CLOSE", [period, knowledge, view, digest, replay.states, monthly,
                                             approval, original.close_id if revised else None,
                                             prior.close_id if prior else None])
    close = Close(identifier, period.month, period.start, period.end, period.effective_before,
                  knowledge, period.locked_at, view, fixture.feed.policy.version, digest, count,
                  original.close_id if revised else None, prior.close_id if prior else None, approval)
    wip = tuple(_wip_rows(close, fixture, summary, replay.states))
    stock = tuple(Stock(close.close_id, close.month, row.scope_type, row.scope_id, row.opening_head,
                        row.receipts, row.sales, row.deaths, row.transfers_in, row.transfers_out,
                        row.closing_head, row.animal_days) for row in monthly)
    warehouse = tuple(_warehouse_rows(close, fixture))
    exceptions = tuple(_exceptions(close, fixture, summary))
    balances = summary.balances
    trial = tuple(Trial(close.close_id, close.month, account,
                        balances[account] - summary.debits[account] + summary.credits[account],
                        summary.debits[account], summary.credits[account], balances[account])
                  for account in Account)
    total = _totals(close, wip, warehouse, summary, exceptions)
    expected_exits = {state.animal_id for state in replay.states
                      if state.status in {AnimalStatus.DEAD, AnimalStatus.SOLD}}
    if warehouse_balances is None:
        warehouse_balances = fixture.operations.warehouse.snapshot(period.effective_before, knowledge).balances
    expected_layers = {(row.bin_id, row.layer_id): (row.g_af, row.cents) for row in warehouse_balances}
    if yardage_days is None:
        yardage_days = sum(period.start <= row.date <= period.end for row in fixture.yardage)
    actual_layers = {(row.bin_id, row.layer_id): (row.closing_g_af, row.closing_cents)
                     for row in warehouse if row.closing_g_af or row.closing_cents}
    checks = [
        ("TRIAL_BALANCE", sum(row.closing_signed_cents for row in trial) == 0
         and sum(row.debit_cents - row.credit_cents for row in trial) == 0
         and all(row.opening_signed_cents + row.debit_cents - row.credit_cents
                 == row.closing_signed_cents for row in trial)),
        ("WAREHOUSE_CONTROL", balances[Account.WAREHOUSE] == total.inventory_cents
         and actual_layers == expected_layers),
        ("OPENING_CONTROL", sum(row.opening_cents for row in warehouse)
         == next(row.opening_signed_cents for row in trial if row.account == Account.WAREHOUSE)
         and total.opening_wip_cents == next(row.opening_signed_cents for row in trial
                                             if row.account == Account.WIP)),
        ("WIP_CONTROL", balances[Account.WIP] == total.closing_wip_cents
         and all(row.opening_cents + row.acquisition_cents + row.feed_consumption_cents
                 + row.feed_absorbed_cents + row.yardage_cents + row.veterinary_cents
                 + row.veterinary_overhead_cents
                 + row.adjustments_cents - row.sales_release_cents - row.mortality_release_cents
                 == row.closing_cents >= 0 for row in wip)),
        ("EXIT_WIP", summary.releases == Counter(dict.fromkeys(expected_exits, 1))
         and all(row.status == AnimalStatus.ACTIVE or not row.closing_cents for row in wip)),
        ("RELEASE_AND_LATE_COST", total.sales_cogs_cents == sum(row.sales_release_cents + row.late_cogs_cents
                                                               for row in wip)
         and total.mortality_burden_cents == sum(row.mortality_release_cents + row.late_mortality_cents
                                                for row in wip)),
        ("CLEARING", sum(balances[account] for account in CLEARING) == total.clearing_cents),
        ("RECEIVABLE", balances[Account.RECEIVABLE]
         == -balances[Account.REVENUE] - balances[Account.PACKER]),
        ("YARDAGE_ELIGIBILITY", yardage_days
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
