"""Stage 6B.1 tests: health repairs, fast canonical serialization, dual validation modes, and supply planning."""

from collections import Counter
from datetime import date, datetime
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from simulator_v2.stage1.model import UTC, midnight
from simulator_v2.stage1.provenance import canonical
from simulator_v2.stage4.ledger import Account, Journal
from simulator_v2.stage6.__main__ import build
from simulator_v2.stage6.benchmark_configs import CONFIGS, SIZES, stage6b1_config
from simulator_v2.stage6.close_index import canonical_journal_bytes, canonical_journal_from_columns
from simulator_v2.stage6.config import Draw, load
from simulator_v2.stage6.epidemiology import epidemiological_bridge, markov_expected_rates
from simulator_v2.stage6.export import Output
from simulator_v2.stage6.runner import Runner
from simulator_v2.stage6.tests.test_stage6 import controlled, read
from simulator_v2.stage6.validation import reconcile_with_mode


def test_canonical_journal_fast_serializers_match_reference_bytes():
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    epoch_day = date(1970, 1, 1)
    samples = [
        Journal(
            journal_id="SYN-JOURNAL-abc",
            source_id="SYN-FIN-SOURCE-123",
            source_system="stage4/feed_cost",
            document_id="DOC/1\"quoted\"",
            line_id="LINE-1",
            animal_id="SYN-LOT-0001-A00001",
            lot_id="SYN-LOT-0001",
            location_id="SYN-P01",
            yard_id="SYN-YARD-01",
            service_date=date(2024, 2, 29),
            effective_at=datetime(2024, 2, 29, 15, 30, 0, tzinfo=UTC),
            source_posted_at=datetime(2024, 2, 29, 16, 0, 1, 123456, tzinfo=UTC),
            posted_at=datetime(2024, 2, 29, 16, 5, 0, tzinfo=UTC),
            available_at=datetime(2024, 2, 29, 16, 5, 0, 500000, tzinfo=UTC),
            accounting_month="2024-02",
            period_routing_at=datetime(2024, 2, 29, 16, 5, 0, tzinfo=UTC),
            debit_account=Account.WIP,
            credit_account=Account.DISTRIBUTION,
            amount_cents=12345,
            component="feed_consumption",
            pool_id="SYN-DEL-1",
            source_snapshot_id="SYN-FIN-VINTAGE-xyz",
            ledger_version="stage6a-finance.1/as_known",
            policy_version="stage6a-stage4-absorption.1",
            approval_id=None,
            restatement_approval_id=None,
            reverses_journal_id=None,
            outcome_event_id=None,
            principal_release=False,
        ),
        Journal(
            journal_id="SYN-JOURNAL-rel",
            source_id="SYN-FIN-SOURCE-456",
            source_system="livestock/movement_events",
            document_id="SYN-SHIP-20240601",
            line_id="SYN-MOV-000000010",
            animal_id="SYN-LOT-0001-A00001",
            lot_id="SYN-LOT-0001",
            location_id="SYN-P01",
            yard_id="SYN-YARD-01",
            service_date=date(2024, 6, 1),
            effective_at=datetime(2024, 6, 1, 19, 0, 0, tzinfo=UTC),
            source_posted_at=datetime(2024, 6, 1, 19, 0, 0, tzinfo=UTC),
            posted_at=datetime(2024, 6, 1, 19, 0, 0, tzinfo=UTC),
            available_at=datetime(2024, 6, 1, 19, 0, 0, tzinfo=UTC),
            accounting_month="2024-06",
            period_routing_at=datetime(2024, 6, 1, 19, 0, 0, tzinfo=UTC),
            debit_account=Account.COGS,
            credit_account=Account.WIP,
            amount_cents=250000,
            component="principal_release",
            pool_id=None,
            source_snapshot_id="SYN-FIN-VINTAGE-rel",
            ledger_version="stage6a-finance.1/restated",
            policy_version="stage6a-stage4-absorption.1",
            approval_id="SYN-APP-1",
            restatement_approval_id="SYN-RESTATE-1",
            reverses_journal_id="SYN-JOURNAL-old",
            outcome_event_id="SYN-FIN-SOURCE-456",
            principal_release=True,
        ),
    ]
    def to_us(dt):
        d = dt - epoch
        return (d.days * 86400 + d.seconds) * 1_000_000 + d.microseconds

    for row in samples:
        expected = canonical(vars(row))[:-1]
        assert canonical_journal_bytes(row) == expected
        col_bytes = canonical_journal_from_columns(
            row.accounting_month, row.amount_cents, row.animal_id, row.approval_id,
            to_us(row.available_at), row.component, str(row.credit_account), str(row.debit_account),
            row.document_id, to_us(row.effective_at), row.journal_id, row.ledger_version,
            row.line_id, row.location_id, row.lot_id, row.outcome_event_id,
            to_us(row.period_routing_at), row.policy_version, row.pool_id, to_us(row.posted_at),
            row.principal_release, row.restatement_approval_id, row.reverses_journal_id,
            (row.service_date - epoch_day).days, row.source_id, to_us(row.source_posted_at),
            row.source_snapshot_id, row.source_system, row.yard_id,
        )
        assert col_bytes == expected


