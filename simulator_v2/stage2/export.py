"""Write an isolated, atomic Stage 2 fixture with typed, hash-indexed tables."""

from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args, get_type_hints

import pyarrow as pa
import pyarrow.parquet as pq

from ..stage1.__main__ import git_commit, runtime
from ..stage1.model import UTC, midnight
from ..stage1.export import arrow_field
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.snapshots import publish_directory
from .backtest import LatentTarget, Pair, evaluate, latent_targets, report
from .biology import GrowthStep, Profile, WeatherDay
from .estimation import DraftAssessment, Estimate, EstimateSnapshot
from .fixture import END, FINAL_CUTOFF, START, build_fixture, draft_example, local
from .health import HealthEvent
from .observations import Observation, WeighAttempt
from .timeline import replay_digest
from .validation import validate_fixture

SCHEMA_VERSION = "stage2.1"


def _schema_field(name, annotation):
    if annotation is float or float in get_args(annotation):
        return pa.field(name, pa.float64(), nullable=type(None) in get_args(annotation))
    return arrow_field(name, annotation)


def _write_table(folder, name, record_type, rows, run_id):
    annotations = get_type_hints(record_type)
    schema = pa.schema([
        pa.field("run_id", pa.string(), nullable=False),
        *(_schema_field(field.name, annotations[field.name]) for field in fields(record_type)),
    ])
    records = [{"run_id": run_id, **asdict(row)} for row in rows]
    table = pa.Table.from_pylist(records, schema=schema)
    file = folder / f"{name}.parquet"
    pq.write_table(table, file, compression="zstd", version="2.6")
    return {"path": str(file.relative_to(folder.parent)), "rows": len(rows),
            "sha256": sha256(file.read_bytes()),
            "canonical_sha256": sha256(b"".join(map(canonical, records)))}


def _inputs(fixture):
    plans = []
    for plan in fixture.weighing_plans:
        row = asdict(plan)
        for name in ("posting_lag", "availability_lag"):
            row[f"{name}_seconds"] = row.pop(name).total_seconds()
        plans.append(row)
    return {"config": fixture.config, "profiles": fixture.profiles, "weather": fixture.weather,
            "clinical_inputs": fixture.clinical_inputs, "weighing_plans": plans,
            "physical_snapshot_id": fixture.timeline.snapshot_id,
            "physical_effective_before": fixture.timeline.result.effective_before,
            "physical_knowledge_cutoff": fixture.timeline.result.knowledge_cutoff,
            "physical_replay_sha256": replay_digest(fixture.timeline.result),
            "stage1_config": fixture.ledger.config,
            "stage1_events_sha256": sha256(canonical(fixture.ledger.events)),
            "observation_corrections": tuple(row for row in fixture.observations.records
                                             if row.corrects_observation_id is not None),
            "seed_streams": ["biology-individual", "biology-lot", "scale-missing", "scale-error"],
            "synthetic": True}


def build(output, seed=42):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"build directory already exists: {output}")
    fixture = build_fixture(seed)
    inputs = canonical(_inputs(fixture))
    run_id = stable_id("STAGE2-RUN", [SCHEMA_VERSION, fixture.timeline.run_id, sha256(inputs)])
    daily = tuple(fixture.estimator.daily(START, END))
    snapshots = {snap.snapshot_id: snap for snap, _ in daily}
    estimates = [row for _, rows in daily for row in rows]
    pairs, backtest_snapshots, forecasts = evaluate(
        fixture.estimator, fixture.profiles, start_at=midnight(START),
        evaluation_cutoff=FINAL_CUTOFF, config=fixture.config,
    )
    snapshots.update((row.snapshot_id, row) for row in backtest_snapshots)
    estimates.extend(forecasts)
    latent = latent_targets(pairs, fixture.biology, fixture.timeline.snapshot_id)
    observed_report = report(pairs, fixture.config, latent=latent)

    draft_snapshot, draft_estimates, draft = draft_example(fixture.estimator)
    snapshots[draft_snapshot.snapshot_id] = draft_snapshot
    estimates.extend(draft_estimates)
    revision_origin = local("2024-01-19 09:00")
    for knowledge, reason in ((revision_origin, None),
                              (local("2024-01-19 10:00"), "SYN-SCALE-CORR-05-JAN14")):
        snapshot, rows = fixture.estimator.estimates(revision_origin, knowledge, revision_reason=reason)
        snapshots[snapshot.snapshot_id] = snapshot
        estimates.extend(rows)

    snapshots = tuple(snapshots.values())
    estimates = tuple(estimates)
    checks = validate_fixture(fixture, snapshots, estimates, pairs, (draft,))
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".stage2-", dir=output.parent) as scratch:
        stage = Path(scratch) / "build"
        operational = stage / "operational"
        diagnostic = stage / "diagnostic"
        operational.mkdir(parents=True)
        diagnostic.mkdir()

        tables = (
            (operational, "weigh_attempts", WeighAttempt, fixture.attempts),
            (operational, "weight_observations", Observation, fixture.observations.records),
            (operational, "estimate_snapshots", EstimateSnapshot, snapshots),
            (operational, "weight_estimates", Estimate, estimates),
            (operational, "draft_assessments", DraftAssessment, (draft,)),
            (diagnostic, "animal_profiles", Profile, fixture.profiles),
            (diagnostic, "synthetic_weather", WeatherDay, fixture.weather),
            (diagnostic, "health_events", HealthEvent, fixture.health),
            (diagnostic, "biology_steps", GrowthStep, fixture.biology.steps),
            (diagnostic, "observed_backtest_pairs", Pair, pairs),
            (diagnostic, "latent_backtest_targets", LatentTarget, latent),
        )
        table_index = {name: _write_table(folder, name, cls, rows, run_id)
                       for folder, name, cls, rows in tables}
        (stage / "inputs.json").write_bytes(inputs)
        (stage / "backtest.json").write_bytes(canonical(observed_report))
        (stage / "validation.json").write_bytes(canonical({
            "run_id": run_id, "checks": checks, "status": "passed", "synthetic": True,
        }))
        files = {str(path.relative_to(stage)): sha256(path.read_bytes())
                 for path in sorted(stage.rglob("*")) if path.is_file()}
        hash_index = canonical({"run_id": run_id, "tables": table_index, "files": files})
        (stage / "hashes.json").write_bytes(hash_index)
        code_hashes = {path.name: sha256(path.read_bytes())
                       for path in sorted(Path(__file__).parent.glob("*.py"))}
        manifest = {
            "run_id": run_id, "stage1_run_id": fixture.timeline.run_id,
            "physical_snapshot_id": fixture.timeline.snapshot_id,
            "schema_version": SCHEMA_VERSION, "scenario_version": fixture.config["version"],
            "seed": fixture.timeline.seed, "git_commit": git_commit(), "generator_files": code_hashes,
            "generator_sha256": sha256(canonical(code_hashes)), "runtime": runtime(),
            "hashes_sha256": sha256(hash_index), "built_at": datetime.now(UTC),
            "status": "passed", "synthetic": True,
        }
        (stage / "run_manifest.json").write_bytes(canonical(manifest))
        if not publish_directory(stage, output):
            raise FileExistsError(f"build directory already exists: {output}")
    return run_id
