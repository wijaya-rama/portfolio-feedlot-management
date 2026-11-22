"""Credit physical feed once, then spend nutrients forward in elapsed time."""

from bisect import bisect_right
from dataclasses import dataclass
from math import isfinite

from ..stage2.biology import DAY, GrowthStep
from ..stage2.config import bounded
from ..stage3_5.biology import ChronologicalBiology


@dataclass(frozen=True)
class NutrientStep(GrowthStep):
    weather_kind: str = ""
    temperature_c: float = 0.0
    elapsed_days: float = 0.0
    maintenance_required_me_mj: float = 0.0
    maintenance_used_me_mj: float = 0.0
    gain_used_me_mj: float = 0.0
    starting_me_mj: float = 0.0
    ending_me_mj: float = 0.0
    excess_me_mj: float = 0.0
    cp_maintenance_used_kg: float = 0.0
    cp_gain_used_kg: float = 0.0
    starting_cp_kg: float = 0.0
    ending_cp_kg: float = 0.0
    excess_cp_kg: float = 0.0
    gain_kg: float = 0.0
    loss_kg: float = 0.0


class CalibratedBiology(ChronologicalBiology):
    def __init__(self, timeline, profiles, health, config, *, adapter, clock, forcing, calibration):
        self.forcing = forcing
        self.calibration = calibration
        self.reserves = {}
        self.minimum_gain = config["biology"]["gain_bounds_kg_per_day"][0]
        super().__init__(timeline, profiles, health, (), config, adapter=adapter, clock=clock)

    def _weather_points(self, day, first, last, weather_rows):
        return self.forcing.points(first, last)

    def _weather_at(self, day, start, weather_rows, config):
        row = self.forcing.at(start)
        return row, row.kind, row.mean_c

    def _fluxes(self, weight, elapsed, potential, rates, reserves):
        energy = self.calibration["maintenance"]
        maintenance_me, maintenance_cp = rates
        reserve_me, reserve_cp = reserves
        need = maintenance_me * elapsed
        used_me = min(reserve_me, need)
        used_cp = min(reserve_cp, maintenance_cp * elapsed)
        buffer = energy["buffer_hours"] / 24
        gain_me_per_kg = energy["net_gain_mj_per_kg_live"] / energy["gain_me_efficiency"]
        gain = min(potential * elapsed,
                   max(0.0, reserve_me - used_me - maintenance_me * buffer) / gain_me_per_kg,
                   max(0.0, reserve_cp - used_cp - maintenance_cp * buffer) / energy["cp_per_kg_gain"],
                   self.bounds[1] - weight)
        loss = min(-self.minimum_gain * elapsed, (need - used_me) * energy["deficit_kg_per_mj_me"],
                   weight - self.bounds[0])
        return used_me, used_cp, gain, loss

    def _advance(self, profile, timeline, interval, start, end, entered, stage, window,
                 health, weather_row, weather_key, temperature, weight, config):
        bio, clinical = config["biology"], config["health"]
        energy, stress = self.calibration["maintenance"], self.calibration["stress"]
        elapsed = (end - start) / DAY
        age = profile.entry_age_days + (start - entered) / DAY
        burden = health.burden if health else 0.0
        heat = min(stress["max_heat_gain_penalty"],
                   max(0.0, temperature - stress["heat_reference_c"]) * stress["heat_gain_penalty_per_c"])
        cold = min(stress["max_cold_surcharge"],
                   max(0.0, stress["cold_reference_c"] - temperature) * stress["cold_maintenance_per_c"])
        maturity = bounded(1 - age / bio["maturity_age_days"], (bio["maturity_floor"], 1))
        potential = (bio["reference_adg_kg"] * maturity * profile.individual_factor * profile.lot_factor
                     * bio["breed_factor"][profile.breed] * bio["sex_factor"][profile.sex]
                     * bio["frame_factor"][profile.frame] * config["rations"][stage]["potential_factor"]
                     * (1 - burden * clinical["gain_penalty"]) * (1 - heat))
        _, high = bio["gain_bounds_kg_per_day"]
        potential = min(high, potential)
        shrunk = weight * energy["live_to_shrunk_bw"]
        maintenance_me = (energy["net_mcal_per_kg_shrunk_bw_075"] * shrunk**0.75 * energy["mj_per_mcal"]
                          * (1 + cold) * (1 + burden * clinical["maintenance_surcharge"])
                          / energy["maintenance_me_efficiency"])
        gain_me_per_kg = energy["net_gain_mj_per_kg_live"] / energy["gain_me_efficiency"]
        maintenance_cp = energy["cp_maintenance_kg_at_400kg"] * (weight / 400)**0.75
        cp_per_kg = energy["cp_per_kg_gain"]
        reserve_me, reserve_cp = self.reserves.get(profile.animal_id, (0.0, 0.0))
        need = maintenance_me * elapsed
        used_me, used_cp, gain, loss = self._fluxes(
            weight, elapsed, potential, (maintenance_me, maintenance_cp), (reserve_me, reserve_cp))
        new_weight = weight + gain - loss

        feed = self.adapter.consume_for(profile.animal_id, interval.location_id, start=start,
                                        end=end, window=window) if window else None
        dm, intake_me, intake_cp = ((feed.consumed_g_dm, feed.energy_mj, feed.protein_kg)
                                    if feed else (0, 0.0, 0.0))
        gain_me, gain_cp = gain * gain_me_per_kg, gain * cp_per_kg
        available_me = reserve_me - used_me - gain_me + intake_me
        available_cp = reserve_cp - used_cp - gain_cp + intake_cp
        horizon = energy["reserve_hours"] / 24
        ending_me = bounded(available_me, (0, (maintenance_me + high * gain_me_per_kg) * horizon))
        ending_cp = bounded(available_cp, (0, (maintenance_cp + high * cp_per_kg) * horizon))
        self.reserves[profile.animal_id] = ending_me, ending_cp
        if not all(isfinite(value) for value in (new_weight, ending_me, ending_cp)):
            raise ValueError("nonfinite biological state")

        return NutrientStep(
            profile.animal_id, profile.lot_id, start, end, interval.location_id,
            interval.start_event_id, stage, age, potential, health.health_event_id if health else None,
            burden, weather_key, weather_row.source_id, weight, loss / elapsed,
            new_weight, new_weight, window[0] if window else None, window[1] if window else None,
            feed.access_fraction if feed else 0.0, dm, dm, intake_me, intake_cp,
            self.adapter.version, config["biology_version"], timeline.snapshot_id,
            weather_kind=weather_row.kind, temperature_c=temperature, elapsed_days=elapsed,
            maintenance_required_me_mj=need, maintenance_used_me_mj=used_me, gain_used_me_mj=gain_me,
            starting_me_mj=reserve_me, ending_me_mj=ending_me, excess_me_mj=max(0.0, available_me - ending_me),
            cp_maintenance_used_kg=used_cp, cp_gain_used_kg=gain_cp, starting_cp_kg=reserve_cp,
            ending_cp_kg=ending_cp, excess_cp_kg=max(0.0, available_cp - ending_cp), gain_kg=gain, loss_kg=loss,
        )

    def weight_at(self, animal_id, instant):
        if self.through is None or instant > self.through:
            raise ValueError("weight requested ahead of the biological clock")
        index = bisect_right(self.start_times.get(animal_id, ()), instant) - 1
        if index < 0:
            entry = self.timeline.entries[animal_id].effective_at
            return self.profiles[animal_id].entry_weight_kg if instant == entry else None
        row = self.steps_by_animal[animal_id][index]
        if instant > row.end_at:
            return None
        if instant == row.end_at:
            return row.end_weight_kg
        elapsed = (instant - row.start_at) / DAY
        maintenance_cp = (self.calibration["maintenance"]["cp_maintenance_kg_at_400kg"]
                          * (row.start_weight_kg / 400)**0.75)
        rates = row.maintenance_required_me_mj / row.elapsed_days, maintenance_cp
        _, _, gain, loss = self._fluxes(row.start_weight_kg, elapsed, row.potential_adg_kg, rates,
                                       (row.starting_me_mj, row.starting_cp_kg))
        return row.start_weight_kg + gain - loss
