"""Collect reproducible preflight result counts and validation reports."""

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import platform


def read(path):
    return json.loads(path.read_bytes())


def machine():
    cgroup = Path("/sys/fs/cgroup")
    cpuinfo = Path("/proc/cpuinfo")
    details = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus_visible": len(os.sched_getaffinity(0)),
    }
    if cpuinfo.exists():
        details["cpu_model"] = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                                     if line.startswith("model name")), None)
    for key, file in (("cpu_quota_usec_and_period_usec", "cpu.max"), ("memory_limit_bytes", "memory.max"),
                      ("effective_cpuset", "cpuset.cpus.effective")):
        if (cgroup / file).exists():
            details[key] = (cgroup / file).read_text().strip()
    return details


def collect(dataset, profile):
    diagnostics = read(dataset / "diagnostics.json")
    performance = read(dataset / "performance.json")
    validation = read(dataset / "validation.json")
    hashes = read(dataset / "hashes.json")
    manifest = read(dataset / "run_manifest.json")
    config = read(dataset / "config.json")
    closes = read(dataset / "monthly_summary.json")
    counts = Counter()
    for part in hashes["partitions"].values():
        counts[part["table"]] += part["rows"]
    calendar = (date.fromisoformat(config["end"]) - date.fromisoformat(config["start"])).days + 1
    totals = {key: {"closing_wip_cents": next(row["closing_wip_cents"] for row in reversed(closes) if row["view"] == key),
                    "close_count": sum(row["view"] == key for row in closes)} for key in {"as_known", "restated"}}
    checks_passed = all(row["failed_count"] == 0 for row in (*validation["movement"], *validation["financial"]))
    hard_gates_passed = all(row["passed"] for row in validation["hard_gates"].values())
    if not checks_passed or not hard_gates_passed:
        raise ValueError(f"benchmark validation failed: {dataset}")
    if diagnostics["head"]["placements"] != sum(row["head"] for row in config["placements"]):
        raise ValueError("benchmark placement backlog remained at the horizon")
    phases = profile["timings"]
    return {
        "dataset": dataset.name, "run_id": hashes["run_id"], "schema_version": hashes["schema_version"],
        "code_checkout_commit": manifest["code_checkout_commit_at_build"],
        "input_hashes": manifest["input_hashes"],
        "hashes_sha256": manifest["hashes_sha256"], "config_sha256": manifest["config_sha256"],
        "calendar": {"start": config["start"], "end": config["end"], "days": calendar},
        "seed": config["seed"], "head": diagnostics["head"], "stock_reporting": diagnostics.get("stock_reporting"),
        "peak_concurrent_inventory": diagnostics.get("peak_concurrent_inventory"),
        "animal_days": diagnostics["animal_days"], "feeding_windows": phases["feeding"]["calls"],
        "counts_by_table": counts, "closes": totals, "operating_exceptions": diagnostics["exceptions"],
        "realized_sale_dof": diagnostics["carcass"]["sale_dof"], "performance": performance,
        "wall_seconds_including_atomic_publish": profile["wall_seconds_including_atomic_publish"],
        "performance_phases": phases, "book_view_profiles": profile.get("book_view_profiles"), "weather": {key: value for key, value in read(dataset / "weather.json").items()
                                                 if key.endswith("_seconds")},
        "validation": {
            "status": "passed", "gate_category_count": len(validation["hard_gates"]),
            "assertion_count": sum(row["assertions"] for row in validation["hard_gates"].values()),
            "gates": validation["hard_gates"],
            "movement_checks": len(validation["movement"]), "stage4_controls": len(validation["financial"]),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    result = {"machine": machine(),
              "runs": [collect(args.work / name, read(args.work / f"{name}-profile.json")) for name in args.runs]}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
