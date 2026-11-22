"""Summarize physical flows, variance and the one selected WIP cost basis."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from ..stage1.model import business_date
from ..stage1.provenance import stable_id
from .allocation import Method
from .ration import FeedAmount, add_amounts


@dataclass(frozen=True)
class ActiveSettlement:
    delivery_id: str
    settlement_id: str
    method: Method


@dataclass(frozen=True)
class WipCandidate:
    candidate_id: str
    allocation_id: str
    settlement_id: str
    delivery_id: str
    mix_id: str
    animal_id: str
    lot_id: str
    pen_id: str
    service_date: date
    access_end: datetime
    available_at: datetime
    g_dm: int
    provisional_cents: int


@dataclass(frozen=True)
class FeedBridge:
    period: str
    issue: FeedAmount
    mixed: FeedAmount
    mix_loss: FeedAmount
    loaded: FeedAmount
    delivered: FeedAmount
    delivery_loss: FeedAmount
    consumed: FeedAmount
    refusal: FeedAmount
    bunk_loss: FeedAmount
    selected_allocation_g_dm: int
    selected_allocation_cents: int


def active_settlements(fixture):
    method = Method(fixture.scenario["method"])
    return tuple(ActiveSettlement(row.row.delivery_id, row.row.settlement_id, method)
                 for row in fixture.active_settlements)


def wip_candidates(fixture):
    method = Method(fixture.scenario["method"])
    return tuple(
        WipCandidate(stable_id("WIP-CANDIDATE", row.allocation_id), row.allocation_id, row.settlement_id,
                     row.delivery_id, row.mix_id, row.animal_id, row.lot_id, row.pen_id,
                     business_date(row.window_start), row.access_end, row.available_at, row.g_dm, row.cents)
        for settlement in fixture.active_settlements for row in settlement.allocations
        if row.method == method and (row.g_dm or row.cents))


def feed_bridges(fixture, candidates):
    groups = defaultdict(lambda: defaultdict(list))
    for mix in fixture.mixes:
        period = business_date(mix.effective_at).strftime("%Y-%m")
        for key in (period, "horizon"):
            groups[key]["issue"].append(mix.input)
            groups[key]["mixed"].append(mix.produced)
            groups[key]["mix_loss"].append(mix.loss)
    settlements = {row.row.delivery_id: row.row for row in fixture.active_settlements}
    for delivery in fixture.deliveries:
        period = business_date(delivery.effective_at).strftime("%Y-%m")
        settlement = settlements[delivery.delivery_id]
        for key in (period, "horizon"):
            values = groups[key]
            values["loaded"].append(delivery.loaded)
            values["delivered"].append(delivery.delivered)
            values["delivery_loss"].append(delivery.delivery_loss)
            values["consumed"].append(settlement.modeled_consumption)
            values["refusal"].append(settlement.refusal)
            values["bunk_loss"].append(settlement.bunk_loss)
    for row in candidates:
        for key in (row.service_date.strftime("%Y-%m"), "horizon"):
            groups[key]["selected"].append(row)
    columns = ("issue", "mixed", "mix_loss", "loaded", "delivered", "delivery_loss",
               "consumed", "refusal", "bunk_loss")
    return tuple(FeedBridge(key, *(add_amounts(values[column]) for column in columns),
                            sum(row.g_dm for row in values["selected"]),
                            sum(row.provisional_cents for row in values["selected"]))
                 for key, values in sorted(groups.items()))
