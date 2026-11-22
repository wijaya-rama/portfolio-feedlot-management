"""Saved-archive evaluation and distinct pilot authorization."""

import ast
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import tarfile
import tempfile
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from simulator_v2.stage2.observations import Kind, Observations, correct
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
        assert result["interval_status"] == "insufficient_calibration_pairs_at_july_cutoff"
    assert report["horizons"]["60"]["intersection"]["legacy_capped_model_b_pairs"] > 0
    assert report["horizons"]["7"]["carry_in"]["eligible_animals"] == 1

    cutoff = at(date(2026, 2, 1), 0)
    horizons = [7, 30, 60]
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
    before = holdout.forecast_pairs(holdout.forecast_origins(config, estimator, opening),
                                    estimator.observations, horizons, cutoff, cutoff)
    after = holdout.forecast_pairs(holdout.forecast_origins(config, revised_estimator, revised_opening),
                                   revised_estimator.observations, horizons, cutoff, cutoff)
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
    code = holdout.BASELINE_CODE if baseline else holdout.PILOT_CODE
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
def test_reader_checks_audit_scope_archive_hash_and_receipts(tmp_path, size, monkeypatch):
    monkeypatch.setattr(holdout, "git_commit", lambda: "a-different-evaluator-commit")
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


def test_evaluation_cap_applies_to_nowcast_before_origin_only():
    origin = at(date(2025, 6, 2), 8)
    forecast = holdout.OriginForecast(origin, "SYN-LOT-0001", False, "eligible",
                                      400, origin - timedelta(days=14), 1.28, 35)
    for lead, expected, legacy, capped in ((0, 417.92, 417.92, False),
                                           (7, 426.88, 426.88, False),
                                           (30, 456.32, 444.8, True),
                                           (60, 494.72, 444.8, True)):
        label = SimpleNamespace(measured_at=origin + timedelta(days=lead), measured_weight_kg=450)
        error, legacy_error, legacy_capped = forecast.score(label)
        assert error == pytest.approx((-50, expected - 450))
        assert legacy_error == pytest.approx(legacy - 450)
        assert legacy_capped is capped


def test_interval_folds_resolve_label_versions_and_hold_out_lots_and_carry_in():
    origin = at(date(2025, 6, 2), 8)
    early, late, july = (at(date(2025, month, day), 8) for month, day in ((6, 16), (6, 23), (7, 1)))
    training = "SYN-LOT-0001"
    held = "SYN-LOT-0003"
    assert not holdout.lot_holdout(training) and holdout.lot_holdout(held)

    def ticket(identifier, measured, available, kg, *, parent=None):
        return SimpleNamespace(observation_id=identifier, measured_at=measured, available_at=available,
                               kind=Kind.FOLLOW_UP, quality_flag="corrected" if parent else "accepted",
                               corrects_observation_id=parent, measured_weight_kg=kg)

    measured = origin + timedelta(days=7)
    original = ticket("original", measured, measured, 402)
    revision = ticket("revision", measured, late, 406, parent="original")
    future_revision = ticket("future revision", measured, july + timedelta(days=1), 650, parent="revision")
    held_ticket = ticket("held", measured, measured, 900)
    carry_ticket = ticket("carry", measured, measured, 200)
    after_development = ticket("late target", july + timedelta(days=2), july + timedelta(days=2), 800)
    observations = object.__new__(Observations)
    observations.by_animal = {"development": (original, revision, future_revision, after_development),
                              "held": (held_ticket,), "carry": (carry_ticket,)}
    forecasts = {
        key: [holdout.OriginForecast(instant, lot, carry, "eligible", 400, instant, 1, 35) for instant in starts]
        for key, lot, carry, starts in (("development", training, False, (origin, july - timedelta(days=5))),
                                       ("held", held, False, (origin,)), ("carry", training, True, (origin,)))
    }
    reported = [{"origin": early}, {"origin": late}, {"origin": july + timedelta(days=14)}]
    folds = holdout.interval_folds(forecasts, observations, reported, [7], july, minimum=1)
    assert folds[early, 7] == (1, [[-2, -2], [5, 5]])
    assert folds[late, 7] == folds[july, 7] == (1, [[-6, -6], [1, 1]])
    assert len(folds) == 3


