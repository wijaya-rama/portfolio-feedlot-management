import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.parquet as pq

from simulator_v2.stage1.__main__ import validation_checks
from simulator_v2.stage1.fixture import END, FINAL_CUTOFF, START
from simulator_v2.stage1.model import midnight
from simulator_v2.stage1.provenance import sha256
from simulator_v2.stage1.soh import YARD, calculate_soh
from simulator_v2.stage2.backtest import evaluate, latent_targets, report
from simulator_v2.stage2.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[3]


class BacktestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = build_fixture()
        cls.pairs, cls.snapshots, cls.predictions = evaluate(
            cls.f.estimator, cls.f.profiles, start_at=midnight(START),
            evaluation_cutoff=FINAL_CUTOFF, config=cls.f.config,
        )

    def test_rolling_origin_cutoffs_and_targets(self):
        by_id = {row.estimate_id: row for row in self.predictions}
        for pair in self.pairs:
            self.assertEqual(pair.target_at - pair.origin_at, timedelta(days=pair.horizon_days))
            target = self.f.observations.by_id[pair.target_observation_id]
            self.assertGreater(target.available_at, pair.origin_at)
            if pair.eligibility != "eligible":
                continue
            for key in (pair.model_a_estimate_id, pair.model_b_estimate_id):
                forecast = by_id[key]
                self.assertEqual(forecast.knowledge_cutoff, pair.origin_at)
                self.assertLessEqual(forecast.last_available_at, forecast.knowledge_cutoff)
                self.assertNotEqual(forecast.last_observation_id, target.observation_id)

    def test_fixture_coverage_and_sample_gate(self):
        summary = report(self.pairs, self.f.config)
        for horizon, eligible in ((7, 15), (30, 8), (60, 2)):
            result = summary["horizons"][str(horizon)]
            totals = result["observed"]
            self.assertEqual(totals["candidate_targets"], 19)
            self.assertEqual(totals["eligible_predictions_per_model"], eligible)
            self.assertAlmostEqual(totals["horizon_coverage"], eligible / 19, places=6)
            self.assertIsNone(totals["statistics"])
            self.assertEqual(totals["statistics_status"], "insufficient_support")
            for buckets in result["strata"].values():
                self.assertEqual(sum(row["candidate_targets"] for row in buckets.values()), 19)
        self.assertEqual(summary["model_training"], "fixed_scenario_priors_no_fit")

    def test_metrics_bias_error_quantiles_and_improvement_when_supported(self):
        pair = next(row for row in self.pairs if row.eligibility == "eligible" and row.horizon_days == 7)
        example = [
            replace(pair, target_weight_kg=400, prediction_a_kg=390, prediction_b_kg=398),
            replace(pair, target_weight_kg=400, prediction_a_kg=404, prediction_b_kg=401),
        ]
        settings = {**self.f.config, "backtest": {
            "min_pairs": 2, "min_animals": 1, "min_lots": 1, "horizons_days": [7],
        }}
        metrics = report(example, settings)["horizons"]["7"]["observed"]["statistics"]
        self.assertEqual(metrics["A"]["mean_bias_kg"], -3)
        self.assertEqual(metrics["A"]["signed_error_quantiles_kg"], {"p10": -8.6, "p50": -3, "p90": 2.6})
        self.assertEqual(metrics["B"]["mae_kg"], 1.5)
        self.assertEqual(metrics["mae_improvement_b_vs_a_kg"], 5.5)

    def test_latent_diagnostic_targets_stay_separate(self):
        latent = latent_targets(self.pairs, self.f.biology, self.f.timeline.snapshot_id)
        self.assertEqual(len(latent), 25)
        targets = {(row.target_observation_id, row.horizon_days): row for row in latent}
        differences = [row.target_weight_kg - targets[row.target_observation_id,
                       row.horizon_days].simulated_weight_kg
                       for row in self.pairs if row.eligibility == "eligible"]
        self.assertTrue(any(abs(value) > 0.01 for value in differences))
        observed = report(self.pairs, self.f.config)
        combined = report(self.pairs, self.f.config, latent=latent)
        for horizon, result in observed["horizons"].items():
            self.assertEqual(result["observed"], combined["horizons"][horizon]["observed"])

    def test_stage1_manual_movements_and_stock_bridge(self):
        checks = validation_checks(self.f.ledger)
        self.assertEqual(len(checks), 49)
        self.assertTrue(all(check.failed_count == 0 for check in checks))
        result, daily, _, _ = calculate_soh(self.f.ledger, START, END, FINAL_CUTOFF)
        yard = [row for row in daily if (row.scope_type, row.scope_id) == YARD]
        self.assertEqual((yard[0].opening_head, sum(row.receipts for row in yard),
                          sum(row.sales for row in yard), sum(row.deaths for row in yard),
                          yard[-1].closing_head, sum(row.animal_days for row in yard)),
                         (2, 10, 5, 2, 5, 338))
        self.assertEqual(result.events, self.f.timeline.result.events)
        self.assertEqual(result.intervals, self.f.timeline.result.intervals)

    def test_daily_estimates_tie_to_operational_active_roster(self):
        daily = tuple(self.f.estimator.daily(START, END))
        self.assertEqual(len(daily), (END - START).days + 1)
        for snapshot, estimates in daily:
            stages = self.f.estimator.snapshot(snapshot.effective_before)[2]
            self.assertEqual(len(estimates), len(stages) * 2)
            self.assertTrue(all(row.snapshot_id == snapshot.snapshot_id for row in estimates))


