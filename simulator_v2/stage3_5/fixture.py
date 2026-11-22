"""Run the 12-cattle integration window by window."""

import json
from collections import defaultdict
from dataclasses import dataclass, fields, replace
from datetime import timedelta
from pathlib import Path

from ..stage1.fixture import END, FINAL_CUTOFF, START, animal_id, fixture as livestock, local
from ..stage1.model import midnight
from ..stage1.snapshots import RevisionApproval
from ..stage1.soh import calendar_days
from ..stage2.biology import make_profile
from ..stage2.config import load_config
from ..stage2.estimation import Estimator, Model, operational_health
from ..stage2.feed import feeding_windows
from ..stage2.fixture import PROFILE_INPUTS, clinical_inputs, weather_inputs, weighing_plans
from ..stage2.health import build_health
from ..stage2.observations import Kind as ScaleKind
from ..stage2.timeline import PhysicalTimeline, checked_replay
from ..stage3.allocation import settle
from ..stage3.fixture import Fixture, Schedule, feeding_schedule, formula_inputs, warehouse_inputs
from ..stage3.fixture import load_scenario as archived_scenario
from ..stage3.ration import dispatch, mix_feed
from ..stage3.warehouse import Kind, Warehouse, bridges
from .biology import ChronologicalBiology, ChronologicalFeed
from .feeding import IssueBook, TimedAllocation, growth_clock
from .observations import ScaleBook, added_plans
from .provenance import decision_sources

TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class IntegratedFixture(Fixture):
    scale_samples: tuple
    scale_cancellations: tuple
    scale_revisions: tuple
    restated_snapshots: tuple
    restated_estimates: tuple
    decision_sources: tuple
    feed_releases: tuple
    final_estimator: Estimator


def load_scenario():
    scenario = json.loads(Path(__file__).with_name("scenario.json").read_bytes())
    base = archived_scenario()
    if base["version"] != scenario["base_scenario"]:
        raise ValueError("unexpected archived Stage 3 scenario version")
    del base["operational_scale_reference"]
    return {**base, **scenario}


