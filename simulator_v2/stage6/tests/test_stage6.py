"""Independent expectations for small controlled operations and accounting failures."""

from collections import Counter
from datetime import date


import pyarrow.parquet as pq
import pytest

from simulator_v2.stage6.__main__ import build
from simulator_v2.stage6.config import DIAGNOSTIC, load


def read(root, name):
    return [row for path in sorted(root.glob(f"{name}/**/*.parquet"))
            for row in pq.ParquetFile(path).read().to_pylist()]


def controlled(**updates):
    config = load()
    config.update(start="2025-12-31", end="2026-01-03", carry_in=[], placements=[
        {"date": "2025-12-31", "head": 3, "mean_kg": 370}], capacities={
        "receiving": [1], "production": [1], "hospital": [1]}, receiving_days=[1, 1],
        weather={"retrospective": False, "forecasts": []})
    config["health"].update(onset_daily=0, background_death_daily=0)
    config["shipment"]["minimum_dof"] = 999
    config.update(updates)
    return config


def yard_month(root, view):
    closes = {row["close_id"]: row for row in read(root, "finance_snapshots") if row["view"] == view}
    return [row for row in read(root, "finance_soh") if row["scope_type"] == "yard"
            and row["close_id"] in closes]


def test_capacity_stock_and_wip_exact(tmp_path):
    config = load(DIAGNOSTIC.with_name("adversarial-shortage.json"))
    output = tmp_path / "shortage"
    build(config, output)
    scopes = [row for row in read(output, "daily_soh") if row["scope_type"] == "yard"]
    assert [row["closing_head"] for row in scopes] == [1, 2, 2, 2]
    assert [row["animal_days"] for row in scopes] == [1, 2, 2, 2]
    assert [row["receipts"] for row in yard_month(output, "as_known")] == [1, 1]
    assert Counter(row["kind"] for row in read(output, "movement_events")) == {"receipt": 2, "transfer": 1}
    reasons = Counter(row["reason"] for row in read(output, "exceptions"))
    assert reasons == {"receiving_full_rescheduled": 4, "production_full_rescheduled": 2,
                       "placement_unfulfilled_at_horizon": 1, "ingredient_shortage_load_cancelled": 14}
    assert read(output, "feed_allocations") == []
    assert read(output, "warehouse_receipts") == []
    profiles = read(output, "animal_profiles")
    purchase = sum(round(row["entry_weight_kg"] * 435) for row in profiles)
    closes = {(row["view"], row["month"]): row for row in read(output, "finance_monthly")}
    assert closes["as_known", "2026-01"]["closing_wip_cents"] == purchase + 7 * 125 + 25
    assert closes["restated", "2025-12"]["closing_wip_cents"] - closes["as_known", "2025-12"]["closing_wip_cents"] == 25
    assert closes["restated", "2026-01"]["closing_wip_cents"] == closes["as_known", "2026-01"]["closing_wip_cents"]
    with pytest.raises(FileExistsError):
        build(config, output)


@pytest.mark.parametrize("treated", [False, True])
def test_in_horizon_death_with_and_without_treatment(tmp_path, treated):
    config = controlled(capacities={"receiving": [2], "production": [2], "hospital": [1]},
                        placements=[{"date": "2025-12-31", "head": 2, "mean_kg": 370}])
    config["health"].update(onset_daily=1, severity_weights=[0, 0, 1], detection_daily=[1, 1, 1],
                            untreated_death_daily=[0, 0, 0] if treated else [1, 1, 1],
                            detected_death_daily=[1, 1, 1], treatment_probability=1)
    output = tmp_path / "deaths"
    build(config, output)
    deaths = read(output, "animal_outcomes")
    assert len(deaths) == 2 and all(row["status"] == "dead" for row in deaths)
    actions = Counter(row["action"] for row in read(output, "health_events"))
    assert actions["treatment"] == 2 * treated
    assert actions["hospital_admission"] == int(treated)
    assert sum(row["reason"] == "hospital_full_triaged_in_place" for row in read(output, "exceptions")) == int(treated)
    assert len(read(output, "shipment_lines")) == 0
    wip = [row for row in read(output, "wip") if row["month"] == "2026-01"]
    assert all(row["closing_cents"] == 0 for row in wip)
    releases = [row for row in read(output, "journals_as_known") if row["principal_release"]]
    assert len(releases) == 2 and {row["debit_account"] for row in releases} == {"5200"}


