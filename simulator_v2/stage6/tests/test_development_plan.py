"""Development-only forecasts and read-only production resource planning."""

from datetime import date, timedelta
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from simulator_v2.stage2.config import load_config
from simulator_v2.stage6.__main__ import build
from simulator_v2.stage6.colab import development, holdout, production_plan
from simulator_v2.stage6.config import at
from simulator_v2.stage6.tests.test_stage6 import controlled, read


def test_phase_projection_splits_at_known_adaptation_and_season_boundaries():
    origin = at(date(2025, 11, 14), 8)
    target = origin + timedelta(days=2)
    window = holdout.OriginForecast(origin, "SYN-LOT-0001", False, "eligible", 400, origin, .75, 35,
                                    "adaptation", origin + timedelta(days=1), "healthy")
    result = development.phase_scorer(load_config())(
        window, SimpleNamespace(measured_at=target, measured_weight_kg=400))
    # 16 h neutral adaptation, 8 h cold adaptation, and 24 h cold finishing.
    assert result["candidate_error"] == pytest.approx(1.908)
    assert result["crossed_adaptation"] and result["crossed_calendar_season"]
    hospital = holdout.OriginForecast(origin, "SYN-LOT-0001", False, "eligible", 400, origin, .18 * .48, 35,
                                      "hospital", origin + timedelta(days=1), "ill")
    result = development.phase_scorer(load_config())(
        hospital, SimpleNamespace(measured_at=target, measured_weight_kg=400))
    assert result["candidate_error"] == pytest.approx(.164)
    assert not result["crossed_adaptation"]


def test_finishing_without_calendar_change_matches_v2_across_horizons():
    origin = at(date(2025, 12, 1), 8)
    window = holdout.OriginForecast(origin, "SYN-LOT-0001", False, "eligible", 470, origin - timedelta(days=7),
                                    1.28 * .92, 35, "finishing", origin - timedelta(days=2), "healthy")
    score = development.phase_scorer(load_config())
    for lead in (7, 30, 60):
        label = SimpleNamespace(measured_at=origin + timedelta(days=lead), measured_weight_kg=505)
        assert score(window, label)["candidate_error"] == pytest.approx(window.score(label)[0][1])


def test_private_evaluation_rows_and_late_revisions_do_not_reach_development():
    cutoff = at(date(2025, 7, 1), 0)
    early = cutoff - timedelta(days=1)
    rows = [{"animal_id": key, "lot_id": lot, "effective_at": effective, "available_at": availability}
            for key, lot, effective, availability in (
                ("development", "SYN-LOT-0001", early, early),
                ("held-lot", "SYN-LOT-0003", early, early),
                ("carry", "SYN-LOT-0001", early, early),
                ("future", "SYN-LOT-0001", cutoff, cutoff),
                ("known-later", "SYN-LOT-0001", early, cutoff + timedelta(days=1)),
            )]
    tables = {"animals": rows, "opening_cattle": [{"animal_id": "carry"}], "lots": [], "locations": [],
              "movement_events": rows, "health_events": rows, "weight_observations": [
                  row | {"measured_at": row["effective_at"]} for row in rows
              ] + [{"animal_id": "development", "measured_at": early,
                    "available_at": cutoff + timedelta(seconds=1)}]}
    filtered = development.development_tables(tables, cutoff)
    for name in ("animals", "movement_events", "health_events", "weight_observations"):
        assert [row["animal_id"] for row in filtered[name]] == ["development"]
    assert filtered["opening_cattle"] == []


def test_development_comparison_uses_audited_fixture_without_holdout_or_carry(tmp_path):
    config = controlled(start="2025-03-03", end="2025-05-18", follow_up_days=6,
                        placements=[{"date": f"2025-03-0{day}", "head": 1, "mean_kg": 370}
                                    for day in (3, 4, 5)],
                        capacities={"receiving": [3], "production": [4], "hospital": [1]})
    dataset = tmp_path / "small"
    build(config, dataset)
    tables = {name: [{key: value for key, value in row.items() if key != "run_id"} for row in read(dataset, name)]
              for name in holdout.TABLES | {"health_events"}}
    baseline = development.compare(config, tables, {})
    assert baseline["scope"] == "development_only" and baseline["promotion_eligible"] is False
    for horizon in baseline["horizons"].values():
        assert horizon["eligible_lots"] == 2 and horizon["eligible_pairs"]
        assert {"truncated_B", "constant_ADG_B", "phase_calendar_B"} <= horizon["errors"].keys()
    tables["weight_observations"] = [
        row | {"measured_weight_kg": -100} if row["lot_id"] == "SYN-LOT-0003" else row
        for row in tables["weight_observations"]
    ]
    assert development.compare(config, tables, {}) == baseline


def test_read_only_production_projection_checks_pilot_metadata_hash_and_uses_phase_windows(tmp_path):
    gib = production_plan.GIB
    phases = {name: {"seconds": sec, "peak_rss_kib": 3 * gib // 1024}
              for name, sec in (("operations", 3600), ("finance", 2400), ("validation", 600), ("report", 120))}
    perf = {"phases": phases, "parquet_bytes": 4 * gib, "peak_rss_kib_linux": 3 * gib // 1024}
    raw = json.dumps(perf).encode()
    (tmp_path / "performance.json").write_bytes(raw)
    status = {"status": "completed", "purpose": holdout.EVALUATION_ONLY, "code_sha": holdout.PILOT_CODE,
              "config_version": "stage7-pilot-1500.1", "head": {"placements": 1500}, "placements": 1500,
              "validation_status": "passed", "complete_independent_audit": True, "financial_closes": 48,
              "saved_sha256": {production_plan.ARCHIVE: "archive", "performance.json": sha256(raw).hexdigest()},
              "performance": perf, "package_bytes": 4 * gib, "save_seconds": 300,
              "artifact_verification_seconds": 60,
              "checkpoints": {"operations": {"bytes": 3 * gib}, "finance": {"bytes": 2 * gib}},
              "run_id": "synthetic-test", "seed": 42, "resources": {"ram_available_bytes": 11.45 * gib}}
    (tmp_path / "status.json").write_text(json.dumps(status))
    plan = production_plan.project(tmp_path)
    assert plan["production_authorized"] is False
    assert plan["longest_compute_phase"] == "operations"
    assert plan["projected_phase_hours"]["operations"] == {"linear": 10, "planning": 15}
    assert plan["planning_floors_gib"] == {"ram": 45, "local_disk": 195, "drive": 135}
    (tmp_path / "performance.json").write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="Performance SHA-256"):
        production_plan.project(tmp_path)
