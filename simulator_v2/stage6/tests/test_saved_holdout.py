"""Saved-archive evaluation and distinct pilot authorization."""

import ast
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
import tarfile
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from simulator_v2.stage2.observations import correct
from simulator_v2.stage6.__main__ import build
from simulator_v2.stage6.colab import holdout
from simulator_v2.stage6.config import HERE, at
from simulator_v2.stage6.tests.test_stage6 import controlled, read


def test_historical_config_cannot_furnish_five_seeds():
    config = json.loads((HERE / "configs/stage6b1-baseline-250.json").read_bytes())
    held = [row for slot, row in enumerate(config["placements"], 1)
            if holdout.lot_holdout(f"SYN-LOT-{slot:04d}")]
    assert len(held) == 18 and sum(row["head"] for row in held) == 75
    assert config["seed"] == 42


def test_replay_recovers_weekly_features_and_future_corrections_only_as_labels(tmp_path):
    config = controlled(start="2025-08-25", end="2025-11-30",
                        placements=[{"date": "2025-08-25", "head": 1, "mean_kg": 370},
                                    {"date": "2025-08-26", "head": 1, "mean_kg": 370},
                                    {"date": "2025-08-27", "head": 1, "mean_kg": 370}],
                        capacities={"receiving": [4], "production": [5], "hospital": [1]},
                        carry_in=[{"head": 1, "location": "SYN-P01", "weight_kg": 480,
                                   "entry_age_days": 390, "days_on_feed": 80, "wip_cents": 190000,
                                   "status": "active", "source": "SYN-HOLDOUT-OPEN"}],
                        follow_up_days=6)
    output = tmp_path / "fixture"
    build(config, output)
    tables = defaultdict(list)
    for name in holdout.TABLES | {"health_events"}:
        tables[name] = [{key: value for key, value in row.items() if key != "run_id"} for row in read(output, name)]
    report = holdout.evaluate(config, tables, {})
    assert report["stage5_status"] == "incomplete" and report["promotion_eligible"] is False
    assert report["evaluated_seed"] == 42 and len(report["required_seeds"]) == 5
    for horizon in ("7", "30", "60"):
        result = report["horizons"][horizon]
        assert result["intersection"]["eligible_pairs"] > 0
        assert result["intersection"]["eligible_lots"] == 1
        assert not result["intersection"]["meets_sample_support"]
        assert result["interval_status"] == "insufficient_calibration_pairs"
    assert report["horizons"]["60"]["intersection"]["capped_model_b_pairs"] > 0
    assert report["horizons"]["7"]["carry_in"]["eligible_animals"] == 1

    cutoff = at(date(2026, 2, 1), 0)
    development = at(date(2025, 7, 1), 0)
    protocol = {"horizons_elapsed_days": [7, 30, 60]}
    estimator, opening = holdout.observation_history(config, tables, cutoff)
    labels = [row for row in estimator.observations.records
              if row.kind == "follow_up" and row.measured_at >= at(date(2025, 10, 1), 0)]
    original = labels[0]
    revision = correct(original, source_id="SYN-TEST-FUTURE-CORRECTION",
                       posted_at=cutoff - timedelta(hours=1), available_at=cutoff,
                       measured_weight_kg=original.measured_weight_kg + 22)
    tables["weight_observations"].append(vars(revision))
    revised_estimator, revised_opening = holdout.observation_history(config, tables, cutoff)
    origin = original.measured_at + timedelta(days=1)
    old_snapshot = estimator.snapshot(origin)[0]
    assert old_snapshot == revised_estimator.snapshot(origin)[0]
    before, _ = holdout.forecast_pairs(config, estimator, opening, protocol, cutoff, development)
    after, _ = holdout.forecast_pairs(config, revised_estimator, revised_opening, protocol, cutoff, development)
    for pairs in (before, after):
        assert len(pairs) == len({(row["animal"], row["horizon"], row["target"]) for row in pairs})
    changed = [row for row in before if row["animal"] == original.animal_id
               and row["target"] == original.measured_at and row["errors"]]
    assert changed
    for row in changed:
        corresponding = next(candidate for candidate in after if candidate["animal"] == row["animal"]
                             and candidate["target"] == row["target"] and candidate["horizon"] == row["horizon"])
        assert corresponding["errors"] == pytest.approx([error - 22 for error in row["errors"]])


