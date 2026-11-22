"""Forward-only latent state. No observation or operational estimate is an input."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite

from ..stage1.model import business_date, is_utc, midnight
from ..stage1.soh import calendar_days
from .config import bounded, season, uniform
from .feed import TemporaryFeed, feeding_windows
from .timeline import production_stage

DAY = timedelta(days=1)


@dataclass(frozen=True)
class Profile:
    animal_id: str
    lot_id: str
    breed: str
    sex: str
    frame: str
    entry_weight_kg: float
    entry_age_days: int
    individual_factor: float
    lot_factor: float
    entry_event_id: str
    model_version: str
    synthetic: bool = True


@dataclass(frozen=True)
class WeatherDay:
    source_id: str
    day: date
    observed_at: datetime
    available_at: datetime
    scenario: str
    synthetic: bool = True


@dataclass(frozen=True)
class GrowthStep:
    animal_id: str
    lot_id: str
    start_at: datetime
    end_at: datetime
    location_id: str
    location_event_id: str
    production_stage: str
    age_at_start_days: float
    potential_adg_kg: float
    health_event_id: str | None
    health_burden: float
    weather_scenario: str
    weather_source_id: str | None
    start_weight_kg: float
    maintenance_loss_kg_per_day: float
    weight_before_feed_kg: float
    end_weight_kg: float
    window_start_at: datetime | None
    window_end_at: datetime | None
    access_fraction: float
    demand_g_dm: int
    consumed_g_dm: int
    energy_mj: float
    protein_kg: float
    feed_adapter_version: str
    biology_version: str
    physical_snapshot_id: str
    synthetic: bool = True


def make_profile(timeline, config, animal_id, *, breed, sex, frame, entry_weight_kg, entry_age_days):
    entry = timeline.entries[animal_id]
    lot_id = timeline.animals[animal_id].lot_id
    bio = config["biology"]

    def variation(stream, key, half_width):
        return 1 + half_width * (2 * uniform(timeline.seed, stream, key) - 1)

    return Profile(animal_id, lot_id, breed, sex, frame, entry_weight_kg, entry_age_days,
                   variation("biology-individual", animal_id, bio["individual_variation"]),
                   variation("biology-lot", lot_id, bio["lot_variation"]),
                   entry.event_id, config["biology_version"])


class Biology:
    def __init__(self, timeline, profiles, health, weather, config, *, adapter=None):
        streams = self._growth_streams(timeline, profiles, health, weather, config, adapter)
        self.steps_by_animal = {key: tuple(stream) for key, stream in streams.items()}
        self.start_times = {key: tuple(row.start_at for row in steps)
                            for key, steps in self.steps_by_animal.items()}
        self.steps = tuple(row for rows in self.steps_by_animal.values() for row in rows)

    def _growth_streams(self, timeline, profiles, health, weather, config, adapter):
        self.bounds = tuple(config["biology"]["weight_bounds_kg"])
        self.adapter = adapter if adapter is not None else TemporaryFeed(config)
        by_animal = defaultdict(list)
        for event in health:
            by_animal[event.animal_id].append(event)
        weather_by_day = {}
        for row in weather:
            if (row.day in weather_by_day or not row.source_id.startswith("SYN-")
                    or row.scenario not in config["weather"] or row.synthetic is not True
                    or not is_utc(row.observed_at) or not is_utc(row.available_at)
                    or row.available_at < row.observed_at or business_date(row.observed_at) != row.day):
                raise ValueError(f"invalid synthetic weather observation: {row.source_id}")
            weather_by_day[row.day] = row
        self.profiles = {row.animal_id: row for row in profiles}
        if len(self.profiles) != len(profiles) or self.profiles.keys() != timeline.entries.keys():
            raise ValueError("one biological profile is required for every effective entry")
        for key, profile in sorted(self.profiles.items()):
            self._validate_profile(profile, timeline, config)
        return {key: self._grow(self.profiles[key], timeline, by_animal[key], weather_by_day, config)
                for key in sorted(self.profiles)}

    def _additional_growth_points(self, windows):
        return ()

    def _weather_points(self, day, first, last, weather_rows):
        row = weather_rows.get(day)
        return (row.observed_at,) if row and first < row.observed_at < last else ()

    def _weather_at(self, day, start, weather_rows, config):
        row = weather_rows.get(day)
        if row and row.observed_at <= start:
            return row, row.scenario, config["weather"][row.scenario]
        key = season(day, config)
        return None, key, config["weather"][key]

    def _validate_profile(self, profile, timeline, config):
        bio = config["biology"]
        if (profile.lot_id != timeline.animals[profile.animal_id].lot_id
                or profile.entry_event_id != timeline.entries[profile.animal_id].event_id
                or profile.model_version != config["biology_version"] or profile.synthetic is not True
                or profile.breed not in bio["breed_factor"] or profile.sex not in bio["sex_factor"]
                or profile.frame not in bio["frame_factor"]
                or type(profile.entry_age_days) is not int or profile.entry_age_days <= 0
                or not self.bounds[0] <= profile.entry_weight_kg <= self.bounds[1]
                or not all(isfinite(value) and value > 0 for value in (
                    profile.individual_factor, profile.lot_factor))):
            raise ValueError(f"invalid biological profile for {profile.animal_id}")

    def _grow(self, profile, timeline, health, weather_rows, config):
        animal_id = profile.animal_id
        entered = timeline.entries[animal_id].effective_at
        stop = timeline.stop_at(animal_id)
        bio = config["biology"]
        weight = profile.entry_weight_kg
        active_health = None
        health = iter(event for event in health if event.effective_at < stop)
        next_health = next(health, None)
        adaptation_end = entered + bio["adaptation_days"] * DAY

        for day in calendar_days(business_date(entered), business_date(stop)):
            first, last = max(entered, midnight(day)), min(stop, midnight(day + DAY))
            if first >= last:
                continue
            windows = feeding_windows(day, config)
            points = {first, last}
            points.update(self._weather_points(day, first, last, weather_rows))
            points.update(point for window in windows for point in window if first < point < last)
            points.update(point for point in self._additional_growth_points(windows) if first < point < last)
            if first < adaptation_end < last:
                points.add(adaptation_end)
            points.update(row.start_at for row in timeline.intervals[animal_id]
                          if first < row.start_at < last)
            health_changes = {}
            while next_health and next_health.effective_at < last:
                health_changes[next_health.effective_at] = next_health
                points.add(next_health.effective_at)
                next_health = next(health, None)
            ordered = sorted(points)
            for start, end in zip(ordered, ordered[1:]):
                active_health = health_changes.get(start, active_health)
                applied_weather, weather_key, weather = self._weather_at(day, start, weather_rows, config)
                interval = timeline.location_at(animal_id, start)
                stage = production_stage(timeline.kinds[interval.location_id], entered, start,
                                         bio["adaptation_days"])
                window = next((pair for pair in windows if pair[0] <= start < pair[1]), None)
                step = self._advance(profile, timeline, interval, start, end, entered, stage, window,
                                     active_health, applied_weather, weather_key, weather, weight, config)
                yield step
                weight = step.end_weight_kg

    def _consume_feed(self, animal_id, location_id, *, start, end, window, stage,
                      start_weight_kg, health_burden, weather):
        return self.adapter.consume(start=start, end=end, window=window, stage=stage,
                                    start_weight_kg=start_weight_kg,
                                    health_burden=health_burden, weather=weather)

    def _advance(self, profile, timeline, interval, start, end, entered, stage, window,
                 health, weather_row, weather_key, weather, weight, config):
        bio = config["biology"]
        health_config = config["health"]
        burden = health.burden if health else 0.0
        age = profile.entry_age_days + (start - entered) / DAY
        maturity = bounded(1 - age / bio["maturity_age_days"], (bio["maturity_floor"], 1))
        potential = bio["reference_adg_kg"] * maturity * profile.individual_factor * profile.lot_factor
        potential *= (bio["breed_factor"][profile.breed] * bio["sex_factor"][profile.sex]
                      * bio["frame_factor"][profile.frame] * config["rations"][stage]["potential_factor"]
                      * (1 - burden * health_config["gain_penalty"]))
        gain_low, gain_high = bio["gain_bounds_kg_per_day"]
        potential = min(gain_high, potential)
        size = weight / bio["reference_weight_kg"]
        maintenance = (bio["maintenance_mj_at_reference"] * size**0.75
                       * weather["maintenance_factor"]
                       * (1 + burden * health_config["maintenance_surcharge"]))
        protein_maintenance = bio["cp_maintenance_kg_at_reference"] * size**0.75
        loss_rate = min(-gain_low, maintenance * bio["deficit_kg_per_mj"])
        before_feed = bounded(weight - loss_rate * ((end - start) / DAY), self.bounds)
        result = before_feed
        share = energy = protein = 0.0
        demand = consumed = 0
        if window:
            feed = self._consume_feed(
                profile.animal_id, interval.location_id, start=start, end=end, window=window,
                stage=stage, start_weight_kg=weight, health_burden=burden, weather=weather)
            share, energy, protein = feed.access_fraction, feed.energy_mj, feed.protein_kg
            demand, consumed = feed.demand_g_dm, feed.consumed_g_dm
            if (not 0 <= consumed <= demand or not 0 < share <= 1
                    or not all(isfinite(value) and value >= 0 for value in (energy, protein))
                    or (feed.start_at, feed.end_at) != (start, end)
                    or feed.adapter_version != self.adapter.version):
                raise ValueError("invalid feed adapter output")
            maintenance_credit = loss_rate * min(share, energy / maintenance)
            gain = max(0.0, min(potential * share,
                                (energy - maintenance * share) / bio["gain_mj_per_kg"],
                                (protein - protein_maintenance * share) / bio["gain_cp_kg_per_kg"]))
            result = bounded(before_feed + maintenance_credit + gain, self.bounds)
        return GrowthStep(
            profile.animal_id, profile.lot_id, start, end, interval.location_id,
            interval.start_event_id, stage, age, potential, health.health_event_id if health else None,
            burden, weather_key, weather_row.source_id if weather_row else None, weight, loss_rate,
            before_feed, result, window[0] if window else None, window[1] if window else None,
            share, demand, consumed, energy, protein, self.adapter.version, config["biology_version"],
            timeline.snapshot_id,
        )

    def weight_at(self, animal_id, instant):
        """Interpolate maintenance between steps. Feeding is credited at the segment close."""
        index = bisect_right(self.start_times.get(animal_id, ()), instant) - 1
        if index < 0:
            return None
        step = self.steps_by_animal[animal_id][index]
        if instant > step.end_at:
            return None
        if instant == step.end_at:
            return step.end_weight_kg
        return bounded(step.start_weight_kg - step.maintenance_loss_kg_per_day
                       * ((instant - step.start_at) / DAY), self.bounds)
