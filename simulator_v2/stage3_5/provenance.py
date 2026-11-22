"""Materialize decision inputs from the same as-of interfaces used by planning."""

from dataclasses import dataclass
from datetime import datetime

from ..stage1.fixture import local
from ..stage1.provenance import canonical, sha256
from ..stage2.timeline import ENTRY


@dataclass(frozen=True)
class DecisionSource:
    snapshot_id: str
    plan_id: str | None
    animal_id: str | None
    source_type: str
    source_id: str
    effective_at: datetime
    available_at: datetime


def decision_sources(schedule, estimator, formulas, scenario):
    policy_start = local(scenario["effective_from_local"])
    scripts = {(local(row[0]), row[1]): row for row in scenario["scripted_dispatch"]}
    planning_policy = sha256(canonical(scenario["planning"]))
    for row in schedule.snapshots:
        cutoff = row.knowledge_cutoff
        snapshot, movements, roster, weights, clinical = estimator.snapshot(row.effective_before, cutoff)
        if snapshot != row or policy_start > cutoff:
            raise ValueError("decision input snapshot changed during planning")
        yield DecisionSource(row.snapshot_id, None, None, "estimator_policy", row.policy_sha256,
                             policy_start, policy_start)
        yield DecisionSource(row.snapshot_id, None, None, "stage1_replay", row.movement_sha256, cutoff, cutoff)
        events = {event.event_id: event for event in movements.events}
        entries = {event.animal_id: event for event in movements.events if event.kind in ENTRY}
        for state in roster:
            key = state.animal_id
            for kind, event in (("entry", entries[key]), ("roster_movement", events[state.last_event_id])):
                yield DecisionSource(row.snapshot_id, None, key, kind, event.event_id,
                                     event.effective_at, event.available_at)
            for observation in weights[key]:
                yield DecisionSource(row.snapshot_id, None, key, "scale_ticket", observation.observation_id,
                                     observation.measured_at, observation.available_at)
            for fact in clinical[key]:
                yield DecisionSource(row.snapshot_id, None, key, "clinical_fact", fact.health_event_id,
                                     fact.effective_at, fact.available_at)
        for plan in (plan for plan in schedule.plans if plan.decision_snapshot_id == row.snapshot_id):
            yield DecisionSource(row.snapshot_id, plan.plan_id, None, "feeding_policy", planning_policy,
                                 policy_start, policy_start)
            recipe = formulas.versions[plan.ration_version_id]
            for source_id in (recipe.record_id, *(line.component_id for line in formulas.lines[recipe.record_id])):
                yield DecisionSource(row.snapshot_id, plan.plan_id, None, "ration", source_id,
                                     recipe.effective_at, recipe.available_at)
            if plan.status == "scripted_dispatch":
                script = scripts[plan.window_start, plan.pen_id]
                yield DecisionSource(row.snapshot_id, plan.plan_id, None, "scripted_dispatch",
                                     sha256(canonical(script)), policy_start, policy_start)
            for weight in schedule.frozen_weights[cutoff].values():
                if weight.roster_pen_id == plan.pen_id:
                    yield DecisionSource(row.snapshot_id, plan.plan_id, weight.animal_id, "frozen_weight",
                                         weight.weight_input_id, cutoff, cutoff)
