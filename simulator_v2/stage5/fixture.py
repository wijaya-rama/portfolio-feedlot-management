"""Build candidate operations from as-known documents and replay physical exposure separately."""

import json
from collections import defaultdict
from copy import copy, deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from ..stage1.fixture import END, FINAL_CUTOFF, START
from ..stage1.model import AnimalStatus
from ..stage1.provenance import stable_id
from ..stage1.replay import LocationInterval
from ..stage1.soh import calendar_days
from ..stage2.feed import feeding_windows
from ..stage2.timeline import ENTRY, EXIT, checked_replay
from ..stage3.allocation import settle
from ..stage3_5.biology import ChronologicalFeed
from ..stage3_5.feeding import TimedAllocation, growth_clock
from ..stage3_5.fixture import integrated_fixture, load_scenario
from .biology import CalibratedBiology
from .weather import Weather

TICK = timedelta(microseconds=1)
CALIBRATION = Path(__file__).with_name("calibration.json")


def settings():
    policy = json.loads(CALIBRATION.read_bytes())
    values = policy["maintenance"]
    if (not 0 < values["maintenance_me_efficiency"] <= 1
            or not 0 < values["gain_me_efficiency"] <= 1
            or not 0 <= values["buffer_hours"] < values["reserve_hours"] <= 24
            or any(amount <= 0 for key, amount in values.items() if key != "buffer_hours")):
        raise ValueError("invalid calibration parameters")
    return policy


def candidate_scenario(calibration):
    scenario = load_scenario()
    return {**scenario, "version": calibration["scenario_version"],
            "biology_version": calibration["biology_version"],
            "observation_version": calibration["observation_version"],
            "allocation_policy": {**scenario["allocation_policy"], "version": "timed-clinical-weights.2"},
            "planning": {**scenario["planning"], "version": "stage5-window-target.1",
                         "clinical_intake_bps": calibration["clinical_intake_bps"]}}


def as_known_timeline(ledger, physical):
    """Represent movement corrections prospectively for the synthetic scale process."""
    if any(row.available_at != row.effective_at for row in ledger.events if row.kind in (*ENTRY, *EXIT)):
        raise ValueError("the fixture scale path requires contemporaneous entries and exits")
    events = {row.event_id: row for row in ledger.events}
    boundaries = sorted({max(row.effective_at, row.available_at) for row in events.values()
                         if max(row.effective_at, row.available_at) < physical.result.effective_before})
    intervals, open_rows = defaultdict(list), {}
    for instant in boundaries:
        current = checked_replay(ledger, instant + TICK, instant)
        for state in current.states:
            previous = open_rows.get(state.animal_id)
            if previous and previous.location_id == state.location_id:
                continue
            if previous:
                intervals[state.animal_id].append(replace(previous, end_at=instant,
                                                         end_event_id=state.last_event_id))
                del open_rows[state.animal_id]
            if state.status == AnimalStatus.ACTIVE:
                event = events[state.last_event_id]
                open_rows[state.animal_id] = LocationInterval(state.animal_id, state.lot_id,
                                                              state.location_id, instant, event.sequence,
                                                              state.last_event_id)
    for key, row in open_rows.items():
        intervals[key].append(row)
    result = copy(physical)
    result.intervals = {key: tuple(rows) for key, rows in intervals.items()}
    result.starts = {key: tuple(row.start_at for row in rows) for key, rows in result.intervals.items()}
    result.snapshot_id = stable_id("STAGE5-SCALE-PHYSICAL", result.intervals)
    return result


class ScaleIntegration:
    def __init__(self, weather, calibration):
        if weather.mode == "retrospective":
            raise ValueError("the synthetic scale process cannot use retrospective weather")
        self.weather = weather
        self.calibration = calibration
        self.settlements = []

    def biology(self, ledger, timeline, profiles, health, config, adapter, windows, policy, clinical_intake_bps):
        self.timeline = as_known_timeline(ledger, timeline)
        clock = growth_clock(windows, self.timeline, (), health, config, policy["release_minutes"])
        self.allocation = TimedAllocation(clock, "timed-access-as-known.2", clinical_intake_bps)
        return CalibratedBiology(self.timeline, profiles, health, config, adapter=adapter, clock=clock,
                                 forcing=self.weather, calibration=self.calibration)

    def observation_allocations(self, ledger, delivery, plan, ticket, weights, fallback):
        end = delivery.window_end
        verified = checked_replay(ledger, end + TICK, end)
        intervals = tuple(
            replace(row, end_at=None, end_event_id=None) if row.end_at is not None and row.end_at > end else row
            for rows in self.timeline.intervals.values() for row in rows
            if row.start_at < end and (row.end_at is None or row.end_at > delivery.window_start)
        )
        available = replace(verified, intervals=intervals)
        scale_ticket = replace(ticket, record_id=f"{ticket.record_id}-SCALE",
                               posted_at=end, available_at=end)
        result = settle(ledger, delivery, plan, scale_ticket, weights, fallback,
                        replay=available, allocation_policy=self.allocation)
        self.settlements.append(result)
        return result.allocations


def build_operations(seed, weather, calibration, *, scenario=None, ledger=None):
    integration = ScaleIntegration(weather, calibration)
    operations = integrated_fixture(seed, weather=(), integration=integration, ledger=ledger,
                                    scenario=scenario if scenario is not None else candidate_scenario(calibration))
    return operations, tuple(integration.settlements)


def replay_growth(operations, forcing, calibration, *, method=None, health=None):
    config = operations.biology_config
    method = method if method is not None else operations.scenario["method"]
    health = operations.health if health is None else health
    windows = tuple(window for day in calendar_days(START, END) for window in feeding_windows(day, config))
    clock = growth_clock(windows, operations.timeline, (), operations.health, config,
                         operations.scenario["allocation_policy"]["release_minutes"])
    feed = ChronologicalFeed(method, len(config["feed_windows_local"]))
    for row in operations.active_settlements:
        feed.add(row.allocations)
    model = CalibratedBiology(operations.timeline, operations.profiles, health, config,
                              adapter=feed, clock=clock, forcing=forcing, calibration=calibration)
    model.advance(FINAL_CUTOFF)
    return model


def changed_scenario(calibration, intervention):
    scenario = deepcopy(candidate_scenario(calibration))
    settings = calibration["sensitivity"]
    if intervention == "lower_me":
        factor = settings["ingredient_me_multiplier"]
        for ingredient in scenario["warehouse"]["ingredients"]:
            if ingredient[0] != "SYN-HAND-SILAGE":
                ingredient[3] = round(ingredient[3] * factor)
        for recipe in scenario["recipes"]:
            if recipe["id"] != "SYN-HAND-RATION":
                recipe["target_kj_per_kg_dm"] = round(recipe["target_kj_per_kg_dm"] * factor)
    elif intervention == "reduced_offer":
        targets = scenario["planning"]["stage_dm_g_per_window"]
        for key in targets:
            targets[key] = round(targets[key] * settings["feed_target_multiplier"])
    elif intervention == "elevated_mix_loss":
        scenario["planning"]["mix_loss_bps"] = settings["elevated_mix_loss_bps"]
    elif intervention == "elevated_distribution_loss":
        scenario["planning"]["truck_loss_bps"] = settings["elevated_distribution_loss_bps"]
    else:
        raise ValueError(f"unknown controlled intervention: {intervention}")
    return scenario


def weather_scenario(calibration, mean_c=None):
    return Weather("operational_as_of" if mean_c is None else "controlled",
                   calibration["stress"]["fallback_c_by_month"], scenario_c=mean_c)
