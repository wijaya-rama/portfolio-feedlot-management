"""Focused release capacity and cross-process recovery controls."""

from datetime import date
import json
import os
import shutil
import subprocess
import sys

import pytest

from simulator_v2.stage6.__main__ import build
from simulator_v2.stage6.config import DIAGNOSTIC, load
from simulator_v2.stage6.release_configs import RELEASE_SIZES, release_config, release_path
from simulator_v2.stage6.release_preflight import inspect
from simulator_v2.stage6.tests.test_stage6 import controlled, read


@pytest.mark.parametrize("size", RELEASE_SIZES)
def test_release_plan_and_supply(size):
    config = load(release_path(size))
    assert config == release_config(size)
    assert (config["start"], config["end"]) == ("2024-01-01", "2025-12-31")
    assert sum(row["head"] for row in config["placements"]) == size
    result = inspect(config)
    reserve = result["sale_delay_days"]["35"]
    assert reserve["concurrent_head"] < config["warehouse"]["design_head"]
    assert reserve["production_spare_pens"] >= 3
    assert reserve["receiving_spare_pens"] >= 1
    for seed in result["supplier"].values():
        assert seed["lead_days"] == 3 and seed["second_receipt_calendar_days"] == 5
        assert min(seed["minimum_stock_g_af"].values()) > 0
    stress = result["silage_stress"]
    assert stress["second_receipt_calendar_days"] == 6
    assert min(stress["minimum_stock_g_af"].values()) > 0


def test_lot_segregation_routes_receiving_and_production_overflow(tmp_path):
    config = controlled(capacities={"receiving": [5], "production": [5], "hospital": [1]},
                        placements=[{"date": "2025-12-31", "head": 2, "mean_kg": 370},
                                    {"date": "2025-12-31", "head": 2, "mean_kg": 370},
                                    {"date": "2026-01-01", "head": 1, "mean_kg": 370}],
                        lot_segregation=True)
    output = tmp_path / "overflow"
    build(config, output)
    movements = read(output, "movement_events")
    assert {row["animal_id"].split("-A")[0] for row in movements if row["kind"] == "transfer"} == {"SYN-LOT-0001"}
    reasons = {row["reason"] for row in read(output, "exceptions")}
    assert {"receiving_full_rescheduled", "production_full_rescheduled", "placement_unfulfilled_at_horizon"} <= reasons
    config["required_placements"] = 5
    with pytest.raises(ValueError, match="exact_placements"):
        build(config, tmp_path / "rejected")


def test_release_equipment_window_budget_is_enforced(tmp_path):
    config = controlled(capacities={"receiving": [1, 1], "production": [1], "hospital": [1]},
                        placements=[{"date": "2025-12-31", "head": 2, "mean_kg": 370}])
    config["warehouse"].update(equipment_pairs=1, equipment_cycle_minutes=120)
    with pytest.raises(ValueError, match="equipment cycles exhausted"):
        build(config, tmp_path / "equipment")


def test_hospital_triage_and_return_respect_segregated_lots(tmp_path):
    config = controlled(capacities={"receiving": [2], "production": [2, 2], "hospital": [1]},
                        carry_in=[
                            {"head": 1, "location": f"SYN-P{pen:02d}", "weight_kg": 440,
                             "entry_age_days": 360, "days_on_feed": 40, "wip_cents": 190000,
                             "status": "active", "source": f"SYN-TRIAGE-{pen}"}
                            for pen in (1, 2)
                        ],
                        placements=[], lot_segregation=True)
    config["health"].update(onset_daily=1, severity_weights=[0, 0, 1], detection_daily=[1, 1, 1],
                            untreated_death_daily=[0, 0, 0], detected_death_daily=[0, 0, 0],
                            recovery_daily=[1, 1, 1], reassess_days=1, chronic_after_days=2)
    output = tmp_path / "triage"
    build(config, output)
    assert any(row["reason"] == "hospital_full_triaged_in_place" for row in read(output, "exceptions"))
    movements = read(output, "movement_events")
    assert any(row["reason"] == "clinical_return" for row in movements)
    assert json.loads((output / "validation.json").read_text())["hard_gates"]["lot_segregation"]["passed"]
    config["capacities"]["hospital"] = [2]
    config["hospital_planning_head"] = 1
    with pytest.raises(ValueError, match="hospital_headroom"):
        build(config, tmp_path / "over-planned-hospital-limit")


