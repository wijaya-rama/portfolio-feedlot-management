"""Compare fixed weight-forecast rules on Stage 5 development tickets only."""

import argparse
from collections import defaultdict
from datetime import datetime
from functools import cache
import json
from pathlib import Path

from ...stage1.__main__ import git_commit
from ...stage1.model import EDMONTON, UTC, business_date, midnight
from ...stage1.provenance import canonical, sha256
from ...stage1.soh import calendar_days
from ...stage2.config import season
from ..config import model
from .holdout import DAY, STAGE5, errors_summary, forecast_origins, forecast_pairs, lot_holdout
from .holdout import observation_history, read_saved

CANDIDATE = "stage5-phase-calendar-forecast.1"


def development_tables(tables, cutoff):
    """Seal the analysis input before reconstructing scale observations or forecasts."""
    carry = {row["animal_id"] for row in tables["opening_cattle"]}

    def known(row, effective):
        return row[effective] < cutoff and row["available_at"] <= cutoff

    animals = [row for row in tables["animals"] if row["animal_id"] not in carry
               and not lot_holdout(row["lot_id"]) and known(row, "effective_at")]
    ids = {row["animal_id"] for row in animals}
    return {
        "animals": animals,
        "opening_cattle": [],
        "lots": [row for row in tables["lots"] if known(row, "effective_at")],
        "locations": [row for row in tables["locations"] if known(row, "effective_at")],
        **{table: [row for row in tables.get(table, ()) if row["animal_id"] in ids and known(row, clock)]
           for table, clock in (
               ("movement_events", "effective_at"), ("health_events", "effective_at"),
               ("weight_observations", "measured_at"),
           )},
    }


def phase_scorer(bio):
    """Use only the origin phase/health and deterministic local calendar transitions."""
    policy = bio["estimation"]
    rates = policy["stage_adg_kg"]
    health_scales = {"ill": policy["observed_illness_multiplier"],
                     "chronic": policy["observed_chronic_multiplier"]}

    @cache
    def season_spans(origin, end_day):
        first = business_date(origin)
        points = [origin]
        cold = season(first, bio)
        for day in calendar_days(first + DAY, end_day):
            following = season(day, bio)
            if cold != following:
                points.append(midnight(day))
                cold = following
        points.append(midnight(end_day + DAY))
        return tuple((left, right, policy["cold_adg_multiplier"] if season(business_date(left), bio) == "cold" else 1)
                     for left, right in zip(points, points[1:]))

    def score(window, label):
        target = label.measured_at
        anchor_age = (window.origin - window.anchor_at) / DAY
        nowcast_gain = window.prior_kg_per_day * min(anchor_age, window.nowcast_limit_days)
        health_scale = health_scales.get(window.clinical_status, 1)
        gain = 0.0
        crossed_season = False
        for start, stop, season_scale in season_spans(window.origin, business_date(target)):
            if start >= target:
                break
            crossed_season |= start > window.origin
            stop = min(stop, target)
            days = (stop - start) / DAY
            if window.stage == "adaptation":
                adaptation_days = max(0, (min(stop, window.adaptation_end) - start) / DAY)
                weighted_days = rates["adaptation"] * adaptation_days + rates["finishing"] * (days - adaptation_days)
            else:
                weighted_days = rates[window.stage] * days
            gain += weighted_days * season_scale * health_scale
        predicted = round(window.anchor_kg + nowcast_gain + gain, 3)
        return {
            "candidate_error": predicted - label.measured_weight_kg,
            "origin_phase": window.stage,
            "crossed_adaptation": window.stage == "adaptation" and window.adaptation_end < target,
            "crossed_calendar_season": crossed_season,
        }

    return score


def paired_metrics(rows):
    usable = [row for row in rows if row["errors"]]
    return {
        "candidate_pairs": len(rows),
        "eligible_pairs": len(usable),
        "eligible_animals": len({row["animal"] for row in usable}),
        "eligible_lots": len({row["lot"] for row in usable}),
        "legacy_capped_pairs": sum(row["legacy_capped"] for row in usable),
        "crossed_adaptation_pairs": sum(row["crossed_adaptation"] for row in usable),
        "crossed_calendar_season_pairs": sum(row["crossed_calendar_season"] for row in usable),
        "errors": {
            "A": errors_summary([row["errors"][0] for row in usable]),
            "truncated_B": errors_summary([row["legacy_b_error"] for row in usable]),
            "constant_ADG_B": errors_summary([row["errors"][1] for row in usable]),
            "phase_calendar_B": errors_summary([row["candidate_error"] for row in usable]),
        } if usable else None,
    }


def compare(config, tables, provenance):
    protocol = json.loads((STAGE5 / "evaluation.json").read_bytes())
    cutoff = datetime.fromisoformat(protocol["development_target_before_local"]).replace(tzinfo=EDMONTON).astimezone(UTC)
    estimator, opening = observation_history(config, development_tables(tables, cutoff), cutoff)
    bio, _ = model(config)
    horizons = protocol["horizons_elapsed_days"]
    forecasts = forecast_origins(config, estimator, opening, before=cutoff)
    rows = forecast_pairs(forecasts, estimator.observations, horizons, cutoff, cutoff, extra_score=phase_scorer(bio))
    comparison = {}
    for horizon in horizons:
        matched = [row for row in rows if row["horizon"] == horizon]
        phases = defaultdict(list)
        for row in matched:
            phases[row.get("origin_phase", "no_eligible_anchor")].append(row)
        comparison[str(horizon)] = paired_metrics(matched) | {
            "by_origin_phase": {name: paired_metrics(group) for name, group in sorted(phases.items())}
        }
    return {
        **provenance, "evaluated_seed": config["seed"], "candidate": CANDIDATE, "evaluator_commit": git_commit(),
        "protocol_version": protocol["version"], "protocol_sha256": sha256(canonical(protocol)),
        "forecast_policy_sha256": sha256(canonical({
            "estimation": bio["estimation"], "calendar": bio["calendar"],
            "adaptation_days": bio["biology"]["adaptation_days"],
        })),
        "development_cutoff": cutoff.isoformat(), "scope": "development_only",
        "stage5_status": "incomplete", "promotion_eligible": False, "horizons": comparison,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(*read_saved(args.archive)), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
