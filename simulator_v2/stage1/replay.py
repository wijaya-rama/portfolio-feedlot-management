"""Reconstruct animal state and half-open location intervals at two cutoffs."""

from dataclasses import dataclass
from datetime import datetime

from .ledger import known_events, resolved_events
from .model import Animal, AnimalEvent, AnimalStatus, EventKind, LocationKind, LocationVersion, Lot
from .validation import Check, ValidationError, require

TRANSFERS = {
    LocationKind.RECEIVING: {LocationKind.PRODUCTION, LocationKind.HOSPITAL},
    LocationKind.PRODUCTION: {LocationKind.PRODUCTION, LocationKind.HOSPITAL},
    LocationKind.HOSPITAL: {LocationKind.PRODUCTION},
}


@dataclass(frozen=True)
class AnimalState:
    animal_id: str
    lot_id: str
    status: AnimalStatus
    location_id: str | None = None
    last_event_id: str | None = None
    synthetic: bool = True


@dataclass(frozen=True)
class LocationInterval:
    animal_id: str
    lot_id: str
    location_id: str
    start_at: datetime
    start_sequence: int
    start_event_id: str
    end_at: datetime | None = None
    end_event_id: str | None = None
    synthetic: bool = True


@dataclass(frozen=True)
class ReplayResult:
    effective_before: datetime
    knowledge_cutoff: datetime
    known_events: tuple[AnimalEvent, ...]
    animals: tuple[Animal, ...]
    lots: tuple[Lot, ...]
    location_versions: tuple[LocationVersion, ...]
    events: tuple[AnimalEvent, ...]
    states: tuple[AnimalState, ...]
    intervals: tuple[LocationInterval, ...]
    checks: tuple[Check, ...]


def visible_masters(records, effective_before, knowledge_cutoff):
    return tuple(record for record in records
                 if record.available_at <= knowledge_cutoff and record.effective_at < effective_before)


def replay(ledger, effective_before, knowledge_cutoff):
    """Report rejected transitions without applying them. Reports with errors block publication."""
    known = known_events(ledger.events, knowledge_cutoff)
    events = resolved_events(known, effective_before)
    lots = visible_masters(ledger.lots.values(), effective_before, knowledge_cutoff)
    animals = visible_masters(ledger.animals.values(), effective_before, knowledge_cutoff)
    versions = visible_masters(ledger.location_versions.values(), effective_before, knowledge_cutoff)
    lots_by_id = {lot.lot_id: lot for lot in lots}
    states = {animal.animal_id: AnimalState(animal.animal_id, animal.lot_id, AnimalStatus.PENDING)
              for animal in animals}
    animal_master = {animal.animal_id: animal for animal in animals}
    locations = {}
    members = {}
    starts = {}
    intervals = []
    accepted = []
    checks = []

    def add_interval(start, end=None):
        intervals.append(LocationInterval(
            start.animal_id, animal_master[start.animal_id].lot_id, start.to_location_id,
            start.effective_at, start.sequence, start.event_id,
            end.effective_at if end else None, end.event_id if end else None,
        ))

    def apply_version(version):
        locations[version.location_id] = version
        count = len(members.setdefault(version.location_id, set()))
        require(count <= version.capacity_head, "CAPACITY_VERSION", version.location_id,
                version.capacity_head, count, version.location_version_id)

    def apply_event(event):
        animal_id = event.animal_id
        eid = event.event_id
        animal = animal_master.get(animal_id)
        lot = lots_by_id.get(animal.lot_id) if animal else None
        require(animal is not None and lot is not None
                and max(animal.effective_at, lot.effective_at) <= event.effective_at,
                "MASTER_EFFECTIVE", "event", "known and effective animal and lot", animal_id, eid)
        state = states[animal_id]
        source_id, target_id = event.from_location_id, event.to_location_id
        if event.kind in (EventKind.OPENING, EventKind.RECEIPT):
            require(state.status == AnimalStatus.PENDING, "ENTRY_STATE", "event",
                    AnimalStatus.PENDING, state.status, eid)
        else:
            require(state.status == AnimalStatus.ACTIVE, "ACTIVE_REQUIRED", "event",
                    AnimalStatus.ACTIVE, state.status, eid)
            require(state.location_id == source_id, "SOURCE_STATE", "event",
                    state.location_id, source_id, eid)
        if target_id is not None:
            target = locations.get(target_id)
            require(target is not None, "LOCATION_EFFECTIVE", "event",
                    "available, effective target version", target_id, eid)
            if event.kind == EventKind.TRANSFER:
                source_kind = locations[source_id].kind
                require(target.kind in TRANSFERS[source_kind], "TRANSFER_ROUTE", "event",
                        sorted(TRANSFERS[source_kind]), (source_kind, target.kind), eid)
            require(len(members[target_id]) < target.capacity_head, "CAPACITY", target_id,
                    target.capacity_head, len(members[target_id]) + 1, eid)
            if target.kind == LocationKind.PRODUCTION:
                groups = {lots_by_id[states[member].lot_id].compatibility_group
                          for member in members[target_id]}
                require(not groups or groups == {lot.compatibility_group},
                        "LOT_COMPATIBILITY", target_id, sorted(groups), lot.compatibility_group, eid)

        if source_id is not None:
            members[source_id].remove(animal_id)
            add_interval(starts.pop(animal_id), event)
        status = AnimalStatus.ACTIVE
        if target_id is not None:
            members[target_id].add(animal_id)
            starts[animal_id] = event
        elif event.kind == EventKind.SALE:
            status = AnimalStatus.SOLD
        else:
            status = AnimalStatus.DEAD
        states[animal_id] = AnimalState(animal_id, animal.lot_id, status, target_id, eid)
        accepted.append(event)

    # Master versions become effective before any movement at the same UTC instant.
    points = [(event.order, event, apply_event) for event in events]
    points.extend(((version.effective_at, -1, version.location_version_id), version, apply_version)
                  for version in versions)
    for _, record, apply in sorted(points, key=lambda item: item[0]):
        try:
            apply(record)
        except ValidationError as exc:
            checks.extend(exc.checks)
    for start in starts.values():
        add_interval(start)
    if not checks:
        checks.append(Check("REPLAY_TRANSITIONS", "event/location", "all accepted",
                            {"events": len(accepted), "location_versions": len(versions)}))
    intervals.sort(key=lambda row: (row.animal_id, row.start_at, row.start_sequence, row.start_event_id))
    return ReplayResult(effective_before, knowledge_cutoff, known, animals, lots, versions,
                        tuple(accepted), tuple(states.values()), tuple(intervals), tuple(checks))
