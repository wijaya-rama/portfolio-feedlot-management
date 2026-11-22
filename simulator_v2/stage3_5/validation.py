"""Integration gates that must pass before a corrected run can be published."""

from collections import Counter, defaultdict
from itertools import pairwise

from ..stage1.fixture import local
from ..stage1.model import EventKind, business_date
from ..stage1.validation import Check, reject_failures
from ..stage2.estimation import Model
from ..stage2.observations import Kind
from ..stage3.allocation import Method, feed_plan, freeze
from ..stage3.ration import FeedAmount, add_amounts, partition
from ..stage3.units import seconds
from ..stage3.validation import validate as validate_stage3
from .provenance import decision_sources


def _check(key, rule, failures):
    failures = tuple(failures)
    return Check(key, "stage3_5", rule, "matched" if not failures else "failed",
                 len(failures), failures[:10])


def validate(fixture, candidates, feed_bridges, dm, backtest):
    checks = (*validate_stage3(fixture, feed_bridges, timed=True), _scale(fixture), _revisions(fixture),
              _decisions(fixture), _releases(fixture), _dry_matter(fixture, dm, feed_bridges),
              _wip(fixture, candidates), _backtest(fixture, *backtest))
    reject_failures(checks)
    return checks


def _scale(fixture):
    records = {row.observation_id: row for row in fixture.observations}
    samples = {row.observation_id: row for row in fixture.scale_samples}
    originals = {row.observation_id for row in fixture.observations if not row.corrects_observation_id}
    failures = list(samples.keys() ^ originals)
    if len(samples) != len(fixture.scale_samples):
        failures.append("duplicate-sample")
    measured = {row.observation_id for row in fixture.attempts if row.status == "measured"}
    failures.extend(originals ^ measured)
    for key, sample in samples.items():
        observed = records.get(key)
        if observed is None:
            continue
        latent = fixture.biology.weight_at(observed.animal_id, observed.measured_at)
        model = fixture.biology_config["weighing"]
        scale = model["scales"][observed.scale_id]
        rounded = round(round(
            (latent + (sample.scale_bias_kg + sample.measurement_error_kg) - sample.shrink_kg)
            / sample.precision_kg) * sample.precision_kg, 6)
        exit_event = fixture.timeline.exits.get(observed.animal_id)
        pre_sale = (observed.kind == Kind.FINAL_SALE and exit_event and exit_event.kind == EventKind.SALE
                    and exit_event.effective_at == observed.measured_at)
        if (sample.animal_id != observed.animal_id or sample.effective_at != observed.measured_at
                or sample.observed_at != observed.measured_at or sample.latent_kg != latent
                or sample.business_date != business_date(observed.measured_at)
                or sample.precision_kg != model["precision_kg"]
                or (sample.scale_bias_kg, sample.shrink_kg) != (scale["bias_kg"], 0.0)
                or abs(sample.measurement_error_kg) > scale["error_half_width_kg"]
                or rounded != observed.measured_weight_kg
                or (not pre_sale and fixture.timeline.location_at(observed.animal_id, observed.measured_at) is None)):
            failures.append(key)
    return _check("LATENT_SCALE", "each measured ticket samples the active animal at the exact observed timestamp",
                  failures)


def _revisions(fixture):
    snapshots = {row.knowledge_cutoff: row for row in fixture.schedule.snapshots}
    estimates = {(row.snapshot_id, row.animal_id): row for row in fixture.restated_estimates}
    approvals = {row.approval_id: row for row in fixture.approvals}
    records = {row.observation_id: row for row in fixture.observations}
    failures = []
    if (len(fixture.scale_revisions) != len(fixture.restated_snapshots)
            or len(approvals) != len(fixture.approvals)):
        failures.append("revision-cardinality")
    for revision, child in zip(fixture.scale_revisions, fixture.restated_snapshots):
        parent = snapshots.get(revision.restated_origin_at)
        corrected = records[revision.observation_id]
        revised_estimate = estimates.get((child.snapshot_id, corrected.animal_id))
        approval = approvals.get(revision.approval_id)
        if (parent is None or parent.snapshot_id != child.revises_snapshot_id
                or parent.snapshot_id == child.snapshot_id
                or child.effective_before != revision.restated_origin_at
                or child.knowledge_cutoff != corrected.available_at
                or corrected.corrects_observation_id != revision.parent_observation_id
                or approval is None or approval.approved_at != child.knowledge_cutoff
                or revised_estimate is None):
            failures.append(revision.observation_id)
    return _check("AUTHORIZED_SCALE_REVISION", "restatement keeps the original decision vintage and approval chain",
                  failures)


