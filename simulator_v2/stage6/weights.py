"""Scale tickets and as-of snapshots from current observations and visible clinical facts."""

from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace

from ..stage1.model import business_date
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage2.estimation import EstimateSnapshot, Estimator, Model
from ..stage2.observations import Kind, WeighPlan, correct, simulate_observations
from ..stage3_5.observations import ScaleSample
from .livestock import DAY


class OnlineEstimator(Estimator):
    """The Stage 2 projection evaluated against an indexed, immutable decision vintage."""

    def __init__(self, config):
        self.policy = config["estimation"]
        self.calendar_config = config
        self.version = config["estimator_version"]


class Weights:
    def __init__(self, yard, emit, correction_cutoff):
        self.yard, self.emit = yard, emit
        self.model = OnlineEstimator(yard.bio)
        self.observations = defaultdict(list)
        self.correction_cutoff = correction_cutoff
        self.corrected = False
        self.policy_digest = sha256(canonical(yard.bio["estimation"]))

    def weigh(self, live, when, kind, movement=None):
        kind = Kind(kind)
        source = f"{live.key}-WEIGH-{kind}-{when:%Y%m%dT%H%M%S}"
        current = live.interval.start_event_id
        self.yard.context(when, source, [current])
        lag = self.yard.draw.integer("scale/posting-minutes", 7, 50, source)
        plan = WeighPlan(source, live.key, kind, when, timedelta(minutes=lag),
                         timedelta(minutes=5), movement_event_id=movement.event_id if movement else None)
        # Current latent state is read exclusively by the scale sampler.
        physical = SimpleNamespace(weight_at=lambda _key, _when: live.weight_kg)
        def sampled(source_plan, observation_id, latent, bias, error, precision):
            sample = ScaleSample(observation_id, source_plan.animal_id, when, when, business_date(when),
                                 self.yard.snapshot_id, latent, bias, error, 0.0, precision)
            self.emit("scale_samples_diagnostic", [sample], when)

        attempts, records = simulate_observations(self.yard, physical, (plan,), self.yard.bio, on_sample=sampled)
        self.emit("weigh_attempts", attempts, when)
        self.emit("weight_observations", records, when)
        self.observations[live.key].extend(records)
        if (kind == Kind.FOLLOW_UP and records and not self.corrected and self.correction_cutoff
                and self.correction_cutoff - 8 * DAY <= when < self.correction_cutoff - timedelta(hours=3)):
            # A dated re-entry of the scale ticket, visible only after the month lock.
            posted = self.correction_cutoff + DAY + timedelta(hours=8)
            old = records[0]
            revised = correct(old, source_id=f"{source}-REV2", posted_at=posted,
                              available_at=posted + timedelta(minutes=5),
                              measured_weight_kg=round(old.measured_weight_kg + 1.1, 1))
            self.observations[live.key].append(revised)
            self.emit("weight_observations", [revised], when)
            self.corrected = True
        return records[0] if records else None

    def anchor(self, animal, cutoff):
        tickets = self.observations.get(animal, ())
        eligible = [row for row in tickets
                    if row.kind != Kind.FINAL_SALE and row.measured_at < cutoff and row.available_at <= cutoff]
        latest = max(eligible, key=lambda row: (row.measured_at, row.available_at, row.observation_id), default=None)
        if latest:
            self.observations[animal] = [latest, *(row for row in tickets if row.available_at > cutoff)]
        return latest

    def freeze(self, when, candidates):
        roster = tuple(sorted(candidates, key=lambda live: live.key))
        anchors = [self.anchor(live.key, when) for live in roster]
        movements = [live.interval.start_event_id for live in roster]
        observation_ids = [row.observation_id if row else None for row in anchors]
        clinical = [live.observed_health for live in roster]
        clinical_ids = [row.health_event_id if row else None for row in clinical]
        digests = [sha256(canonical(value)) for value in (movements, observation_ids, clinical_ids)]
        identity = stable_id("STAGE6-DECISION", [self.yard.run_id, when, *digests, self.policy_digest])
        snapshot = EstimateSnapshot(identity, self.yard.run_id, when, when, *digests, self.policy_digest,
                                    None, None, self.model.version)
        estimates = {}
        for live, anchor, health in zip(roster, anchors, clinical):
            state = SimpleNamespace(animal_id=live.key, lot_id=live.lot, location_id=live.pen,
                                    last_event_id=live.interval.start_event_id)
            estimates[live.key] = self.model._estimate(snapshot, state, self.yard.stage(live, when),
                                                       health, anchor, when, Model.B)
        self.emit("decision_snapshots", [snapshot], when)
        self.emit("weight_estimates", estimates.values(), when)
        return snapshot, estimates

    def follow_up(self, day, instant):
        for live in self.yard.active.values():
            if live.next_weighing <= day:
                self.weigh(live, instant, Kind.FOLLOW_UP)
                live.next_weighing = day + self.yard.config["follow_up_days"] * DAY

    def depart(self, key):
        self.observations.pop(key, None)
