"""Capacity-aware placement queues and a bounded live animal roster."""

from collections import Counter, deque
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from ..stage1.ledger import Ledger
from ..stage1.model import Animal, AnimalEvent, EventKind, LocationKind, LocationVersion, Lot, RunConfig, Source, business_date, midnight
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.replay import LocationInterval, TRANSFERS
from ..stage2.biology import make_profile
from ..stage2.timeline import production_stage
from .config import at

TICK = timedelta(microseconds=1)
DAY = timedelta(days=1)
PREFIX = {"receiving": "R", "production": "P", "hospital": "H"}


@dataclass(frozen=True)
class Placement:
    lot_id: str
    requested_date: date
    animal_id: str
    position: int
    reference_kg: float


@dataclass(frozen=True)
class Opening:
    animal_id: str
    lot_id: str
    status: str
    location_id: str
    weight_kg: float
    entry_age_days: int
    prior_dof: int
    wip_cents: int
    source_document_id: str


@dataclass(frozen=True)
class ExceptionRow:
    exception_id: str
    effective_at: datetime
    domain: str
    reason: str
    entity_id: str
    quantity: int
    unit: str


@dataclass(frozen=True)
class PhysicalContext:
    snapshot_id: str
    effective_at: datetime
    purpose: str
    movement_sha256: str
    movement_count: int


@dataclass
class Live:
    master: Animal
    entry: AnimalEvent
    interval: LocationInterval
    profile: object
    production_age_origin: datetime
    receiving_until: date | None
    next_weighing: date
    clinical: object = None
    observed_health: object = None
    episode_number: int = 0
    last_recovery: date | None = None
    weight_kg: float = 0.0

    @property
    def key(self):
        return self.master.animal_id

    @property
    def lot(self):
        return self.master.lot_id

    @property
    def pen(self):
        return self.interval.location_id


