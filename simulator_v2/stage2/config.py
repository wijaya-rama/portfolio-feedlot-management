"""Versioned synthetic parameters and independently keyed random draws."""

import json
from pathlib import Path

from ..stage1.provenance import canonical, sha256

CONFIG_PATH = Path(__file__).with_name("scenario.json")


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_bytes())


def uniform(seed, stream, key):
    digest = sha256(canonical([seed, stream, key]))
    return int(digest[:13], 16) / 16**13


def bounded(value, bounds):
    low, high = bounds
    return min(high, max(low, value))


def season(day, config):
    month_day = day.month, day.day
    calendar = config["calendar"]
    cold = (month_day >= tuple(calendar["cold_start_month_day"])
            or month_day <= tuple(calendar["cold_end_month_day"]))
    return "cold" if cold else "neutral"