def integrated_fixture(seed=42, *, scenario=None, ledger=None, clinical=None, weather=None,
                       weigh_plans=None, config=None, integration=None):
    scenario = load_scenario() if scenario is None else scenario
    ledger = livestock(seed) if ledger is None else ledger
    config = load_config() if config is None else config
    config = {**config, "biology_version": scenario["biology_version"], "sale_at_exit": True,
              "observation_version": scenario["observation_version"],
              "feed_windows_local": scenario["feeding_windows_local"]}
    if scenario["weighing"]["shrink_kg"] != 0:
        raise ValueError("the fixture has no handling-shrink evidence")
    timeline = PhysicalTimeline(ledger, FINAL_CUTOFF, FINAL_CUTOFF)
    health = build_health(timeline, clinical_inputs() if clinical is None else clinical, config)
    weather = tuple(weather_inputs() if weather is None else weather)
    profiles = tuple(
        make_profile(timeline, config, animal_id(n), breed=breed, sex=sex, frame=frame,
                     entry_weight_kg=kg, entry_age_days=age)
        for n, (breed, sex, frame, kg, age) in enumerate(PROFILE_INPUTS, 1))
    windows = tuple(window for day in calendar_days(START, END) for window in feeding_windows(day, config))
    policy = scenario["allocation_policy"]
    clock = growth_clock(windows, timeline, weather, health, config, policy["release_minutes"])
    allocation_policy = TimedAllocation(clock, policy["version"], scenario["planning"].get("clinical_intake_bps"))
    adapter = ChronologicalFeed(scenario["method"], len(config["feed_windows_local"]))
    if integration is None:
        biology = ChronologicalBiology(timeline, profiles, health, weather, config, adapter=adapter, clock=clock)
    else:
        biology = integration.biology(ledger, timeline, profiles, health, config, adapter, windows,
                                      policy, scenario["planning"].get("clinical_intake_bps"))
    if weigh_plans is None:
        standard = (replace(row, measured_at=timeline.exits[row.animal_id].effective_at)
                    if row.kind == ScaleKind.FINAL_SALE else row for row in weighing_plans(timeline))
        weigh_plans = (*standard, *added_plans(scenario))
    scale = ScaleBook(timeline, biology, weigh_plans, config, scenario["scale_corrections"])

    masters, transactions = warehouse_inputs(scenario)
    formulas = formula_inputs(masters, scenario)
    issues = IssueBook(masters, transactions)
    available_health = operational_health(health)
    fallback = scenario["planning"]["fallback_weight_g"]
    aggregate = defaultdict(list)
    frozen = {}
    mixes, mix_inputs, comparisons, deliveries, used_entries = [], [], [], [], []
    initial_settlements, active_settlements, releases, approvals, sources = [], [], [], [], []
    for start, end in windows:
        biology.advance(start)
        scale.observe_through(start)
        estimator = Estimator(ledger, scale.as_of(start), available_health, config)
        before = len(transactions)
        window = feeding_schedule(scenario, config, formulas, estimator, transactions,
                                  windows=((start, end),), issue_sequence_offset=len(aggregate["mix_issues"]))
        allocation_policy.bind_clinical(window.estimates)
        if integration is not None:
            integration.allocation.bind_clinical(window.estimates)
        for field in fields(Schedule):
            if field.name != "frozen_weights":
                aggregate[field.name].extend(getattr(window, field.name))
        frozen.update(window.frozen_weights)
        sources.extend(decision_sources(window, estimator, formulas, scenario))

        pool = issues.issue(start, transactions[before:])
        used_entries.extend(pool.entries)
        mixed, inputs, formula_deltas = mix_feed(masters, formulas, pool, window.mix_orders, window.mix_issues)
        mixes.extend(mixed)
        mix_inputs.extend(inputs)
        comparisons.extend(formula_deltas)
        plans_by_id = {row.plan_id: row for row in window.plans}
        dispatched = tuple(dispatch(masters, mixed, window.truck_tickets, plans_by_id))
        deliveries.extend(dispatched)
        if dispatched:
            observed = checked_replay(ledger, end + TICK, window.bunk_tickets[0].available_at)
            physical = checked_replay(ledger, end + TICK, FINAL_CUTOFF)
            for delivery, ticket in zip(dispatched, window.bunk_tickets, strict=True):
                plan = plans_by_id[delivery.plan_id]
                initial = settle(ledger, delivery, plan, ticket, frozen[start], fallback,
                                 replay=observed, allocation_policy=allocation_policy)
                approval = RevisionApproval(f"{delivery.delivery_id}-APPROVED", "SYN-FEED-CONTROLLER", FINAL_CUTOFF,
                                            "Stage 1 movement correction changes historical bunk access")
                active = settle(ledger, delivery, plan, ticket, frozen[start], fallback, parent=initial,
                                approval=approval, replay=physical, allocation_policy=allocation_policy)
                initial_settlements.append(initial)
                releases.extend(allocation_policy.evidence(initial, delivery, ticket))
                if active != initial:
                    initial_settlements.append(active)
                    approvals.append(approval)
                    releases.extend(allocation_policy.evidence(active, delivery, ticket))
                active_settlements.append(active)
                if integration is None:
                    adapter.add(active.allocations)
                else:
                    adapter.add(integration.observation_allocations(ledger, delivery, plan, ticket,
                                                                    frozen[start], fallback))
        biology.advance(end)
        scale.observe_through(end)

    biology.advance(FINAL_CUTOFF)
    scale.observe_through(FINAL_CUTOFF)
    observations = scale.finish()
    estimator = Estimator(ledger, observations, available_health, config)
    restated_snapshots, restated_estimates = [], []
    for revision, approval in zip(scale.revisions, scale.approvals, strict=True):
        snapshot, rows = estimator.estimates(
            revision.restated_origin_at, revision.knowledge_cutoff, revision_reason=approval.reason, models=(Model.B,))
        restated_snapshots.append(snapshot)
        restated_estimates.extend(rows)

    warehouse = Warehouse(masters, transactions)
    closing = warehouse.snapshot(FINAL_CUTOFF, FINAL_CUTOFF)
    if tuple(row for row in closing.entries if row.kind == Kind.ISSUE) != tuple(used_entries):
        raise ValueError("posted FIFO issue lineage differs from chronological issue draws")
    effective, revision_at = local("2024-01-11 00:00"), local("2024-01-11 07:30")
    original = warehouse.snapshot(effective, effective)
    wh_approval = RevisionApproval("SYN-APPROVE-LATE-RECEIPT", "SYN-STOCK-CONTROLLER",
                                   revision_at, "Late physical receipt ticket verified")
    revised = warehouse.snapshot(effective, revision_at, parent=original, approval=wh_approval)
    first = midnight(START)
    bounds = first, local("2024-01-01 00:00"), local("2024-02-01 00:00"), local("2024-03-01 00:00"), FINAL_CUTOFF
    stock = (*bridges(closing, bounds), *bridges(closing, (first, FINAL_CUTOFF)),
             *bridges(original, (first, effective)), *bridges(revised, (first, effective)))
    schedule = Schedule(frozen_weights=frozen, **{key: tuple(value) for key, value in aggregate.items()})
    return IntegratedFixture(
        scenario, ledger, timeline, config, profiles, weather, health, tuple(scale.attempts), observations.records,
        warehouse, (closing, original, revised), stock, formulas, schedule, tuple(mixes), tuple(mix_inputs),
        tuple(comparisons), tuple(deliveries), tuple(initial_settlements), tuple(active_settlements),
        (wh_approval, *approvals, *scale.approvals), biology, adapter.growth_inputs(biology),
        tuple(scale.samples), tuple(scale.cancellations), tuple(scale.revisions),
        tuple(restated_snapshots), tuple(restated_estimates), tuple(sources), tuple(releases), estimator,
    )
