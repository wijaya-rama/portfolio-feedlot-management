"""Bitemporal daily estimates from Stage 1 replay and observed facts only."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from ..stage1.model import AnimalStatus, business_date, is_utc, midnight
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.soh import calendar_days
from .config import season
from .timeline import ENTRY, checked_replay, production_stage, replay_digest

DAY = timedelta(days=1)
PREVIOUS_INSTANT = timedelta(microseconds=1)


class Model(StrEnum):
    A = "A"
    B = "B"


@dataclass(frozen=True)
class ClinicalFact:
    health_event_id: str
    animal_id: str
    effective_at: datetime
    available_at: datetime
    clinical_status: str
    movement_event_id: str | None
    model_version: str


def operational_health(events):
    return tuple(ClinicalFact(event.health_event_id, event.animal_id, event.effective_at,
                              event.available_at, event.clinical_status, event.movement_event_id,
                              event.model_version)
                 for event in events if event.operational_visible)


@dataclass(frozen=True)
class EstimateSnapshot:
    snapshot_id: str
    stage1_run_id: str
    effective_before: datetime
    knowledge_cutoff: datetime
    movement_sha256: str
    observations_sha256: str
    clinical_sha256: str
    policy_sha256: str
    revises_snapshot_id: str | None
    revision_reason: str | None
    estimator_version: str
    synthetic: bool = True


@dataclass(frozen=True)
class Estimate:
    estimate_id: str
    snapshot_id: str
    animal_id: str
    lot_id: str
    location_id: str
    location_event_id: str
    production_stage: str
    clinical_status: str
    health_event_id: str | None
    estimate_date: date
    effective_before: datetime
    knowledge_cutoff: datetime
    estimate_for: datetime
    model: Model
    model_version: str
    last_observation_id: str | None
    last_measured_at: datetime | None
    last_available_at: datetime | None
    days_since_last_weighing: float | None
    estimated_liveweight_kg: float | None
    estimated_adg_kg: float | None
    adg_prior_kg: float | None
    confidence_status: str
    data_quality_flag: str
    fallback_flag: str
    synthetic: bool = True


@dataclass(frozen=True)
class DraftAssessment:
    draft_id: str
    animal_id: str
    estimate_id: str
    snapshot_id: str
    decided_at: datetime
    threshold_kg: float
    status: str
    reason: str
    synthetic: bool = True


def assess_draft(estimate, threshold_kg):
    """Assess a synthetic candidate without creating a Stage 1 movement."""
    if (not 0 < threshold_kg < float("inf") or estimate.estimate_for != estimate.effective_before
            or estimate.knowledge_cutoff > estimate.effective_before):
        raise ValueError("draft requires a positive target and a contemporaneous estimate")
    if estimate.estimated_liveweight_kg is None or estimate.confidence_status == "low_stale":
        status, reason = "deferred", "insufficient_weight_evidence"
    elif estimate.clinical_status in {"ill", "chronic"}:
        status, reason = "deferred", "observed_health"
    elif estimate.estimated_liveweight_kg < threshold_kg:
        status, reason = "deferred", "below_scenario_threshold"
    else:
        status, reason = "selected", "meets_scenario_threshold"
    return DraftAssessment(stable_id("DRAFT", [estimate.estimate_id, threshold_kg]),
                           estimate.animal_id, estimate.estimate_id, estimate.snapshot_id,
                           estimate.effective_before, threshold_kg, status, reason)


class Estimator:
    def __init__(self, ledger, observations, clinical_facts, config):
        self.ledger = ledger
        self.observations = observations
        self.stage1_run_id = stable_id("RUN", ledger.config)
        self.version = config["estimator_version"]
        self.policy = deepcopy(config["estimation"])
        self.adaptation_days = config["biology"]["adaptation_days"]
        self.calendar_config = {"calendar": deepcopy(config["calendar"])}
        self.policy_hash = sha256(canonical([
            self.version, self.policy, self.adaptation_days, self.calendar_config,
        ]))
        by_animal = defaultdict(list)
        for event in clinical_facts:
            by_animal[event.animal_id].append(event)
        self.clinical = {key: tuple(sorted(items, key=lambda row: (
            row.effective_at, row.health_event_id))) for key, items in by_animal.items()}

    def snapshot(self, effective_before, knowledge_cutoff=None, *, revision_reason=None):
        if knowledge_cutoff is None:
            knowledge_cutoff = effective_before
        if not is_utc(effective_before) or not is_utc(knowledge_cutoff):
            raise ValueError("estimate cutoffs must be UTC")
        retrospective = knowledge_cutoff > effective_before
        if retrospective != bool(revision_reason and revision_reason.strip()):
            raise ValueError("retrospective cutoff requires a revision reason")
        parent = self.snapshot(effective_before)[0] if retrospective else None
        replay = checked_replay(self.ledger, effective_before, knowledge_cutoff)
        active = [row for row in replay.states if row.status == AnimalStatus.ACTIVE]
        event_ids = {row.event_id for row in replay.events}
        observations = {}
        clinical = {}
        for row in active:
            animal_id = row.animal_id
            observations[animal_id] = self.observations.eligible(
                animal_id, effective_before, knowledge_cutoff)
            clinical[animal_id] = tuple(
                event for event in self.clinical.get(animal_id, ())
                if event.effective_at < effective_before and event.available_at <= knowledge_cutoff
                and (event.movement_event_id is None or event.movement_event_id in event_ids)
            )
        # Physical snapshot IDs describe the full truth build. They are not features.
        observation_facts = []
        for rows in observations.values():
            for row in rows:
                fact = asdict(row)
                del fact["physical_snapshot_id"]
                observation_facts.append(fact)
        metadata = (
            self.stage1_run_id, effective_before, knowledge_cutoff, replay_digest(replay),
            sha256(canonical(observation_facts)), sha256(canonical(clinical)), self.policy_hash,
            parent.snapshot_id if parent else None, revision_reason, self.version,
        )
        snapshot = EstimateSnapshot(stable_id("WEIGHT-SNAPSHOT", metadata), *metadata)
        return snapshot, replay, active, observations, clinical

    def estimates(self, effective_before, knowledge_cutoff=None, *, estimate_for=None,
                  revision_reason=None, models=(Model.A, Model.B), animal_id=None):
        """Use origin features for both nowcasts and fixed-origin forecasts."""
        target = effective_before if estimate_for is None else estimate_for
        if not is_utc(effective_before) or not is_utc(target) or target < effective_before:
            raise ValueError("estimate target must be UTC and at or after the origin")
        models = tuple(Model(model) for model in models)
        if len(set(models)) != len(models):
            raise ValueError("duplicate estimate model")
        snapshot, replay, active, weights, clinical = self.snapshot(
            effective_before, knowledge_cutoff, revision_reason=revision_reason)
        entered = {event.animal_id: event.effective_at for event in replay.events if event.kind in ENTRY}
        kinds = {version.location_id: version.kind for version in replay.location_versions}
        rows = []
        for state in active:
            key = state.animal_id
            if animal_id is not None and animal_id != key:
                continue
            stage = production_stage(kinds[state.location_id], entered[key],
                                     effective_before - PREVIOUS_INSTANT, self.adaptation_days)
            anchor = weights[key][-1] if weights[key] else None
            health = clinical[key][-1] if clinical[key] else None
            rows.extend(self._estimate(snapshot, state, stage, health, anchor, target, model)
                        for model in models)
        return snapshot, tuple(rows)

    def _estimate(self, snapshot, state, stage, health, anchor, target, model):
        settings = self.policy
        origin = snapshot.effective_before
        day = business_date(target - PREVIOUS_INSTANT)
        status = health.clinical_status if health else "no_observed_episode"
        prior = adg = weight = age = None
        confidence = "unavailable"
        flag = "no_eligible_measurement"
        fallback = "missing_anchor"
        if anchor:
            age = (origin - anchor.measured_at) / DAY
            elapsed = (target - anchor.measured_at) / DAY
            confidence = "high_recent"
            if elapsed > settings["fresh_days"]:
                confidence = "moderate_aged"
            if elapsed >= settings["stale_days"]:
                confidence = "low_stale"
            prior = 0.0
            if model == Model.B:
                prior = settings["stage_adg_kg"][stage]
                if season(business_date(origin - PREVIOUS_INSTANT), self.calendar_config) == "cold":
                    prior *= settings["cold_adg_multiplier"]
                if status == "ill":
                    prior *= settings["observed_illness_multiplier"]
                elif status == "chronic":
                    prior *= settings["observed_chronic_multiplier"]
            projected_days = min(elapsed, settings["projection_limit_days"])
            gain = prior * projected_days
            adg = gain / elapsed if elapsed else prior
            weight = round(anchor.measured_weight_kg + gain, 3)
            flag = anchor.quality_flag
            fallback = ("projection_capped" if model == Model.B and projected_days < elapsed
                        else "none")

        identity = [snapshot.snapshot_id, state.animal_id, target, model]
        return Estimate(
            stable_id("ESTIMATE", identity), snapshot.snapshot_id, state.animal_id, state.lot_id,
            state.location_id, state.last_event_id, stage, status,
            health.health_event_id if health else None, day, origin, snapshot.knowledge_cutoff,
            target, model, f"{self.version}.{model}", anchor.observation_id if anchor else None,
            anchor.measured_at if anchor else None, anchor.available_at if anchor else None,
            age, weight, round(adg, 6) if adg is not None else None, prior, confidence, flag, fallback,
        )

    def daily(self, start, end):
        if type(start) is not date or type(end) is not date or start > end:
            raise ValueError("daily estimates require an ordered date range")
        for day in calendar_days(start, end):
            yield self.estimates(midnight(day + DAY))