def test_intersection_exposes_primary_and_stratum_support_without_relaxing_primary():
    protocol = json.loads((holdout.STAGE5 / "evaluation.json").read_bytes())
    origin = at(date(2025, 10, 6), 8)
    cutoff = at(date(2025, 7, 1), 0)
    rows = [{"animal": f"A{i % 54}", "lot": f"LOT-{(i % 54) % 4}", "origin": origin,
             "target": origin + timedelta(days=60), "reason": "eligible", "errors": (-65, -30),
             "legacy_b_error": -30, "legacy_capped": True, "horizon": 60} for i in range(104)]
    folds = {(cutoff, 60): (100, [[-90, -50], [-35, -20]])}
    stratum = holdout.summarize(rows, protocol["sufficiency"], folds, cutoff, support_level="stratum")
    primary = holdout.summarize(rows, protocol["sufficiency"], folds, cutoff)
    assert stratum["meets_sample_support"] and stratum["meets_stratum_support"]
    assert not stratum["meets_primary_support"] and not primary["meets_sample_support"]
    assert stratum["observed_errors"]["B"]["interval_coverage"] == 1
    assert stratum["observed_errors"]["B"]["interval_width_kg"] == 15


def test_interval_quantiles_weight_each_development_lot_equally():
    rows = ([{"lot": "large", "errors": (0, 2)}] * 95 +
            [{"lot": "small", "errors": (100, 50)}] * 5)
    assert holdout.calibrate(rows, minimum=100) == [[0, 100], [2, 50]]
    assert holdout.calibrate(rows, minimum=101) is None


def test_notebook_evaluation_keeps_old_report_and_uses_separately_pinned_evaluator(tmp_path):
    code = notebook_code("Evaluate Saved Dataset")
    relative = "evaluation-1500/dataset-evaluation-only.tar"
    archive = tmp_path / relative
    archive.parent.mkdir()
    archive.touch()
    archive.with_name("status.json").touch()
    output = tmp_path / "Feedlot_V2_Holdout"
    output.mkdir()
    old = output / "holdout-1500-seed-42-abcdefgh1234.json"
    old.write_text("historical report")
    report = {"report_version": "stage5-saved-holdout.2", "evaluator_commit": "evaluator-sha",
              "stage5_status": "incomplete", "promotion_eligible": False, "placements": 1500,
              "evaluated_seed": 42, "archive_sha256": "abcdefgh1234rest", "horizons": {}}
    fetches = []
    evaluator = tmp_path / "evaluator"

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def run(command, *, cwd, **kwargs):
        assert cwd == evaluator
        assert command == ["python", "-m", "simulator_v2.stage6.colab.holdout", str(archive)]
        return SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr="")

    ns = {"MY_DRIVE": tmp_path, "SESSION": tmp_path, "PILOT_ARCHIVE": archive.name,
          "EVALUATOR_SOURCE": evaluator, "EVALUATOR_SHA": "evaluator-sha", "PYTHON": "python",
          "get_source": lambda *args: fetches.append(args), "check_dependencies": lambda *_: None,
          "runner_env": dict, "require": require, "subprocess": SimpleNamespace(run=run),
          "tempfile": tempfile, "Path": Path, "json": json,
          "copy_verified": lambda source, dest: dest.write_bytes(source.read_bytes())}
    exec(code, ns)
    assert fetches == []
    ns["evaluate_saved_archive"](relative)
    assert fetches == [(evaluator, "evaluator-sha")]
    assert old.read_text() == "historical report"
    assert json.loads(old.with_stem(old.stem + "-v2").read_text()) == report
