"""Hard gates for warehouse, feed settlement and biological integration."""

from collections import Counter, defaultdict
from itertools import pairwise

from ..stage1.__main__ import validation_checks as livestock_checks
from ..stage1.fixture import animal_id, local
from ..stage1.validation import Check, reject_failures
from ..stage2.timeline import checked_replay, replay_digest
from .allocation import Method
from .ration import FeedAmount, add_amounts
from .units import seconds
from .warehouse import Kind


def _check(check_id, expected, failures):
    failures = tuple(failures)
    return Check(check_id, "stage3_fixture", expected, "failed" if failures else "matched",
                 len(failures), failures[:10])


def validate(fixture, feed_bridges, *, timed=False):
    checks = list(livestock_checks(fixture.ledger))
    checks.extend(_warehouse_checks(fixture))
    checks.extend(_feed_checks(fixture, feed_bridges, timed=timed))
    checks.extend(_access_checks(fixture))
    checks.extend(_biology_checks(fixture))
    reject_failures(checks)
    return tuple(checks)


def _warehouse_checks(fixture):
    ledger_errors, balance_errors, invoice_errors, version_errors = [], [], [], []
    for snap in fixture.warehouse_snapshots:
        layers = {row.layer_id: row for row in snap.layers}
        entries = {row.entry_id: row for row in snap.entries}
        moves = set(snap.transaction_ids)
        running = defaultdict(lambda: [0, 0])
        sinks = Counter()
        for row in snap.entries:
            layer = layers.get(row.layer_id)
            balance = running[row.bin_id, row.layer_id]
            balance[0] += row.g_af
            balance[1] += row.cents
            if (row.transaction_id not in moves or layer is None
                    or (row.ingredient_id, row.batch_id) != (layer.ingredient_id, layer.batch_id)
                    or row.effective_at >= snap.effective_before or row.available_at > snap.knowledge_cutoff
                    or min(balance) < 0 or (not balance[0] and balance[1])):
                ledger_errors.append(row.entry_id)
            if row.kind == "transfer_in":
                parent = entries.get(row.transfer_from_entry_id)
                if (parent is None or parent.layer_id != row.layer_id or parent.kind != "transfer_out"
                        or parent.transaction_id != row.transaction_id or parent.g_af != -row.g_af
                        or parent.g_dm != -row.g_dm or parent.cents != -row.cents):
                    ledger_errors.append(row.entry_id)
                sinks[row.transfer_from_entry_id] += 1
        ledger_errors.extend(row.entry_id for row in snap.entries
                             if row.kind == "transfer_out" and sinks[row.entry_id] != 1)
        if (len(entries) != len(snap.entries) or len(layers) != len(snap.layers)
                or {key: tuple(value) for key, value in running.items() if value[0]}
                != {(row.bin_id, row.layer_id): (row.g_af, row.cents) for row in snap.balances}):
            ledger_errors.append(snap.snapshot_id)
        layers_by_id = {row.layer_id: row for row in snap.layers}
        expected_close = defaultdict(lambda: [0, 0])
        for row in snap.balances:
            layer = layers_by_id[row.layer_id]
            close = expected_close[layer.ingredient_id, layer.batch_id, row.bin_id]
            close[0] += row.g_af
            close[1] += row.cents
        totals = Counter()
        for row in snap.invoice_splits:
            totals[row.invoice_transaction_id] += row.delta_cents
            link = entries.get(row.historical_entry_id or row.inventory_entry_id)
            if (row.delta_cents and link is None) or (link is not None and (
                    (link.bin_id, link.layer_id) != (row.bin_id, row.layer_id)
                    or (row.historical_entry_id and link.g_af != -row.basis_g_af)
                    or (row.inventory_entry_id and link.cents != row.delta_cents))):
                invoice_errors.append(row.split_id)
        for row in fixture.warehouse.transactions:
            if row.kind == Kind.INVOICE and row.record_id in moves and totals[row.record_id] != row.amount_cents:
                invoice_errors.append(row.record_id)
        for row in fixture.stock_bridges:
            if row.snapshot_id != snap.snapshot_id:
                continue
            grams = sum((row.opening_g_af, row.receipt_g_af, row.transfer_in_g_af, row.issue_g_af,
                         row.transfer_out_g_af, row.adjustment_g_af, row.spoilage_g_af, row.return_g_af))
            cents = sum((row.opening_cents, row.receipt_cents, row.transfer_in_cents, row.issue_cents,
                         row.transfer_out_cents, row.adjustment_cents, row.spoilage_cents, row.return_cents,
                         row.invoice_cents))
            key = row.ingredient_id, row.batch_id, row.bin_id
            reference = (grams, cents)
            if row.period_end == snap.effective_before:
                reference = tuple(expected_close[key])
            if (grams, cents) != (row.closing_g_af, row.closing_cents) or (grams, cents) != reference:
                balance_errors.append(f"{row.snapshot_id}/{row.bin_id}/{row.batch_id}")
    closing, original, revised = fixture.warehouse_snapshots
    old_entries = {row.entry_id: row for row in original.entries}
    comparable = {row.entry_id: row for row in revised.entries if row.entry_id in old_entries}
    difference = (
        sum(row.g_af for row in revised.balances) - sum(row.g_af for row in original.balances),
        sum(row.cents for row in revised.balances) - sum(row.cents for row in original.balances),
    )
    if (revised.revises_snapshot_id != original.snapshot_id or comparable != old_entries
            or difference != (6_000_000, 147_000)):
        version_errors.append(revised.snapshot_id)
    hand_errors = []
    first = local("2024-01-01 00:00")
    demo = {row.bin_id: (row.closing_g_af, row.closing_cents) for row in fixture.stock_bridges
            if row.snapshot_id == closing.snapshot_id and row.period_end == first
            and row.bin_id.startswith("SYN-DEMO-") and row.closing_g_af}
    if demo != {"SYN-DEMO-1": (3000, 120), "SYN-DEMO-2": (4000, 120)}:
        hand_errors.append("SYN-HAND-T1")
    inputs = [row for row in fixture.mix_inputs if row.mix_id == "SYN-MIX-202312311500-PEN-A"]
    if [(row.batch_id, row.amount.g_af, row.amount.cents) for row in inputs] != [
            ("SYN-HAND-OLD", 6000, 180), ("SYN-HAND-NEW", 2000, 80)]:
        hand_errors.append("SYN-MIX-202312311500-PEN-A")
    return (
        _check("WAREHOUSE_LEDGER", "nonnegative closed layer balances and matched transfer legs", ledger_errors),
        _check("WAREHOUSE_BRIDGE", "all stock periods conserve signed grams AF and CAD cents", balance_errors),
        _check("INVOICE_SPLIT", "invoice delta conserved between remaining stock and historical issues/losses",
               invoice_errors),
        _check("WAREHOUSE_RESTATEMENT", "late receipt adds 6,000 kg and 147,000 cents with immutable old entries",
               version_errors),
        _check("MANUAL_FIFO", "hand-verified transfer, FIFO draws and closing balances", hand_errors),
    )


