"""Contemporaneous feeding decisions and versioned physical-access settlements."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from math import isqrt

from ..stage1.model import is_utc
from ..stage1.provenance import stable_id
from ..stage1.snapshots import RevisionApproval
from ..stage2.estimation import Model
from ..stage2.timeline import checked_replay, replay_digest
from .ration import FeedAmount, partition
from .units import BPS, seconds, split, whole
from .warehouse import Document


class Method(StrEnum):
    EQUAL = "equal_head"
    BODYWEIGHT = "bodyweight"
    METABOLIC = "metabolic_bodyweight"


MODEL_VERSION = "exposure-weighted.1"
DEFAULT_METHOD = Method.METABOLIC


@dataclass(frozen=True)
class WeightInput:
    weight_input_id: str
    animal_id: str
    cutoff: datetime
    estimate_snapshot_id: str
    estimate_id: str | None
    estimate_model_version: str | None
    anchor_observation_id: str | None
    anchor_available_at: datetime | None
    roster_pen_id: str | None
    roster_movement_event_id: str | None
    production_stage: str | None
    estimated_kg: float | None
    score_weight_g: int
    fallback_reason: str | None


@dataclass(frozen=True)
class Plan:
    plan_id: str
    pen_id: str
    window_start: datetime
    window_end: datetime
    decision_at: datetime
    decision_snapshot_id: str
    ration_version_id: str
    planned_g_dm: int
    known_head: int
    policy_version: str
    status: str


@dataclass(frozen=True)
class BunkTicket(Document):
    delivery_id: str
    observed_refusal_g_af: int
    bunk_loss_g_af: int = 0


@dataclass(frozen=True)
class Settlement:
    settlement_id: str
    delivery_id: str
    bunk_ticket_id: str
    access_snapshot_id: str
    decision_snapshot_id: str
    revises_settlement_id: str | None
    revision_approval_id: str | None
    finalized_at: datetime
    available_at: datetime
    roster_status: str
    planned_head: int
    eligible_head: int
    observed_refusal_g_af: int
    inferred_unconsumed_g_af: int
    modeled_consumption: FeedAmount
    refusal: FeedAmount
    bunk_loss: FeedAmount


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    settlement_id: str
    delivery_id: str
    animal_id: str
    lot_id: str
    pen_id: str
    first_at: datetime
    end_at: datetime
    duration_seconds: int
    movement_in_id: str
    movement_out_id: str | None
    weight_input_id: str


@dataclass(frozen=True)
class Allocation:
    allocation_id: str
    settlement_id: str
    exposure_id: str
    delivery_id: str
    mix_id: str
    animal_id: str
    lot_id: str
    pen_id: str
    window_start: datetime
    window_end: datetime
    access_start: datetime
    access_end: datetime
    duration_seconds: int
    weight_input_id: str
    estimate_id: str | None
    decision_cutoff: datetime
    method: Method
    model_version: str
    score: int
    g_dm: int
    energy_kj: int
    cp_g: int
    cents: int
    finalized_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class AccessSnapshot:
    access_snapshot_id: str
    effective_before: datetime
    knowledge_cutoff: datetime
    replay_sha256: str


@dataclass(frozen=True)
class Settled:
    row: Settlement
    access: AccessSnapshot
    exposures: tuple[Exposure, ...]
    weights: tuple[WeightInput, ...]
    allocations: tuple[Allocation, ...]


def _weight(animal_id, cutoff, snapshot_id, fallback_g, estimate=None):
    estimate_id = estimate.estimate_id if estimate else None
    frozen = None
    if estimate is None:
        reason = "unknown_at_decision"
    elif estimate.estimated_liveweight_kg is None:
        reason = "missing_anchor"
    elif estimate.confidence_status == "low_stale":
        reason = "stale_anchor"
    else:
        frozen = int((Decimal(str(estimate.estimated_liveweight_kg)) * 1000)
                     .to_integral_value(rounding=ROUND_HALF_UP))
        whole(frozen, "as-of weight in grams", minimum=1)
        reason = None
    return WeightInput(
        stable_id("FEED-WEIGHT", [snapshot_id, animal_id, estimate_id, fallback_g]),
        animal_id, cutoff, snapshot_id, estimate_id, estimate.model_version if estimate else None,
        estimate.last_observation_id if estimate else None,
        estimate.last_available_at if estimate else None, estimate.location_id if estimate else None,
        estimate.location_event_id if estimate else None, estimate.production_stage if estimate else None,
        estimate.estimated_liveweight_kg if estimate else None, frozen if frozen is not None else fallback_g,
        reason)


def freeze(estimator, cutoff, fallback_g):
    whole(fallback_g, "fallback weight in grams", minimum=1)
    snapshot, estimates = estimator.estimates(cutoff, models=(Model.B,))
    weights = {row.animal_id: _weight(row.animal_id, cutoff, snapshot.snapshot_id, fallback_g, row)
               for row in estimates}
    return snapshot, estimates, weights


def feed_plan(pen, start, end, snapshot, weights, formulas, ration_id, policy,
              *, override_g_dm=None):
    if not all(map(is_utc, (start, end))) or not start < end or (
            snapshot.effective_before != start or snapshot.knowledge_cutoff != start):
        raise ValueError("feeding plan needs an ordered UTC window and contemporaneous input")
    roster = tuple(row for row in weights.values() if row.roster_pen_id == pen)
    recipe = formulas.at(ration_id, start)
    if any(row.production_stage not in recipe.eligible_stages.split(",") for row in roster):
        raise ValueError(f"ration is ineligible for the decision roster: {pen}")
    target = sum(min(policy["stage_dm_g_per_window"][row.production_stage],
                     row.score_weight_g * policy["intake_limit_bps_per_window"] // BPS)
                 for row in roster)
    if override_g_dm is not None:
        target = whole(override_g_dm, "scripted target DM", minimum=1)
        status = "scripted_dispatch"
    else:
        status = "roster_planned" if roster else "no_known_roster"
    plan_id = stable_id("FEED-PLAN", [pen, start, end, snapshot.snapshot_id, recipe, target, policy,
                                     status, roster])
    return Plan(plan_id, pen, start, end, start, snapshot.snapshot_id, recipe.record_id, target,
                len(roster), policy["version"], status)


def _intervals(replay, delivery):
    start, end = delivery.window_start, delivery.window_end
    return tuple(sorted(
        ((row.animal_id, row.lot_id, max(start, row.start_at), min(end, row.end_at or end),
          row.start_event_id, row.end_event_id if row.end_at and row.end_at <= end else None)
         for row in replay.intervals
         if row.location_id == delivery.pen_id and row.start_at < end
         and (row.end_at is None or row.end_at > max(start, row.start_at))),
        key=lambda row: (row[0], row[2], row[4])))


def _scores(weights, method):
    if method == Method.EQUAL:
        return dict.fromkeys(weights, 1)
    if method == Method.BODYWEIGHT:
        return {key: row.score_weight_g for key, row in weights.items()}
    # Exact integer fourth root of grams cubed, scaled by 1,000 for precision.
    return {key: isqrt(isqrt(row.score_weight_g**3 * 10**12)) for key, row in weights.items()}


def settle(ledger, delivery, plan, ticket, frozen, fallback_g, *,
           parent=None, approval=None, replay=None, allocation_policy=None):
    if (ticket.delivery_id != delivery.delivery_id or plan.plan_id != delivery.plan_id
            or not delivery.window_end <= ticket.effective_at <= ticket.posted_at
            or not delivery.available_at <= ticket.available_at
            or (parent is None) != (approval is None)):
        raise ValueError("invalid bunk evidence or settlement revision")
    if approval is not None and not isinstance(approval, RevisionApproval):
        raise ValueError("invalid settlement revision approval")
    cutoff = ticket.available_at if approval is None else approval.approved_at
    if parent is not None:
        if (not approval.synthetic
                or ticket.available_at > cutoff
                or not approval.approval_id.startswith("SYN-") or not approval.approved_by.startswith("SYN-")
                or not approval.reason.strip() or not is_utc(cutoff)
                or cutoff <= parent.row.available_at or parent.row.delivery_id != delivery.delivery_id
                or parent.row.decision_snapshot_id != plan.decision_snapshot_id):
            raise ValueError("settlement revision requires explicit later approval for the same decision")
    # Read through the exact end instant to capture an exit/transfer there as lineage.
    effective_before = delivery.window_end + timedelta(microseconds=1)
    if replay is None:
        replay = checked_replay(ledger, effective_before, cutoff)
    if replay.effective_before != effective_before or replay.knowledge_cutoff != cutoff:
        raise ValueError("access replay cutoffs do not match settlement")
    digest = replay_digest(replay)
    access = AccessSnapshot(stable_id("FEED-ACCESS", [effective_before, cutoff, digest]),
                            effective_before, cutoff, digest)
    intervals = _intervals(replay, delivery)
    if parent is not None and ticket.record_id == parent.row.bunk_ticket_id and intervals == tuple(
            (row.animal_id, row.lot_id, row.first_at, row.end_at, row.movement_in_id, row.movement_out_id)
            for row in parent.exposures):
        return parent
    refusal_g = whole(ticket.observed_refusal_g_af, "observed bunk refusals")
    loss_g = whole(ticket.bunk_loss_g_af, "bunk loss")
    if refusal_g + loss_g > delivery.delivered.g_af:
        raise ValueError("refusal and bunk loss exceed delivery")
    if not intervals and allocation_policy is None:
        refusal_g = delivery.delivered.g_af - loss_g
    amounts = partition(delivery.delivered, {"refusal": refusal_g, "bunk_loss": loss_g,
                                             "consumption": delivery.delivered.g_af - refusal_g - loss_g})
    allocation_version = MODEL_VERSION
    if allocation_policy is not None:
        allocation_version = allocation_policy.version
        amounts, releases = allocation_policy.release(delivery, intervals, amounts)
        refusal_g = amounts["refusal"].g_af
    actual_animals = {row[0] for row in intervals}
    planned_animals = {row.animal_id for row in frozen.values() if row.roster_pen_id == delivery.pen_id}
    if not intervals:
        status = "empty_no_access"
    elif any(key not in frozen for key in actual_animals):
        status = "incomplete_at_decision"
    elif actual_animals != planned_animals or any(
            start != delivery.window_start or end != delivery.window_end
            for _, _, start, end, _, _ in intervals):
        status = "roster_changed"
    else:
        status = "roster_confirmed"
    if any(row.cutoff != plan.decision_at or row.estimate_snapshot_id != plan.decision_snapshot_id
           for row in frozen.values()):
        raise ValueError("settlement weights must use the frozen decision snapshot")
    weights = {}
    for animal in sorted(actual_animals):
        weights[animal] = frozen.get(animal) or _weight(animal, plan.decision_at,
                                                       plan.decision_snapshot_id, fallback_g)
    parent_id = parent.row.settlement_id if parent else None
    identity = [allocation_version, delivery, plan, ticket, access, parent_id, approval, amounts,
                list(weights.values())]
    if allocation_policy is not None:
        identity.append(releases)
    settlement_id = stable_id("BUNK-SETTLEMENT", identity)
    finalized = approval.approved_at if approval else ticket.posted_at
    settlement = Settlement(settlement_id, delivery.delivery_id, ticket.record_id, access.access_snapshot_id,
                            plan.decision_snapshot_id, parent_id, approval.approval_id if approval else None,
                            finalized, cutoff, status, plan.known_head, len(actual_animals),
                            ticket.observed_refusal_g_af, refusal_g - ticket.observed_refusal_g_af,
                            amounts["consumption"], amounts["refusal"],
                            amounts["bunk_loss"])
    exposures = []
    for animal, lot, start, end, entered, exited in intervals:
        exposures.append(Exposure(
            stable_id("FEED-EXPOSURE", [settlement_id, animal, start, end]), settlement_id,
            delivery.delivery_id, animal, lot, delivery.pen_id, start, end, seconds(start, end),
            entered, exited, weights[animal].weight_input_id))
    if allocation_policy is None:
        allocations = tuple(_allocate(settlement, delivery, plan, exposures, weights))
    else:
        allocations = tuple(allocation_policy.allocate(settlement, delivery, plan, exposures,
                                                       weights, releases))
    return Settled(settlement, access, tuple(exposures), tuple(weights.values()), allocations)


def _allocate(settlement, delivery, plan, exposures, weights, *, pool=None, model_version=MODEL_VERSION):
    by_animal = defaultdict(list)
    for row in exposures:
        by_animal[row.animal_id].append(row)
    if pool is None:
        pool = settlement.modeled_consumption
    for method in Method:
        scores = _scores(weights, method)
        drivers = {key: scores[key] * sum(row.duration_seconds for row in rows)
                   for key, rows in by_animal.items()}
        dm_by_animal = split(pool.g_dm, drivers)
        energy_by_animal = split(pool.kj, dm_by_animal)
        cp_by_animal = split(pool.cp_g, dm_by_animal)
        # An animal can carry allocated intake value only if it receives DM (AF for a zero-DM pool).
        cents_by_animal = split(pool.cents, dm_by_animal if pool.g_dm else drivers)
        for animal, rows in by_animal.items():
            times = {row.exposure_id: row.duration_seconds for row in rows}
            dm = split(dm_by_animal[animal], times)
            energy = split(energy_by_animal[animal], dm)
            protein = split(cp_by_animal[animal], dm)
            cents = split(cents_by_animal[animal], dm if dm_by_animal[animal] else times)
            for row in rows:
                key = row.exposure_id
                weight = weights[animal]
                identity = [key, method, model_version]
                if model_version != MODEL_VERSION:
                    identity.extend((row.first_at, row.end_at))
                yield Allocation(
                    stable_id("FEED-ALLOCATION", identity), settlement.settlement_id,
                    key, delivery.delivery_id, delivery.mix_id, animal, row.lot_id, delivery.pen_id,
                    delivery.window_start, delivery.window_end, row.first_at, row.end_at,
                    row.duration_seconds, weight.weight_input_id, weight.estimate_id, plan.decision_at,
                    method, f"{model_version}.{method}", scores[animal], dm[key], energy[key], protein[key],
                    cents[key], settlement.finalized_at, settlement.available_at)
