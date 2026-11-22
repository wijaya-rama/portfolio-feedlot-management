"""Extend the accepted 12-animal fixture with auditable feed operations."""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..stage1.fixture import A, B, H, R, FINAL_CUTOFF, START, END, animal_id, fixture as livestock, local
from ..stage1.model import midnight
from ..stage1.snapshots import RevisionApproval
from ..stage1.soh import calendar_days
from ..stage2.biology import make_profile
from ..stage2.config import load_config
from ..stage2.estimation import Estimator, operational_health
from ..stage2.feed import feeding_windows
from ..stage2.fixture import PROFILE_INPUTS, clinical_inputs, weather_inputs, weighing_plans
from ..stage2.health import build_health
from ..stage2.observations import Observations, correct, simulate_observations
from ..stage2.timeline import PhysicalTimeline, checked_replay
from .allocation import BunkTicket, Method, feed_plan, freeze, settle
from .biology import LedgerBiology, LedgerFeed
from .ration import Component, Formulas, MixIssue, MixOrder, Recipe, TruckTicket, dispatch, mix_feed
from .units import BPS, half_up
from .warehouse import (Assay, Batch, Bin, Equipment, Ingredient, Kind, Masters, Price,
                        PurchaseOrder, Supplier, Transaction, Warehouse, WarehouseLocation, bridges)

PENS = (A, B, R, H)
DAY = timedelta(days=1)
SOURCE = "SYN-FEED-SUPPLIER"
YARD_RATION = "SYN-YARD-RATION"
BIOLOGY_VERSION = "biology.1+feed-ledger.1"


def load_scenario():
    return json.loads(Path(__file__).with_name("scenario.json").read_bytes())


def same_day_meta(key, when):
    return key, f"{key}-DOC", when, when, when


def warehouse_inputs(scenario):
    settings = scenario["warehouse"]
    base = local(scenario["effective_from_local"])
    ingredients = [Ingredient(*same_day_meta(f"{key}-V1", base), key, name, dm, kj, cp)
                   for key, name, dm, kj, cp in settings["ingredients"]]
    supplier = Supplier(*same_day_meta(f"{SOURCE}-V1", base), SOURCE, "Synthetic Feed Supply")
    bins = [Bin(*same_day_meta(f"{key}-V1", base), key, warehouse, capacity)
            for key, warehouse, capacity in settings["bins"]]
    by_batch = {}
    assays = []
    for key, ingredient, supplier_lot, dm in settings["batches"]:
        effective = base
        available = base
        if key == "SYN-SILAGE-NEW":
            receipt = next(row for row in settings["receipts"] if row[5] == key)
            effective, available = local(receipt[1]), local(receipt[3])
        batch = Batch(f"{key}-V1", f"{key}-DOC", effective, available, available,
                      key, ingredient, SOURCE, supplier_lot)
        by_batch[key] = batch
        assays.append(Assay(f"{key}-DM-1", f"{key}-LAB-1", effective, available, available, key, dm))
    key, effective, posted, available, dm = settings["late_assay"]
    assays.append(Assay(f"{key}-DM-2", f"{key}-LAB-2", local(effective), local(posted),
                        local(available), key, dm))
    orders, prices = [], []
    for key, ingredient, price, unit, grams in settings["purchase_orders"]:
        price_row = Price(*same_day_meta(f"{key}-PRICE-V1", base), ingredient, SOURCE, price, unit)
        prices.append(price_row)
        orders.append(PurchaseOrder(*same_day_meta(f"{key}-V1", base), key, SOURCE,
                                    ingredient, price_row.record_id, grams))
    equipment = [Equipment(*same_day_meta(f"{key}-V1", base), key, kind, capacity)
                 for key, kind, capacity in settings["equipment"]]
    warehouses = [WarehouseLocation(*same_day_meta(f"{key}-V1", base), key, "Synthetic feed warehouse")
                  for key in sorted({row.warehouse_id for row in bins})]
    masters = Masters(ingredients=ingredients, suppliers=[supplier], warehouses=warehouses, bins=bins,
                      batches=by_batch.values(), assays=assays, prices=prices,
                      orders=orders, equipment=equipment)
    transactions = []
    for batch, bin_id, grams, cents in settings["opening"]:
        transactions.append(Transaction(*same_day_meta(f"{batch}-OPEN", base), Kind.OPENING,
                                        len(transactions), bin_id, by_batch[batch].ingredient_id,
                                        grams, batch, amount_cents=cents))
    for key, effective, posted, available, bin_id, batch, po, grams, freight in settings["receipts"]:
        transactions.append(Transaction(
            key, f"{key}-TICKET", local(effective), local(posted), local(available),
            Kind.RECEIPT, len(transactions), bin_id, by_batch[batch].ingredient_id,
            grams, batch, po_line_id=po, freight_cents=freight))
    for key, when, source, target, ingredient, grams in settings["transfers"]:
        transactions.append(Transaction(*same_day_meta(key, local(when)), Kind.TRANSFER,
                                        len(transactions), source, ingredient, grams, target_bin_id=target))
    for key, when, bin_id, batch, counted in settings["counts"]:
        transactions.append(Transaction(*same_day_meta(key, local(when)), Kind.COUNT,
                                        len(transactions), bin_id, by_batch[batch].ingredient_id, counted, batch))
    for key, when, bin_id, batch, grams, cents, reference, reason in settings["adjustments"]:
        transactions.append(Transaction(*same_day_meta(key, local(when)), Kind.ADJUST,
                                        len(transactions), bin_id, by_batch[batch].ingredient_id,
                                        grams, batch, amount_cents=cents, reference_id=reference, reason=reason))
    for key, when, bin_id, batch, grams, reason in settings["spoilage"]:
        transactions.append(Transaction(*same_day_meta(key, local(when)), Kind.SPOILAGE,
                                        len(transactions), bin_id, by_batch[batch].ingredient_id,
                                        grams, batch, reason=reason))
    for key, when, bin_id, batch, reference, invoice_date, cents in settings["invoices"]:
        transactions.append(Transaction(*same_day_meta(key, local(when)), Kind.INVOICE,
                                        len(transactions), bin_id, by_batch[batch].ingredient_id,
                                        batch_id=batch, amount_cents=cents,
                                        reference_id=reference, invoice_date=date.fromisoformat(invoice_date)))
    return masters, transactions


