"""Capacity and feed-supply checks without running the simulator or publishing data."""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
import json
from math import ceil

from ..stage1.model import midnight
from ..stage1.soh import calendar_days
from ..stage3.units import BPS
from ..stage3.warehouse import Kind
from .config import Draw, at, load, model
from .livestock import DAY
from .release_configs import RELEASE_SIZES, release_path
from .warehouse import Supply

BASE_MIX = {"finishing": 85, "adaptation": 10, "receiving": 4, "hospital": 1}
SILAGE_STRESS_MIX = {"finishing": 68, "adaptation": 25, "receiving": 6, "hospital": 1}


def capacity(config, weight_delay):
    """Hold every lot to an assumed threshold date, then apply the actual weekly caps.

    This deterministic schedule check assumes no mortality, clinical moves, or missed
    tickets. It reports a planning envelope for each chosen sale delay.
    """
    first, last = (date.fromisoformat(config[key]) for key in ("start", "end"))
    sale = config["shipment"]
    receiving_days = config["receiving_days"][1]
    receiving, production = [], []
    peak = Counter()
    sold = 0
    arrivals = {date.fromisoformat(row["date"]): row for row in config["placements"]}
    for row in config["carry_in"]:
        eligible = first + (row["minimum_dof"] - row["days_on_feed"] + weight_delay) * DAY
        production.append((eligible, row["head"]))
    for day in calendar_days(first, last):
        for _, eligible, head in [lot for lot in receiving if lot[0] == day]:
            production.append((eligible, head))
        receiving = [lot for lot in receiving if lot[0] > day]
        if day in arrivals:
            row = arrivals[day]
            receiving.append((day + receiving_days * DAY,
                              day + (row["minimum_dof"] + weight_delay) * DAY, row["head"]))
        for field, value in (
            ("production_pens", len(production)), ("receiving_pens", len(receiving)),
            ("concurrent_head", sum(row[-1] for row in production + receiving)),
        ):
            peak[field] = max(peak[field], value)
        if day.weekday() == sale["weekday"]:
            quota = sale["maximum_head"]
            remaining = []
            for eligible, head in sorted(production):
                count = min(quota, ceil(head * sale["lot_fraction"])) if day >= eligible else 0
                quota -= count
                sold += count
                if head > count:
                    remaining.append((eligible, head - count))
            production = remaining
    return {**peak, "sold": sold, "year_end_head": sum(row[-1] for row in production + receiving),
            "receiving_spare_pens": len(config["capacities"]["receiving"]) - peak["receiving_pens"],
            "production_spare_pens": len(config["capacities"]["production"]) - peak["production_pens"]}


def supply_capacity(config, seed, phases=BASE_MIX):
    """Drive actual PO, split receipts, assays, bins and FIFO with a high fixed demand."""
    first = date.fromisoformat(config["start"])
    last = first + 55 * DAY
    policy = config["warehouse"]
    design = policy["design_head"]
    supply = Supply(config, first, design, Draw(seed), lambda *args, **kwargs: None)
    demand = []
    for index, ingredient in enumerate(supply.masters.ingredients):
        mix_share = sum(policy["recipes"][phase][index] * percent for phase, percent in phases.items())
        demand.append((ingredient.ingredient_id, (design * 11_000 * mix_share + 999_999) // 1_000_000))
    peak_inbound = 0
    minima = {}
    for day in calendar_days(first, last):
        peak_inbound = max(peak_inbound, sum(row[2] for row in supply.inbound.get(day, ())))
        supply.day(day)
        for hour in (8, 15):
            when = at(day, hour)
            for key, daily in demand:
                grams = supply.grams_for_dm(key, (daily + 1) // 2, when)
                if grams is None:
                    raise ValueError(f"feed shortfall for {key} at {when}")
                supply.apply(Kind.ISSUE, when, supply.main[key], key, grams)
                balance = supply.state.bin_quantities[supply.main[key]]
                minima[key] = min(minima.get(key, balance), balance)
    _, replay = supply.finish(midnight(last + DAY), midnight(last + DAY))
    return {"demand_g_dm_per_day": dict(demand), "minimum_stock_g_af": minima,
            "peak_inbound_g_af": peak_inbound, "purchase_orders": len(supply.masters.orders),
            "receipts": len(replay.receipts), "lead_days": policy["lead_days"],
            "second_receipt_calendar_days": policy["lead_days"] + policy["split_receipt_delay_days"]}


def equipment_capacity(config):
    policy = config["warehouse"]
    bio, _ = model(config)
    max_dm = max(row["dm_kg_per_day"] for row in bio["rations"].values())
    min_dm = min(row["dm_bps"] - 175 for row in policy["ingredients"])
    # Mirror the conservative split threshold at a full pen and model all pens occupied.
    load = policy["equipment_g_af"] * min_dm // BPS - len(policy["ingredients"])
    maximum_loads = sum(ceil(pen * max_dm * 500 / load)
                        for group in config["capacities"].values() for pen in group)
    slots = 120 // policy["equipment_cycle_minutes"] * policy["equipment_pairs"]
    return {"max_loads_per_window": maximum_loads, "short_window_slots": slots}


def inspect(config):
    plan = {str(delay): capacity(config, delay) for delay in (0, 21, 35)}
    equipment = equipment_capacity(config)
    if (plan["21"]["production_spare_pens"] < 1 or plan["21"]["receiving_spare_pens"] < 1
            or plan["21"]["concurrent_head"] > config["warehouse"]["design_head"]
            or equipment["max_loads_per_window"] > equipment["short_window_slots"]):
        raise ValueError(f"insufficient headroom in {config['version']}: {plan}, {equipment}")
    stress = deepcopy(config)
    stress["warehouse"]["split_receipt_delay_days"] += 1
    return {"version": config["version"], "scheduled_receipts": config["required_placements"],
            "carry_in": sum(row["head"] for row in config["carry_in"]), "sale_delay_days": plan,
            "equipment": equipment, "supplier": {str(seed): supply_capacity(config, seed)
                                                for seed in (42, 171, 382, 901, 1009)},
            "silage_stress": supply_capacity(stress, 42, SILAGE_STRESS_MIX)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("size", type=int, choices=RELEASE_SIZES)
    args = parser.parse_args()
    print(json.dumps(inspect(load(release_path(args.size))), indent=2))


if __name__ == "__main__":
    main()
