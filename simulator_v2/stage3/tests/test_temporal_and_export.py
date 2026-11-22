import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pyarrow as pa
import pyarrow.parquet as pq

from simulator_v2.stage1.fixture import animal_id, local
from simulator_v2.stage1.ledger import Ledger
from simulator_v2.stage1.provenance import sha256
from simulator_v2.stage2.fixture import build_fixture, clinical_inputs
from simulator_v2.stage2.health import Action
from simulator_v2.stage2.observations import Kind
from simulator_v2.stage3.allocation import Method
from simulator_v2.stage3.biology import LedgerFeed
from simulator_v2.stage3.fixture import load_scenario, stage3_fixture
from simulator_v2.stage3.reconciliation import wip_candidates


class TemporalTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = stage3_fixture()

    def assert_same_feed_before(self, changed, cutoff):
        left, right = self.fixture, changed
        self.assertEqual(tuple(row for row in left.schedule.plans if row.window_start < cutoff),
                         tuple(row for row in right.schedule.plans if row.window_start < cutoff))
        self.assertEqual({key: row for key, row in left.schedule.frozen_weights.items() if key < cutoff},
                         {key: row for key, row in right.schedule.frozen_weights.items() if key < cutoff})
        first = tuple(row for row in left.deliveries if row.window_end < cutoff)
        second = tuple(row for row in right.deliveries if row.window_end < cutoff)
        self.assertEqual(first, second)
        ids = {row.delivery_id for row in first}
        self.assertEqual(tuple(row for row in left.active_settlements if row.row.delivery_id in ids),
                         tuple(row for row in right.active_settlements if row.row.delivery_id in ids))

    def test_late_observation_and_future_terminal_measurement(self):
        def change(row):
            if (row.source_event_id == "SYN-SCALE-05-2024-01-14-follow_up"
                    or row.kind == Kind.FINAL_SALE and row.measured_at > local("2024-01-17 12:00")):
                return replace(row, measured_weight_kg=row.measured_weight_kg + 100)
            return row

        changed = stage3_fixture(observation_transform=change)
        self.assert_same_feed_before(changed, local("2024-01-17 12:15"))
        at = local("2024-01-17 15:00")
        animal = animal_id(5)
        left, right = (candidate.schedule.frozen_weights[at][animal] for candidate in (self.fixture, changed))
        self.assertEqual(left.anchor_available_at, local("2024-01-17 12:15"))
        self.assertEqual(left.anchor_observation_id, right.anchor_observation_id)
        self.assertNotEqual(left.score_weight_g, right.score_weight_g)

    def test_weather_can_change_later_growth_without_changing_any_feed(self):
        records = tuple(replace(row, scenario="hot") if index == 0 else row
                        for index, row in enumerate(self.fixture.weather))
        changed = stage3_fixture(weather=records)
        self.assert_same_feed_before(changed, local("2024-03-12 00:00"))
        animal = animal_id(5)
        before, after = local("2024-01-12 11:30"), local("2024-01-12 19:00")
        self.assertEqual(self.fixture.biology.weight_at(animal, before), changed.biology.weight_at(animal, before))
        self.assertNotEqual(self.fixture.biology.weight_at(animal, after), changed.biology.weight_at(animal, after))

    def test_future_health_and_terminal_outcome_cannot_change_prior_feed(self):
        stage1 = self.fixture.ledger
        death = self.fixture.timeline.exits[animal_id(1)]
        ledger = Ledger(stage1.config, stage1.lots.values(), stage1.animals.values(),
                        stage1.location_versions.values())
        ledger.ingest(row for row in stage1.events if row.event_id != death.event_id)
        outcome = stage3_fixture(ledger=ledger)
        self.assert_same_feed_before(outcome, death.effective_at)
        self.assertNotEqual(self.fixture.timeline.snapshot_id, outcome.timeline.snapshot_id)
        self.assertIn(animal_id(1), outcome.schedule.frozen_weights[local("2024-02-01 08:00")])
        records = tuple(replace(row, effective_at=row.effective_at + timedelta(days=3))
                        if row.animal_id == animal_id(5) and row.action == Action.RECOVER else row
                        for row in clinical_inputs())
        changed = stage3_fixture(clinical=records)
        self.assert_same_feed_before(changed, local("2024-01-24 07:30"))
        at = local("2024-01-25 08:00")
        self.assertNotEqual(self.fixture.schedule.frozen_weights[at][animal_id(5)].score_weight_g,
                            changed.schedule.frozen_weights[at][animal_id(5)].score_weight_g)

    def test_growth_credits_exact_ledger_grams_and_only_after_segment(self):
        f = self.fixture
        totals = Counter()
        for row in f.growth_inputs:
            totals[row.allocation_id] += row.g_dm
        for settlement in f.active_settlements:
            for row in settlement.allocations:
                if row.method == Method.METABOLIC:
                    self.assertEqual(totals[row.allocation_id], row.g_dm)
        step = next(row for row in f.biology.steps if row.animal_id == animal_id(1)
                    and row.start_at == local("2023-12-31 08:00"))
        self.assertGreater(step.consumed_g_dm, 0)
        self.assertAlmostEqual(f.biology.weight_at(step.animal_id, step.end_at - timedelta(microseconds=1)),
                               step.weight_before_feed_kg, places=8)
        self.assertEqual(f.biology.weight_at(step.animal_id, step.end_at), step.end_weight_kg)
        baseline = build_fixture().biology
        self.assertNotEqual(baseline.adapter.version, LedgerFeed.version)
        self.assertNotEqual(baseline.weight_at(step.animal_id, local("2024-01-15 12:00")),
                            f.biology.weight_at(step.animal_id, local("2024-01-15 12:00")))

    def test_changing_allocation_method_holds_delivery_and_operational_weights_fixed(self):
        scenario = load_scenario()
        scenario["method"] = Method.EQUAL
        comparison = stage3_fixture(scenario=scenario)
        self.assertEqual(comparison.deliveries, self.fixture.deliveries)
        self.assertEqual(comparison.schedule.frozen_weights, self.fixture.schedule.frozen_weights)
        self.assertEqual(comparison.active_settlements, self.fixture.active_settlements)
        self.assertEqual(sum(row.provisional_cents for row in wip_candidates(comparison)),
                         sum(row.provisional_cents for row in wip_candidates(self.fixture)))
        self.assertNotEqual(comparison.biology.steps, self.fixture.biology.steps)