def _decisions(fixture):
    failures = []
    replayed = tuple(decision_sources(fixture.schedule, fixture.final_estimator, fixture.formulas, fixture.scenario))
    if replayed != fixture.decision_sources:
        failures.append("published-source-replay")
    snapshots = {row.snapshot_id: row for row in fixture.schedule.snapshots}
    estimates = defaultdict(list)
    for row in fixture.schedule.estimates:
        estimates[row.snapshot_id].append(row)
    planning = fixture.scenario["planning"]
    fallback = planning["fallback_weight_g"]
    weights_at = fixture.schedule.frozen_weights
    overrides = {(local(when), pen): dm for when, pen, _, dm, *_ in fixture.scenario["scripted_dispatch"]}
    for row in snapshots.values():
        reproduced, rows, weights = freeze(fixture.final_estimator, row.knowledge_cutoff, fallback)
        if (reproduced != row or tuple(estimates[row.snapshot_id]) != rows
                or weights_at[row.knowledge_cutoff] != weights):
            failures.append(row.snapshot_id)
    for plan in fixture.schedule.plans:
        ration = fixture.formulas.versions[plan.ration_version_id]
        reproduced = feed_plan(plan.pen_id, plan.window_start, plan.window_end,
                               snapshots[plan.decision_snapshot_id], weights_at[plan.decision_at],
                               fixture.formulas, ration.ration_id, planning,
                               override_g_dm=overrides.get((plan.decision_at, plan.pen_id)))
        if plan != reproduced:
            failures.append(plan.plan_id)
    for row in fixture.decision_sources:
        snapshot = snapshots[row.snapshot_id]
        if (row.available_at > snapshot.knowledge_cutoff or row.effective_at > snapshot.effective_before
                or (row.source_type in {"scale_ticket", "clinical_fact", "roster_movement", "entry"}
                    and row.effective_at == snapshot.effective_before)):
            failures.append(row.source_id)
    return _check("DECISION_SOURCE_AVAILABILITY", "plans replay from contemporaneous documented inputs", failures)


