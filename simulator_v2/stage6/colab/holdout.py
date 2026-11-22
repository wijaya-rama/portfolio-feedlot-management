"""Evaluate saved Stage 6 scale and movement records without running the simulator."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
from statistics import fmean, median
import tarfile

import pyarrow.parquet as pq

from ...stage1.__main__ import git_commit
from ...stage1.ledger import Ledger
from ...stage1.model import (EDMONTON, UTC, Animal, AnimalEvent, EventKind, LocationKind,
                            LocationVersion, Lot, RunConfig, Source, midnight)
from ...stage2.estimation import Estimator, Model, operational_health
from ...stage2.health import HealthEvent
from ...stage2.observations import Kind, Observation, Observations
from ...stage2.timeline import ENTRY, PhysicalTimeline, production_stage
from ..config import HERE, SCHEMA, at, model
from ..export import digest

BASELINE_CODE = "39770fb9e2867127f1ddac671ac694997e26b864"
PILOT_CODE = "e59d04ecf24eddcdc0473f33e98ae1ea381f595d"
STAGE5 = HERE.parent / "stage5"
ENTRY_TICKETS = (Kind.OPENING, Kind.RECEIVING)
DAY = timedelta(days=1)
TICK = timedelta(microseconds=1)
TABLES = {"animals", "lots", "locations", "movement_events", "weight_observations", "opening_cattle"}
EVALUATION_ONLY = "evaluation_only"
AUDIT_GATES = {"placement_disposition", "yard_capacity", "weighing_chronology", "no_future_estimates",
               "balanced_two_line_journal", "financial_close_publication", "warehouse_replay_publication",
               "stable_original_snapshot", "stable_restated_snapshot"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_saved(path):
    status = json.loads(path.with_name("status.json").read_bytes())
    size = status["placements"]
    code = status["code_sha"]
    baseline = size == 250 and code == BASELINE_CODE
    pilot = size == 1500 and code == PILOT_CODE and status.get("purpose") == EVALUATION_ONLY
    require(baseline or pilot, "Expected the reviewed 250 archive or an evaluation-only 1,500 archive.")
    require(status["status"] == "completed" and status["validation_status"] == "passed"
            and status["complete_independent_audit"] is True and status["financial_closes"] == 48
            and status["head"]["placements"] == size and (baseline or (
                status.get("stage5_status") == "incomplete" and status.get("promotion_eligible") is False
            )), "The saved build must have passed its complete audit.")
    archive_hash = digest(path)
    require(path.stat().st_size == status["package_bytes"]
            and archive_hash == status["saved_sha256"][path.name], "Saved archive hash or size differs.")

    with tarfile.open(path, "r:") as archive:
        members = {}
        for member in archive:
            name = PurePosixPath(member.name)
            require(member.isfile() and len(name.parts) >= 2 and name.parts[0] == "dataset"
                    and ".." not in name.parts and member.name == name.as_posix()
                    and member.name not in members, "Unexpected or duplicate archive entry.")
            members[member.name] = member

        def read(name, expected_hash):
            with archive.extractfile(members["dataset/" + name]) as stream:
                data = stream.read()
            require(sha256(data).hexdigest() == expected_hash, f"Saved hash differs for {name}.")
            return data

        manifest = json.loads(read("run_manifest.json", status["saved_sha256"]["run_manifest.json"]))
        index = json.loads(read("hashes.json", manifest["hashes_sha256"]))
        require(manifest["synthetic"] is True and manifest["code_checkout_commit_at_build"] == code
                and manifest["schema_version"] == index["schema_version"] == SCHEMA
                and manifest["run_id"] == index["run_id"] == status["run_id"]
                and manifest["hashes_sha256"] == status["saved_sha256"]["hashes.json"],
                "Manifest and saved index disagree.")
        config = json.loads(read("config.json", manifest["config_sha256"]))
        version = "stage6b1-baseline-250.1" if baseline else "stage7-pilot-1500.1"
        require(config["version"] == status["config_version"] == version and config["seed"] == status["seed"]
                and sum(row["head"] for row in config["placements"]) == size
                and (config["start"], config["end"]) == ("2024-01-01", "2025-12-31"),
                "Saved configuration does not describe the expected evaluation build.")
        audit = json.loads(read("validation.json", index["artifacts"]["validation.json"]))
        require(audit["mode"] == "full" and audit["complete_independent_audit"] is True
                and AUDIT_GATES <= audit["hard_gates"].keys()
                and all(row["passed"] is True for row in audit["hard_gates"].values())
                and all(audit[key] and all(check["failed_count"] == 0 for check in audit[key])
                        for key in ("movement", "financial")), "The archive does not contain a passing full audit.")
        partitions = index["partitions"]
        expected = partitions.keys() | index["artifacts"].keys() | {"run_manifest.json", "hashes.json", "performance.json"}
        require(members.keys() == {"dataset/" + name for name in expected}, "Saved archive inventory differs.")

        tables = defaultdict(list)
        for name, part in sorted(partitions.items()):
            table = part["table"]
            if table not in TABLES and table != "health_events":
                continue
            data = read(name, part["sha256"])
            require(len(data) == part["bytes"], f"Saved partition size differs for {name}.")
            rows = pq.ParquetFile(BytesIO(data)).read().to_pylist()
            require(len(rows) == part["rows"] and all(row.pop("run_id") == manifest["run_id"] for row in rows),
                    f"Saved partition rows do not match for {name}.")
            tables[table].extend(rows)
    require(TABLES <= tables.keys(), "Saved archive lacks required evaluation tables.")
    require(sum(row["kind"] == EventKind.RECEIPT for row in tables["movement_events"]) == size
            and len(tables["opening_cattle"]) == status["head"]["opening"], "Saved cattle counts differ.")
    return config, tables, {"run_id": manifest["run_id"], "archive_sha256": archive_hash,
                            "simulator_commit": code, "placements": size}


def lot_holdout(lot):
    return int(sha256(lot.encode()).hexdigest()[:8], 16) % 5 == 0


def observation_history(config, tables, cutoff):
    first, last = (date.fromisoformat(config[key]) for key in ("start", "end"))
    bio, _ = model(config)
    ledger = Ledger(
        RunConfig(config["version"], config["seed"], first, last),
        [Lot(**row) for row in tables["lots"]],
        [Animal(**row) for row in tables["animals"]],
        [LocationVersion(**(row | {"kind": LocationKind(row["kind"])})) for row in tables["locations"]],
    )
    ledger.ingest(AnimalEvent(**(row | {"kind": EventKind(row["kind"]), "source": Source(**row["source"])}))
                  for row in tables["movement_events"])
    timeline = PhysicalTimeline(ledger, midnight(last + DAY), cutoff)
    # Stage 6 stores an individual physical-context ID on each ticket. Reattach
    # validation to the replay of the same movements. Those IDs are excluded from
    # estimator features by Estimator.snapshot.
    tickets = [Observation(**(row | {"kind": Kind(row["kind"]), "physical_snapshot_id": timeline.snapshot_id}))
               for row in tables["weight_observations"]]
    observations = Observations(timeline, tickets, bio)
    health = operational_health(HealthEvent(**row) for row in tables.get("health_events", ()))
    model_estimator = Estimator(ledger, observations, health, bio)
    opening = {row["animal_id"]: midnight(first) - row["prior_dof"] * DAY for row in tables["opening_cattle"]}
    return model_estimator, opening


@dataclass(frozen=True, slots=True)
class OriginForecast:
    origin: datetime
    lot: str
    carry_in: bool
    reason: str
    anchor_kg: float | None = None
    anchor_at: datetime | None = None
    prior_kg_per_day: float | None = None
    nowcast_limit_days: float | None = None
    stage: str | None = None
    adaptation_end: datetime | None = None
    clinical_status: str | None = None

    def score(self, label):
        if self.reason != "eligible":
            return (), None, False
        elapsed = (label.measured_at - self.origin) / DAY
        total_days = (label.measured_at - self.anchor_at) / DAY
        legacy_days = min(total_days, self.nowcast_limit_days)
        age = (self.origin - self.anchor_at) / DAY
        forecast_days = min(age, self.nowcast_limit_days) + elapsed
        actual = label.measured_weight_kg
        errors = (round(self.anchor_kg, 3) - actual,
                  round(self.anchor_kg + self.prior_kg_per_day * forecast_days, 3) - actual)
        legacy_b = round(self.anchor_kg + self.prior_kg_per_day * legacy_days, 3) - actual
        return errors, legacy_b, legacy_days < total_days


def forecast_origins(config, estimator, opening, *, before=None):
    """Freeze inputs once per origin. Target availability is resolved separately."""
    first, last = (date.fromisoformat(config[key]) for key in ("start", "end"))
    monday = first + timedelta(days=(-first.weekday()) % 7)
    forecasts = defaultdict(list)
    policy = estimator.policy
    for offset in range(0, (last - monday).days + 1, 7):
        origin = at(monday + offset * DAY, 8)
        if before is not None and origin >= before:
            break
        snapshot, replay, active, weights, clinical = estimator.snapshot(origin)
        entered = {event.animal_id: event.effective_at for event in replay.events if event.kind in ENTRY}
        kinds = {row.location_id: row.kind for row in replay.location_versions}
        for state in active:
            key = state.animal_id
            anchor = weights[key][-1] if weights[key] else None
            age = (origin - anchor.measured_at) / DAY if anchor else None
            args = (origin, state.lot_id, key in opening)
            if anchor is None:
                row = OriginForecast(*args, "missing_anchor")
            elif age >= policy["stale_days"]:
                row = OriginForecast(*args, "stale_anchor")
            else:
                health = clinical[key][-1] if clinical[key] else None
                entry = opening.get(key, entered[key])
                stage = production_stage(kinds[state.location_id], entry, origin - TICK, estimator.adaptation_days)
                nowcast = estimator._estimate(snapshot, state, stage, health, anchor, origin, Model.B)
                row = OriginForecast(*args, "eligible", anchor.measured_weight_kg, anchor.measured_at,
                                     nowcast.adg_prior_kg, policy["projection_limit_days"], stage,
                                     entry + estimator.adaptation_days * DAY, nowcast.clinical_status)
            forecasts[key].append(row)
    return forecasts


def forecast_pairs(forecasts, observations, horizons, effective_before, knowledge_cutoff, *, extra_score=None):
    """Choose the first eligible ticket per window and deduplicate in that ticket vintage."""
    leads = [(horizon, horizon * DAY) for horizon in sorted(horizons)]
    selected = {}
    for animal, windows in forecasts.items():
        labels = [row for row in observations.eligible(animal, effective_before, knowledge_cutoff,
                                                       include_terminal=True) if row.kind not in ENTRY_TICKETS]
        if not labels:
            continue
        stamps = [row.measured_at for row in labels]
        for window in windows:
            if window.origin + leads[0][1] - 3 * DAY > stamps[-1]:
                break
            for horizon, lead in leads:
                target = window.origin + lead
                i = bisect_left(stamps, target - 3 * DAY)
                if i == len(labels) or stamps[i] > target + 3 * DAY:
                    continue
                label = labels[i]
                pair_key = (animal, horizon, label.observation_id)
                rank = (abs(label.measured_at - target), window.origin)
                if pair_key in selected and selected[pair_key][0] <= rank:
                    continue
                errors, legacy_b_error, legacy_capped = window.score(label)
                pair = {
                    "animal": animal, "lot": window.lot, "carry_in": window.carry_in, "origin": window.origin,
                    "target": label.measured_at, "horizon": horizon, "kind": label.kind,
                    "reason": window.reason, "errors": errors, "legacy_b_error": legacy_b_error,
                    "legacy_capped": legacy_capped,
                }
                if errors and extra_score is not None:
                    pair.update(extra_score(window, label))
                selected[pair_key] = rank, pair
    return [row for _, row in selected.values()]


def calibrate(rows, minimum):
    if len(rows) < minimum:
        return None
    lots = Counter(row["lot"] for row in rows)
    limits = []
    for column in range(2):
        weighted = sorted((row["errors"][column], 1 / lots[row["lot"]]) for row in rows)
        cumulative = 0
        quantiles = []
        for error, weight in weighted:
            cumulative += weight
            if not quantiles and cumulative >= .05 * len(lots):
                quantiles.append(error)
            if cumulative >= .95 * len(lots):
                quantiles.append(error)
                break
        limits.append(quantiles)
    return limits


def interval_folds(forecasts, observations, reported, horizons, development, minimum):
    # Cohort membership is known without any target weights or ticket availability.
    training = {animal: windows for animal, windows in forecasts.items()
                if not windows[0].carry_in and not lot_holdout(windows[0].lot)}
    cutoffs = {min(row["origin"], development) for row in reported}
    results = {}
    for cutoff in sorted(cutoffs | {development}):
        pool = defaultdict(list)
        for row in forecast_pairs(training, observations, horizons, development, cutoff):
            if row["errors"]:
                pool[row["horizon"]].append(row)
        for horizon in horizons:
            rows = pool[horizon]
            results[cutoff, horizon] = (len(rows), calibrate(rows, minimum))
    return results


def summarize(rows, thresholds, folds, development, *, support_level="primary"):
    usable = [row for row in rows if row["errors"]]
    count, animals, lots = len(usable), len({row["animal"] for row in usable}), len({row["lot"] for row in usable})
    coverage = count / len(rows) if rows else 0
    support = {
        name: (count >= thresholds[f"{name}_pairs"] and animals >= thresholds[f"{name}_animals"]
               and lots >= thresholds[f"{name}_lots"] and coverage >= thresholds["min_prediction_coverage"])
        for name in ("primary", "stratum")
    }
    return {
        "forecast_target_pairs": len(rows), "eligible_pairs": count, "eligible_animals": animals, "eligible_lots": lots,
        "prediction_coverage": round(coverage, 6) if rows else None,
        "eligibility": dict(Counter(row["reason"] for row in rows)),
        "legacy_capped_model_b_pairs": sum(row["legacy_capped"] for row in usable),
        "actual_lead_days": ([min((row["target"] - row["origin"]) / DAY for row in rows),
                              max((row["target"] - row["origin"]) / DAY for row in rows)] if rows else None),
        "support_level": support_level,
        "meets_sample_support": support[support_level],
        "meets_primary_support": support["primary"],
        "meets_stratum_support": support["stratum"],
        "observed_errors": error_metrics(usable, folds, development) if usable else None,
    }


def errors_summary(errors):
    return {"mae_kg": round(fmean(map(abs, errors)), 4), "bias_kg": round(fmean(errors), 4)}


def error_metrics(rows, folds, development):
    result = {}
    for column, label in enumerate(("A", "B")):
        fitted = []
        for row in rows:
            cutoff = min(row["origin"], development)
            _, quantiles = folds[cutoff, row["horizon"]]
            if quantiles is not None:
                low, high = quantiles[column]
                fitted.append((row["errors"][column], low, high))
        stats = errors_summary([row["errors"][column] for row in rows])
        stats.update(
            interval_pairs=len(fitted), interval_pairs_without_calibration=len(rows) - len(fitted),
            interval_width_kg=round(median(high - low for _, low, high in fitted), 4) if fitted else None,
            interval_coverage=round(fmean(low <= error <= high for error, low, high in fitted), 6) if fitted else None,
        )
        result[label] = stats
    a, b = result["A"]["mae_kg"], result["B"]["mae_kg"]
    result["relative_mae_improvement_b_vs_a"] = round((a - b) / a, 6) if a else None
    result["legacy_B"] = errors_summary([row["legacy_b_error"] for row in rows])
    return result


def evaluate(config, tables, provenance):
    protocol = json.loads((STAGE5 / "evaluation.json").read_bytes())
    seeds = json.loads((STAGE5 / "pilot.json").read_bytes())["seeds"]

    def boundary(key):
        return datetime.fromisoformat(protocol[key]).replace(tzinfo=EDMONTON).astimezone(UTC)

    cutoff = boundary("evaluation_knowledge_cutoff_local")
    development = boundary("development_target_before_local")
    temporal_start = boundary("temporal_holdout_target_from_local")
    temporal_stop = boundary("temporal_holdout_target_until_local_exclusive")
    estimator, opening = observation_history(config, tables, cutoff)
    forecasts = forecast_origins(config, estimator, opening)
    leads = protocol["horizons_elapsed_days"]
    reported = forecast_pairs(forecasts, estimator.observations, leads, cutoff, cutoff)
    thresholds = protocol["sufficiency"]
    folds = interval_folds(forecasts, estimator.observations, reported, leads, development,
                           thresholds["calibration_pairs_per_horizon"])
    horizons = {}
    for horizon in leads:
        july_pairs, july_quantiles = folds[development, horizon]
        groups = {name: [] for name in ("lot_holdout", "temporal_holdout", "intersection", "carry_in")}
        for row in reported:
            if row["horizon"] != horizon:
                continue
            if row["carry_in"]:
                groups["carry_in"].append(row)
                continue
            is_lot = lot_holdout(row["lot"])
            is_temporal = temporal_start <= row["target"] < temporal_stop
            if is_lot:
                groups["lot_holdout"].append(row)
            if is_temporal:
                groups["temporal_holdout"].append(row)
            if is_lot and is_temporal:
                groups["intersection"].append(row)
        horizons[str(horizon)] = {
            "calibration_pairs_at_july_cutoff": july_pairs,
            "july_residual_quantiles_kg": dict(zip(("A", "B"), july_quantiles, strict=True)) if july_quantiles else None,
            "calibration_folds_with_intervals": sum(limits is not None for (_, lead), (_, limits) in folds.items()
                                                    if lead == horizon),
            "interval_status": "rolling_vintage" if july_quantiles else "insufficient_calibration_pairs_at_july_cutoff",
            **{name: summarize(rows, thresholds, folds, development,
                               support_level="primary" if name in ("lot_holdout", "temporal_holdout") else "stratum") | {
                "by_ticket_kind": {kind.value: summarize([row for row in rows if row["kind"] == kind], thresholds,
                                                         folds, development, support_level="stratum")
                                   for kind in Kind if kind not in ENTRY_TICKETS},
            } for name, rows in groups.items()},
        }
    return {
        **provenance, "protocol_version": protocol["version"], "report_version": "stage5-saved-holdout.2",
        "stage5_status": "incomplete", "promotion_eligible": False, "evaluated_seed": config["seed"],
        "required_seeds": seeds, "support_thresholds": thresholds, "acceptance_thresholds": protocol["acceptance"],
        "horizons": horizons,
        "origin_schedule": "Monday 08:00 America/Edmonton; elapsed UTC horizons",
        "deduplication": "same animal, horizon and final ticket; closest nominal target then earliest origin",
        "evaluator_commit": git_commit(),
        "forecast_rule": "stage5-origin-projection.1; cap the anchor-to-origin nowcast; extend at origin ADG",
        "legacy_forecast_rule": "Stage 2 projection cap from the anchor through the target",
        "confidence_rule": "anchor freshness at origin; shared eligible pairs for A and both B rules",
        "interval_rule": "development ticket vintage at min(origin, July cutoff); equal weight per lot",
        "error_convention": "prediction minus observation; interval = [prediction - q95, prediction - q05]",
        "scope": "observed single-seed diagnostics; no multi-seed, clustered bootstrap or full promotion assessment",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(*read_saved(args.archive))
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.exit(2, f"Evaluasi arsip gagal: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
