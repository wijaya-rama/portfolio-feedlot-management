"""Bounded Stage 5 nutrient integration over the current operational roster."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from ..stage1.model import midnight
from ..stage3.allocation import DEFAULT_METHOD
from ..stage3_5.biology import ChronologicalFeed
from ..stage5.biology import CalibratedBiology
from ..stage5.weather import Forecast, Weather, load_archive


@dataclass(frozen=True)
class WeatherSpan:
    path: str
    start_at: datetime
    end_at: datetime
    kind: str
    source_id: str
    mean_c: float


class Growth(CalibratedBiology):
    """Use the accepted Stage 5 flux update without retaining completed growth steps."""

    def __init__(self, yard, config, calibration, forcing, path, emit):
        self.yard = yard
        self.config = config
        self.calibration = calibration
        self.forcing = forcing
        self.emit = emit
        self.path = path
        self.start = midnight(yard.first)
        self.bounds = tuple(config["biology"]["weight_bounds_kg"])
        self.minimum_gain = config["biology"]["gain_bounds_kg_per_day"][0]
        self.reserves, self.weights = {}, {}
        self.adapter = ChronologicalFeed(DEFAULT_METHOD, len(config["feed_windows_local"]))
        self.weather_totals = Counter()

    def advance(self, first, last, *, window=None, allocations=(), clock=()):
        source_grid = (first, *self.forcing.points(first, last), last)
        for left, right in pairwise(source_grid):
            source = self.forcing.at(left)
            self.weather_totals[source.kind] += (right - left).total_seconds()
            self.emit("weather_exposure", [WeatherSpan(self.path, left, right, source.kind, source.source_id,
                                                      source.mean_c)], left)
        grid = sorted({*source_grid, *clock})
        self.adapter.add(allocations)
        snapshot = self.yard.context(first, self.path, [row.interval.start_event_id
                                                       for row in self.yard.active.values()])
        for live in self.yard.active.values():
            weight = self.weights.get(live.key, live.profile.entry_weight_kg)
            end_adaptation = live.production_age_origin + timedelta(days=self.config["biology"]["adaptation_days"])
            boundaries = grid if not first < end_adaptation < last else sorted([*grid, end_adaptation])
            health = live.clinical.last if live.clinical else None
            for start, end in pairwise(boundaries):
                if start == end:
                    continue
                weather = self.forcing.at(start)
                stage = self.yard.stage(live, start)
                step = self._advance(live.profile, snapshot, live.interval, start, end,
                                     max(self.start, live.entry.effective_at), stage, window, health,
                                     weather, weather.kind, weather.mean_c, weight, self.config)
                weight = step.end_weight_kg
                self.emit(f"growth_{self.path}", [step], start)
            self.weights[live.key] = weight
            if self.path == "operational":
                live.weight_kg = weight
        self.adapter.index.clear()

    def depart(self, key):
        self.weights.pop(key, None)
        self.reserves.pop(key, None)


def weather_inputs(config, calibration):
    policy = config["weather"]
    forecasts = [Forecast(row["source_id"], datetime.fromisoformat(row["day"]).date(),
                          datetime.fromisoformat(row["issued_at"]), datetime.fromisoformat(row["available_at"]),
                          row["mean_c"]) for row in policy["forecasts"]]
    fallback = calibration["stress"]["fallback_c_by_month"]
    operational = Weather("operational_as_of", fallback, forecasts=forecasts)
    archive, metadata = load_archive() if policy["retrospective"] else ((), None)
    retrospective = Weather("retrospective", fallback, archive=archive) if policy["retrospective"] else None
    return operational, retrospective, metadata
