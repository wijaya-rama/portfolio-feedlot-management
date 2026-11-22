"""Physical weighing attempts and an immutable measurement correction chain."""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite

from ..stage1.model import EventKind, LocationKind, is_utc
from ..stage1.provenance import stable_id
from .config import uniform


class Kind(StrEnum):
    OPENING = "opening"
    RECEIVING = "receiving"
    FOLLOW_UP = "follow_up"
    HOSPITAL = "hospital"
    DRAFTING = "drafting"
    FINAL_SALE = "final_sale"


@dataclass(frozen=True)
class WeighPlan:
    source_id: str
    animal_id: str
    kind: Kind
    measured_at: datetime
    posting_lag: timedelta = timedelta(minutes=10)
    availability_lag: timedelta = timedelta(minutes=5)
    missing_probability: float | None = None
    movement_event_id: str | None = None


@dataclass(frozen=True)
class WeighAttempt:
    source_event_id: str
    animal_id: str
    lot_id: str
    location_id: str
    location_event_id: str
    movement_event_id: str | None
    kind: Kind
    scheduled_at: datetime
    observation_id: str | None
    status: str
    physical_snapshot_id: str
    synthetic: bool = True


@dataclass(frozen=True)
class Observation:
    observation_id: str
    animal_id: str
    lot_id: str
    kind: Kind
    measured_weight_kg: float
    measured_at: datetime
    posted_at: datetime
    available_at: datetime
    scale_id: str
    quality_flag: str
    source_event_id: str
    location_id: str
    location_event_id: str
    movement_event_id: str | None
    corrects_observation_id: str | None
    source_version: str
    model_version: str
    physical_snapshot_id: str
    synthetic: bool = True


def _context(timeline, animal_id, instant, kind, movement_id, *, sale_at_exit=False):
    movement = timeline.events.get(movement_id)
    lookup = instant
    if (sale_at_exit and kind == Kind.FINAL_SALE and movement and movement.kind == EventKind.SALE
            and instant == movement.effective_at):
        # At the sale boundary, sample before the exit transition.
        lookup -= timedelta(microseconds=1)
    interval = timeline.location_at(animal_id, lookup)
    if interval is None:
        raise ValueError(f"live measurement outside active interval: {animal_id}")
    if kind in {Kind.OPENING, Kind.RECEIVING}:
        expected = EventKind.OPENING if kind == Kind.OPENING else EventKind.RECEIPT
        if (movement is None or movement.kind != expected
                or movement.event_id != interval.start_event_id or instant != movement.effective_at):
            raise ValueError(f"measurement must link to effective entry: {animal_id}")
    elif kind == Kind.FINAL_SALE:
        if (movement is None or movement.kind != EventKind.SALE or movement.animal_id != animal_id
                or interval.end_event_id != movement.event_id):
            raise ValueError(f"measurement must precede sale in the exit location: {animal_id}")
    elif movement_id is not None:
        raise ValueError("movement event links are reserved for entry and sale")
    if kind == Kind.HOSPITAL and timeline.kinds[interval.location_id] != LocationKind.HOSPITAL:
        raise ValueError(f"hospital measurement requires an active hospital stay: {animal_id}")
    return interval, movement


def simulate_observations(timeline, biology, plans, config, *, on_sample=None):
    attempts = []
    records = []
    seen = set()
    weighing = config["weighing"]
    version = config["observation_version"]
    for plan in sorted(plans, key=lambda row: (row.measured_at, row.source_id)):
        if (not plan.source_id.startswith("SYN-") or plan.source_id in seen
                or not isinstance(plan.kind, Kind) or not is_utc(plan.measured_at)
                or min(plan.posting_lag, plan.availability_lag) < timedelta(0)):
            raise ValueError(f"invalid weighing plan: {plan.source_id}")
        seen.add(plan.source_id)
        interval, movement = _context(timeline, plan.animal_id, plan.measured_at, plan.kind,
                                      plan.movement_event_id, sale_at_exit=config.get("sale_at_exit", False))
        probability = plan.missing_probability
        if probability is None:
            probability = weighing["default_missing_probability"][plan.kind]
        if not 0 <= probability <= 1:
            raise ValueError(f"invalid missing probability: {plan.source_id}")

        observation_id = None
        if uniform(timeline.seed, "scale-missing", plan.source_id) >= probability:
            scale_id = _scale(plan.kind)
            scale = weighing["scales"][scale_id]
            random_error = (2 * uniform(timeline.seed, "scale-error", plan.source_id) - 1)
            error = scale["bias_kg"] + random_error * scale["error_half_width_kg"]
            precision = weighing["precision_kg"]
            latent = biology.weight_at(plan.animal_id, plan.measured_at)
            kg = round(round((latent + error) / precision) * precision, 6)
            posted = plan.measured_at + plan.posting_lag
            if movement and plan.kind == Kind.FINAL_SALE:
                posted = max(posted, movement.effective_at, movement.available_at)
            observation_id = stable_id("WEIGHT", [version, plan.source_id])
            if on_sample is not None:
                on_sample(plan, observation_id, latent, scale["bias_kg"],
                          random_error * scale["error_half_width_kg"], precision)
            records.append(Observation(
                observation_id, plan.animal_id, interval.lot_id, plan.kind, kg,
                plan.measured_at, posted, posted + plan.availability_lag, scale_id,
                "accepted", plan.source_id, interval.location_id, interval.start_event_id,
                plan.movement_event_id, None, "scale-ticket.1", version, timeline.snapshot_id,
            ))
        attempts.append(WeighAttempt(
            plan.source_id, plan.animal_id, interval.lot_id, interval.location_id,
            interval.start_event_id, plan.movement_event_id, plan.kind, plan.measured_at,
            observation_id, "measured" if observation_id else "missing", timeline.snapshot_id,
        ))
    return tuple(attempts), tuple(records)


