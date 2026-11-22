"""Versioned Stage 6A inputs and deterministic random draws."""

import json
from datetime import date, datetime, time
from pathlib import Path

from ..stage1.model import EDMONTON, UTC
from ..stage2.config import load_config, uniform
from ..stage5.fixture import settings

HERE = Path(__file__).resolve().parent
DIAGNOSTIC = HERE / "configs/diagnostic.json"
SCHEMA = "stage6a.1"
MODEL = "stage6a-forward.1"


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), EDMONTON).astimezone(UTC)


def merge(target, overrides):
    for key, value in overrides.items():
        if key not in target:
            raise ValueError(f"unknown model parameter: {key}")
        if isinstance(target[key], dict):
            merge(target[key], value)
        else:
            target[key] = value


def load(path=DIAGNOSTIC, seed=None):
    config = json.loads(Path(path).read_bytes())
    if seed is not None:
        config["seed"] = seed
    validate(config)
    return config


def validate(config):
    first, last = (date.fromisoformat(config[field]) for field in ("start", "end"))
    if first > last or type(config["seed"]) is not int or not config["version"]:
        raise ValueError("invalid horizon, seed or version")
    caps = config["capacities"]
    if set(caps) != {"receiving", "production", "hospital"} or any(
        not pens or any(type(cap) is not int or cap < 1 for cap in pens) for pens in caps.values()
    ):
        raise ValueError("each location type needs positive integer capacities")
    if any(not first <= date.fromisoformat(row["date"]) <= last or type(row["head"]) is not int
           or row["head"] < 1 or not 207 <= row["mean_kg"] <= 873 for row in config["placements"]):
        raise ValueError("placement date, count or weight outside scenario range")
    if any(type(row["head"]) is not int or row["head"] < 1 or row["status"] != "active" or not row["source"].startswith("SYN-")
           or not 180 <= row["weight_kg"] <= 900 or row["wip_cents"] < 1
           or row["days_on_feed"] < 0 or row["entry_age_days"] <= row["days_on_feed"]
           for row in config["carry_in"]):
        raise ValueError("carry-in requires active status, weight, prior DOF and explicit WIP")
    lo, hi = config["receiving_days"]
    sale = config["shipment"]
    earliest, latest = sale["settlement_lag_days"]
    if (not 1 <= lo <= hi or config["follow_up_days"] < 1 or config["release_minutes"] < 1
            or not 0 <= sale["weekday"] <= 6 or not 0 < sale["lot_fraction"] <= 1
            or sale["maximum_head"] < 1 or not 0 <= sale["grade_missing_probability"] <= 1
            or not 1 <= earliest <= latest or sale["threshold_kg"] <= 0
            or sale["minimum_dof"] < 0 or not 0 <= sale["freight_cents"]
            or sale["grid_cents_per_kg"] <= 62
            or not 0 <= config["regroup_weekday"] <= 6):
        raise ValueError("invalid operations policy")
    health = config["health"]
    for field in ("severity_weights", "detection_daily", "untreated_death_daily",
                  "detected_death_daily", "recovery_daily"):
        if len(health[field]) != 3 or any(not 0 <= value <= 1 for value in health[field]):
            raise ValueError(f"invalid severity-specific probabilities: {field}")
    if abs(sum(health["severity_weights"]) - 1) > 1e-9:
        raise ValueError("severity probabilities must sum to one")
    for field in ("onset_daily", "background_death_daily", "treatment_probability",
                  "repeat_probability", "chronic_probability"):
        if not 0 <= health[field] <= 1:
            raise ValueError(f"invalid probability: {field}")
    if (min(health["receiving_multiplier"], health["post_recovery_multiplier"]) < 0
            or not 1 <= health["reassess_days"] < health["chronic_after_days"]):
        raise ValueError("invalid clinical schedule")
    if any(type(value) is not int or value < 0 for value in config["finance"].values()):
        raise ValueError("finance values must be nonnegative integer cents")
    if config["finance"]["purchase_cents_per_kg"] <= 0:
        raise ValueError("purchase basis must be positive")


def model(config):
    biology = load_config()
    biology["feed_windows_local"] = [[8, 11], [15, 17]]
    biology["sale_at_exit"] = True
    biology["biology_version"] = MODEL
    biology["observation_version"] = "stage6a-scale.1"
    biology["estimator_version"] = "stage6a-as-of.1"
    merge(biology, config["biology_overrides"])
    if biology["feed_windows_local"] != [[8, 11], [15, 17]]:
        raise ValueError("the operational schedule requires the 08–11 and 15–17 windows")
    calibration = settings()
    merge(calibration, config["calibration_overrides"])
    energy = calibration["maintenance"]
    if (not 0 < energy["maintenance_me_efficiency"] <= 1
            or not 0 < energy["gain_me_efficiency"] <= 1
            or not 0 <= energy["buffer_hours"] < energy["reserve_hours"] <= 24
            or any(value <= 0 for key, value in energy.items() if key != "buffer_hours")):
        raise ValueError("invalid nutrient reserve calibration")
    return biology, calibration


class Draw:
    def __init__(self, seed):
        self.seed = seed

    def __call__(self, stream, *key):
        return uniform(self.seed, f"stage6a/{stream}", "/".join(map(str, key)))

    def integer(self, stream, low, high, *key):
        return low + min(high - low, int(self(stream, *key) * (high - low + 1)))
