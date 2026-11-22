"""Project pilot resource ranges from measured 24-month workload increments."""

import argparse
import json
from pathlib import Path

from ..benchmark_configs import PLAN
from .collect import read

FACTS = ("growth_operational", "growth_retrospective", "feed_allocations", "accounting_feed_allocations",
         "journals_as_known", "journals_restated", "journal_lines", "financial_sources")


def phase(run, name):
    return run["performance_phases"][name]["seconds"]


def workload(run):
    counts = run["counts_by_table"]
    return {
        "animal_days": run["animal_days"],
        "feeding_windows": run["feeding_windows"],
        "month_ends": run["closes"]["as_known"]["close_count"],
        "movements": counts["movement_events"],
        "release_allocations": counts["feed_allocations"],
        "posting_allocations": counts["accounting_feed_allocations"],
        "source_events": counts["financial_sources"],
        "journals": counts["journals_as_known"] + counts["journals_restated"],
        "journal_lines": counts["journal_lines"],
        "published_audit_fact_rows": sum(counts.get(table, 0) for table in FACTS),
    }


def measures(run):
    perf = run["performance"]
    data = {
        "operations_seconds": perf["operations_seconds"],
        "accounting_and_close_seconds": perf["accounting_and_close_seconds"],
        "cross_domain_validation_seconds": perf["cross_domain_validation_seconds"],
        "wall_seconds": run["wall_seconds_including_atomic_publish"],
        "parquet_bytes": perf["parquet_bytes"],
        "peak_rss_kib": perf["peak_rss_kib_linux"],
        "close_journal_fingerprint_seconds": phase(run, "close_journal_fingerprints"),
        "file_hash_seconds": phase(run, "input_and_artifact_file_hashes") + phase(run, "parquet_file_hashes"),
    }
    data["accounting_and_validation_seconds"] = (
        data["accounting_and_close_seconds"] + data["cross_domain_validation_seconds"])
    data["fingerprint_and_file_hash_seconds"] = data["close_journal_fingerprint_seconds"] + data["file_hash_seconds"]
    return data


def project(anchor_a, anchor_b):
    a, b = map(workload, (anchor_a, anchor_b))
    values_a, values_b = map(measures, (anchor_a, anchor_b))

    def extend(base, current, x_base, x_current, x_target):
        return current + (current - base) * (x_target - x_current) / (x_current - x_base)

    plan = read(PLAN)
    capacity_report = read(PLAN.parent / "evidence" / "pilot_capacity.json")
    driver = {
        "operations_seconds": "animal_days", "accounting_and_close_seconds": "source_events",
        "cross_domain_validation_seconds": "published_audit_fact_rows",
        "wall_seconds": "animal_days", "parquet_bytes": "published_audit_fact_rows",
        "peak_rss_kib": "published_audit_fact_rows",
        "close_journal_fingerprint_seconds": "journals",
    }
    cases = []
    for scenario in capacity_report["capacity_scenarios"]:
        days = scenario["forecast_head_days_inclusive"]
        inputs = {key: round(extend(a[key], b[key], a["animal_days"], b["animal_days"], days))
                  for key in a}
        values = {key: round(extend(values_a[key], values_b[key], a[by], b[by], inputs[by]), 3)
                  for key, by in driver.items()}
        # The number of months is fixed. Bound file hashing using the measured bytes per second.
        values["file_hash_seconds"] = round(values_b["file_hash_seconds"] * values["parquet_bytes"]
                                             / values_b["parquet_bytes"], 3)
        values["fingerprint_and_file_hash_seconds"] = round(
            values["file_hash_seconds"] + values["close_journal_fingerprint_seconds"], 3)
        values["accounting_and_validation_seconds"] = round(
            values["accounting_and_close_seconds"] + values["cross_domain_validation_seconds"], 3)
        cases.append({"stay_days_stage5_capacity_scenario": scenario["stay_elapsed_days"],
                      "projected_workload": inputs, "projected_resources": values})
    preflight_days = [case["projected_workload"]["animal_days"] * 500 / plan["placements"] for case in cases]
    preflight_500 = {
        "placements": 500,
        "projected_animal_days": [round(days) for days in preflight_days],
        "projected_wall_seconds": [
            round(extend(values_a["wall_seconds"], values_b["wall_seconds"],
                         a["animal_days"], b["animal_days"], days), 3)
            for days in preflight_days
        ],
    }
    return {"status": "projection_only", "target_placements": plan["placements"],
            "release_target_placements": plan["final_release_placements"], "pilot_budgets": plan["budgets"],
            "method": "Same 24 months. Extend measured deltas at observed workload rates to Stage 5 animal-days.",
            "drivers": driver, "anchors": [{"placements": run["head"]["placements"], "workload": data,
                                            "measured_resources": values}
                                           for run, data, values in ((anchor_a, a, values_a), (anchor_b, b, values_b))],
            "cases": cases, "preflight_500": preflight_500}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs = {run["head"]["placements"]: run for run in read(args.measurements)["runs"] if run["seed"] == 42
            and run["calendar"]["days"] == 731}
    populations = sorted(runs)
    result = project(*(runs[size] for size in populations[-2:]))
    preflight = result["preflight_500"]
    if 500 in runs:
        preflight.update(status="measured", measured_resources=measures(runs[500]))
    elif (250 in runs and measures(runs[250])["cross_domain_validation_seconds"]
          > result["pilot_budgets"]["reconciliation_seconds"]):
        preflight.update(status="skipped",
                         decision_basis="The 250-placement validation alone exceeded the proposed reconciliation budget.")
    else:
        preflight["status"] = "unmeasured"
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
