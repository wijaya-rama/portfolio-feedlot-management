"""Build and independently audit one chronological Stage 6 dataset."""

import argparse
from datetime import datetime
from pathlib import Path
from resource import RUSAGE_SELF, getrusage
from shutil import copyfile
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace

import numpy as np

from ..stage1.__main__ import git_commit, runtime
from ..stage1.model import UTC
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.snapshots import publish_directory
from ..stage4.fixture import YardageDay
from ..stage5.weather import ARCHIVE
from .config import DIAGNOSTIC, HERE, MODEL, SCHEMA, load, validate
from .diagnostics import summarize
from .export import Output, digest
from .feeding import read_checkpoints
from .finance import Finance
from .recovery import Checkpoints, PHASES
from .runner import Runner
from .validation import Audit, reconcile


def input_hashes(config):
    inputs = {}
    for stage in ("stage1", "stage2", "stage3", "stage3_5", "stage4", "stage5", "stage6"):
        for path in sorted((HERE.parent / stage).glob("*")):
            if path.suffix in {".py", ".json", ".txt"}:
                inputs[str(path.relative_to(HERE.parents[1]))] = digest(path)
    if config["weather"]["retrospective"]:
        for path in sorted(ARCHIVE.iterdir()):
            if path.is_file():
                inputs[str(path.relative_to(HERE.parents[1]))] = digest(path)
    return inputs


def elapsed(start):
    return {"seconds": round(perf_counter() - start, 3), "peak_rss_kib": getrusage(RUSAGE_SELF).ru_maxrss}


def generate_operations(root, config, run_id):
    started = perf_counter()
    writer = Output(root / "dataset", run_id)
    try:
        runner = Runner(config, run_id, writer, retain_yardage=False)
        operations, replay, daily, monthly, movement_checks = runner.operations()
        tables = writer.finish()
    finally:
        writer.abort()
    # Retain independent replay inputs. The active scheduler, live nutrient reserves,
    # and Parquet writers have reached the end of their lifecycle.
    yard = runner.yard
    books_yard = SimpleNamespace(opening=yard.opening, entries=yard.entries, entry_costs=yard.entry_costs)
    sales = SimpleNamespace(settlements=runner.sales.settlements, carcasses=runner.sales.carcasses)
    operations.timeline.kinds = dict(operations.timeline.kinds)
    audit = SimpleNamespace(
        config=config, start=runner.start, end=runner.end, first=runner.first, last=runner.last,
        cutoff=runner.cutoff, calendar=runner.calendar, archive=runner.archive, daily_active=runner.daily_active,
        yard=SimpleNamespace(opening=yard.opening, pending=yard.pending, kinds=yard.kinds, capacity=yard.capacity),
        feeding=SimpleNamespace(planning=runner.feeding.planning),
        supply=SimpleNamespace(masters=runner.supply.masters, transactions=runner.supply.transactions,
                               max_bin=runner.supply.max_bin),
        warehouse_snapshot=runner.warehouse_snapshot, warehouse_stock_bridges=runner.warehouse_stock_bridges,
        operational=SimpleNamespace(weather_totals=runner.operational.weather_totals),
        retro=SimpleNamespace(weather_totals=runner.retro.weather_totals) if runner.retro else None,
    )
    state = SimpleNamespace(audit=audit, books_yard=books_yard, sales=sales, operations=operations,
                            replay=replay, daily=daily, monthly=monthly, movement_checks=movement_checks)
    return tables, state, elapsed(started)


def generate_finance(root, state, operations_root, run_id, tables):
    started = perf_counter()
    writer = Output(root / "dataset", run_id)
    audit = state.audit
    # Yardage is consumed twice in source order. Stream the sealed Parquet so the
    # finance phase can reopen in a fresh process without an animal-day object list.
    class Yardage:
        def __iter__(self):
            for row in Audit(operations_root / "dataset", tables).rows("yardage"):
                row.pop("run_id")
                yield YardageDay(**row)

    try:
        finance = Finance(state.books_yard, state.operations, state.sales, Yardage(), audit.config, audit.first,
                          audit.last, audit.cutoff, writer.emit,
                          read_checkpoints(operations_root / "feed-accounting-checkpoints.pickle"),
                          root / "finance.sqlite")
        try:
            closes = tuple(finance.books(audit.cutoff))
            approvals = tuple(finance.approvals)
        finally:
            finance.store.close()
        tables = writer.finish()
    finally:
        writer.abort()
    (root / "finance.sqlite").unlink()
    return tables, (closes, approvals), elapsed(started)