class ExportTests(TestCase):
    def build(self, output, hash_seed):
        return subprocess.run([sys.executable, "-m", "simulator_v2.stage3", "--output", str(output)],
                              env={**os.environ, "PYTHONHASHSEED": hash_seed},
                              text=True, capture_output=True, check=False)

    def test_two_cold_builds_publish_identical_typed_artifacts(self):
        with TemporaryDirectory() as folder:
            first, second = Path(folder) / "first", Path(folder) / "second"
            for path, seed in ((first, "19"), (second, "73")):
                completed = self.build(path, seed)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            hashes = (first / "hashes.json").read_bytes()
            self.assertEqual(hashes, (second / "hashes.json").read_bytes())
            index = json.loads(hashes)
            for path, digest in index["files"].items():
                self.assertEqual(sha256((first / path).read_bytes()), digest)
                self.assertEqual((first / path).read_bytes(), (second / path).read_bytes())
            manifest = json.loads((first / "run_manifest.json").read_bytes())
            self.assertEqual(manifest["hashes_sha256"], sha256(hashes))
            self.assertEqual(manifest["default_allocation_method"], "metabolic_bodyweight")
            allocations = pq.read_table(first / "feed" / "allocations.parquet")
            self.assertEqual(allocations.schema.field("cents").type, pa.int64())
            self.assertEqual(allocations.schema.field("access_start").type, pa.timestamp("us", tz="UTC"))
            self.assertEqual(len(set(allocations["allocation_id"].to_pylist())), allocations.num_rows)
            mixes = pq.read_table(first / "feed" / "mix_batches.parquet")
            self.assertTrue(pa.types.is_struct(mixes.schema.field("produced").type))
            failed = self.build(first, "19")
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(json.loads(failed.stderr)["status"], "failed")
            self.assertEqual((first / "hashes.json").read_bytes(), hashes)