def _feed_checks(fixture, bridges, *, timed=False):
    timeline = fixture.timeline
    plans = {row.plan_id: row for row in fixture.schedule.plans}
    snapshots = {row.snapshot_id: row for row in fixture.schedule.snapshots}
    estimates = {row.estimate_id: row for row in fixture.schedule.estimates}
    observations = {row.observation_id: row for row in fixture.observations}
    mixes = {row.mix_id: row for row in fixture.mixes}
    deliveries = {row.delivery_id: row for row in fixture.deliveries}
    rows = {result.row.settlement_id: result.row for result in fixture.settlements}
    active = {result.row.delivery_id: result.row for result in fixture.active_settlements}
    approvals = {row.approval_id for row in fixture.approvals}
    frozen_by_id = {row.weight_input_id: row for snapshot in fixture.schedule.frozen_weights.values()
                    for row in snapshot.values()}
    by_mix, dispatch_by_mix = defaultdict(list), defaultdict(list)
    errors = defaultdict(list)
    issues = {row.entry_id: row for row in fixture.warehouse_snapshots[0].entries if row.kind == Kind.ISSUE}
    issue_usage = Counter()
    for row in fixture.mix_inputs:
        by_mix[row.mix_id].append(row.amount)
        issue_usage[row.layer_entry_id] += 1
        issue = issues.get(row.layer_entry_id)
        if issue is None or not (row.amount.g_af == -issue.g_af and row.amount.g_dm == -issue.g_dm
                                 and row.amount.cents == -issue.cents and row.assay_id == issue.assay_id):
            errors["mix"].append(row.mix_input_id)
    errors["mix"].extend(key for key in issues if issue_usage[key] != 1)
    for row in fixture.deliveries:
        plan = plans.get(row.plan_id)
        dispatch_by_mix[row.mix_id].append(row.loaded)
        if (row.mix_id not in mixes or plan is None or row.pen_id not in timeline.kinds
                or plan.pen_id != row.pen_id or plan.decision_at > row.effective_at
                or row.loaded != add_amounts((row.delivered, row.delivery_loss))):
            errors["delivery"].append(row.delivery_id)
    for row in fixture.mixes:
        if (row.input != add_amounts(by_mix[row.mix_id])
                or row.input != add_amounts((row.produced, row.loss))
                or row.produced != add_amounts(dispatch_by_mix[row.mix_id])):
            errors["mix"].append(row.mix_id)
    for row in fixture.schedule.estimates:
        snapshot = snapshots.get(row.snapshot_id)
        anchor = observations.get(row.last_observation_id)
        if (snapshot is None or row.effective_before != row.estimate_for
                or row.knowledge_cutoff != row.effective_before
                or (row.last_observation_id is not None and (anchor is None
                    or anchor.available_at > row.knowledge_cutoff or anchor.measured_at >= row.effective_before))):
            errors["time"].append(row.estimate_id)
    for result in fixture.settlements:
        row = result.row
        delivery = deliveries[row.delivery_id]
        plan = plans[delivery.plan_id]
        exposures = {item.exposure_id: item for item in result.exposures}
        weights = {item.weight_input_id: item for item in result.weights}
        parent = rows.get(row.revises_settlement_id)
        if (row.decision_snapshot_id != plan.decision_snapshot_id or plan.decision_snapshot_id not in snapshots
                or row.access_snapshot_id != result.access.access_snapshot_id
                or row.available_at < row.finalized_at or row.finalized_at < delivery.window_end
                or (row.revises_settlement_id is not None and (parent is None
                    or parent.delivery_id != delivery.delivery_id or parent.available_at >= row.available_at
                    or row.revision_approval_id not in approvals))):
            errors["time"].append(row.settlement_id)
        if (delivery.delivered != add_amounts((row.modeled_consumption, row.refusal, row.bunk_loss))
                or row.refusal.g_af != row.observed_refusal_g_af + row.inferred_unconsumed_g_af
                or (not exposures and row.modeled_consumption.g_af)):
            errors["bunk"].append(row.settlement_id)
        counts = Counter()
        amounts = defaultdict(lambda: [0, 0, 0, 0])
        spans = defaultdict(list)
        for allocation in result.allocations:
            key = allocation.exposure_id
            exposure = exposures.get(key)
            weight = weights.get(allocation.weight_input_id)
            counts[allocation.method, key] += 1
            spans[allocation.method, key].append((allocation.access_start, allocation.access_end))
            target = amounts[allocation.method]
            target[0] += allocation.g_dm
            target[1] += allocation.energy_kj
            target[2] += allocation.cp_g
            target[3] += allocation.cents
            if (exposure is None or weight is None or exposure.weight_input_id != weight.weight_input_id
                    or exposure.animal_id != allocation.animal_id or allocation.animal_id != weight.animal_id
                    or weight.cutoff != plan.decision_at or weight.estimate_snapshot_id != plan.decision_snapshot_id
                    or not delivery.window_start <= exposure.first_at < exposure.end_at <= delivery.window_end
                    or seconds(exposure.first_at, exposure.end_at) != exposure.duration_seconds
                    or not exposure.first_at <= allocation.access_start < allocation.access_end <= exposure.end_at
                    or seconds(allocation.access_start, allocation.access_end) != allocation.duration_seconds
                    or (weight.estimate_id is not None and (weight.estimate_id not in estimates
                        or frozen_by_id.get(weight.weight_input_id) != weight))
                    or (weight.anchor_available_at is not None and weight.anchor_available_at > plan.decision_at)):
                errors["allocation"].append(allocation.allocation_id)
        pool = row.modeled_consumption
        for method in Method:
            if amounts[method] != [pool.g_dm, pool.kj, pool.cp_g, pool.cents] or any(
                    not spans[method, key] for key in exposures):
                errors["allocation"].append(f"{row.settlement_id}/{method}")
            for key, exposure in exposures.items():
                intervals = sorted(spans[method, key])
                if (not intervals or (not timed and counts[method, key] != 1)
                        or intervals[0][0] != exposure.first_at or intervals[-1][1] != exposure.end_at
                        or any(left[1] != right[0] for left, right in pairwise(intervals))):
                    errors["allocation"].append(f"{key}/{method}")
    for row in bridges:
        if (row.issue != add_amounts((row.mixed, row.mix_loss)) or row.mixed != row.loaded
                or row.loaded != add_amounts((row.delivered, row.delivery_loss))
                or row.delivered != add_amounts((row.consumed, row.refusal, row.bunk_loss))
                or (row.consumed.g_dm, row.consumed.cents)
                != (row.selected_allocation_g_dm, row.selected_allocation_cents)):
            errors["bridge"].append(row.period)
    if (len(active) != len(fixture.active_settlements) or active.keys() != deliveries.keys()
            or len(rows) != len(fixture.settlements)
            or len(deliveries) != len(fixture.deliveries) or len(plans) != len(fixture.schedule.plans)
            or len(mixes) != len(fixture.mixes)):
        errors["bunk"].append("settlement-or-source-cardinality")
    key = "SYN-DELIVERY-202312311500-PEN-A"
    demo = next(result for result in fixture.active_settlements if result.row.delivery_id == key)
    manual_equal = {animal_id(1): (10_800, 1286, 83), animal_id(2): (7200, 857, 56),
                    animal_id(5): (7200, 857, 56)}
    if timed:
        manual_equal = {animal_id(1): (10_800, 1334, 88), animal_id(2): (7200, 834, 54),
                        animal_id(5): (7200, 832, 53)}
    by_animal = defaultdict(lambda: [0, 0, 0])
    for row in demo.allocations:
        if row.method == Method.EQUAL:
            total = by_animal[row.animal_id]
            total[0] += row.duration_seconds
            total[1] += row.g_dm
            total[2] += row.cents
    if (demo.row.modeled_consumption != FeedAmount(6000, 3000, 30_000, 360, 195)
            or demo.row.refusal != FeedAmount(2000, 1000, 10_000, 120, 65)
            or {key: tuple(value) for key, value in by_animal.items()} != manual_equal):
        errors["manual"].append(key)
    return tuple(_check(f"FEED_{key.upper()}", rule, errors[key]) for key, rule in (
        ("mix", "issues consumed exactly once and inputs equal output plus mixing loss"),
        ("delivery", "typed plan/mix/location lineage and loaded equals delivered plus loss"),
        ("time", "point-in-time decisions, anchors and explicitly approved settlement revisions"),
        ("bunk", "delivered equals consumption plus refusals and losses"),
        ("allocation", "each method conserves grams, nutrients and cents using in-window frozen inputs"),
        ("bridge", "conserved monthly feed and value flows through the active WIP basis"),
        ("manual", "hand-verified worked pen and equal-head allocations"),
    ))



