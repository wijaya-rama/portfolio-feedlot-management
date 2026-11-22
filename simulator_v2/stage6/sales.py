"""As-of drafting, partial shipments and separately measured synthetic grid settlements."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from ..stage1.model import EventKind, LocationKind
from ..stage2.estimation import assess_draft
from ..stage2.observations import Kind
from ..stage3.units import half_up
from .config import at
from .livestock import DAY

GRID_VERSION = "synthetic-ab-hcw-grid.1"
QUALITY_CENTS = {"Prime": 30, "AAA": 0, "AA": -20, "A": -40}
YIELD_CENTS = {"Y1": 12, "Y2": 5, "Y3": 0, "Y4": -10, "Y5": -22}


@dataclass(frozen=True)
class ShipmentLine:
    shipment_id: str
    sale_event_id: str
    animal_id: str
    lot_id: str
    draft_id: str
    effective_at: datetime
    days_on_feed: float
    synthetic: bool = True


@dataclass(frozen=True)
class Carcass:
    sale_event_id: str
    animal_id: str
    lot_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    liveweight_observation_id: str | None
    measured_liveweight_kg: float | None
    latent_exit_liveweight_kg: float
    dressing_fraction: float
    hcw_kg: float
    quality_grade: str | None
    yield_class: str | None
    grade_status: str
    model_version: str = "synthetic-carcass.1"
    synthetic: bool = True


@dataclass(frozen=True)
class PackerSettlement:
    sale_event_id: str
    animal_id: str
    settlement_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    grid_version: str
    hcw_kg: float
    base_cents_per_kg_hcw: int
    quality_delta_cents_per_kg_hcw: int
    yield_delta_cents_per_kg_hcw: int
    final_cents_per_kg_hcw: int
    premium_cents: int
    discount_cents: int
    freight_cents: int
    provisional_cents: int
    final_cents: int
    adjustment_cents: int
    synthetic: bool = True


class Sales:
    def __init__(self, yard, weights, emit):
        self.yard, self.weights, self.emit = yard, weights, emit
        self.policy = yard.config["shipment"]
        self.lines, self.carcasses, self.settlements = {}, {}, {}

    def draft(self, day, when):
        if day.weekday() != self.policy["weekday"]:
            return []
        due = [live for live in self.yard.active.values()
               if self.yard.kinds[live.pen] == LocationKind.PRODUCTION
               and (when - live.production_age_origin) / DAY >= self.policy["minimum_dof"]]
        if not due:
            return []
        _, estimates = self.weights.freeze(when, due)
        groups = defaultdict(list)
        head = defaultdict(int)
        decisions = []
        for live in sorted(self.yard.active.values(), key=lambda row: row.key):
            head[live.lot] += 1
        for live in sorted(due, key=lambda row: row.key):
            estimate = estimates[live.key]
            draft = assess_draft(estimate, self.policy["threshold_kg"])
            decisions.append(draft)
            if draft.status == "selected":
                groups[live.lot].append((live, draft, estimate.estimated_liveweight_kg))
                self.weights.weigh(live, when, Kind.DRAFTING)
        self.emit("draft_decisions", decisions, when)
        candidates = []
        for lot, rows in sorted(groups.items()):
            rows.sort(key=lambda item: (-item[2], item[0].key))
            cap = ceil(head[lot] * self.policy["lot_fraction"])
            candidates.extend(rows[:cap])
        candidates.sort(key=lambda item: (-item[2], item[0].key))
        return candidates[:self.policy["maximum_head"]]

    def ship(self, day, when, candidates):
        shipment = f"SYN-SHIP-{day:%Y%m%d}"
        for live, draft, operational_kg in candidates:
            event = self.yard.move(live.key, EventKind.SALE, when, reason="drafted_for_synthetic_grid",
                                   document=shipment)
            observation = self.weights.weigh(live, when, Kind.FINAL_SALE, event)
            dof = (when - live.production_age_origin) / DAY
            line = ShipmentLine(shipment, event.event_id, live.key, live.lot, draft.draft_id, when, dof)
            carcass, settlement = self.grid(day, live, event, observation, dof, operational_kg)
            self.lines[live.key], self.carcasses[live.key], self.settlements[live.key] = line, carcass, settlement
            self.emit("shipment_lines", [line], when)
            self.emit("carcasses", [carcass], when)
            self.emit("packer_settlements", [settlement], when)

    def grid(self, day, live, event, observation, dof, operational_kg):
        p, draw, key = self.policy, self.yard.draw, live.key
        finish = min(dof, 160) / 160 + 0.12 * (live.profile.sex == "heifer")
        finish += 0.09 * (live.profile.breed == "Angus-cross") + 0.40 * draw("carcass/finish", key)
        dressing = round(min(0.64, max(0.55, 0.557 + 0.044 * finish + 0.028 * draw("carcass/dressing", key))), 5)
        hcw = round(live.weight_kg * dressing, 1)
        marbling = finish + 0.63 * draw("carcass/marbling", key)
        quality = "Prime" if marbling > 1.23 else "AAA" if marbling > 0.86 else "AA" if marbling > 0.57 else "A"
        lean = 0.75 * draw("carcass/yield", key) - 0.62 * finish + 0.12 * (live.profile.frame == "large")
        yield_class = f"Y{1 + sum(lean < point for point in (0.42, 0.20, -0.03, -0.25))}"
        missing = draw("carcass/missing", key) < p["grade_missing_probability"]
        if missing:
            quality = yield_class = None
        observed = event.effective_at
        posted = observed + 4 * DAY / 24
        base = p["grid_cents_per_kg"]
        q_delta, y_delta = QUALITY_CENTS.get(quality, 0), YIELD_CENTS.get(yield_class, 0)
        hcw_tenths = round(hcw * 10)
        premium = half_up(hcw_tenths * (max(0, q_delta) + max(0, y_delta)), 10)
        discount = half_up(hcw_tenths * (-min(0, q_delta) - min(0, y_delta)), 10)
        final = half_up(hcw_tenths * base, 10) + premium - discount - p["freight_cents"]
        provisional = round(operational_kg * 0.60 * base) - p["freight_cents"]
        lag = draw.integer("carcass/settlement-lag", *p["settlement_lag_days"], key)
        available = at(day + lag * DAY, 10)
        return (
            Carcass(event.event_id, key, live.lot, observed, posted, posted,
                    observation.observation_id if observation else None,
                    observation.measured_weight_kg if observation else None,
                    round(live.weight_kg, 6), dressing, hcw, quality, yield_class,
                    "missing_synthetic_ticket" if missing else "synthetic_grid_grade"),
            PackerSettlement(event.event_id, key, f"{event.event_id}-FINAL", observed, available, available,
                             GRID_VERSION, hcw, base, q_delta, y_delta, base + q_delta + y_delta,
                             premium, discount, p["freight_cents"], provisional, final, final - provisional),
        )
