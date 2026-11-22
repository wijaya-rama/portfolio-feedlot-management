"""Synthetic episode transitions bound to Stage 1 movements and availability."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..stage1.model import EventKind, LocationKind, is_utc
from ..stage1.provenance import stable_id


class Action(StrEnum):
    ONSET = "onset"
    PULL = "first_observation"
    ADMIT = "hospital_admission"
    TREAT = "treatment"
    REASSESS = "reassessment"
    REPEAT = "repeat_treatment"
    RECOVER = "recovery"
    RETURN = "return_to_production"
    CHRONIC = "chronic"
    DEATH = "death"


TRANSITIONS = {
    None: {Action.ONSET, Action.DEATH},
    Action.ONSET: {Action.PULL, Action.DEATH},
    Action.PULL: {Action.ADMIT, Action.TREAT, Action.REASSESS, Action.DEATH},
    Action.ADMIT: {Action.TREAT, Action.REASSESS, Action.DEATH},
    Action.TREAT: {Action.REASSESS, Action.DEATH},
    Action.REASSESS: {Action.REPEAT, Action.RECOVER, Action.CHRONIC, Action.DEATH},
    Action.REPEAT: {Action.REASSESS, Action.DEATH},
    Action.CHRONIC: {Action.REASSESS, Action.RETURN, Action.DEATH},
    Action.RECOVER: {Action.RETURN, Action.ONSET, Action.DEATH},
    Action.RETURN: {Action.ONSET, Action.REASSESS, Action.DEATH},
    Action.DEATH: set(),
}


@dataclass(frozen=True)
class ClinicalInput:
    source_id: str
    animal_id: str
    action: Action
    effective_at: datetime
    posted_at: datetime | None = None
    available_at: datetime | None = None
    severity: str | None = None
    treatment_response: str | None = None


@dataclass(frozen=True)
class HealthEvent:
    health_event_id: str
    episode_id: str
    previous_health_event_id: str | None
    animal_id: str
    lot_id: str
    action: Action
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    location_id: str
    source_event_id: str
    movement_event_id: str | None
    severity: str | None
    treatment_response: str | None
    burden: float
    clinical_status: str
    operational_visible: bool
    model_version: str
    physical_snapshot_id: str
    synthetic: bool = True


def build_health(timeline, clinical_inputs, config):
    """Merge planned clinical actions with actual admissions, returns and deaths."""
    by_animal = defaultdict(list)
    source_ids = set()
    auto_actions = {Action.ADMIT, Action.RETURN, Action.DEATH}
    for row in clinical_inputs:
        if (not row.source_id.startswith("SYN-") or row.source_id in source_ids
                or not isinstance(row.action, Action) or row.action in auto_actions
                or not is_utc(row.effective_at) or row.animal_id not in timeline.animals):
            raise ValueError(f"invalid clinical source {row.source_id}")
        source_ids.add(row.source_id)
        by_animal[row.animal_id].append((row, None))

    for event in timeline.events.values():
        if event.kind == EventKind.DEATH:
            action = Action.DEATH
        elif (event.kind == EventKind.TRANSFER
              and timeline.kinds[event.to_location_id] == LocationKind.HOSPITAL):
            action = Action.ADMIT
        elif (event.kind == EventKind.TRANSFER
              and timeline.kinds[event.from_location_id] == LocationKind.HOSPITAL):
            action = Action.RETURN
        else:
            continue
        posted = max(event.effective_at, event.posted_at)
        row = ClinicalInput(event.event_id, event.animal_id, action, event.effective_at,
                            posted, max(event.available_at, posted))
        by_animal[row.animal_id].append((row, event))

    result = []
    for animal_id, rows in sorted(by_animal.items()):
        previous = None
        last_public = None
        for row, movement in sorted(rows, key=lambda item: (item[0].effective_at, item[0].source_id)):
            current = _apply(timeline, config, row, movement, previous, last_public)
            result.append(current)
            previous = current
            if current.operational_visible:
                last_public = current
    return tuple(result)


def _apply(timeline, config, row, movement, previous, last_public):
    action = row.action
    instant = row.effective_at
    prior_action = previous.action if previous else None
    if (action not in TRANSITIONS[prior_action]
            or (previous and instant <= previous.effective_at)):
        raise ValueError(f"invalid clinical order for {row.source_id}")
    interval = timeline.location_at(row.animal_id, instant)
    if action == Action.DEATH:
        location_id = movement.from_location_id
    elif interval is None:
        raise ValueError(f"clinical event outside active interval: {row.source_id}")
    else:
        location_id = interval.location_id
    if movement and action != Action.DEATH and location_id != movement.to_location_id:
        raise ValueError(f"hospital movement has no corresponding active interval: {row.source_id}")

    posted = row.posted_at or instant
    available = row.available_at or posted
    if not is_utc(posted) or not is_utc(available) or not instant <= posted <= available:
        raise ValueError(f"invalid clinical timestamps: {row.source_id}")
    public = action != Action.ONSET
    if public and last_public and available < last_public.available_at:
        raise ValueError(f"clinical availability precedes prior public action: {row.source_id}")
    if prior_action == Action.RETURN:
        if action == Action.REASSESS and previous.clinical_status != "chronic":
            raise ValueError(f"recovered animal requires a new onset: {row.source_id}")
        if action == Action.ONSET and previous.clinical_status != "recovered":
            raise ValueError(f"new onset overlaps an unresolved case: {row.source_id}")

    synthetic_health = config["health"]
    new_episode = action == Action.ONSET or (action == Action.DEATH and (
        previous is None or previous.clinical_status == "recovered"))
    severity = row.severity if row.severity is not None else (
        previous.severity if previous and not new_episode else None)
    if ((severity is not None and severity not in synthetic_health["severity"])
            or (action == Action.ONSET and severity is None)):
        raise ValueError(f"invalid synthetic severity: {row.source_id}")
    therapy = action in {Action.TREAT, Action.REPEAT}
    if ((therapy and row.treatment_response not in synthetic_health["treatment_relief"])
            or (not therapy and row.treatment_response is not None)):
        raise ValueError(f"invalid synthetic treatment response: {row.source_id}")

    burden = previous.burden if previous and not new_episode else 0.0
    status = previous.clinical_status if previous and not new_episode else "ill"
    if action == Action.ONSET or row.severity is not None:
        burden = synthetic_health["severity"][severity]
    if therapy:
        burden = max(0.0, burden - synthetic_health["treatment_relief"][row.treatment_response])
    elif action == Action.RECOVER:
        burden, status = 0.0, "recovered"
    elif action == Action.CHRONIC:
        burden, status = synthetic_health["chronic_burden"], "chronic"
    elif action == Action.DEATH:
        status = "dead"

    version = config["health_version"]
    episode = (stable_id("CASE", [row.animal_id, row.source_id])
               if new_episode else previous.episode_id)
    return HealthEvent(
        stable_id("HEALTH", [version, row.source_id]), episode,
        previous.health_event_id if not new_episode else None,
        row.animal_id, timeline.animals[row.animal_id].lot_id, action, instant, posted, available,
        location_id, row.source_id, movement.event_id if movement else None, severity,
        row.treatment_response, burden, status, public, version, timeline.snapshot_id,
    )
