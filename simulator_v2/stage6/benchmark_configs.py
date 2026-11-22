"""Materialize the Stage 5 schedule at the four Stage 6B benchmark scales."""

import argparse
from datetime import date, timedelta
import json
from math import ceil
from pathlib import Path

from .config import HERE, load, validate

SIZES = (25, 100, 250, 500)
PLAN = HERE.parent / "stage5" / "pilot.json"
CONFIGS = HERE / "configs"


def scaled_counts(total, slots):
    """Spread integer head counts across the source schedule without rounding away throughput."""
    return [((slot + 1) * total + slots // 2) // slots - (slot * total + slots // 2) // slots
            for slot in range(slots)]


def benchmark_config(placements, seed=None):
    if placements not in SIZES:
        raise ValueError(f"preflight sizes are {SIZES}")
    plan = json.loads(PLAN.read_bytes())
    config = load(seed=plan["seeds"][0] if seed is None else seed)
    first = date.fromisoformat(plan["start"])
    stays = plan["days_on_feed_scenarios"]
    ratio = placements / plan["placements"]
    caps = {name: [ceil(plan[name]["capacity_per_pen"] * ratio)] * plan[name]["pens"]
            for name in ("receiving", "production", "hospital")}
    arrival_counts = scaled_counts(placements, plan["placement_lots"])
    opening_heads = round(plan["carry_in_lots"] * plan["heads_per_lot"] * ratio)
    open_counts = scaled_counts(opening_heads, plan["carry_in_lots"])
    schedule = [
        {"date": (first + timedelta(days=slot * plan["lot_interval_days"])).isoformat(),
         "head": head, "mean_kg": (352, 363, 374)[slot % 3], "minimum_dof": stays[slot % len(stays)]}
        for slot, head in enumerate(arrival_counts) if head
    ]
    carry_in = []
    used = [0] * len(caps["production"])
    for slot, head in enumerate(open_counts):
        if not head:
            continue
        # Match the proposed opening exit cadence using an earlier synthetic receipt.
        remaining = plan["carry_in_first_exit_day"] + slot * plan["carry_in_exit_interval_days"]
        eligible_stays = [stay for stay in stays if stay >= remaining]
        stay = eligible_stays[slot % len(eligible_stays)]
        prior_dof = stay - remaining
        pen = min(range(len(used)), key=used.__getitem__)
        used[pen] += head
        if used[pen] > caps["production"][pen]:
            raise ValueError("scaled carry-in exceeds its planned production capacity")
        carry_in.append({"head": head, "location": f"SYN-P{pen + 1:02d}",
                         "weight_kg": round(363 + 0.96 * prior_dof, 1), "entry_age_days": 310 + prior_dof,
                         "days_on_feed": prior_dof, "minimum_dof": stay, "wip_cents": 158000 + 410 * prior_dof,
                         "status": "active", "source": f"SYN-PREFLIGHT-OPEN-2024-{slot + 1:02d}"})
    config.update(version=f"stage6b-preflight-{placements}.1", start=plan["start"], end=plan["end"],
                  placements=schedule, carry_in=carry_in, capacities=caps,
                  receiving_days=[2, 4], release_minutes=30)
    config["shipment"].update(minimum_dof=stays[1], threshold_kg=490, lot_fraction=.65,
                              maximum_head=max(2, ceil(75 * ratio)))
    config["warehouse"].update(order_cycle_days=plan["fifo_inbound_cadence_days"], lead_days=5,
                               split_receipt_delay_days=2, opening_grams_per_design_head=58000,
                               ordered_grams_per_design_head=64000, bin_grams_per_design_head=105000,
                               equipment_g_af=5000000)
    validate(config)
    return config


STAGE6B1_BASELINE_HEALTH = {
    "scenario_version": "stage6b1-baseline-health.1",
    "recovery_basis": "daily_compounded",
    "onset_daily": 0.0022,
    "receiving_multiplier": 3.5,
    "post_recovery_multiplier": 2.0,
    "severity_weights": [0.60, 0.30, 0.10],
    "detection_daily": [0.40, 0.70, 0.90],
    "untreated_death_daily": [0.0002, 0.0025, 0.025],
    "detected_death_daily": [0.0001, 0.0010, 0.010],
    "chronic_death_daily": 0.0015,
    "background_death_daily": 0.00004,
    "recovery_daily": [0.38, 0.24, 0.14],
    "treatment_probability": 0.85,
    "repeat_probability": 0.35,
    "chronic_probability": 0.30,
    "reassess_days": 2,
    "chronic_after_days": 9,
}

STAGE6B1_HEALTH_SENSITIVITY_RANGES = {
    "onset_daily": [0.0015, 0.0040],
    "receiving_multiplier": [2.5, 4.5],
    "detected_death_daily_severe": [0.005, 0.020],
    "untreated_death_daily_severe": [0.015, 0.045],
    "chronic_death_daily": [0.0008, 0.0030],
    "background_death_daily": [0.00002, 0.00007],
}

MATERIAL_SPECIFIC_SUPPLY = {
    "SILAGE": {
        "opening_grams_per_design_head": 115000,
        "ordered_grams_per_design_head": 130000,
        "reorder_grams_per_design_head": 95000,
        "bin_grams_per_design_head": 180000,
    },
    "BARLEY": {
        "opening_grams_per_design_head": 70000,
        "ordered_grams_per_design_head": 80000,
        "reorder_grams_per_design_head": 58000,
        "bin_grams_per_design_head": 115000,
    },
    "OATS": {
        "opening_grams_per_design_head": 22000,
        "ordered_grams_per_design_head": 26000,
        "reorder_grams_per_design_head": 18000,
        "bin_grams_per_design_head": 45000,
    },
}


def stage6b1_config(placements, seed=None, *, health_scenario="baseline", supply_policy="material_specific"):
    """Build a Stage 6B.1 benchmark config with versioned health and supply policies."""
    config = benchmark_config(placements, seed)
    if health_scenario == "baseline":
        config["health"] = dict(STAGE6B1_BASELINE_HEALTH)
    elif health_scenario == "adverse":
        config["health"] = {
            **config["health"],
            "scenario_version": "stage6b-adverse-health.1",
            "recovery_basis": "per_reassessment",
        }
    else:
        raise ValueError(f"unknown health_scenario: {health_scenario}")
    if supply_policy == "material_specific":
        for ing in config["warehouse"]["ingredients"]:
            ing.update(MATERIAL_SPECIFIC_SUPPLY[ing["code"]])
    elif supply_policy != "uniform":
        raise ValueError(f"unknown supply_policy: {supply_policy}")
    label = f"{health_scenario}" if supply_policy == "material_specific" else f"{health_scenario}-{supply_policy}"
    config["version"] = f"stage6b1-{label}-{placements}.1"
    validate(config)
    return config


def format_config_json(config):
    # Each placement and opening cohort stays on one line for review.
    text = json.dumps(config, indent=2)
    for key in ("placements", "carry_in"):
        start = text.index(f'  "{key}": [')
        end = text.index("\n  ],", start)
        cohorts = ",\n".join("    " + json.dumps(row) for row in config[key])
        text = text[:start] + f'  "{key}": [\n{cohorts}' + text[end:]
    return text + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placements", type=int, choices=SIZES)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--profile", choices=("stage6b", "stage6b1-baseline", "stage6b1-adverse"), default="stage6b")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.profile == "stage6b":
        config = benchmark_config(args.placements, args.seed)
    elif args.profile == "stage6b1-baseline":
        config = stage6b1_config(args.placements, args.seed, health_scenario="baseline", supply_policy="material_specific")
    else:
        config = stage6b1_config(args.placements, args.seed, health_scenario="adverse", supply_policy="material_specific")
    args.output.write_text(format_config_json(config))


if __name__ == "__main__":
    main()