def test_chronic_death_hazard_override_and_daily_compounded_recovery(tmp_path):
    # Force onset -> detection -> chronic on day 2 (chronic_after_days=2, reassess_days=1),
    # with acute detected death = 0 on days 0..2? Better: acute death = 0, chronic_death_daily = 1 vs 0.
    base = controlled(
        start="2025-12-28", end="2026-01-03",
        capacities={"receiving": [1], "production": [2], "hospital": [1]},
        placements=[{"date": "2025-12-28", "head": 1, "mean_kg": 370}],
    )
    base["health"].update(
        onset_daily=1.0, severity_weights=[0, 0, 1], detection_daily=[1, 1, 1],
        untreated_death_daily=[0, 0, 0], detected_death_daily=[0, 0, 0],
        recovery_daily=[0, 0, 0], treatment_probability=1.0,
        chronic_probability=1.0, reassess_days=1, chronic_after_days=2,
        chronic_death_daily=1.0, recovery_basis="daily_compounded",
        scenario_version="test-chronic-hazard.1",
    )
    out_die = tmp_path / "chronic_die"
    build(base, out_die)
    events_die = read(out_die, "health_events")
    actions = [r["action"] for r in events_die]
    assert "chronic" in actions and "death" in actions
    assert read(out_die, "animal_outcomes")[0]["status"] == "dead"

    # Now with chronic_death_daily=0.0, animal survives after becoming chronic
    base["health"]["chronic_death_daily"] = 0.0
    out_live = tmp_path / "chronic_live"
    build(base, out_live)
    assert read(out_live, "animal_outcomes")[0]["status"] == "active"

    # Verify Markov compounding reflects daily_compounded vs per_reassessment
    p_per = {**base["health"], "recovery_daily": [0.4, 0.25, 0.12], "reassess_days": 2, "recovery_basis": "per_reassessment"}
    p_cmp = {**p_per, "recovery_basis": "daily_compounded"}
    m_per = markov_expected_rates(p_per)
    m_cmp = markov_expected_rates(p_cmp)
    assert m_per["by_severity"]["severe"]["effective_review_recovery_prob"] == pytest.approx(0.12)
    assert m_cmp["by_severity"]["severe"]["effective_review_recovery_prob"] == pytest.approx(1 - 0.88**2)


