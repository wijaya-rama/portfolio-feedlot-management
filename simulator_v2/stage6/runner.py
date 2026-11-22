"""Forward scheduler. All generated physical movements occur between feeding windows."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from ..stage1.model import EventKind, midnight
from ..stage1.provenance import stable_id
from ..stage1.soh import calculate_soh, calendar_days
from ..stage1.validation import reject_failures
from ..stage2.feed import feeding_windows
from ..stage2.timeline import PhysicalTimeline
from ..stage3.warehouse import bridges
from ..stage3_5.reconciliation import dm_bridges
from ..stage4.fixture import YardageDay
from ..stage4.ledger import periods
from .biology import Growth, weather_inputs
from .config import Draw, at, model, validate
from .feeding import Feeding
from .finance import Finance, YARDAGE_TARIFF
from .health import Health
from .livestock import DAY, TICK, Yard
from .sales import Sales
from .warehouse import Supply
from .weights import Weights


@dataclass(frozen=True)
class Terminal:
    animal_id: str
    lot_id: str
    status: str
    location_id: str | None
    movement_event_id: str
    days_on_feed: float
    simulated_days: float
    latent_weight_kg: float
    retrospective_weight_kg: float | None
    entry_weight_kg: float
    synthetic: bool = True


class Runner:
    def __init__(self, config, run_id, writer, *, retain_yardage=True):
        validate(config)
        self.config, self.writer = config, writer
        self.emit = writer.emit
        self.first, self.last = (date.fromisoformat(config[key]) for key in ("start", "end"))
        self.start, self.end = midnight(self.first), midnight(self.last + DAY)
        self.calendar = periods(self.first, self.last)
        self.cutoff = self.end + (max(config["shipment"]["settlement_lag_days"]) + 4) * DAY
        self.bio, self.calibration = model(config)
        self.draw = Draw(config["seed"])
        self.yard = Yard(config, self.first, self.last, run_id, self.bio, self.draw, self.emit)
        self.weights = Weights(self.yard, self.emit, self.calendar[0].locked_at if len(self.calendar) > 1 else None)
        design_head = config["warehouse"].get("design_head", sum(self.yard.capacity.values()))
        self.supply = Supply(config, self.first, design_head, self.draw, self.emit)
        self.health = Health(config, self.yard, self.emit, self.weights.weigh)
        self.sales = Sales(self.yard, self.weights, self.emit)
        self.feeding = Feeding(self.yard, self.supply, self.weights, config, self.calibration, self.emit,
                               writer.root.parent / "feed-accounting-checkpoints.pickle")
        op, retro, self.archive = weather_inputs(config, self.calibration)
        self.operational = Growth(self.yard, self.bio, self.calibration, op, "operational", self.emit)
        self.retro = Growth(self.yard, self.bio, self.calibration, retro, "retrospective", self.emit) if retro else None
        self.yardage = [] if retain_yardage else None
        self.terminal = []
        self.daily_active = Counter()

    def growth(self, first, last, **kwargs):
        self.operational.advance(first, last, **kwargs)
        if self.retro:
            self.retro.advance(first, last, **kwargs)

    def terminal_row(self, live, when, status, event):
        row = Terminal(live.key, live.lot, status, live.pen if status == "active" else None, event,
                       (when - live.production_age_origin) / DAY,
                       (when - max(live.entry.effective_at, self.start)) / DAY,
                       round(live.weight_kg, 6),
                       round(self.retro.weights.get(live.key, live.profile.entry_weight_kg), 6) if self.retro else None,
                       live.profile.entry_weight_kg)
        self.terminal.append(row)
        self.emit("animal_outcomes", [row], when - TICK)
        if status != "active":
            self.operational.depart(live.key)
            if self.retro:
                self.retro.depart(live.key)
            self.weights.depart(live.key)

    def opening(self):
        when = at(self.first - DAY, 12)
        for row in self.yard.opening:
            if row.location_id not in self.yard.kinds:
                raise ValueError(f"opening bin does not exist: {row.location_id}")
            live = self.yard.enroll(row.animal_id, row.location_id, when, row.weight_kg, row.entry_age_days,
                                    row.prior_dof, row.wip_cents, opening=row)
            self.weights.weigh(live, when, "opening", live.entry)
            if self.yard.kinds[live.pen] == "receiving":
                live.receiving_until = self.first + self.config["receiving_days"][0] * DAY

    def day(self, day):
        yard = self.yard
        seen = dict(yard.active)
        midnight_today = midnight(day)
        clinical_at, receiving_at = at(day, 6), at(day, 6, 30)
        noon, sale_at = at(day, 12), at(day, 13)
        finish = midnight(day + DAY)
        self.supply.day(day)
        self.growth(midnight_today, clinical_at)
        # A death removes the live roster record, while `seen` retains its day-service reference.
        self.health.day(day, clinical_at)
        for key in sorted(seen.keys() - yard.active.keys()):
            self.terminal_row(seen[key], clinical_at, "dead", yard.exits[key].event_id)
        yard.receiving_transfers(day, clinical_at)
        yard.regroup(day, clinical_at)
        self.growth(clinical_at, receiving_at)
        for live in yard.receive(day):
            seen[live.key] = live
            self.weights.weigh(live, receiving_at, "receiving", live.entry)
        (am_start, am_end), (pm_start, pm_end) = feeding_windows(day, self.bio)
        self.growth(receiving_at, am_start)
        self.feeding_window(am_start, am_end)
        follow_up = at(day, 11, 45)
        self.growth(am_end, follow_up)
        self.weights.follow_up(day, follow_up)
        self.growth(follow_up, noon)
        drafts = self.sales.draft(day, noon)
        self.growth(noon, sale_at)
        self.sales.ship(day, sale_at, drafts)
        for live, _, _ in drafts:
            self.terminal_row(live, sale_at, "sold", yard.exits[live.key].event_id)
        self.growth(sale_at, pm_start)
        self.feeding_window(pm_start, pm_end)
        self.growth(pm_end, finish)
        self.feeding.checkpoint()
        self.daily_active[day] = len(seen)
        for key, live in sorted(seen.items()):
            exit_event = yard.exits.get(key)
            row = YardageDay(day, key, live.lot, live.pen,
                             exit_event.event_id if exit_event else live.interval.start_event_id,
                             exit_event.effective_at if exit_event else finish - TICK,
                             YARDAGE_TARIFF, self.config["finance"]["yardage_cents"])
            if self.yardage is not None:
                self.yardage.append(row)
            self.emit("yardage", [row], day)

    def feeding_window(self, start, end):
        allocations, clock = self.feeding.window(start, end)
        self.growth(start, end, window=(start, end), allocations=allocations, clock=clock)

    def operations(self):
        self.opening()
        self.emit("weather_forecasts", self.operational.forcing.forecasts.values(), partition_by="issued_at")
        for day in calendar_days(self.first, self.last):
            self.day(day)
            # Retain current/last month because the scale correction shares its origin partition.
            boundary = (day.replace(day=1) - DAY).strftime("%Y-%m")
            self.writer.finalize_months(boundary)
        for live in self.yard.active.values():
            self.terminal_row(live, self.end, "active", live.interval.start_event_id)
        for requested in self.yard.pending:
            self.yard.exception(self.end - TICK, "placement_unfulfilled_at_horizon", requested.animal_id)
        ledger = self.yard.finalize()
        warehouse, wh = self.supply.finish(self.end, self.cutoff)
        self.warehouse_snapshot = wh
        timeline = PhysicalTimeline(ledger, self.end, self.cutoff)
        result, daily, monthly, checks = calculate_soh(ledger, self.first, self.last, self.cutoff)
        reject_failures(checks)
        self.emit("physical_intervals", result.intervals, partition_by="start_at")
        self.emit("daily_soh", daily, partition_by="period_start")
        self.emit("monthly_soh", monthly, partition_by="period_start")
        stock_bridges = tuple(bridges(wh, (self.start, *(row.effective_before for row in self.calendar))))
        operations = SimpleNamespace(mixes=[], mix_inputs=[], deliveries=[], settlements=[],
                                     schedule=SimpleNamespace(bunk_tickets=[]))
        operations.ledger, operations.timeline, operations.health = ledger, timeline, self.health.events
        operations.warehouse, operations.warehouse_snapshots = warehouse, (wh,)
        operations.stock_bridges, operations.approvals = stock_bridges, ()
        self.warehouse_stock_bridges = stock_bridges
        self.emit("warehouse_af_bridge", stock_bridges, partition_by="period_start")
        self.emit("warehouse_dm_bridge", dm_bridges(operations), partition_by="period_start")
        return operations, result, daily, monthly, checks

    def finance(self, operations):
        finance = Finance(self.yard, operations, self.sales, self.yardage, self.config, self.first, self.last,
                          self.cutoff, self.emit, self.feeding.read_checkpoints(),
                          self.writer.root.parent / "finance.sqlite")
        self.financial_approvals = tuple(finance.approvals)
        try:
            return tuple(finance.books(self.cutoff))
        finally:
            finance.store.close()