def test_killed_build_restores_in_fresh_process_and_matches_cold_reference(tmp_path):
    config = controlled(capacities={"receiving": [3], "production": [4, 4], "hospital": [1]},
                        carry_in=[{"head": 1, "location": "SYN-P01", "weight_kg": 550, "entry_age_days": 420,
                                   "days_on_feed": 100, "wip_cents": 190000, "status": "active",
                                   "source": "SYN-RESUME-OPEN", "minimum_dof": 10}],
                        lot_segregation=True, required_placements=3)
    config["shipment"]["weekday"] = date(2026, 1, 1).weekday()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    output = tmp_path / "resumed"
    work = tmp_path / "interrupted"
    # Kill while finance is running, after it has reopened the operation inputs.
    script = """
import importlib
from pathlib import Path
import sys
import time
module = importlib.import_module("simulator_v2.stage6.__main__")
original_books = module.Finance.books
def pause(self, cutoff):
    for close in original_books(self, cutoff):
        yield close
        print("ready to interrupt", flush=True)
        time.sleep(120)
module.Finance.books = pause
module.build(module.load(sys.argv[1]), Path(sys.argv[2]), workspace=Path(sys.argv[3]))
"""
    with subprocess.Popen([sys.executable, "-c", script, str(config_path), str(output), str(work)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
        try:
            assert process.stdout.readline().strip() == "Saved operations checkpoint"
            assert process.stdout.readline().strip() == "ready to interrupt"
        finally:
            process.kill()
            process.wait(timeout=10)
    assert not output.exists() and not (work / "finance").exists()
    assert list(work.glob(".finance-*/finance.sqlite"))

    restored = tmp_path / "fresh-runtime"
    shutil.copytree(work / "operations", restored / "operations")
    command = [sys.executable, "-m", "simulator_v2.stage6", "--config", str(config_path),
               "--output", str(output), "--checkpoint-dir", str(restored)]
    env = {**os.environ, "PYTHONHASHSEED": "19"}
    stdout = subprocess.check_output([*command, "--stop-after", "finance"], env=env, text=True, timeout=60)
    assert "Restored operations checkpoint" in stdout and "Saved finance checkpoint" in stdout
    assert not output.exists()

    # Corrupt a sealed file and prove that the restarted process refuses publication.
    partition = next((restored / "finance" / "dataset").rglob("*.parquet"))
    contents = partition.read_bytes()
    partition.write_bytes(contents[:-1] + bytes([contents[-1] ^ 1]))
    failure = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert failure.returncode and "checkpoint hash mismatch" in failure.stderr and not output.exists()
    partition.write_bytes(contents)
    stdout = subprocess.check_output(command, env=env, text=True, timeout=60)
    assert "Restored operations checkpoint" in stdout and "Restored finance checkpoint" in stdout
    reference = tmp_path / "uninterrupted"
    build(config, reference)
    assert (reference / "hashes.json").read_bytes() == (output / "hashes.json").read_bytes()
    assert len(read(output, "finance_monthly")) == 4
    assert read(output, "feed_allocations") and read(output, "warehouse_receipts")
    assert read(output, "packer_settlements") and read(output, "wip")
    assert json.loads((output / "validation.json").read_text())["complete_independent_audit"] is True


def test_retrospective_checkpoint_can_reopen(tmp_path):
    config = load(DIAGNOSTIC)
    config.update(end="2025-11-22", placements=config["placements"][:1])
    work, output = tmp_path / "work", tmp_path / "dataset"
    build(config, output, workspace=work, stop_after="operations")
    build(config, output, workspace=work)
    assert read(output, "growth_retrospective")