def test_daily_recovery_compounding_is_applied_by_the_simulator(tmp_path):
    base = controlled(
        start="2025-12-28", end="2025-12-31",
        capacities={"receiving": [1], "production": [2], "hospital": [1]},
        placements=[{"date": "2025-12-28", "head": 1, "mean_kg": 370}],
    )
    review_day = date(2025, 12, 31)
    draw = Draw(base["seed"])("health/recovery", "SYN-LOT-0001-A00001", review_day)
    rate = (1 - (1 - draw) ** 0.5 + draw) / 2
    assert rate < draw < 1 - (1 - rate) ** 2
    base["health"].update(
        onset_daily=1, severity_weights=[0, 0, 1], detection_daily=[1, 1, 1],
        untreated_death_daily=[0, 0, 0], detected_death_daily=[0, 0, 0],
        reassess_days=2, recovery_daily=[rate] * 3, chronic_after_days=9,
    )
    for basis in ("per_reassessment", "daily_compounded"):
        base["health"]["recovery_basis"] = basis
        out = tmp_path / basis
        build(base, out)
        events = read(out, "health_events")
        reviews = [event for event in events if event["action"] == "reassessment"]
        recovered = [event for event in events if event["action"] == "recovery"]
        assert len(reviews) == 1
        assert bool(recovered) == (basis == "daily_compounded")
        if recovered:
            assert recovered[0]["effective_at"] == reviews[0]["effective_at"]


def test_markov_respects_detection_delay_and_non_exiting_episodes():
    health = controlled()["health"]
    health.update(
        untreated_death_daily=[0, 0, 0], detected_death_daily=[0.1] * 3,
        detection_daily=[0.2] * 3, recovery_daily=[0.2] * 3,
        reassess_days=2, chronic_after_days=4, chronic_death_daily=0.01, chronic_probability=1,
    )
    # At detection lags of zero or one day, one reassessment precedes chronic eligibility.
    # At longer lags, the first reassessment is already eligible.
    chronic_cfr = (1 - 0.99 ** 2) / (1 - 0.99 ** 2 * 0.8)
    eligible_cfr = 1 - 0.9 ** 2 + 0.9 ** 2 * 0.8 * chronic_cfr
    early_cfr = 1 - 0.9 ** 2 + 0.9 ** 2 * 0.8 * eligible_cfr
    expected = 100 * (0.36 * early_cfr + 0.64 * eligible_cfr)
    assert markov_expected_rates(health)["by_severity"]["severe"]["overall_cfr_pct"] == round(expected, 3)
    health.update(recovery_daily=[0, 0, 0], chronic_death_daily=0)
    assert markov_expected_rates(health)["by_severity"]["severe"]["expected_post_detection_days"] is None


def _replace_cell(root, tables, table, column, transform, *, month=None, position=0):
    filename = next(name for name, info in tables.items()
                    if info["table"] == table and (month is None or info["month"] == month))
    path = root / filename
    original = path.read_bytes()
    data = pq.ParquetFile(path).read()
    values = data[column].to_pylist()
    values[position] = transform(values[position])
    index = data.schema.get_field_index(column)
    pq.write_table(data.set_column(index, data.schema.field(index), pa.array(values, type=data[column].type)), path)
    return path, original


