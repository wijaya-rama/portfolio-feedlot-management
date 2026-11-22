"""Temporary feed demand and realized consumption by occupied feeding segment."""

from dataclasses import dataclass
from datetime import datetime, time

from ..stage1.model import EDMONTON, UTC


@dataclass(frozen=True)
class FeedSegment:
    start_at: datetime
    end_at: datetime
    access_fraction: float
    demand_g_dm: int
    consumed_g_dm: int
    energy_mj: float
    protein_kg: float
    adapter_version: str


def feeding_windows(day, config):
    return tuple(
        (datetime.combine(day, time(start), EDMONTON).astimezone(UTC),
         datetime.combine(day, time(end), EDMONTON).astimezone(UTC))
        for start, end in config["feed_windows_local"]
    )


class TemporaryFeed:
    """A pure adapter. Call with one occupied segment inside a feeding window."""

    def __init__(self, config):
        self.config = config
        self.version = config["feed_version"]

    def consume(self, *, start, end, window, stage, start_weight_kg, health_burden, weather):
        if not window[0] <= start < end <= window[1]:
            raise ValueError("feed segment must be contained in its window")
        windows_per_day = len(self.config["feed_windows_local"])
        share = (end - start) / (window[1] - window[0]) / windows_per_day
        ration = self.config["rations"][stage]
        demand = share * ration["dm_kg_per_day"]
        physical_limit = (share * start_weight_kg
                          * self.config["biology"]["intake_limit_bw_fraction"])
        appetite = 1 - health_burden * self.config["health"]["intake_penalty"]
        consumed = min(demand, physical_limit) * appetite * weather["intake_factor"]
        demand_g = round(demand * 1000)
        consumed_g = min(demand_g, round(consumed * 1000))
        dm_kg = consumed_g / 1000
        return FeedSegment(start, end, share, demand_g, consumed_g,
                           dm_kg * ration["energy_mj_per_kg_dm"],
                           dm_kg * ration["protein_fraction_dm"], self.version)