def _scale(kind):
    if kind == Kind.RECEIVING:
        return "SYN-SCALE-RECEIVING"
    if kind == Kind.HOSPITAL:
        return "SYN-SCALE-HOSPITAL"
    if kind in {Kind.DRAFTING, Kind.FINAL_SALE}:
        return "SYN-SCALE-SHIP"
    return "SYN-SCALE-YARD"


def correct(original, *, source_id, posted_at, available_at, measured_weight_kg, rejected=False):
    return replace(
        original, source_event_id=source_id,
        observation_id=stable_id("WEIGHT", [original.model_version, source_id]),
        posted_at=posted_at, available_at=available_at, measured_weight_kg=measured_weight_kg,
        quality_flag="rejected" if rejected else "corrected",
        corrects_observation_id=original.observation_id, source_version="scale-correction.1",
    )


class Observations:
    """Validated scale records. Resolve revisions using both observation and knowledge time."""

    def __init__(self, timeline, records, config):
        rows = sorted(records, key=lambda row: (row.available_at, row.observation_id))
        by_id = {}
        source_ids = set()
        superseded = set()
        by_animal = defaultdict(list)
        for row in rows:
            self._validate(timeline, config, row)
            if row.observation_id in by_id or row.source_event_id in source_ids:
                raise ValueError(f"duplicate scale record: {row.observation_id}")
            parent_id = row.corrects_observation_id
            if parent_id is not None:
                parent = by_id.get(parent_id)
                immutable = ("animal_id", "lot_id", "kind", "measured_at", "scale_id",
                             "location_id", "location_event_id", "movement_event_id")
                if (parent is None or parent_id in superseded
                        or row.available_at <= parent.available_at or row.posted_at < parent.posted_at
                        or any(getattr(row, key) != getattr(parent, key) for key in immutable)):
                    raise ValueError(f"invalid weighing correction: {row.observation_id}")
                superseded.add(parent_id)
            by_id[row.observation_id] = row
            source_ids.add(row.source_event_id)
            by_animal[row.animal_id].append(row)
        self.records = tuple(rows)
        self.by_id = by_id
        self.by_animal = {key: tuple(values) for key, values in by_animal.items()}

    @staticmethod
    def _validate(timeline, config, row):
        if (not isinstance(row.kind, Kind) or row.synthetic is not True
                or not row.observation_id.startswith("SYN-") or not row.source_event_id.startswith("SYN-")
                or not row.source_version or row.model_version != config["observation_version"]
                or row.physical_snapshot_id != timeline.snapshot_id
                or not isfinite(row.measured_weight_kg) or row.measured_weight_kg <= 0
                or row.scale_id not in config["weighing"]["scales"]
                or row.quality_flag not in ({"accepted", "suspect"} if row.corrects_observation_id is None
                                             else {"corrected", "rejected"})
                or not all(is_utc(value) for value in (row.measured_at, row.posted_at, row.available_at))
                or not row.measured_at <= row.posted_at <= row.available_at):
            raise ValueError(f"invalid scale record: {row.observation_id}")
        interval, movement = _context(timeline, row.animal_id, row.measured_at, row.kind,
                                      row.movement_event_id, sale_at_exit=config.get("sale_at_exit", False))
        if ((row.location_id, row.location_event_id, row.lot_id)
                != (interval.location_id, interval.start_event_id, interval.lot_id)
                or (movement and row.kind == Kind.FINAL_SALE
                    and row.available_at < max(movement.available_at, movement.effective_at))):
            raise ValueError(f"invalid scale lineage: {row.observation_id}")

    def eligible(self, animal_id, effective_before, knowledge_cutoff, *, include_terminal=False):
        known = tuple(row for row in self.by_animal.get(animal_id, ())
                      if row.measured_at < effective_before and row.available_at <= knowledge_cutoff
                      and (include_terminal or row.kind != Kind.FINAL_SALE))
        superseded = {row.corrects_observation_id for row in known}
        return tuple(sorted((row for row in known if row.observation_id not in superseded
                             and row.quality_flag not in {"suspect", "rejected"}),
                            key=lambda row: (row.measured_at, row.available_at, row.observation_id)))