class PublicationTest(unittest.TestCase):
    def test_cold_runs_are_byte_identical_and_old_output_is_immutable(self):
        def launch(folder, hashseed):
            return subprocess.run(
                [sys.executable, "-m", "simulator_v2.stage2", "--output", str(folder)],
                cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": str(hashseed)},
                capture_output=True, text=True,
            )

        with TemporaryDirectory() as scratch:
            a, b = (Path(scratch) / name for name in ("a", "b"))
            first = launch(a, 13)
            second = launch(b, 19)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            index_bytes = (a / "hashes.json").read_bytes()
            self.assertEqual(index_bytes, (b / "hashes.json").read_bytes())
            index = json.loads(index_bytes)
            for name, digest in index["files"].items():
                self.assertEqual(sha256((a / name).read_bytes()), digest)
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            for folder in (a, b):
                manifest = json.loads((folder / "run_manifest.json").read_bytes())
                self.assertEqual(manifest["hashes_sha256"], sha256(index_bytes))
                self.assertEqual(manifest["schema_version"], "stage2.1")
            duplicate = launch(a, 23)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual((a / "hashes.json").read_bytes(), index_bytes)

    def test_exported_scale_schema_and_lineage_foreign_keys(self):
        from simulator_v2.stage2.export import build

        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "stage2"
            build(path)
            observations = pq.read_table(path / "operational" / "weight_observations.parquet")
            estimates = pq.read_table(path / "operational" / "weight_estimates.parquet").to_pylist()
            snapshots = pq.read_table(path / "operational" / "estimate_snapshots.parquet").to_pylist()
            self.assertEqual(str(observations.schema.field("measured_at").type), "timestamp[us, tz=UTC]")
            self.assertEqual(str(observations.schema.field("measured_weight_kg").type), "double")
            known_weights = set(observations["observation_id"].to_pylist())
            known_snapshots = {row["snapshot_id"] for row in snapshots}
            self.assertTrue(all(row["snapshot_id"] in known_snapshots for row in estimates))
            self.assertTrue(all(row["last_observation_id"] in known_weights | {None} for row in estimates))
            self.assertTrue(all(row["revises_snapshot_id"] in known_snapshots | {None} for row in snapshots))
            self.assertNotIn("simulated_weight_kg", estimates[0])