def _access_checks(fixture):
    """Rebuild access independently of score inputs and compare each published snapshot."""
    deliveries = {row.delivery_id: row for row in fixture.deliveries}
    caches = {}
    errors = []
    for result in fixture.settlements:
        access = result.access
        key = access.effective_before, access.knowledge_cutoff
        if key not in caches:
            replay = checked_replay(fixture.ledger, *key)
            caches[key] = replay_digest(replay), replay.intervals
        digest, locations = caches[key]
        delivery = deliveries[result.row.delivery_id]
        expected = set()
        for location in locations:
            if location.location_id != delivery.pen_id:
                continue
            start = max(location.start_at, delivery.window_start)
            end = min(location.end_at or delivery.window_end, delivery.window_end)
            if start < end:
                leave = location.end_event_id if end == location.end_at else None
                expected.add((location.animal_id, location.lot_id, start, end, location.start_event_id, leave))
        actual = {(row.animal_id, row.lot_id, row.first_at, row.end_at, row.movement_in_id,
                   row.movement_out_id) for row in result.exposures}
        if (digest != access.replay_sha256 or actual != expected or len(actual) != len(result.exposures)
                or access.knowledge_cutoff != result.row.available_at
                or result.row.eligible_head != len({row.animal_id for row in result.exposures})):
            errors.append(result.row.settlement_id)
    return (_check("STAGE1_ACCESS_LINEAGE", "each exposure matches the Stage 1 replay at its settlement cutoff",
                   errors),)