def test_missing_grade_and_after_horizon_sale_posting(tmp_path):
    config = controlled(start="2026-01-06", end="2026-01-06", placements=[], carry_in=[
        {"head": 1, "location": "SYN-P01", "weight_kg": 550, "entry_age_days": 420,
         "days_on_feed": 100, "wip_cents": 190000, "status": "active", "source": "SYN-MANUAL-OPEN"}])
    config["shipment"].update(minimum_dof=10, weekday=date.fromisoformat(config["start"]).weekday(),
                              grade_missing_probability=1, settlement_lag_days=[5, 5])
    output = tmp_path / "sale"
    build(config, output)
    sale, = read(output, "carcasses")
    assert sale["quality_grade"] is None and sale["yield_class"] is None
    assert sale["grade_status"] == "missing_synthetic_ticket"
    assert sale["hcw_kg"] == round(sale["latent_exit_liveweight_kg"] * sale["dressing_fraction"], 1)
    close = {row["view"]: row for row in read(output, "finance_monthly")}
    settlement, = read(output, "packer_settlements")
    assert close["as_known"]["net_sales_cents"] == settlement["provisional_cents"]
    assert close["restated"]["net_sales_cents"] == settlement["final_cents"]
    assert close["restated"]["closing_wip_cents"] == 0


def test_dst_and_forecast_availability_and_cold_hashes(tmp_path):
    config = controlled(start="2025-11-02", end="2025-11-03", placements=[], carry_in=[{
        "head": 1, "location": "SYN-H01", "weight_kg": 405, "entry_age_days": 360,
        "days_on_feed": 20, "wip_cents": 161000, "status": "active", "source": "SYN-TEST-OPEN"}])
    config["weather"]["forecasts"] = [
        {"day": "2025-11-02", "source_id": "SYN-FORECAST-KNOWN",
         "issued_at": "2025-11-02T04:00:00+00:00", "available_at": "2025-11-02T04:30:00+00:00", "mean_c": -4},
        {"day": "2025-11-02", "source_id": "SYN-FORECAST-LATE",
         "issued_at": "2025-11-02T05:00:00+00:00", "available_at": "2025-11-02T08:00:00+00:00", "mean_c": -20},
    ]
    a, b = tmp_path / "first", tmp_path / "second"
    build(config, a)
    build(config, b)
    assert (a / "hashes.json").read_bytes() == (b / "hashes.json").read_bytes()
    exposure = read(a, "weather_exposure")
    assert sum((row["end_at"] - row["start_at"]).total_seconds() for row in exposure
               if row["source_id"] == "SYN-FORECAST-KNOWN") == 25 * 3600
    assert all(row["source_id"] != "SYN-FORECAST-LATE" for row in exposure)
    assert {row["reason"] for row in read(a, "movement_events") if row["kind"] == "transfer"} == {"clinical_return"}


def test_financial_parameters_do_not_change_physical_intake(tmp_path):
    first, second = tmp_path / "base", tmp_path / "higher_cost"
    config = controlled()
    build(config, first)
    config["finance"].update(yardage_cents=300, purchase_cents_per_kg=650)
    build(config, second)
    def trajectory(root):
        fields = ("animal_id", "start_at", "end_at", "consumed_g_dm", "energy_mj", "protein_kg", "end_weight_kg")
        return [tuple(row[field] for field in fields) for row in read(root, "growth_operational")]
    assert trajectory(first) == trajectory(second)
    assert read(first, "finance_monthly")[-1]["closing_wip_cents"] < read(second, "finance_monthly")[-1]["closing_wip_cents"]
