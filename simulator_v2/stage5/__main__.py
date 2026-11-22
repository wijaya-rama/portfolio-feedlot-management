"""Publish an immutable Stage 5 diagnostic build. This entry point is fixture-only."""

import argparse
from datetime import datetime
from hashlib import sha256 as new_digest
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.parquet as pq

from ..stage1.__main__ import git_commit, runtime
from ..stage1.model import UTC
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.snapshots import publish_directory
from ..stage2.estimation import Estimate
from ..stage2.export import _write_table
from ..stage2.observations import Observation
from ..stage3.allocation import Allocation, Plan
from ..stage3.biology import GrowthInput
from ..stage3.ration import Delivery
from ..stage3_5.provenance import DecisionSource
from ..stage4.ledger import Journal
from .biology import NutrientStep
from .experiments import run
from .fixture import settings
from .pilot import capacity, plan
from .weather import ARCHIVE

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE_COMMIT = "47c2c64e76972a37d761ece021f8685afadcc03a"
SCHEMA = "stage5-evidence.1"
PINNED_INPUTS = (
    "simulator_v2/stage2/scenario.json", "simulator_v2/stage3/scenario.json",
    "simulator_v2/stage3_5/scenario.json", "simulator_v2/stage4/policy.json",
    "simulator_v2/stage5/calibration.json", "simulator_v2/stage5/pilot.json",
    "simulator_v2/stage5/evaluation.json",
)
SOURCE_DIRS = ("stage1", "stage2", "stage3", "stage3_5", "stage4", "stage5")


def write_verified_table(folder, name, record_type, values, run_id):
    result = _write_table(folder, name, record_type, values, run_id)
    path = f"{name}.parquet"
    parquet = pq.ParquetFile(folder / path)
    digest = new_digest()
    rows = 0
    for batch in parquet.iter_batches():
        rows += batch.num_rows
        for row in batch.to_pylist():
            digest.update(canonical(row))
    if rows != result["rows"]:
        raise ValueError(f"published Parquet row count differs: {name}")
    # Round-trip through the published types, which normalize numeric literals.
    return {**result, "path": path, "canonical_sha256": digest.hexdigest()}


def build(output, seed=42):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Stage 5 evidence already exists: {output}")
    calibration = settings()
    results = run(seed, calibration)
    operations = results["operations"]
    input_hashes = {name: sha256((ROOT / name).read_bytes()) for name in PINNED_INPUTS}
    provenance = ARCHIVE / "weather_manifest.json"
    input_hashes[str(provenance.relative_to(ROOT))] = sha256(provenance.read_bytes())
    archived_indices = {stage: sha256((HERE.parent / stage / "evidence" / "hashes.json").read_bytes())
                        for stage in SOURCE_DIRS[:-1]}
    code = {
        str(path.relative_to(ROOT)): sha256(path.read_bytes())
        for name in SOURCE_DIRS for path in sorted((HERE.parent / name).glob("*.py"))
    }
    archive = results["archive_metadata"]
    run_id = stable_id("STAGE5-RUN", [SCHEMA, seed, input_hashes, archive["raw_sha256"], archived_indices, code])

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".stage5-", dir=output.parent) as temp:
        stage = Path(temp) / "build"
        stage.mkdir()
        artifacts = {
            "experiments.json": results["experiments"],
            "validation.json": results["cross_stage_checks"],
            "finance.json": results["financial_evidence"],
            "weather.json": {**results["weather_coverage"], "source": archive,
                             "availability": "retrospective only, no forecast vintages in this fixture",
                             "extension_attempt": "network CONNECT 403 before provider response"},
            "archived_comparison.json": results["prior_baseline"],
            "backtest_fixture.json": results["backtest"],
            "pilot_capacity.json": capacity(plan()),
        }
        for name, rows in artifacts.items():
            (stage / name).write_bytes(canonical(rows))
        method = operations.scenario["method"]
        operational_allocations = tuple(item for row in results["scale_settlements"] for item in row.allocations
                                        if item.method == method)
        reconciled_allocations = tuple(item for row in operations.active_settlements for item in row.allocations
                                       if item.method == method)
        physical = results["physical"]
        tables = {
            "operational_growth": (NutrientStep, operations.biology.steps),
            "retrospective_growth": (NutrientStep, physical.steps),
            "operational_nutrient_inputs": (GrowthInput, operations.growth_inputs),
            "retrospective_nutrient_inputs": (GrowthInput, physical.adapter.growth_inputs(physical)),
            "operational_allocations": (Allocation, operational_allocations),
            "reconciled_allocations": (Allocation, reconciled_allocations),
            "feed_deliveries": (Delivery, operations.deliveries),
            "scale_observations": (Observation, operations.observations),
            "decision_plans": (Plan, operations.schedule.plans),
            "decision_estimates": (Estimate, operations.schedule.estimates),
            "decision_sources": (DecisionSource, operations.decision_sources),
            "posted_journal": (Journal, results["journal"]),
        }
        table_hashes = {name: write_verified_table(stage, name, kind, values, run_id)
                        for name, (kind, values) in tables.items()}
        hashes = canonical({
            "run_id": run_id, "schema": SCHEMA, "synthetic": True, "tables": table_hashes,
            "files": {file.name: sha256(file.read_bytes()) for file in sorted(stage.iterdir())},
        })
        (stage / "hashes.json").write_bytes(hashes)
        manifest = {
            "run_id": run_id, "schema": SCHEMA, "synthetic": True, "seed": seed,
            "config_sha256": input_hashes, "generator_source_sha256": code, "archived_stage_indices": archived_indices,
            "historical_weather_raw_sha256": archive["raw_sha256"], "model": calibration["biology_version"],
            "source_baseline_commit": BASE_COMMIT, "git_checkout_at_build": git_commit(),
            "runtime": runtime(), "hashes_sha256": sha256(hashes), "created_at_utc": datetime.now(UTC),
            "operational_weather": "seasonal scenario", "retrospective_weather": "archive with separate seasonal fallback",
            "pilot_executed": False,
        }
        (stage / "run_manifest.json").write_bytes(canonical(manifest))
        if not publish_directory(stage, output):
            raise FileExistsError(f"Stage 5 evidence already exists: {output}")
    return run_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_id = build(args.output, args.seed)
    print(canonical({"run_id": run_id, "status": "passed", "synthetic": True}).decode(), end="")


if __name__ == "__main__":
    main()