def _biology_checks(fixture):
    method = Method(fixture.scenario["method"])
    allocation = {row.allocation_id: row for result in fixture.active_settlements
                  for row in result.allocations if row.method == method}
    allocation_totals = defaultdict(lambda: [0, 0, 0])
    segment_totals = defaultdict(lambda: [0, 0, 0])
    errors = []
    for row in fixture.growth_inputs:
        source = allocation.get(row.allocation_id)
        if (source is None or row.animal_id != source.animal_id or row.pen_id != source.pen_id
                or not source.window_start <= row.step_start < row.step_end <= source.window_end
                or row.allocation_available_at != source.available_at):
            errors.append(row.growth_input_id)
        for target in (allocation_totals[row.allocation_id],
                       segment_totals[row.animal_id, row.step_start, row.step_end]):
            target[0] += row.g_dm
            target[1] += row.energy_kj
            target[2] += row.cp_g
    for key, row in allocation.items():
        if allocation_totals[key] != [row.g_dm, row.energy_kj, row.cp_g]:
            errors.append(key)
    for animal, steps in fixture.biology.steps_by_animal.items():
        if (steps[0].start_at != fixture.timeline.entries[animal].effective_at
                or steps[-1].end_at != fixture.timeline.stop_at(animal)
                or any(left.end_at != right.start_at or left.end_weight_kg != right.start_weight_kg
                       for left, right in pairwise(steps))):
            errors.append(animal)
        for row in steps:
            if segment_totals[row.animal_id, row.start_at, row.end_at] != [
                    row.consumed_g_dm, round(row.energy_mj * 1000), round(row.protein_kg * 1000)]:
                errors.append(f"{row.animal_id}/{row.start_at.isoformat()}")
    return (_check("BIOLOGY_FEED_LEDGER", "selected allocation conserved through continuous growth steps",
                   errors),)