def formula_inputs(masters, scenario):
    recipes, components = [], []
    for recipe in scenario["recipes"]:
        key = f"{recipe['id']}-V{recipe['version']}"
        recipes.append(Recipe(*same_day_meta(key, local(recipe["starts_local"])), recipe["id"],
                              "adaptation,finishing,receiving,hospital",
                              recipe["target_kj_per_kg_dm"], recipe["target_cp_bps_dm"]))
        components.extend(Component(f"{key}-L{n}", key, *values)
                          for n, values in enumerate(recipe["components"], 1))
    return Formulas(masters, recipes, components)


@dataclass(frozen=True)
class ScaleReference:
    timeline: PhysicalTimeline
    profiles: tuple
    gain_g_per_day: int

    def weight_at(self, animal_id, instant):
        profile = next(row for row in self.profiles if row.animal_id == animal_id)
        elapsed = (instant - self.timeline.entries[animal_id].effective_at) / DAY
        return profile.entry_weight_kg + self.gain_g_per_day * elapsed / 1000


def field_inputs(seed, scenario, ledger=None, weather=None, clinical=None, observation_transform=None):
    if ledger is None:
        ledger = livestock(seed)
    config = load_config()
    config["biology_version"] = BIOLOGY_VERSION
    config["feed_windows_local"] = scenario["feeding_windows_local"]
    config["observation_version"] = scenario["operational_scale_reference"]["version"]
    timeline = PhysicalTimeline(ledger, FINAL_CUTOFF, FINAL_CUTOFF)
    profiles = tuple(
        make_profile(timeline, config, animal_id(index), breed=breed, sex=sex, frame=frame,
                     entry_weight_kg=kg, entry_age_days=age)
        for index, (breed, sex, frame, kg, age) in enumerate(PROFILE_INPUTS, 1))
    health = build_health(timeline, clinical_inputs() if clinical is None else clinical, config)
    scale = ScaleReference(timeline, profiles, scenario["operational_scale_reference"]["gain_g_per_day"])
    attempts, records = simulate_observations(timeline, scale, weighing_plans(timeline), config)
    parent = next(row for row in records if row.source_event_id == "SYN-SCALE-05-2024-01-14-follow_up")
    correction = correct(parent, source_id="SYN-SCALE-CORR-05-JAN14",
                         posted_at=local("2024-01-19 08:00"), available_at=local("2024-01-19 10:00"),
                         measured_weight_kg=round(parent.measured_weight_kg - 1.6, 1))
    records = (*records, correction)
    if observation_transform is not None:
        records = tuple(observation_transform(row) for row in records)
    observations = Observations(timeline, records, config)
    estimator = Estimator(ledger, observations, operational_health(health), config)
    return timeline, config, profiles, health, tuple(weather_inputs() if weather is None else weather), (
        attempts, records, estimator)