class Yard:
    def __init__(self, config, first, last, run_id, bio, draw, emit):
        self.bio, self.draw, self.emit = bio, draw, emit
        self.config = config
        self.run_id = run_id
        self.first = first
        opened = at(first - DAY, 12)
        self.kinds, self.capacity = {}, {}
        versions = []
        for kind, prefix in PREFIX.items():
            for number, capacity in enumerate(config["capacities"][kind], 1):
                pen = f"SYN-{prefix}{number:02d}"
                self.kinds[pen] = LocationKind(kind)
                self.capacity[pen] = capacity
                versions.append(LocationVersion(f"{pen}-V1", pen, self.kinds[pen], capacity,
                                                opened, opened, opened))
        self.future = deque()
        self.backlog = []
        self.opening = []
        lots, animals = [], []
        self.minimum_dof_by_lot = {}

        def roster(lot_id, due, head, number):
            lots.append(Lot(lot_id, f"SYN-CATTLE-SUPPLIER-{1 + number % 4:02d}", "finisher-mixed",
                            opened, opened, opened))
            for position in range(1, head + 1):
                key = f"{lot_id}-A{position:05d}"
                serial = len(animals) + 1
                row = Animal(key, lot_id, f"000{serial:012d}", due, due, due)
                animals.append(row)
                yield row, position

        for number, cohort in enumerate(config["carry_in"], 1):
            lot = f"SYN-OPEN-{number:04d}"
            self.minimum_dof_by_lot[lot] = cohort.get("minimum_dof", config["shipment"]["minimum_dof"])
            for animal, _ in roster(lot, opened, cohort["head"], number):
                self.opening.append(Opening(
                    animal.animal_id, lot, cohort["status"], cohort["location"], cohort["weight_kg"],
                    cohort["entry_age_days"], cohort["days_on_feed"], cohort["wip_cents"], cohort["source"]))
        rows = sorted(config["placements"], key=lambda row: row["date"])
        for number, row in enumerate(rows, 1):
            due = date.fromisoformat(row["date"])
            lot = f"SYN-LOT-{number:04d}"
            self.minimum_dof_by_lot[lot] = row.get("minimum_dof", config["shipment"]["minimum_dof"])
            self.future.extend(Placement(lot, due, animal.animal_id, position, float(row["mean_kg"]))
                                for animal, position in roster(lot, at(due, 6, 30), row["head"], number))
        self.ledger = Ledger(RunConfig(config["version"], config["seed"], first, last),
                             lots, animals, versions)
        self.active, self.events, self.entries, self.exits = {}, {}, {}, {}
        self.intervals = {}
        self.entry_costs = {}
        self.members = {pen: set() for pen in self.kinds}
        self.segregate_lots = config.get("lot_segregation", False)
        self.pen_lot = {}
        self.peak = Counter()
        self.sequence = 0
        self.seed = draw.seed
        self.snapshot_id = ""
        self.animals = self.ledger.animals
        self.emit("lots", lots)
        self.emit("locations", versions)
        self.emit("placement_requests", self.future)
        self.emit("opening_cattle", self.opening)

    def exception(self, at_time, reason, key, qty=1, unit="head"):
        event_id = stable_id("OPS-EXCEPTION", [self.run_id, at_time, reason, key])
        self.emit("exceptions", [ExceptionRow(event_id, at_time, "livestock", reason, key, qty, unit)], at_time)

    def pick(self, kind, *, not_pen=None, pack=False, lot=None):
        choices = [pen for pen in self.kinds if self.kinds[pen] == kind and pen != not_pen
                   and len(self.members[pen]) < self.capacity[pen]
                   and (not self.segregate_lots or kind == LocationKind.HOSPITAL
                        or self.pen_lot.get(pen, lot) == lot)]
        return min(choices, key=lambda pen: ((-1 if pack else 1) * len(self.members[pen]), pen), default=None)

    def move(self, key, kind, when, target=None, *, reason=None, document=None):
        origin = self.active[key].pen if key in self.active else None
        if (origin is None) != (kind in {EventKind.OPENING, EventKind.RECEIPT}):
            raise ValueError("movement must begin from the correct active state")
        if target is not None and len(self.members[target]) >= self.capacity[target]:
            raise ValueError(f"destination full: {target}")
        lot = self.animals[key].lot_id
        if (self.segregate_lots and target is not None and self.kinds[target] != LocationKind.HOSPITAL
                and self.pen_lot.get(target, lot) != lot):
            raise ValueError(f"incompatible lot at {target}: {lot}")
        if kind == EventKind.TRANSFER and (origin == target or self.kinds[target] not in TRANSFERS[self.kinds[origin]]):
            raise ValueError("ineligible internal movement")
        self.sequence += 1
        event_id = f"SYN-MOV-{self.sequence:09d}"
        row = AnimalEvent(event_id, key, kind, when, when, when, self.sequence,
                          Source("SYN-YARD-LEDGER", document or event_id, event_id), origin, target, reason=reason)
        self.events[event_id] = row
        self.emit("movement_events", [row], when)
        if origin is not None:
            self.intervals[key] = replace(self.active[key].interval, end_at=when, end_event_id=event_id)
            self.members[origin].remove(key)
            if not self.members[origin]:
                self.pen_lot.pop(origin, None)
        if target:
            self.members[target].add(key)
            if self.segregate_lots and self.kinds[target] != LocationKind.HOSPITAL:
                self.pen_lot[target] = lot
            self.peak[target] = max(self.peak[target], len(self.members[target]))
            self.intervals[key] = LocationInterval(key, self.animals[key].lot_id, target, when,
                                                   row.sequence, event_id)
            if key in self.active:
                self.active[key].interval = self.intervals[key]
        if kind in {EventKind.SALE, EventKind.DEATH}:
            self.exits[key] = row
            del self.active[key]
        return row

    def location_at(self, key, instant):
        row = self.intervals.get(key)
        if row and row.start_at <= instant and (row.end_at is None or instant < row.end_at):
            return row
        return None

    def enroll(self, key, pen, when, weight, age, prior_dof, cost, *, opening=None):
        kind = EventKind.OPENING if opening else EventKind.RECEIPT
        event = self.move(key, kind, when, pen, document=opening.source_document_id if opening else
                          f"{self.animals[key].lot_id}-{when.date()}-RECEIPT")
        self.entries[key] = event
        profile = make_profile(self, self.bio, key,
                               breed=self.trait(key, "breed", self.bio["biology"]["breed_factor"]),
                               sex=self.trait(key, "sex", self.bio["biology"]["sex_factor"]),
                               frame=self.trait(key, "frame", self.bio["biology"]["frame_factor"]),
                               entry_weight_kg=weight, entry_age_days=age)
        stay = self.draw.integer("receiving/stay", *self.config["receiving_days"], key)
        effective_day = business_date(when)
        # Openings happen at local noon before the first reporting day.
        next_weigh = self.first + self.draw.integer("weigh/follow-up-offset", 7, 15, key) * DAY if opening else (
            effective_day + self.draw.integer("weigh/follow-up-offset", 10, 19, key) * DAY)
        dof_origin = midnight(self.first) - prior_dof * DAY if opening else when
        live = Live(self.animals[key], event, self.intervals[key], profile,
                    dof_origin, None if opening else effective_day + stay * DAY,
                    next_weigh, weight_kg=weight)
        self.active[key] = live
        self.entry_costs[key] = cost
        self.emit("animal_profiles", [profile], when)
        return live

    def trait(self, key, name, choices):
        labels = sorted(choices)
        return labels[self.draw.integer(f"biology/{name}", 0, len(labels) - 1, key)]

    def stage(self, live, when):
        return production_stage(self.kinds[live.pen], live.production_age_origin, when,
                                self.bio["biology"]["adaptation_days"])

    def receive(self, day):
        when = at(day, 6, 30)
        wait, entered = [], []
        blocked = Counter()
        while self.future and self.future[0].requested_date <= day:
            self.backlog.append(self.future.popleft())
        for row in self.backlog:
            pen = self.pick(LocationKind.RECEIVING, pack=True, lot=row.lot_id)
            if not pen:
                wait.append(row)
                blocked[row.lot_id] += 1
                continue
            spread = 27 * (2 * self.draw("placement/weight", row.animal_id) - 1)
            kg = round(row.reference_kg + spread, 3)
            age = self.draw.integer("placement/age", 255, 365, row.animal_id)
            cost = round(kg * self.config["finance"]["purchase_cents_per_kg"])
            entered.append(self.enroll(row.animal_id, pen, when, kg, age, 0, cost))
        self.backlog = wait
        for lot, count in sorted(blocked.items()):
            self.exception(when, "receiving_full_rescheduled", lot, count)
        return entered

    def receiving_transfers(self, day, when):
        for key in sorted(self.active):
            live = self.active[key]
            if self.kinds[live.pen] != LocationKind.RECEIVING or day < live.receiving_until:
                continue
            pen = self.pick(LocationKind.PRODUCTION, pack=True, lot=live.lot)
            if pen:
                self.move(key, EventKind.TRANSFER, when, pen, reason="receiving_complete")
            else:
                self.exception(when, "production_full_rescheduled", key)

    def regroup(self, day, when):
        if self.segregate_lots or day.weekday() != self.config["regroup_weekday"]:
            return
        pens = [p for p in self.members if self.kinds[p] == LocationKind.PRODUCTION]
        heavy = max(pens, key=lambda p: (len(self.members[p]), p))
        light = self.pick(LocationKind.PRODUCTION, not_pen=heavy)
        if light and len(self.members[heavy]) > len(self.members[light]) + 4:
            candidates = sorted(self.members[heavy])
            for key in candidates[:min(2, self.capacity[light] - len(self.members[light]))]:
                self.move(key, EventKind.TRANSFER, when, light, reason="occupancy_regroup")

    @property
    def pending(self):
        return (*self.backlog, *self.future)

    def finalize(self):
        # The placement request owns a reserved tag. The physical master becomes visible only
        # on actual entry, which keeps rescheduled requests out of historical WIP/stock books.
        realized = [replace(self.animals[key], effective_at=row.effective_at, posted_at=row.posted_at,
                            available_at=row.available_at) for key, row in sorted(self.entries.items())]
        ledger = Ledger(self.ledger.config, self.ledger.lots.values(), realized, self.ledger.location_versions.values())
        ledger.ingest(self.events.values())
        self.emit("animals", realized)
        return ledger

    def context(self, instant, purpose, movement_ids):
        self.snapshot_id = stable_id("STAGE6-PHYSICAL", [self.run_id, instant, purpose, movement_ids])
        self.emit("physical_contexts", [PhysicalContext(
            self.snapshot_id, instant, purpose, sha256(canonical(movement_ids)), len(movement_ids))], instant)
        return SimpleNamespace(snapshot_id=self.snapshot_id)
