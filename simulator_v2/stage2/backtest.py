"""Rolling-origin coverage and gated error summaries using future observed targets."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from ..stage1.model import business_date, is_utc
from .config import season
from .estimation import Model
from .observations import Kind


@dataclass(frozen=True)
class Pair:
    target_observation_id: str
    animal_id: str
    lot_id: str
    breed: str
    sex: str
    frame: str
    target_kind: Kind
    horizon_days: int
    origin_at: datetime
    target_at: datetime
    snapshot_id: str | None
    clinical_status: str | None
    production_stage: str | None
    season: str
    eligibility: str
    model_a_estimate_id: str | None
    model_b_estimate_id: str | None
    target_weight_kg: float
    prediction_a_kg: float | None
    prediction_b_kg: float | None
    synthetic: bool = True


@dataclass(frozen=True)
class LatentTarget:
    target_observation_id: str
    horizon_days: int
    animal_id: str
    target_at: datetime
    simulated_weight_kg: float
    physical_snapshot_id: str
    synthetic: bool = True


def evaluate(estimator, profiles, *, start_at, evaluation_cutoff, config):
    """At t−h form a fixed-origin forecast for a scale ticket taken at t."""
    if (not is_utc(start_at) or not is_utc(evaluation_cutoff)
            or start_at >= evaluation_cutoff):
        raise ValueError("backtest requires an ordered UTC evaluation window")
    settings = config["backtest"]
    pairs = []
    snapshots = {}
    forecasts = {}
    for profile in sorted(profiles, key=lambda row: row.animal_id):
        targets = estimator.observations.eligible(profile.animal_id, evaluation_cutoff,
                                                  evaluation_cutoff, include_terminal=True)
        for target in targets:
            if target.kind in {Kind.OPENING, Kind.RECEIVING} or target.measured_at < start_at:
                continue
            for horizon in settings["horizons_days"]:
                origin = target.measured_at - timedelta(days=horizon)
                snapshot_id = health = stage = first = other = None
                reason = "origin_before_evaluation_window"
                if origin >= start_at:
                    snapshot, estimates = estimator.estimates(origin, estimate_for=target.measured_at,
                                                               animal_id=profile.animal_id)
                    snapshots[snapshot.snapshot_id] = snapshot
                    snapshot_id = snapshot.snapshot_id
                    reason = "animal_inactive_at_origin"
                    if estimates:
                        first, other = estimates
                        health, stage = first.clinical_status, first.production_stage
                        forecasts.update((row.estimate_id, row) for row in estimates)
                        reason = ("eligible" if first.estimated_liveweight_kg is not None
                                  and other.estimated_liveweight_kg is not None else "missing_anchor")
                pairs.append(Pair(
                    target.observation_id, target.animal_id, target.lot_id, profile.breed, profile.sex,
                    profile.frame, target.kind, horizon, origin, target.measured_at, snapshot_id,
                    health, stage, season(business_date(origin), config), reason,
                    first.estimate_id if first else None, other.estimate_id if other else None,
                    target.measured_weight_kg, first.estimated_liveweight_kg if first else None,
                    other.estimated_liveweight_kg if other else None,
                ))
    return tuple(pairs), tuple(snapshots.values()), tuple(forecasts.values())


def latent_targets(pairs, biology, physical_snapshot_id):
    """Describe a comparison against simulation truth independently of observed evaluation."""
    return tuple(LatentTarget(
        row.target_observation_id, row.horizon_days, row.animal_id, row.target_at,
        biology.weight_at(row.animal_id, row.target_at), physical_snapshot_id,
    ) for row in pairs if row.eligibility == "eligible")


def _quantile(ordered, fraction):
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def _summary(rows, config, latent=None):
    eligible = tuple(row for row in rows if row.eligibility == "eligible")
    count = len(eligible)
    animals = len({row.animal_id for row in eligible})
    lots = len({row.lot_id for row in eligible})
    reasons = defaultdict(int)
    for row in rows:
        reasons[row.eligibility] += 1
    summary = {
        "candidate_targets": len(rows), "eligible_predictions_per_model": count,
        "eligible_animals": animals, "eligible_lots": lots,
        "horizon_coverage": round(count / len(rows), 6) if rows else None,
        "eligibility": dict(reasons),
        "statistics": None,
    }
    if (count < config["min_pairs"] or animals < config["min_animals"]
            or lots < config["min_lots"]):
        summary["statistics_status"] = "insufficient_support"
        return summary
    summary["statistics_status"] = "reported"
    statistics = {}
    for model, field in ((Model.A, "prediction_a_kg"), (Model.B, "prediction_b_kg")):
        errors = sorted(getattr(row, field) - (
            row.target_weight_kg if latent is None else latent[row.target_observation_id, row.horizon_days]
        ) for row in eligible)
        statistics[model] = {
            "mae_kg": round(fmean(map(abs, errors)), 4),
            "mean_bias_kg": round(fmean(errors), 4),
            "signed_error_quantiles_kg": {
                f"p{percent:02d}": round(_quantile(errors, percent / 100), 4)
                for percent in (10, 50, 90)
            },
        }
    statistics["mae_improvement_b_vs_a_kg"] = round(
        statistics[Model.A]["mae_kg"] - statistics[Model.B]["mae_kg"], 4)
    summary["statistics"] = statistics
    return summary


def report(pairs, config, *, latent=()):
    settings = config["backtest"]
    latent_lookup = {(row.target_observation_id, row.horizon_days): row.simulated_weight_kg
                     for row in latent}
    result = {"synthetic": True, "support_thresholds": {
        key: settings[key] for key in ("min_pairs", "min_animals", "min_lots")
    }, "model_training": "fixed_scenario_priors_no_fit",
              "coverage_denominator": "observed_nonentry_targets_per_horizon", "horizons": {}}
    strata = ("breed", "sex", "frame", "production_stage", "season", "clinical_status",
              "lot_id", "target_kind")
    for horizon in settings["horizons_days"]:
        matching = [row for row in pairs if row.horizon_days == horizon]
        grouped = {}
        for field in strata:
            buckets = defaultdict(list)
            for row in matching:
                buckets[getattr(row, field) or "unavailable_at_origin"].append(row)
            grouped[field] = {key: _summary(rows, settings) for key, rows in sorted(buckets.items())}
        result["horizons"][str(horizon)] = {
            "observed": _summary(matching, settings),
            "strata": grouped,
            "latent_diagnostic": _summary(matching, settings, latent_lookup) if latent_lookup else None,
        }
    return result