def test_full_vs_incremental_validation_and_tamper_detection(tmp_path):
    cfg = controlled(
        start="2025-12-30", end="2026-01-10",
        capacities={"receiving": [2], "production": [2], "hospital": [1]},
        placements=[{"date": "2025-12-30", "head": 2, "mean_kg": 370}],
    )
    out = tmp_path / "dataset"
    out.mkdir()
    writer = Output(out, "SYN-TEST-MODE")
    runner = Runner(cfg, "SYN-TEST-MODE", writer)
    ops, replay, daily, monthly, _ = runner.operations()
    closes = runner.finance(ops)
    tables = writer.finish()

    full = reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes, mode="full")
    assert full["mode"] == "full" and full["complete_independent_audit"] is True
    assert all(g["passed"] for g in full["hard_gates"].values())

    prior_digests = {name: info["sha256"] for name, info in tables.items()}
    inc = reconcile_with_mode(
        out, tables, runner, replay, daily, monthly, closes,
        mode="incremental", changed_months=["2026-01"], prior_partition_digests=prior_digests,
    )
    assert inc["mode"] == "incremental" and inc["complete_independent_audit"] is False
    assert inc["changed_months"] == ["2026-01"] and inc["dependent_months"] == ["2026-01"]
    assert inc["verified_unchanged_partitions"] > 0
    assert inc["hard_gates"]["immutable_partition_digest"]["passed"] is True

    # Tamper with an unchanged 2025-12 partition -> incremental mode must detect digest mismatch
    dec_part = next(name for name, info in tables.items() if info["month"] == "2025-12" and info["table"] == "yardage")
    path, original = _replace_cell(out, tables, "yardage", "cents", lambda value: value + 1, month="2025-12")
    with pytest.raises(ValueError, match="immutable_partition_digest"):
        reconcile_with_mode(
            out, tables, runner, replay, daily, monthly, closes,
            mode="incremental", changed_months=["2026-01"], prior_partition_digests=prior_digests,
        )
    path.write_bytes(original)

    with pytest.raises(ValueError, match="requires prior_partition_digests"):
        reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes,
                            mode="incremental", changed_months=["2026-01"])
    with pytest.raises(ValueError, match="immutable_partition_digest"):
        reconcile_with_mode(out, {name: info for name, info in tables.items() if name != dec_part},
                            runner, replay, daily, monthly, closes, mode="incremental",
                            changed_months=["2026-01"], prior_partition_digests=prior_digests)

    with pytest.raises(ValueError, match="immutable_partition_digest"):
        reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes,
                            mode="incremental", changed_months=["2026-01"],
                            prior_partition_digests={name: digest for name, digest in prior_digests.items()
                                                     if name != dec_part})

    immutable_path = out / dec_part
    immutable_bytes = immutable_path.read_bytes()
    immutable_path.unlink()
    try:
        with pytest.raises(ValueError, match="immutable_partition_digest"):
            reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes,
                                mode="incremental", changed_months=["2026-01"],
                                prior_partition_digests=prior_digests)
    finally:
        immutable_path.write_bytes(immutable_bytes)

    path, original = _replace_cell(out, tables, "feed_plans", "planned_g_dm", lambda value: value + 1, month="2026-01")
    with pytest.raises(ValueError, match="ration_and_plan"):
        reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes, mode="incremental",
                            changed_months=["2025-12"], prior_partition_digests=prior_digests)
    path.write_bytes(original)

    for table, column, delta, gate in (
        ("wip", "closing_cents", 10_000, "financial_close_publication"),
        ("finance_monthly", "sales_cogs_cents", 10_000, "financial_close_publication"),
        ("warehouse_receipts", "g_af", 1, "warehouse_replay_publication"),
    ):
        path, original = _replace_cell(out, tables, table, column, lambda value: value + delta)
        with pytest.raises(ValueError, match=gate):
            reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes, mode="full")
        path.write_bytes(original)

    growth = pq.ParquetFile(out / "growth_operational/month=2026-01/part.parquet").read()
    no_feed = growth["window_start_at"].to_pylist().index(None)
    for nonfinite in (float("inf"), float("-inf"), float("nan")):
        path, original = _replace_cell(out, tables, "growth_operational", "starting_me_mj", lambda _: nonfinite,
                                       month="2026-01", position=no_feed)
        with pytest.raises(ValueError, match="biological_reserve_balance"):
            reconcile_with_mode(out, tables, runner, replay, daily, monthly, closes, mode="full")
        path.write_bytes(original)

    # Tamper with a changed 2026-01 journal amount -> incremental mode must fail fingerprint/line balance
    jan_j = out / "journals_as_known/month=2026-01/part.parquet"
    tbl = pq.read_table(jan_j)
    amts = tbl["amount_cents"].to_pylist()
    amts[0] += 1
    idx = tbl.schema.get_field_index("amount_cents")
    tampered = tbl.set_column(idx, tbl.schema.field(idx), pa.array(amts, type=tbl.schema.field(idx).type))
    pq.write_table(tampered, jan_j, compression="zstd", version="2.6")
    with pytest.raises(ValueError):
        reconcile_with_mode(
            out, tables, runner, replay, daily, monthly, closes,
            mode="incremental", changed_months=["2026-01"], prior_partition_digests=prior_digests,
        )


