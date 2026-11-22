"""Stage 1 physical and operational replay, with indexed half-open intervals."""

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta

from ..stage1.model import AnimalStatus, EventKind, LocationKind, is_utc
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.replay import replay
from ..stage1.validation import reject_failures

ENTRY = (EventKind.OPENING, EventKind.RECEIPT)
EXIT = (EventKind.SALE, EventKind.DEATH)


def checked_replay(ledger, effective_before, knowledge_cutoff):
    if not is_utc(effective_before) or not is_utc(knowledge_cutoff):
        raise ValueError("replay cutoffs must be UTC")
    result = replay(ledger, effective_before, knowledge_cutoff)
    reject_failures(result.checks)
    return result


def replay_digest(result):
    # Exclude effective-future records even when they have already been posted.
    return sha256(canonical([result.animals, result.lots, result.location_versions,
                             result.events, result.states, result.intervals]))


class PhysicalTimeline:
    def __init__(self, ledger, effective_before, knowledge_cutoff):
        self.result = checked_replay(ledger, effective_before, knowledge_cutoff)
        self.run_id = stable_id("RUN", ledger.config)
        self.snapshot_id = stable_id("STAGE2-PHYSICAL", [
            self.run_id, effective_before, knowledge_cutoff, replay_digest(self.result),
        ])
        self.seed = ledger.config.seed
        self.kinds = ledger.location_kinds
        self.animals = {row.animal_id: row for row in self.result.animals}
        self.events = {row.event_id: row for row in self.result.events}
        self.entries = {row.animal_id: row for row in self.result.events if row.kind in ENTRY}
        self.exits = {row.animal_id: row for row in self.result.events if row.kind in EXIT}
        self.states = {row.animal_id: row for row in self.result.states}
        intervals = defaultdict(list)
        for row in self.result.intervals:
            if row.end_at != row.start_at:
                intervals[row.animal_id].append(row)
        self.intervals = {key: tuple(rows) for key, rows in intervals.items()}
        self.starts = {key: tuple(row.start_at for row in rows)
                       for key, rows in self.intervals.items()}

    def location_at(self, animal_id, instant):
        if instant >= self.result.effective_before:
            return None
        offsets = self.starts.get(animal_id, ())
        index = bisect_right(offsets, instant) - 1
        if index < 0:
            return None
        row = self.intervals[animal_id][index]
        return row if row.end_at is None or instant < row.end_at else None

    def stop_at(self, animal_id):
        exit_event = self.exits.get(animal_id)
        return exit_event.effective_at if exit_event else self.result.effective_before


def production_stage(location_kind, entered_at, instant, adaptation_days):
    if location_kind != LocationKind.PRODUCTION:
        return str(location_kind)
    if instant - entered_at < timedelta(days=adaptation_days):
        return "adaptation"
    return "finishing"
