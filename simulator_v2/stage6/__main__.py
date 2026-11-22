"""Build a new deterministic Stage 6A dataset."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from resource import RUSAGE_SELF, getrusage
from tempfile import TemporaryDirectory
from time import perf_counter

from ..stage1.__main__ import git_commit, runtime
from ..stage1.model import UTC
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.snapshots import publish_directory
from ..stage5.weather import ARCHIVE
from .config import DIAGNOSTIC, HERE, MODEL, SCHEMA, load
from .export import Output, digest
from .diagnostics import summarize
from .runner import Runner
from .validation import reconcile


def build(config, output):
    started = perf_counter()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for stage in ("stage1", "stage2", "stage3", "stage3_5", "stage4", "stage5", "stage6"):
        for path in sorted((HERE.parent / stage).glob("*")):
            if path.suffix in {".py", ".json", ".txt"}:
                inputs[str(path.relative_to(HERE.parents[1]))] = digest(path)
    if config["weather"]["retrospective"]:
        for path in sorted(ARCHIVE.iterdir()):
            if path.is_file():
                inputs[str(path.relative_to(HERE.parents[1]))] = digest(path)
    run_id = stable_id("STAGE6-RUN", [SCHEMA, config, inputs])
    with TemporaryDirectory(prefix=".stage6-", dir=output.parent) as temporary:
        staging = Path(temporary) / "dataset"
        staging.mkdir()
        writer = Output(staging, run_id)
        try:
            runner = Runner(config, run_id, writer)
            operations, timeline, daily, monthly, movement_checks = runner.operations()
            generated = perf_counter()
            closes = runner.finance(operations)
            accounted = perf_counter()
            tables = writer.finish()
            validation_started = perf_counter()
            hard_gates = reconcile(staging, tables, runner, timeline, daily, monthly, closes)
            reconciled = perf_counter()
        finally:
            writer.abort()
        diagnostics_started = perf_counter()
        diagnostics = summarize(staging, tables, runner, daily, monthly, closes)
        artifacts = {"config.json": config, "diagnostics.json": diagnostics,
                     "validation.json": {"mode": "full", "complete_independent_audit": True,
                                         "hard_gates": hard_gates, "movement": movement_checks,
                                         "financial": [check for _, close in closes for check in close[7]]},
                     "monthly_summary.json": [close[6] for _, close in closes],
                     "weather.json": {"archive": runner.archive, "operational_seconds": runner.operational.weather_totals,
                                      "retrospective_seconds": runner.retro.weather_totals if runner.retro else None}}
        for name, value in artifacts.items():
            (staging / name).write_bytes(canonical(value))
        index = canonical({"run_id": run_id, "schema_version": SCHEMA, "partitions": tables,
                           "artifacts": {name: digest(staging / name) for name in artifacts}})
        (staging / "hashes.json").write_bytes(index)
        manifest = {"run_id": run_id, "model_version": MODEL, "schema_version": SCHEMA, "synthetic": True,
                    "calendar": "America/Edmonton", "built_at": datetime.now(UTC), "runtime": runtime(),
                    "code_checkout_commit_at_build": git_commit(), "input_hashes": inputs,
                    "config_sha256": sha256(canonical(config)), "hashes_sha256": sha256(index),
                    "effective_before": runner.end, "final_knowledge_cutoff": runner.cutoff,
                    "archive": runner.archive}
        (staging / "run_manifest.json").write_bytes(canonical(manifest))
        (staging / "performance.json").write_bytes(canonical({
            "operations_seconds": round(generated - started, 3),
            "accounting_and_close_seconds": round(accounted - generated, 3),
            "cross_domain_validation_seconds": round(reconciled - validation_started, 3),
            "diagnostics_and_manifest_seconds": round(perf_counter() - diagnostics_started, 3),
            "wall_seconds_before_atomic_rename": round(perf_counter() - started, 3),
            "peak_rss_kib_linux": getrusage(RUSAGE_SELF).ru_maxrss,
            "parquet_bytes": sum(part["bytes"] for part in tables.values()),
            "parquet_partitions": len(tables),
            "snapshot_parquet_bytes": sum(part["bytes"] for part in tables.values() if part["table"] in {
                "decision_snapshots", "physical_contexts", "feed_access_snapshots", "finance_snapshots"}),
            "largest_partition_bytes": max((part["bytes"] for part in tables.values()), default=0),
            "source_and_fact_counts": diagnostics["source_and_fact_counts"]
        }))
        if not publish_directory(staging, output):
            raise FileExistsError(output)
    return run_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(load(args.config, args.seed), args.output))


if __name__ == "__main__":
    main()
