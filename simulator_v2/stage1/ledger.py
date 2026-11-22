"""Append-only in-memory event ledger and bitemporal correction selection."""

import re
from collections import defaultdict
from threading import RLock
from types import MappingProxyType

from .model import EventKind, LocationKind, Source, is_utc, midnight
from .validation import require

MOVEMENTS = {
    EventKind.OPENING: (False, True),
    EventKind.RECEIPT: (False, True),
    EventKind.TRANSFER: (True, True),
    EventKind.SALE: (True, False),
    EventKind.DEATH: (True, False),
    EventKind.REVERSAL: (False, False),
}


def is_id(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def synthetic_id(value):
    return is_id(value) and value.startswith("SYN-")


def unique(records, field, kind):
    result = {}
    for record in records:
        key = getattr(record, field)
        require(synthetic_id(key) and key not in result, "MASTER_PK", kind,
                "unique nonblank SYN- ID", key)
        result[key] = record
    return dict(sorted(result.items()))


def validate_times(record, scope, record_id):
    times = record.effective_at, record.posted_at, record.available_at
    require(all(is_utc(value) for value in times) and record.available_at >= record.posted_at,
            "TIMESTAMPS", scope, "UTC timestamps and posted_at <= available_at",
            tuple(str(value) for value in times), record_id)
    require(record.synthetic is True, "SYNTHETIC", scope, True, record.synthetic, record_id)


class Ledger:
    def __init__(self, config, lots, animals, location_versions):
        self.config = config
        self.lots = MappingProxyType(unique(lots, "lot_id", "lot"))
        self.animals = MappingProxyType(unique(animals, "animal_id", "animal"))
        self.location_versions = MappingProxyType(
            unique(location_versions, "location_version_id", "location"))
        location_keys = defaultdict(set)
        rfids = set()
        for lot in self.lots.values():
            validate_times(lot, "lot", lot.lot_id)
            require(synthetic_id(lot.supplier_id) and is_id(lot.compatibility_group),
                    "LOT_ATTRIBUTES", "lot", "synthetic supplier and compatibility group",
                    (lot.supplier_id, lot.compatibility_group), lot.lot_id)
        for animal in self.animals.values():
            validate_times(animal, "animal", animal.animal_id)
            require(synthetic_id(animal.lot_id) and animal.lot_id in self.lots,
                    "ANIMAL_LOT_FK", "animal", "known lot", animal.lot_id, animal.animal_id)
            lot = self.lots[animal.lot_id]
            require(lot.effective_at <= animal.effective_at and lot.available_at <= animal.available_at,
                    "ANIMAL_LOT_TIMESTAMPS", "animal", "lot visible whenever animal is visible",
                    lot.lot_id, animal.animal_id)
            require(isinstance(animal.rfid, str) and re.fullmatch(r"000[0-9]{12}", animal.rfid)
                    and animal.rfid not in rfids, "RFID", "animal",
                    "unique synthetic 15-digit text", animal.rfid, animal.animal_id)
            rfids.add(animal.rfid)
        kinds = {}
        for version in self.location_versions.values():
            validate_times(version, "location", version.location_version_id)
            require(synthetic_id(version.location_id) and isinstance(version.kind, LocationKind)
                    and type(version.capacity_head) is int and version.capacity_head >= 0,
                    "LOCATION_ATTRIBUTES", "location", "synthetic ID, valid type, capacity >= 0",
                    (version.location_id, str(version.kind), version.capacity_head),
                    version.location_version_id)
            location_id = version.location_id
            require(version.effective_at not in location_keys[location_id]
                    and kinds.get(location_id, version.kind) == version.kind,
                    "LOCATION_VERSION", "location", "distinct effective starts and stable type",
                    version.effective_at.isoformat(), version.location_version_id)
            location_keys[location_id].add(version.effective_at)
            kinds[location_id] = version.kind
        self.location_kinds = MappingProxyType(dict(sorted(kinds.items())))
        self._events = {}
        self._source_keys = {}
        self._successors = {}
        self._lock = RLock()

    @property
    def events(self):
        with self._lock:
            return tuple(sorted(self._events.values(), key=lambda event: event.order))

    def _validate_record(self, event):
        eid = event.event_id
        validate_times(event, "event", eid)
        require(synthetic_id(eid) and type(event.sequence) is int and event.sequence >= 0
                and isinstance(event.kind, EventKind), "EVENT_FIELDS", "event",
                "synthetic ID, nonnegative integer sequence, valid kind",
                (eid, event.sequence, str(event.kind)), eid)
        require(synthetic_id(event.animal_id) and event.animal_id in self.animals,
                "EVENT_ANIMAL_FK", "event", "known animal", event.animal_id, eid)
        source = event.source
        require(isinstance(source, Source) and source.synthetic is True
                and all(synthetic_id(value) for value in (source.system, source.document_id))
                and is_id(source.line_id) and type(source.revision) is int and source.revision >= 1,
                "EVENT_SOURCE", "event", "synthetic system/document, line, positive revision",
                str(source), eid)
        endpoints = event.from_location_id, event.to_location_id
        require(tuple(value is not None for value in endpoints) == MOVEMENTS[event.kind],
                "EVENT_ENDPOINTS", "event", MOVEMENTS[event.kind], endpoints, eid)
        for value in endpoints:
            if value is not None:
                require(synthetic_id(value) and value in self.location_kinds, "LOCATION_FK",
                        "event", "known location", value, eid)
        if event.kind == EventKind.TRANSFER:
            require(endpoints[0] != endpoints[1], "TRANSFER_SELF", "event",
                    "distinct locations", endpoints, eid)
        if event.kind == EventKind.OPENING:
            require(event.effective_at < midnight(self.config.start_date), "OPENING_TIME", "event",
                    "before reporting horizon", event.effective_at.isoformat(), eid)
        if event.kind == EventKind.RECEIPT:
            require(self.location_kinds[endpoints[1]] == LocationKind.RECEIVING,
                    "RECEIPT_TARGET", "event", "receiving location", endpoints[1], eid)
        if event.supersedes_event_id is not None or event.kind == EventKind.REVERSAL:
            require(synthetic_id(event.supersedes_event_id) and is_id(event.reason),
                    "CORRECTION_FIELDS", "event", "target ID and reason", event.reason, eid)

    def ingest(self, records):
        """Stage a batch atomically. Return the number of newly appended records."""
        with self._lock:
            events = self._events.copy()
            keys = self._source_keys.copy()
            successors = self._successors.copy()
            additions = []
            for event in records:
                self._validate_record(event)
                if event.event_id in events:
                    require(events[event.event_id] == event, "DUPLICATE_EVENT_ID", "event",
                            "byte-equivalent retry", event.event_id, event.event_id)
                    continue
                require(event.source not in keys, "DUPLICATE_SOURCE_KEY", "event",
                        "one ID per source row/version", keys.get(event.source), event.event_id)
                keys[event.source] = event.event_id
                events[event.event_id] = event
                additions.append(event)

            for event in additions:
                target_id = event.supersedes_event_id
                if target_id is None:
                    continue
                target = events.get(target_id)
                require(target is not None and target.kind != EventKind.REVERSAL
                        and target.animal_id == event.animal_id, "CORRECTION_TARGET", "event",
                        "movement for same animal", target_id, event.event_id)
                require(target_id not in successors, "CORRECTION_BRANCH", "event",
                        "one successor per record", successors.get(target_id), event.event_id)
                require(event.available_at > target.available_at and event.posted_at >= target.posted_at,
                        "CORRECTION_CLOCK", "event", "available after and posted no earlier than target",
                        target_id, event.event_id)
                if event.kind == EventKind.REVERSAL:
                    require(event.effective_at == target.effective_at, "REVERSAL_TIME", "event",
                            target.effective_at.isoformat(), event.effective_at.isoformat(), event.event_id)
                successors[target_id] = event.event_id
            self._events, self._source_keys, self._successors = events, keys, successors
            return len(additions)


def known_events(events, knowledge_cutoff):
    require(is_utc(knowledge_cutoff), "CUTOFF_UTC", "replay", "UTC", str(knowledge_cutoff))
    return tuple(event for event in events if event.available_at <= knowledge_cutoff)


def resolved_events(known, effective_before):
    """Resolve known revisions, then select the effective-time window."""
    require(is_utc(effective_before), "CUTOFF_UTC", "replay", "UTC", str(effective_before))
    hidden = {event.supersedes_event_id for event in known if event.supersedes_event_id}
    return tuple(sorted(
        (event for event in known if event.event_id not in hidden
         and event.kind != EventKind.REVERSAL and event.effective_at < effective_before),
        key=lambda event: event.order,
    ))
