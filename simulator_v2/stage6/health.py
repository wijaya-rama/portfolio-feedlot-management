"""Daily competing clinical transitions, with observed status separate from latent burden."""

from dataclasses import dataclass

from ..stage1.model import EventKind, LocationKind
from ..stage2.health import Action, HealthEvent
from .config import MODEL

SEVERITIES = ("mild", "moderate", "severe")


@dataclass
class Episode:
    number: int
    severity: int
    onset_day: object
    last: HealthEvent | None = None
    detected: bool = False
    treated: bool = False
    chronic: bool = False
    recovered: bool = False
    last_review: object = None


class Health:
    def __init__(self, config, yard, emit, weigh):
        self.policy = config["health"]
        self.yard, self.emit, self.weigh = yard, emit, weigh
        self.events = []

    def record(self, live, ep, action, when, *, movement=None):
        previous = ep.last
        ordinal = len(self.events) + 1
        key = f"SYN-HEALTH-{ordinal:09d}"
        latent = action == Action.ONSET
        status = "dead" if action == Action.DEATH else "healthy" if ep.recovered else (
            "chronic" if ep.chronic else "ill")
        biology = self.yard.bio["health"]
        severity = None if action == Action.DEATH and previous is None else SEVERITIES[ep.severity]
        burden = 0.0 if ep.recovered or action == Action.DEATH else (
            biology["chronic_burden"] if ep.chronic else biology["severity"][severity])
        # The synthetic treatment charge and timing do not alter the transition probabilities.
        location_event = movement or self.yard.events[live.interval.start_event_id]
        snapshot = self.yard.context(when, key, [location_event.event_id]).snapshot_id
        row = HealthEvent(key, f"{live.key}-EP{ep.number:03d}", previous.health_event_id if previous else None,
                          live.key, live.lot, action, when, when, when, live.pen, f"{key}-SOURCE",
                          movement.event_id if movement else None, severity, None, burden, status,
                          not latent, MODEL, snapshot)
        ep.last = row
        self.events.append(row)
        self.emit("health_events", [row], when)
        if not latent:
            live.observed_health = row

    def start(self, live, day, severity, when):
        live.episode_number += 1
        ep = Episode(live.episode_number, severity, day)
        live.clinical = ep
        self.record(live, ep, Action.ONSET, when)
        return ep

    def day(self, day, when):
        for key in sorted(self.yard.active):
            live = self.yard.active[key]
            ep = live.clinical
            draw = self.yard.draw
            p = self.policy
            if not ep or ep.recovered:
                if self.yard.kinds[live.pen] == LocationKind.HOSPITAL:
                    self.return_to_production(live, ep, when)
                if draw("health/background-death", key, day) < p["background_death_daily"]:
                    live.episode_number += 1
                    self.death(live, Episode(live.episode_number, 0, day), when)
                    continue
                risk = p["onset_daily"]
                if self.yard.kinds[live.pen] == LocationKind.RECEIVING:
                    risk *= p["receiving_multiplier"]
                if live.last_recovery and (day - live.last_recovery).days < 30:
                    risk *= p["post_recovery_multiplier"]
                if draw("health/onset", key, day) >= min(1, risk):
                    continue
                value = draw("health/severity", key, live.episode_number + 1)
                a, b, _ = p["severity_weights"]
                ep = self.start(live, day, int(value >= a) + int(value >= a + b), when)

            i = ep.severity
            hazard = p["detected_death_daily" if ep.detected else "untreated_death_daily"][i]
            if draw("health/episode-death", key, day) < hazard:
                self.death(live, ep, when)
                continue

            if not ep.detected:
                if draw("health/detection", key, day) < p["detection_daily"][i]:
                    ep.detected = True
                    ep.last_review = day
                    self.record(live, ep, Action.PULL, when)
                    self.admit(live, ep, when)
                    if draw("health/treatment", key, day) < p["treatment_probability"]:
                        ep.treated = True
                        self.record(live, ep, Action.TREAT, when)
                continue

            if ep.chronic:
                self.return_to_production(live, ep, when)
            else:
                self.admit(live, ep, when)
            if (day - ep.last_review).days < p["reassess_days"]:
                continue
            ep.last_review = day
            self.record(live, ep, Action.REASSESS, when)
            if draw("health/recovery", key, day) < p["recovery_daily"][i]:
                ep.recovered = True
                live.last_recovery = day
                self.record(live, ep, Action.RECOVER, when)
                self.return_to_production(live, ep, when)
            elif not ep.chronic and (day - ep.onset_day).days >= p["chronic_after_days"] and (
                    draw("health/chronic", key, day) < p["chronic_probability"]):
                ep.chronic = True
                self.record(live, ep, Action.CHRONIC, when)
                self.return_to_production(live, ep, when)
            elif ep.treated and draw("health/repeat", key, day) < p["repeat_probability"]:
                self.record(live, ep, Action.REPEAT, when)

    def admit(self, live, ep, when):
        if ep.severity != 2 or ep.chronic or self.yard.kinds[live.pen] == LocationKind.HOSPITAL:
            return
        pen = self.yard.pick(LocationKind.HOSPITAL)
        if pen is None:
            self.yard.exception(when, "hospital_full_triaged_in_place", live.key)
            return
        movement = self.yard.move(live.key, EventKind.TRANSFER, when, pen, reason="clinical_admission")
        self.record(live, ep, Action.ADMIT, when, movement=movement)
        self.weigh(live, when, "hospital")

    def return_to_production(self, live, ep, when):
        if self.yard.kinds[live.pen] != LocationKind.HOSPITAL:
            return
        pen = self.yard.pick(LocationKind.PRODUCTION, pack=True)
        if pen is None:
            self.yard.exception(when, "hospital_return_rescheduled", live.key)
            return
        movement = self.yard.move(live.key, EventKind.TRANSFER, when, pen, reason="clinical_return")
        if ep is not None:
            self.record(live, ep, Action.RETURN, when, movement=movement)

    def death(self, live, ep, when):
        reason = "synthetic_clinical_outcome" if ep.last else "synthetic_unknown_cause"
        movement = self.yard.move(live.key, EventKind.DEATH, when, reason=reason)
        self.record(live, ep, Action.DEATH, when, movement=movement)
