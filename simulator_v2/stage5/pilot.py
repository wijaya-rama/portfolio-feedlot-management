"""Estimate scheduling and storage envelopes with lot arithmetic only."""

import json
from datetime import date, timedelta
from math import ceil
from pathlib import Path


def plan(path=Path(__file__).with_name("pilot.json")):
    return json.loads(path.read_bytes())


def capacity(config):
    first, last = (date.fromisoformat(config[key]) for key in ("start", "end"))
    days = (last - first).days + 1
    group = config["heads_per_lot"]
    production = config["production"]
    receiving = config["receiving"]
    if config["placement_lots"] * group != config["placements"]:
        raise ValueError("placement arithmetic is inconsistent")
    arrivals = [n * config["lot_interval_days"] for n in range(config["placement_lots"])]
    carry_in_exits = [config["carry_in_first_exit_day"] + n * config["carry_in_exit_interval_days"]
                     for n in range(config["carry_in_lots"])]
    if arrivals[-1] >= days or max(carry_in_exits) >= days:
        raise ValueError("planned receiving or carry-in schedule outside horizon")
    results = []
    for stay in config["days_on_feed_scenarios"]:
        head_days = peak_yard = peak_production = peak_receiving = 0
        for day in range(days):
            yard = group * (sum(day <= end for end in carry_in_exits)
                            + sum(begin <= day <= begin + stay for begin in arrivals))
            on_receiving = group * sum(begin <= day < begin + receiving["days_per_lot"] for begin in arrivals)
            head_days += yard
            peak_yard = max(yard, peak_yard)
            peak_production = max(yard - on_receiving, peak_production)
            peak_receiving = max(on_receiving, peak_receiving)
        carry_out = group * sum(begin <= days - 1 < begin + stay for begin in arrivals)
        if (ceil(peak_production / group) > production["pens"] * (production["planning_max_per_pen"] // group)
                or peak_receiving > receiving["pens"] * receiving["capacity_per_pen"]):
            raise ValueError("planned lots exceed receiving or production envelope")
        results.append({
            "stay_elapsed_days": stay, "forecast_head_days_inclusive": head_days,
            "peak_concurrent_yard_head": peak_yard, "peak_production_before_hospital_transfers": peak_production,
            "peak_receiving_head": peak_receiving, "carry_out_head": carry_out,
            "completed_outcomes": config["placements"] + group * len(carry_in_exits) - carry_out,
            "allocation_window_rows_upper": head_days * len(config["feeding_windows_local"]),
            "allocation_slice_rows_per_method_estimate": head_days * config["feed_releases_per_full_head_day"],
        })
    high = max(row["peak_concurrent_yard_head"] for row in results)
    dm_high = config["feed_dm_kg_per_head_day_planning"][1]
    wet_low = config["feed_ration_dm_fraction_planning"][0]
    tonnes_day = high * dm_high / wet_low / 1000
    return {
        "calendar_days": days, "opening_head": group * len(carry_in_exits),
        "last_placement_day": first + timedelta(days=arrivals[-1]), "capacity_scenarios": results,
        "maximum_deliveries_before_split_loads": days * len(config["feeding_windows_local"])
        * sum(config[key]["pens"] for key in ("production", "receiving", "hospital")),
        "estimated_peak_as_fed_tonnes_per_day_before_losses": tonnes_day,
        "as_fed_tonnes_inbound_plus_buffer": tonnes_day * (
            config["fifo_inbound_cadence_days"] + config["fifo_buffer_days"]),
        "basis": "slot arithmetic; no cattle, events, journal or pilot dataset generated",
    }