@dataclass(frozen=True)
class Schedule:
    plans: tuple
    snapshots: tuple
    estimates: tuple
    frozen_weights: dict
    mix_orders: tuple
    mix_issues: tuple
    truck_tickets: tuple
    bunk_tickets: tuple


def feeding_schedule(scenario, stage2_config, formulas, estimator, transactions, *, windows=None,
                     issue_sequence_offset=0):
    policy = scenario["planning"]
    scripts = {(local(when), pen): (recipe, dm, mix_loss, truck_loss, refusal, bunk_loss)
               for when, pen, recipe, dm, mix_loss, truck_loss, refusal, bunk_loss
               in scenario["scripted_dispatch"]}
    substitution_time, substitution_pen, substitution_bps = scenario["substitution"]
    substitution_time = local(substitution_time)
    bins = {"SYN-HAND-SILAGE": "SYN-DEMO-1", "SYN-SILAGE": "SYN-SILAGE-BIN",
            "SYN-BARLEY": "SYN-GRAIN-BIN", "SYN-OATS": "SYN-GRAIN-BIN"}
    plans, snapshots, estimates, frozen, orders, issues, trucks, bunks = [], [], [], {}, [], [], [], []
    if windows is None:
        windows = (window for day in calendar_days(START, END)
                   for window in feeding_windows(day, stage2_config))
    for start, end in windows:
        snapshot, rows, frozen[start] = freeze(estimator, start, policy["fallback_weight_g"])
        clinical_statuses = {row.animal_id: row.clinical_status for row in rows}
        snapshots.append(snapshot)
        estimates.extend(rows)
        for pen in PENS:
            recipe, dm, mix_loss, truck_loss, refused, bunk_loss = scripts.get(
                (start, pen), (YARD_RATION, None, None, None, None, 0))
            plan = feed_plan(pen, start, end, snapshot, frozen[start], formulas, recipe, policy,
                             override_g_dm=dm, clinical_statuses=clinical_statuses)
            plans.append(plan)
            if not plan.planned_g_dm:
                continue
            recipe_id = plan.ration_version_id
            mix_id = f"SYN-MIX-{start:%Y%m%d%H%M}-{pen.removeprefix('SYN-')}"
            delivery_id = mix_id.replace("SYN-MIX-", "SYN-DELIVERY-", 1)
            targets = formulas.targets(recipe_id, plan.planned_g_dm)
            gross = 0
            for line in formulas.lines[recipe_id]:
                _, af = targets[line.component_id]
                substitute = 0
                if (start, pen) == (substitution_time, substitution_pen) and line.substitute_ingredient_id:
                    substitute = af * substitution_bps // BPS
                for ingredient, grams, reason in (
                        (line.ingredient_id, af - substitute, None),
                        (line.substitute_ingredient_id, substitute, "scripted barley short load")):
                    if not grams:
                        continue
                    key = f"{mix_id}-ISSUE-{issue_sequence_offset + len(issues) + 1}"
                    transactions.append(Transaction(*same_day_meta(key, start), Kind.ISSUE,
                                                    len(transactions), bins[ingredient], ingredient, grams))
                    issues.append(MixIssue(key, mix_id, line.component_id, reason))
                    gross += grams
            if mix_loss is None:
                mix_loss = half_up(gross * policy["mix_loss_bps"], BPS)
            orders.append(MixOrder(*same_day_meta(mix_id, start), recipe_id, "SYN-MIXER-V1",
                                   plan.planned_g_dm, mix_loss))
            loaded = gross - mix_loss
            if truck_loss is None:
                truck_loss = half_up(loaded * policy["truck_loss_bps"], BPS)
            trucks.append(TruckTicket(*same_day_meta(delivery_id, start), mix_id, plan.plan_id,
                                      "SYN-TRUCK-V1", loaded, truck_loss))
            if refused is None:
                refused = half_up((loaded - truck_loss) * policy["bunk_refusal_bps"], BPS)
            key = f"{delivery_id}-BUNK"
            bunks.append(BunkTicket(key, f"{key}-DOC", end, end + timedelta(minutes=15),
                                    end + timedelta(minutes=30), delivery_id, refused, bunk_loss))
    return Schedule(tuple(plans), tuple(snapshots), tuple(estimates), frozen, tuple(orders),
                    tuple(issues), tuple(trucks), tuple(bunks))