def saved_archive(tmp_path, *, size=250):
    baseline = size == 250
    config = json.loads((HERE / "configs" / ("stage6b1-baseline-250.json" if baseline
                                              else "stage7-pilot-1500.json")).read_bytes())
    code = holdout.BASELINE_CODE if baseline else holdout.git_commit()
    version = holdout.SCHEMA
    run = "SYN-STAGE6-RUN-archive-reader-test"
    hash_bytes = lambda data: sha256(data).hexdigest()
    files, parts = {}, {}
    audit = {"mode": "full", "complete_independent_audit": True,
             "hard_gates": {key: {"passed": True} for key in holdout.AUDIT_GATES},
             "movement": [{"failed_count": 0}], "financial": [{"failed_count": 0}]}
    for table in holdout.TABLES:
        kinds = ["receipt"] * size if table == "movement_events" else ["fixture"]
        sink = BytesIO()
        pq.write_table(pa.table({"run_id": [run] * len(kinds), "kind": kinds}), sink)
        payload = sink.getvalue()
        name = f"{table}/part.parquet"
        parts[name] = {"table": table, "rows": len(kinds), "bytes": len(payload), "sha256": hash_bytes(payload)}
        files[name] = payload
    for name, payload in (("config.json", config), ("validation.json", audit)):
        files[name] = json.dumps(payload).encode()
    files["hashes.json"] = json.dumps({"run_id": run, "schema_version": version, "partitions": parts,
                                      "artifacts": {name: hash_bytes(files[name]) for name in (
                                          "config.json", "validation.json")}}).encode()
    files["run_manifest.json"] = json.dumps({"synthetic": True, "code_checkout_commit_at_build": code,
                                             "schema_version": version, "run_id": run,
                                             "hashes_sha256": hash_bytes(files["hashes.json"]),
                                             "config_sha256": hash_bytes(files["config.json"])}).encode()
    files["performance.json"] = b"{}"
    archive = tmp_path / ("dataset.tar" if baseline else "dataset-evaluation-only.tar")
    with tarfile.open(archive, "w") as tar:
        for name, payload in files.items():
            member = tarfile.TarInfo("dataset/" + name)
            member.size = len(payload)
            tar.addfile(member, BytesIO(payload))
    hashes = {name: hash_bytes(payload) for name, payload in files.items()}
    hashes[archive.name] = holdout.digest(archive)
    status = {"status": "completed", "validation_status": "passed", "complete_independent_audit": True,
              "financial_closes": 48, "head": {"placements": size, "opening": 1},
              "placements": size, "config_version": config["version"], "seed": 42, "code_sha": code,
              "run_id": run, "package_bytes": archive.stat().st_size, "saved_sha256": hashes}
    if not baseline:
        status.update(purpose="evaluation_only", stage5_status="incomplete", promotion_eligible=False)
    return archive, status


@pytest.mark.parametrize("size", [250, 1500])
def test_reader_checks_audit_scope_archive_hash_and_receipts(tmp_path, size):
    archive, status = saved_archive(tmp_path, size=size)
    marker = tmp_path / "status.json"
    marker.write_text(json.dumps(status))
    config, tables, provenance = holdout.read_saved(archive)
    assert provenance["placements"] == len(tables["movement_events"]) == size
    assert config["seed"] == 42
    marker.write_text(json.dumps(status | {"complete_independent_audit": False}))
    with pytest.raises(ValueError, match="complete audit"):
        holdout.read_saved(archive)
    marker.write_text(json.dumps(status | {"stage5_status": "passed"}))
    if size == 1500:
        with pytest.raises(ValueError, match="complete audit"):
            holdout.read_saved(archive)
    marker.write_text(json.dumps(status))
    raw = archive.read_bytes()
    archive.write_bytes(raw[:-1] + b"X")
    with pytest.raises(ValueError, match="archive hash"):
        holdout.read_saved(archive)


