"""Versioned integrated synthetic yard plans for the pilot and production release."""

from datetime import date, timedelta
import json

from .benchmark_configs import PLAN, format_config_json, stage6b1_config
from .config import HERE, validate

RELEASE_SIZES = (1500, 15000)


def release_config(size):
    if size not in RELEASE_SIZES:
        raise ValueError(f"release sizes are {RELEASE_SIZES}")
    plan = json.loads(PLAN.read_bytes())
    config = stage6b1_config(250)
    first, last = (date.fromisoformat(plan[key]) for key in ("start", "end"))
    stays = plan["days_on_feed_scenarios"]
    pilot = size == 1500
    lots, lot_head, opening_lots = (60, 25, 14) if pilot else (150, 100, 35)
    offsets = (range(0, lots * 12, 12) if pilot else
               [slot * (last - first).days // (lots - 1) for slot in range(lots)])
    schedule = [{"date": (first + timedelta(days=offset)).isoformat(), "head": lot_head,
                 "mean_kg": (352, 363, 374)[slot % 3], "minimum_dof": stays[slot % 3]}
                for slot, offset in enumerate(offsets)]
    carry = []
    for slot in range(opening_lots):
        remaining = (6 + 12 * slot) if pilot else (4 + 5 * slot)
        eligible = [stay for stay in stays if stay >= remaining]
        stay = eligible[slot % len(eligible)]
        prior_dof = stay - remaining
        carry.append({"head": lot_head, "location": f"SYN-P{slot + 1:02d}",
                      "weight_kg": round(363 + 0.96 * prior_dof, 1), "entry_age_days": 310 + prior_dof,
                      "days_on_feed": prior_dof, "minimum_dof": stay, "wip_cents": 158000 + 410 * prior_dof,
                      "status": "active", "source": f"SYN-2024-OPEN-{slot + 1:03d}"})
    capacity = ({"receiving": [30] * 2, "production": [30] * 23, "hospital": [16] * 2} if pilot else
                {"receiving": [115] * 3, "production": [115] * 57, "hospital": [20] * 4})
    config.update(version=f"stage7-{'pilot' if pilot else 'production'}-{size}.1",
                  start=plan["start"], end=plan["end"], placements=schedule, carry_in=carry,
                  capacities=capacity, required_placements=size, lot_segregation=True,
                  hospital_planning_head=plan["hospital"]["planning_max_total"] if pilot else 60)
    config["shipment"].update(maximum_head=70 if pilot else 285, late_draft_after_days=21,
                              late_threshold_kg=440, freight_cents=4250 if pilot else 3800)
    config["finance"]["yardage_cents"] = 125 if pilot else 110
    sizes = {"SILAGE": (65, 78, 52, 95), "BARLEY": (49, 58, 32, 72), "OATS": (16, 20, 10, 26)}
    fields = ("opening", "ordered", "reorder", "bin")
    warehouse = config["warehouse"]
    warehouse.update(design_head=550 if pilot else 5000, lead_days=3, split_receipt_delay_days=2,
                     equipment_g_af=5_000_000 if pilot else 8_000_000,
                     equipment_pairs=3 if pilot else 6, equipment_cycle_minutes=10,
                     max_supplier_daily_g_af=65_000_000 if pilot else 500_000_000)
    for row in warehouse["ingredients"]:
        row.update({f"{name}_grams_per_design_head": kg * 1000
                    for name, kg in zip(fields, sizes[row["code"]], strict=True)})
    validate(config)
    return config


def release_path(size):
    name = "pilot" if size == 1500 else "production"
    return HERE / "configs" / f"stage7-{name}-{size}.json"


if __name__ == "__main__":
    for size in RELEASE_SIZES:
        release_path(size).write_text(format_config_json(release_config(size)))