def publish(checkpoints, output, run_id, state, closes, tables_by_phase, identity, performance):
    with TemporaryDirectory(prefix=".stage6-publish-", dir=output.parent) as temporary:
        staging = Path(temporary)
        tables = {}
        for phase, partitions in tables_by_phase.items():
            if tables.keys() & partitions.keys():
                raise ValueError("operations and finance share a publication partition")
            for name in partitions:
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                source = checkpoints.root / phase / "dataset" / name
                if checkpoints.retain:
                    copyfile(source, target)
                else:
                    source.replace(target)
            tables.update(partitions)
        runner = state.audit
        started = perf_counter()
        hard_gates = reconcile(staging, tables, runner, state.replay, state.daily, state.monthly, closes)
        validation = elapsed(started)
        started = perf_counter()
        diagnostics = summarize(staging, tables, runner, state.daily, state.monthly, closes)
        artifacts = {"config.json": runner.config, "diagnostics.json": diagnostics,
                     "validation.json": {"mode": "full", "complete_independent_audit": True,
                                         "hard_gates": hard_gates, "movement": state.movement_checks,
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
                    "calendar": "America/Edmonton", "built_at": datetime.now(UTC), "runtime": identity["runtime"],
                    "code_checkout_commit_at_build": identity["commit"], "input_hashes": identity["inputs"],
                    "config_sha256": identity["config_sha256"], "hashes_sha256": sha256(index),
                    "effective_before": runner.end, "final_knowledge_cutoff": runner.cutoff,
                    "archive": runner.archive}
        (staging / "run_manifest.json").write_bytes(canonical(manifest))
        report = elapsed(started)
        stages = {**performance, "validation": validation, "report": report}
        (staging / "performance.json").write_bytes(canonical({
            "operations_seconds": stages["operations"]["seconds"],
            "accounting_and_close_seconds": stages["finance"]["seconds"],
            "cross_domain_validation_seconds": validation["seconds"],
            "diagnostics_and_manifest_seconds": report["seconds"],
            "wall_seconds_before_atomic_rename": round(sum(row["seconds"] for row in stages.values()), 3),
            "peak_rss_kib_linux": max(row["peak_rss_kib"] for row in stages.values()),
            "phases": stages,
            "parquet_bytes": sum(part["bytes"] for part in tables.values()),
            "parquet_partitions": len(tables),
            "snapshot_parquet_bytes": sum(part["bytes"] for part in tables.values() if part["table"] in {
                "decision_snapshots", "physical_contexts", "feed_access_snapshots", "finance_snapshots"}),
            "largest_partition_bytes": max((part["bytes"] for part in tables.values()), default=0),
            "source_and_fact_counts": diagnostics["source_and_fact_counts"]
        }))
        if not publish_directory(staging, output):
            raise FileExistsError(output)


def run_build(config, output, workspace, *, retain, stop_after):
    inputs = input_hashes(config)
    run_id = stable_id("STAGE6-RUN", [SCHEMA, config, inputs])
    identity = {"run_id": run_id, "commit": git_commit(), "inputs": inputs, "runtime": runtime(),
                "numpy": np.__version__, "config_sha256": sha256(canonical(config))}
    with Checkpoints(workspace, identity, retain) as checkpoints:
        if (checkpoints.root / "finance").exists() and not (checkpoints.root / "operations").exists():
            raise ValueError("finance checkpoint requires its operations checkpoint")
        op, state = checkpoints.run("operations", None, lambda root: generate_operations(root, config, run_id))
        if stop_after == "operations":
            return run_id
        op_root = checkpoints.root / "operations"
        fin, (closes, approvals) = checkpoints.run(
            "finance", digest(op_root / "checkpoint.json"),
            lambda root: generate_finance(root, state, op_root, run_id, op["partitions"]),
        )
        if stop_after == "finance":
            return run_id
        state.audit.financial_approvals = approvals
        publish(checkpoints, output, run_id, state, closes,
                {"operations": op["partitions"], "finance": fin["partitions"]}, identity,
                {"operations": op["performance"], "finance": fin["performance"]})
    return run_id


def build(config, output, *, workspace=None, stop_after=None):
    validate(config)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    if stop_after is not None and (stop_after not in PHASES or workspace is None):
        raise ValueError("stopping at a boundary requires a persistent checkpoint workspace")
    output.parent.mkdir(parents=True, exist_ok=True)
    if workspace is not None:
        workdir = Path(workspace).resolve()
        if output == workdir or workdir in output.parents or output in workdir.parents:
            raise ValueError("output and checkpoint workspace cannot contain one another")
        return run_build(config, output, workdir, retain=True, stop_after=stop_after)
    with TemporaryDirectory(prefix=".stage6-", dir=output.parent) as temporary:
        return run_build(config, output, temporary, retain=False, stop_after=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, help="trusted local workspace for completed phases")
    parser.add_argument("--stop-after", choices=PHASES, help="save a checkpoint without publishing a dataset")
    args = parser.parse_args()
    print(build(load(args.config, args.seed), args.output, workspace=args.checkpoint_dir, stop_after=args.stop_after))


if __name__ == "__main__":
    main()