def notebook_code(title):
    notebook = json.loads((HERE / "colab/Feedlot_V2_Benchmark.ipynb").read_bytes())
    return next("".join(cell["source"]) for cell in notebook["cells"]
                if "".join(cell["source"]).startswith(f"# @title {title}\n"))


def test_evaluation_pilot_requires_distinct_authorization_and_production_is_locked(tmp_path):
    code = notebook_code("Run Evaluation-Only Pilot")

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    prompts = []
    ns = {"require": require, "re": re, "input": prompts.append}
    exec(code, ns)
    assert prompts == [] and ns["Jalankan_pilot_evaluasi"] is False
    assert "Gerbang_estimator_selesai" not in code
    confirm = ns["pilot_confirmation"]
    assert confirm(1500, "") == "MULAI EVALUASI 1500"
    assert confirm(1500, "evaluation-1500-20261122-110450-deadbeef") == "LANJUT EVALUASI 1500"
    with pytest.raises(RuntimeError, match="15.000 HOLD"):
        confirm(15000, "")
    with pytest.raises(RuntimeError, match="khusus evaluasi"):
        confirm(1500, "placements-1500-20261122-110450-deadbeef")
    # Attempt creation independently enforces the same size guard as the UI.
    with pytest.raises(RuntimeError, match="15.000 HOLD"):
        ns["open_attempt"]({}, 15000, "")
    ns.update(
        SIZE=15000, Attempt_ID="", SOURCE=None, PYTHON=None,
        verify_source=lambda *_: pytest.fail("the production guard must run before source or worker calls"),
    )
    enabled = code.replace("Jalankan_pilot_evaluasi = False", "Jalankan_pilot_evaluasi = True")
    with pytest.raises(RuntimeError, match="15.000 HOLD"):
        exec(enabled, ns)
    assert prompts == []
    session, drive = tmp_path / "session", tmp_path / "drive"
    session.mkdir()
    drive.mkdir()
    ns.update(SESSION=session, DRIVE_ROOT=drive, REVIEWED_SHA="pinned", SEED=42, PINS=(),
              HEALTH_VERSION="baseline", SUPPLY_POLICY="material_specific", EVALUATION_ONLY="evaluation_only",
              environment=lambda _: {}, datetime=datetime, timezone=timezone, uuid=uuid, json=json,
              copy_verified=lambda source, dest: dest.write_bytes(source.read_bytes()))
    attempt = ns["open_attempt"]({"version": "pilot"}, 1500, "")
    state = json.loads((attempt["durable"] / "status.json").read_text())
    assert state["purpose"] == "evaluation_only" and state["stage5_status"] == "incomplete"
    assert state["promotion_eligible"] is False and state["validation_status"] == "pending"
    ns.update(
        SIZE=1500, PREFLIGHT={"version": "pilot"}, SELECTED_CONFIG={"version": "pilot"},
        verify_source=lambda *_: None, check_dependencies=lambda *_: None, require_pilot_resources=lambda *_: None,
        input=lambda _: "MULAI 1500",
    )
    calls = []
    ns.update(open_attempt=lambda *args: args, run_simulation=calls.append)
    guard = ast.parse(code).body[-1]
    execute = compile(ast.Module(body=[guard], type_ignores=[]), "<pilot authorization>", "exec")
    exec(execute, ns)
    assert calls == []
    ns["input"] = lambda _: "MULAI EVALUASI 1500"
    exec(execute, ns)
    assert calls == [({"version": "pilot"}, 1500, "")]