def test_material_specific_supply_eliminates_silage_shortage_with_explicit_pos(tmp_path):
    # Create a 20-day scenario where uniform low silage stock runs out,
    # whereas material-specific silage target + reorder point prevents stockout via documented POs.
    base = controlled(
        start="2025-12-01", end="2025-12-20",
        capacities={"receiving": [2], "production": [6], "hospital": [1]},
        placements=[],
        carry_in=[{
            "head": 6, "location": "SYN-P01", "weight_kg": 440, "entry_age_days": 360,
            "days_on_feed": 40, "wip_cents": 175000, "status": "active", "source": "SYN-SUPPLY-OPEN",
        }],
    )
    base["warehouse"].update(
        order_cycle_days=7, lead_days=5, split_receipt_delay_days=2,
        opening_grams_per_design_head=30000, ordered_grams_per_design_head=35000,
        bin_grams_per_design_head=120000, opening_spoilage_g_af=0,
    )
    out_short = tmp_path / "uniform_short"
    build(base, out_short)
    short_exc = Counter(r["reason"] for r in read(out_short, "exceptions"))
    assert short_exc["ingredient_shortage_load_cancelled"] > 0

    # Now apply material-specific planning for SILAGE/BARLEY/OATS
    fixed = json.loads(json.dumps(base))
    specs = {
        "SILAGE": {"opening_grams_per_design_head": 115000, "ordered_grams_per_design_head": 130000,
                   "reorder_grams_per_design_head": 95000, "bin_grams_per_design_head": 180000},
        "BARLEY": {"opening_grams_per_design_head": 70000, "ordered_grams_per_design_head": 80000,
                   "reorder_grams_per_design_head": 58000, "bin_grams_per_design_head": 115000},
        "OATS": {"opening_grams_per_design_head": 22000, "ordered_grams_per_design_head": 26000,
                 "reorder_grams_per_design_head": 18000, "bin_grams_per_design_head": 45000},
    }
    for ing in fixed["warehouse"]["ingredients"]:
        ing.update(specs[ing["code"]])
    out_fixed = tmp_path / "material_sufficient"
    build(fixed, out_fixed)
    assert read(out_fixed, "exceptions") == []
    # Every replenishment enters via explicit PurchaseOrder + receipt transactions
    orders = read(out_fixed, "warehouse_orders")
    receipts = read(out_fixed, "warehouse_receipts")
    assert len(orders) > 0 and len(receipts) > 0
    val_report = json.loads((out_fixed / "validation.json").read_bytes())
    assert val_report["mode"] == "full" and val_report["complete_independent_audit"] is True
    # Also verify epidemiological_bridge works cleanly on published output
    epi = epidemiological_bridge(out_fixed)
    assert epi["denominators_and_competing_exits"]["total_animals_at_risk"] == 6
    assert epi["rng_stream_independence"]["all_streams_distinct"] is True


@pytest.mark.parametrize("size", SIZES)
def test_stage6b1_materialized_configs_match_builder(size):
    cfg = load(CONFIGS / f"stage6b1-baseline-{size}.json")
    assert cfg == stage6b1_config(size, health_scenario="baseline", supply_policy="material_specific")
    assert cfg["health"]["scenario_version"] == "stage6b1-baseline-health.1"
    assert cfg["health"]["recovery_basis"] == "daily_compounded"
    assert "chronic_death_daily" in cfg["health"]
    adv = load(CONFIGS / "stage6b1-adverse-health-250.json")
    assert adv == stage6b1_config(250, health_scenario="adverse", supply_policy="material_specific")
    assert adv["health"]["scenario_version"] == "stage6b-adverse-health.1"
