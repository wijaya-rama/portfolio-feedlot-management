"""Read saved pilot metadata and project resources without starting a build."""

import argparse
from hashlib import sha256
import json
from math import ceil, isfinite
from pathlib import Path

from .holdout import EVALUATION_ONLY, PILOT_CODE, require

GIB = 1024**3
ARCHIVE = "dataset-evaluation-only.tar"
PLACEMENT_SCALE = 15000 / 1500
PLANNING_MULTIPLIER = 1.5  # Upper sensitivity from FINAL_DATASET_READINESS.md.
FLOORS_GIB = {"ram": 24, "local_disk": 120, "drive": 85}


def positive(value, label):
    require(type(value) in (int, float) and isfinite(value) and value > 0, f"Invalid or missing {label}.")
    return value


def project(pilot_dir):
    status = json.loads((pilot_dir / "status.json").read_bytes())
    require(status["status"] == "completed" and status["purpose"] == EVALUATION_ONLY
            and status["code_sha"] == PILOT_CODE and status["config_version"] == "stage7-pilot-1500.1"
            and status["placements"] == status["head"]["placements"] == 1500
            and status["validation_status"] == "passed" and status["complete_independent_audit"] is True
            and status["financial_closes"] == 48, "Expected completed 1,500 pilot metadata with full audit and 48 closes.")
    raw = (pilot_dir / "performance.json").read_bytes()
    require(sha256(raw).hexdigest() == status["saved_sha256"]["performance.json"],
            "Performance SHA-256 differs from status.json.")
    perf = json.loads(raw)
    require(perf == status["performance"], "Performance values differ from status.json.")
    phases = perf["phases"]
    compute = {name: positive(phases[name]["seconds"], f"{name} seconds") for name in ("operations", "finance")}
    report_seconds = phases["report"]["seconds"]
    require(type(report_seconds) in (int, float) and isfinite(report_seconds) and report_seconds >= 0,
            "Invalid report seconds.")
    compute["audit_and_report"] = positive(phases["validation"]["seconds"], "validation seconds") + report_seconds
    peak_rss = max(positive(phases[name]["peak_rss_kib"], f"{name} peak RSS")
                   for name in ("operations", "finance", "validation", "report")) * 1024
    require(peak_rss == positive(perf["peak_rss_kib_linux"], "reported peak RSS") * 1024,
            "Phase RSS differs from aggregate peak.")
    parquet_bytes = positive(perf["parquet_bytes"], "Parquet bytes")
    package_bytes = positive(status["package_bytes"], "final archive bytes")
    checkpoints = {name: positive(status["checkpoints"][name]["bytes"], f"{name} checkpoint bytes")
                   for name in ("operations", "finance")}
    checkpoint_bytes = sum(checkpoints.values())
    save_seconds = positive(status["save_seconds"], "final archive/save seconds")
    verify_seconds = positive(status["artifact_verification_seconds"], "artifact verification seconds")
    disk_bytes = {"ram": peak_rss, "local_disk": checkpoint_bytes + parquet_bytes + package_bytes,
                  "drive": checkpoint_bytes + package_bytes}
    stress = PLACEMENT_SCALE * PLANNING_MULTIPLIER
    return {
        "scope": "planning_only",
        "production_authorized": False,
        "run_id": status["run_id"],
        "pilot_archive_sha256": status["saved_sha256"][ARCHIVE],
        "pilot_seed": status["seed"],
        "scale": PLACEMENT_SCALE,
        "planning_multiplier": PLANNING_MULTIPLIER,
        "pilot_available_ram_gib": round(positive(status["resources"]["ram_available_bytes"], "pilot available RAM") / GIB, 3),
        "pilot_phase_seconds": compute,
        "pilot_peak_rss_gib": round(peak_rss / GIB, 3),
        "pilot_checkpoint_gib": {key: round(value / GIB, 3) for key, value in checkpoints.items()},
        "pilot_package_gib": round(package_bytes / GIB, 3),
        "projected_phase_hours": {phase: {"linear": round(seconds * PLACEMENT_SCALE / 3600, 3),
                                         "planning": round(seconds * stress / 3600, 3)}
                                  for phase, seconds in compute.items()},
        "projected_verify_and_save_hours_excluding_checkpoints": round((verify_seconds + save_seconds) * stress / 3600, 3),
        "planning_floors_gib": {name: max(FLOORS_GIB[name], ceil(value * stress / GIB))
                                for name, value in disk_bytes.items()},
        "longest_compute_phase": max(compute, key=compute.get),
        "unmeasured": ["transient SQLite and sort high-water", "per-phase checkpoint copy and restore wall time",
                       "production-scale nonlinear memory growth", "uninterrupted production runtime window"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(project(args.pilot_dir), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
