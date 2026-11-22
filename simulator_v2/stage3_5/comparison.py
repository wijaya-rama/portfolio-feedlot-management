"""Compare the corrected run with the archived Stage 3 fixture."""

from collections import Counter

from ..stage1.fixture import B, animal_id, local
from ..stage3.fixture import stage3_fixture
from ..stage3.reconciliation import feed_bridges, wip_candidates


def compare(corrected, corrected_totals, seed):
    baseline = stage3_fixture(seed)
    old_totals = feed_bridges(baseline, wip_candidates(baseline))
    old_obs = {row.source_event_id: row for row in baseline.observations}
    old_plans = {(row.pen_id, row.window_start): row for row in baseline.schedule.plans}
    new_plans = {(row.pen_id, row.window_start): row for row in corrected.schedule.plans}
    changes = Counter()
    for row in corrected.schedule.plans:
        prior = old_plans[row.pen_id, row.window_start]
        if row.planned_g_dm != prior.planned_g_dm:
            changes[row.pen_id] += 1
    examples = []
    for n in (3, 5, 7):
        animal = animal_id(n)
        readings = [
            {"source": row.source_event_id, "old_observed_at": old_obs[row.source_event_id].measured_at,
             "new_observed_at": row.measured_at,
             "old_scale_kg": old_obs[row.source_event_id].measured_weight_kg,
             "new_scale_kg": row.measured_weight_kg,
             "old_latent_at_old_observation_kg": round(baseline.biology.weight_at(
                 animal, old_obs[row.source_event_id].measured_at), 6),
             "new_latent_at_new_observation_kg": round(corrected.biology.weight_at(animal, row.measured_at), 6)}
            for row in corrected.observations if row.animal_id == animal and row.source_event_id in old_obs
            and not row.corrects_observation_id
        ]
        stop = baseline.timeline.stop_at(animal)
        examples.append({"animal_id": animal, "growth_to": stop, "scale_tickets": readings,
                         "entry_kg": baseline.biology.profiles[animal].entry_weight_kg,
                         "old_end_latent_kg": round(baseline.biology.weight_at(animal, stop), 6),
                         "new_end_latent_kg": round(corrected.biology.weight_at(animal, stop), 6)})
    decisions = []
    for stamp, n in (("2024-01-14 15:00", 3), ("2024-01-18 15:00", 5), ("2024-02-27 15:00", 7)):
        cutoff, animal = local(stamp), animal_id(n)
        decisions.append({
            "decision_at": cutoff, "pen_id": B, "animal_id": animal,
            "old_estimate_kg": baseline.schedule.frozen_weights[cutoff][animal].estimated_kg,
            "new_estimate_kg": corrected.schedule.frozen_weights[cutoff][animal].estimated_kg,
            "old_pen_planned_g_dm": old_plans[B, cutoff].planned_g_dm,
            "new_pen_planned_g_dm": new_plans[B, cutoff].planned_g_dm,
        })
    return {
        "archived_scenario": baseline.scenario["version"], "corrected_scenario": corrected.scenario["version"],
        "old_observations": len(old_obs), "new_observations": len(corrected.observations),
        "changed_plan_dm_count": sum(changes.values()), "changed_plan_dm_count_by_pen": dict(changes),
        "old_planned_g_dm": sum(row.planned_g_dm for row in old_plans.values()),
        "new_planned_g_dm": sum(row.planned_g_dm for row in corrected.schedule.plans),
        "old_horizon_feed": next(row for row in old_totals if row.period == "horizon"),
        "new_horizon_feed": next(row for row in corrected_totals if row.period == "horizon"),
        "examples": examples,
        "decision_examples": decisions,
    }
