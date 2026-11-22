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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placements", type=int, choices=SIZES)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = benchmark_config(args.placements, args.seed)
    # Each placement and opening cohort stays on one line for review.
    text = json.dumps(config, indent=2)
    for key in ("placements", "carry_in"):
        start = text.index(f'  "{key}": [')
        end = text.index("\n  ],", start)
        cohorts = ",\n".join("    " + json.dumps(row) for row in config[key])
        text = text[:start] + f'  "{key}": [\n{cohorts}' + text[end:]
    args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