def _releases(fixture):
    deliveries = {row.delivery_id: row for row in fixture.deliveries}
    grouped = defaultdict(list)
    failures = []
    for row in fixture.feed_releases:
        grouped[row.settlement_id].append(row)
    for result in fixture.settlements:
        settlement = result.row
        delivery = deliveries[settlement.delivery_id]
        rows = grouped[settlement.settlement_id]
        cursor = delivery.window_start
        totals = defaultdict(list)
        allocations = defaultdict(list)
        observed = partition(delivery.delivered, {
            "refusal": settlement.observed_refusal_g_af,
            "bunk_loss": settlement.bunk_loss.g_af,
            "scheduled": delivery.delivered.g_af - settlement.observed_refusal_g_af - settlement.bunk_loss.g_af,
        })
        scheduled = observed["scheduled"]
        duration = seconds(delivery.window_start, delivery.window_end)
        released_af = 0
        for row in result.allocations:
            allocations[row.access_start, row.access_end, row.method].append(row)
        for row in rows:
            ids = {exposure.exposure_id for exposure in result.exposures
                   if exposure.first_at <= row.start_at < row.end_at <= exposure.end_at}
            pool = FeedAmount(row.g_af, row.g_dm, row.energy_kj, row.cp_g, row.cents)
            totals[bool(ids)].append(pool)
            released_af += row.g_af
            if (cursor != row.start_at or len(ids) != row.eligible_head
                    or released_af != scheduled.g_af * seconds(delivery.window_start, row.end_at) // duration):
                failures.append(row.release_id)
            cursor = row.end_at
            for method in Method:
                slices = allocations.pop((row.start_at, row.end_at, method), [])
                expected = (pool.g_dm, pool.kj, pool.cp_g, pool.cents) if ids else (0, 0, 0, 0)
                actual = tuple(sum(getattr(item, field) for item in slices)
                               for field in ("g_dm", "energy_kj", "cp_g", "cents"))
                if actual != expected or {item.exposure_id for item in slices} != ids:
                    failures.append(row.release_id)
        if (cursor != delivery.window_end or allocations
                or add_amounts(totals[True]) != settlement.modeled_consumption
                or add_amounts((*totals[True], *totals[False])) != scheduled
                or add_amounts((*totals[False], observed["refusal"])) != settlement.refusal):
            failures.append(settlement.settlement_id)
    return _check("CAUSAL_FEED_RELEASE", "each release reconciles its entrants, feed, nutrients and provisional cents",
                  failures)


def _dry_matter(fixture, dm, feed_bridges):
    failures = []
    by_scope = defaultdict(int)
    by_layer = defaultdict(list)
    for row in dm:
        if row.closing_g_dm != sum((row.opening_g_dm, row.receipts_g_dm, row.transfers_g_dm, row.issues_g_dm,
                                   row.adjustments_g_dm, row.spoilage_g_dm, row.returns_g_dm,
                                   row.assay_revaluation_g_dm, row.rounding_g_dm)):
            failures.append(row.layer_id)
        by_scope[row.snapshot_id, row.period_start, row.period_end] += row.issues_g_dm
        by_layer[row.snapshot_id, row.bin_id, row.layer_id].append(row)
    closing = fixture.warehouse_snapshots[0]
    horizon = next(row for row in feed_bridges if row.period == "horizon")
    full = [row for row in dm if row.snapshot_id == closing.snapshot_id]
    start = min(row.period_start for row in full)
    for rows in by_layer.values():
        own = [row for row in rows if (row.period_start, row.period_end) != (start, closing.effective_before)]
        for left, right in pairwise(own):
            if left.period_end == right.period_start and left.closing_g_dm != right.opening_g_dm:
                failures.append(left.layer_id)
    if by_scope[closing.snapshot_id, start, closing.effective_before] != -horizon.issue.g_dm:
        failures.append("warehouse-to-mix")
    return _check("WAREHOUSE_DRY_MATTER", "stock DM bridges match issue DM after explicit assay and gram rounding",
                  failures)


def _wip(fixture, candidates):
    ids = Counter(row.allocation_id for row in candidates)
    method = Method(fixture.scenario["method"])
    selected = {row.allocation_id: row for result in fixture.active_settlements for row in result.allocations
                if row.method == method and (row.g_dm or row.cents)}
    failures = list(ids.keys() ^ selected.keys())
    for row in candidates:
        source = selected.get(row.allocation_id)
        if (source is None or ids[row.allocation_id] != 1
                or (row.g_dm, row.provisional_cents, row.available_at, row.access_end)
                != (source.g_dm, source.cents, source.available_at, source.access_end)
                or row.access_end > fixture.timeline.stop_at(row.animal_id)):
            failures.append(row.allocation_id)
    return _check("UNIQUE_WIP_BASIS", "one active-method provisional cost row per qualifying allocation", failures)


def _backtest(fixture, pairs, snapshots, forecasts):
    by_id = {row.estimate_id: row for row in forecasts}
    snapshots = {row.snapshot_id: row for row in snapshots}
    observations = fixture.final_estimator.observations.by_id
    failures = []
    for pair in pairs:
        if pair.eligibility != "eligible":
            continue
        snapshot = snapshots[pair.snapshot_id]
        for model, key in ((Model.A, pair.model_a_estimate_id), (Model.B, pair.model_b_estimate_id)):
            row = by_id[key]
            anchor = observations[row.last_observation_id]
            if (anchor.kind == Kind.FINAL_SALE or anchor.available_at > pair.origin_at
                    or anchor.measured_at >= pair.origin_at or row.estimate_for != pair.target_at
                    or row.model != model or snapshot.effective_before != snapshot.knowledge_cutoff
                    or snapshot.knowledge_cutoff != pair.origin_at
                    or anchor.observation_id == pair.target_observation_id):
                failures.append(key)
    return _check("BACKTEST_ORIGIN", "observed targets and each fixed-origin forecast use separate time cutoffs",
                  failures)