@dataclass(frozen=True)
class Fixture:
    scenario: dict
    ledger: object
    timeline: PhysicalTimeline
    biology_config: dict
    profiles: tuple
    weather: tuple
    health: tuple
    attempts: tuple
    observations: tuple
    warehouse: Warehouse
    warehouse_snapshots: tuple
    stock_bridges: tuple
    formulas: Formulas
    schedule: Schedule
    mixes: tuple
    mix_inputs: tuple
    comparisons: tuple
    deliveries: tuple
    settlements: tuple
    active_settlements: tuple
    approvals: tuple
    biology: LedgerBiology
    growth_inputs: tuple


def stage3_fixture(seed=42, *, ledger=None, weather=None, clinical=None, observation_transform=None,
                   scenario=None):
    if scenario is None:
        scenario = load_scenario()
    timeline, config, profiles, health, weather, (attempts, records, estimator) = field_inputs(
        seed, scenario, ledger, weather, clinical, observation_transform)
    ledger = estimator.ledger
    masters, transactions = warehouse_inputs(scenario)
    formulas = formula_inputs(masters, scenario)
    schedule = feeding_schedule(scenario, config, formulas, estimator, transactions)
    warehouse = Warehouse(masters, transactions)
    closing = warehouse.snapshot(FINAL_CUTOFF, FINAL_CUTOFF)
    effective = local("2024-01-11 00:00")
    original = warehouse.snapshot(effective, effective)
    revision_cutoff = local("2024-01-11 07:30")
    wh_approval = RevisionApproval("SYN-APPROVE-LATE-RECEIPT", "SYN-STOCK-CONTROLLER",
                                   revision_cutoff, "Late physical receipt ticket verified")
    revised = warehouse.snapshot(effective, revision_cutoff, parent=original, approval=wh_approval)
    bridge_boundaries = (midnight(START), local("2024-01-01 00:00"), local("2024-02-01 00:00"),
                         local("2024-03-01 00:00"), FINAL_CUTOFF)
    stock = (*bridges(closing, bridge_boundaries), *bridges(closing, (midnight(START), FINAL_CUTOFF)),
             *bridges(original, (midnight(START), effective)), *bridges(revised, (midnight(START), effective)))
    mixes, mix_inputs, comparisons = mix_feed(masters, formulas, closing, schedule.mix_orders,
                                               schedule.mix_issues)
    plans = {row.plan_id: row for row in schedule.plans}
    deliveries = tuple(dispatch(masters, mixes, schedule.truck_tickets, plans))
    tickets = {row.delivery_id: row for row in schedule.bunk_tickets}
    settlements, active, approvals = [], [], [wh_approval]
    replays = {}
    fallback = scenario["planning"]["fallback_weight_g"]
    for row in deliveries:
        plan, ticket = plans[row.plan_id], tickets[row.delivery_id]
        frozen = schedule.frozen_weights[row.window_start]
        effective = row.window_end + timedelta(microseconds=1)
        for cutoff in (ticket.available_at, FINAL_CUTOFF):
            key = (effective, cutoff)
            if key not in replays:
                replays[key] = checked_replay(ledger, *key)
        initial = settle(ledger, row, plan, ticket, frozen, fallback,
                         replay=replays[effective, ticket.available_at])
        approval = RevisionApproval(f"{row.delivery_id}-APPROVED", "SYN-FEED-CONTROLLER", FINAL_CUTOFF,
                                    "Stage 1 movement correction changes historical bunk access")
        current = settle(ledger, row, plan, ticket, frozen, fallback, parent=initial, approval=approval,
                         replay=replays[effective, FINAL_CUTOFF])
        settlements.append(initial)
        if current != initial:
            settlements.append(current)
            approvals.append(approval)
        active.append(current)
    allocations = tuple(row for result in active for row in result.allocations)
    adapter = LedgerFeed(allocations, Method(scenario["method"]), len(config["feed_windows_local"]))
    biology = LedgerBiology(timeline, profiles, health, weather, config, adapter=adapter)
    return Fixture(scenario, ledger, timeline, config, profiles, weather, health, attempts, records,
                   warehouse, (closing, original, revised), stock, formulas, schedule, mixes, mix_inputs,
                   comparisons, deliveries, tuple(settlements), tuple(active), tuple(approvals), biology,
                   adapter.growth_inputs(biology))
