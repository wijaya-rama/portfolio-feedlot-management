"""Hard gates for publishing the synthetic overlay and its lineage."""

from collections import Counter
from datetime import timedelta
from math import isclose, isfinite

from ..stage1.__main__ import validation_checks as stage1_checks
from ..stage1.model import AnimalStatus, business_date
from ..stage1.validation import Check, reject_failures
from .observations import Kind


def _check(check_id, expected, failures):
    return Check(check_id, "stage2_fixture", expected, "matched" if not failures else "failed",
                 len(failures), tuple(failures[:10]))


def validate_fixture(fixture, snapshots, estimates, pairs, drafts):
    timeline = fixture.timeline
    profiles = fixture.biology.profiles
    steps = fixture.biology.steps_by_animal
    health = {row.health_event_id: row for row in fixture.health}
    observations = fixture.observations.by_id
    cuts = {row.snapshot_id: row for row in snapshots}
    estimate_by_id = {row.estimate_id: row for row in estimates}
    checks = list(stage1_checks(fixture.ledger))

    sequence_errors = []
    weight_errors = []
    feed_errors = []
    health_errors = []
    per_window_cap = 1 / len(fixture.config["feed_windows_local"])
    for animal_id, rows in steps.items():
        profile = profiles[animal_id]
        last_at = timeline.entries[animal_id].effective_at
        last_weight = profile.entry_weight_kg
        access = Counter()
        for row in rows:
            label = f"{animal_id}/{row.start_at.isoformat()}"
            interval = timeline.location_at(animal_id, row.start_at)
            if (row.start_at != last_at or row.start_at >= row.end_at
                    or row.lot_id != profile.lot_id or interval is None
                    or row.location_event_id != interval.start_event_id
                    or row.location_id != interval.location_id
                    or row.end_at > (interval.end_at or timeline.result.effective_before)):
                sequence_errors.append(label)
            if row.start_weight_kg != last_weight or not all(
                isfinite(kg) and fixture.biology.bounds[0] <= kg <= fixture.biology.bounds[1]
                for kg in (row.start_weight_kg, row.weight_before_feed_kg, row.end_weight_kg)
            ):
                weight_errors.append(label)
            last_at, last_weight = row.end_at, row.end_weight_kg
            if row.window_start_at is not None:
                access[row.window_start_at, row.window_end_at] += row.access_fraction
                if (not row.window_start_at <= row.start_at < row.end_at <= row.window_end_at
                        or not 0 <= row.consumed_g_dm <= row.demand_g_dm):
                    feed_errors.append(label)
            elif any((row.window_end_at, row.access_fraction, row.demand_g_dm, row.consumed_g_dm)):
                feed_errors.append(label)
            if row.health_event_id:
                cause = health.get(row.health_event_id)
                if (cause is None or cause.animal_id != animal_id
                        or cause.effective_at > row.start_at or cause.burden != row.health_burden):
                    health_errors.append(label)
        if last_at != timeline.stop_at(animal_id):
            sequence_errors.append(animal_id)
        if any(share > per_window_cap and not isclose(share, per_window_cap)
               for share in access.values()):
            feed_errors.append(animal_id)
    checks.extend((
        _check("LATENT_TIMELINE", "contiguous same-animal and lot intervals until exit", sequence_errors),
        _check("LATENT_WEIGHT", "finite weights within configured bounds and continuous state", weight_errors),
        _check("FEED_ACCESS", "valid occupied windows and capped DM", feed_errors),
        _check("CLINICAL_LINEAGE", "matching prior health facts", health_errors),
    ))

    attempt_errors = [
        row.source_event_id for row in fixture.attempts
        if (row.status == "measured" and row.observation_id not in observations)
        or (row.status == "missing" and row.observation_id is not None)
    ]
    checks.append(_check("SCALE_MISSING", "missing attempts carry no scale record", attempt_errors))
    estimate_errors = []
    for row in estimates:
        snap = cuts.get(row.snapshot_id)
        if (snap is None or (snap.effective_before, snap.knowledge_cutoff)
                != (row.effective_before, row.knowledge_cutoff)
                or row.estimate_for < row.effective_before):
            estimate_errors.append(row.estimate_id)
            continue
        if row.last_observation_id is not None:
            anchor = observations.get(row.last_observation_id)
            if (anchor is None or anchor.animal_id != row.animal_id or anchor.kind == Kind.FINAL_SALE
                    or anchor.measured_at != row.last_measured_at
                    or not anchor.measured_at < row.effective_before
                    or not anchor.available_at == row.last_available_at <= row.knowledge_cutoff
                    or row.estimated_liveweight_kg is None or row.estimated_liveweight_kg <= 0):
                estimate_errors.append(row.estimate_id)
        elif row.estimated_liveweight_kg is not None:
            estimate_errors.append(row.estimate_id)
        if row.health_event_id is not None:
            event = health.get(row.health_event_id)
            if (event is None or event.animal_id != row.animal_id or not event.operational_visible
                    or event.effective_at >= row.effective_before
                    or event.available_at > row.knowledge_cutoff):
                estimate_errors.append(row.estimate_id)
    checks.append(_check("AS_OF_FEATURES", "scale and clinical features are visible at origin", estimate_errors))

    lineage_errors = []
    for row in pairs:
        target = observations.get(row.target_observation_id)
        if (target is None or target.animal_id != row.animal_id
                or target.measured_at != row.target_at or target.measured_weight_kg != row.target_weight_kg
                or row.target_at - row.origin_at != timedelta(days=row.horizon_days)):
            lineage_errors.append(row.target_observation_id)
        for key in (row.model_a_estimate_id, row.model_b_estimate_id):
            if key is not None:
                estimate = estimate_by_id.get(key)
                if (estimate is None or estimate.snapshot_id != row.snapshot_id
                        or estimate.estimate_for != row.target_at
                        or estimate.knowledge_cutoff != row.origin_at):
                    lineage_errors.append(key)
    for draft in drafts:
        estimate = estimate_by_id.get(draft.estimate_id)
        if estimate is None or draft.snapshot_id != estimate.snapshot_id:
            lineage_errors.append(draft.draft_id)
    checks.append(_check("DECISION_AND_EVALUATION_LINEAGE", "references to frozen predictions", lineage_errors))

    identity_errors = []
    for prefix, items in (
        ("snapshot", tuple(cuts)), ("estimate", tuple(estimate_by_id)),
        ("measurement", tuple(observations)), ("health", tuple(health)),
        ("pair", tuple((row.horizon_days, row.target_observation_id) for row in pairs)),
    ):
        if len(items) != len(set(items)):
            identity_errors.append(prefix)
    if len(cuts) != len(snapshots) or len(estimate_by_id) != len(estimates) or len(health) != len(fixture.health):
        identity_errors.append("dimension")
    for row in snapshots:
        if row.revises_snapshot_id is not None and row.revises_snapshot_id not in cuts:
            identity_errors.append(row.snapshot_id)
    checks.append(_check("PUBLISHED_IDENTITIES", "unique keys and valid revision parents", identity_errors))
    reject_failures(checks)
    return tuple(checks)
