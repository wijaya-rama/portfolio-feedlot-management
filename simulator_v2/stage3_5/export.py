"""Publish a separately versioned, validated Stage 3.5 fixture."""

from pathlib import Path

from ..stage1.fixture import END, FINAL_CUTOFF, START
from ..stage1.model import midnight
from ..stage1.provenance import canonical, sha256
from ..stage1.soh import StockRow, calculate_soh
from ..stage2 import backtest
from ..stage2.estimation import Estimate, EstimateSnapshot
from ..stage3.export import publish
from ..stage3.reconciliation import feed_bridges, wip_candidates
from .comparison import compare
from .feeding import FeedRelease
from .fixture import integrated_fixture
from .observations import ScaleCancellation, ScaleRevision, ScaleSample
from .provenance import DecisionSource
from .reconciliation import StockDMBridge, dm_bridges, stock_summary
from .validation import validate

SCHEMA_VERSION = "stage3.5.1"
ARCHIVED_COMMIT = "b818906368ee2fe3b88a65d5064464161712c061"


def build(output, seed=42):
    if Path(output).exists():
        raise FileExistsError(f"build directory already exists: {output}")
    fixture = integrated_fixture(seed)
    candidates = wip_candidates(fixture)
    totals = feed_bridges(fixture, candidates)
    dm = tuple(dm_bridges(fixture))
    evaluation = backtest.evaluate(fixture.final_estimator, fixture.profiles, start_at=midnight(START),
                                   evaluation_cutoff=FINAL_CUTOFF, config=fixture.biology_config)
    pairs, snapshots, forecasts = evaluation
    targets = backtest.latent_targets(pairs, fixture.biology, fixture.timeline.snapshot_id)
    checks = validate(fixture, candidates, totals, dm, evaluation)
    _, daily_stock, monthly_stock, _ = calculate_soh(fixture.ledger, START, END, FINAL_CUTOFF)
    extra = (
        ("livestock", "daily_soh", StockRow, daily_stock),
        ("livestock", "monthly_soh", StockRow, monthly_stock),
        ("operational", "decision_sources", DecisionSource, fixture.decision_sources),
        ("operational", "scale_revisions", ScaleRevision, fixture.scale_revisions),
        ("operational", "restated_estimate_snapshots", EstimateSnapshot, fixture.restated_snapshots),
        ("operational", "restated_estimates", Estimate, fixture.restated_estimates),
        ("operational", "scale_cancellations", ScaleCancellation, fixture.scale_cancellations),
        ("diagnostic", "scale_samples", ScaleSample, fixture.scale_samples),
        ("warehouse", "dry_matter_bridges", StockDMBridge, dm),
        ("feed", "timed_releases", FeedRelease, fixture.feed_releases),
        ("backtest", "pairs", backtest.Pair, pairs),
        ("backtest", "snapshots", EstimateSnapshot, snapshots),
        ("backtest", "forecasts", Estimate, forecasts),
        ("diagnostic", "latent_backtest_targets", backtest.LatentTarget, targets),
    )
    stock = stock_summary(fixture, dm)
    return publish(
        output, seed, fixture, candidates, totals, checks, schema=SCHEMA_VERSION,
        run_prefix="STAGE35-RUN", stages=("stage1", "stage2", "stage3", "stage3_5"),
        extra_tables=extra, artifacts={
            "backtest.json": backtest.report(pairs, fixture.biology_config, latent=targets),
            "comparison.json": compare(fixture, totals, seed),
        }, manifest={
            "archived_baseline_commit": ARCHIVED_COMMIT,
            "observation_version": fixture.biology_config["observation_version"],
            "allocation_policy_version": fixture.scenario["allocation_policy"]["version"],
            "stage4_input": "authoritative_synthetic_12_cattle_fixture",
        }, input_metadata={
            "archived_baseline_commit": ARCHIVED_COMMIT,
            "weigh_attempt_sha256": sha256(canonical(fixture.attempts)),
        }, reconciliation={
            "warehouse_horizon": stock,
            "selected_growth_nutrients": {
                "g_dm": sum(row.g_dm for row in fixture.growth_inputs),
                "energy_kj": sum(row.energy_kj for row in fixture.growth_inputs),
                "cp_g": sum(row.cp_g for row in fixture.growth_inputs),
            },
            "active_wip_candidates": len(candidates),
        },
    )
