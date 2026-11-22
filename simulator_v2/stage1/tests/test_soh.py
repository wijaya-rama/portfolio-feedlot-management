import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pyarrow as pa
import pyarrow.parquet as pq

from simulator_v2.stage1.__main__ import validation_checks
from simulator_v2.stage1.expected import fixture_checks
from simulator_v2.stage1.export import load_ledger
from simulator_v2.stage1.fixture import A, B, END, FINAL_CUTOFF, H, ORIGINAL_CUTOFF, R, REVISED_CUTOFF, START
from simulator_v2.stage1.fixture import animal_id, fixture, local
from simulator_v2.stage1.model import EventKind
from simulator_v2.stage1.provenance import sha256
from simulator_v2.stage1.snapshots import RevisionApproval, SnapshotStore
from simulator_v2.stage1.soh import YARD, calculate_soh
from simulator_v2.stage1.validation import ValidationError

from test_ledger import movement


class StockTest(TestCase):
    def setUp(self):
        self.ledger = fixture()
        self.result, self.daily, self.monthly, self.checks = calculate_soh(
            self.ledger, START, END, FINAL_CUTOFF)

    def test_fixture_has_independent_expected_daily_and_monthly_counts(self):
        report = fixture_checks(self.result, self.daily, self.monthly)
        self.assertTrue(all(check.failed_count == 0 for check in (*self.checks, *report)))
        self.assertEqual(len(self.daily), 576)
        self.assertEqual(len(self.monthly), 32)
        self.assertEqual(sum(row.animal_days for row in self.monthly if row.scope_type == "yard"), 338)
        transfers = [row for row in self.result.events if row.kind == EventKind.TRANSFER]
        self.assertEqual(len(transfers), 15)

    def test_same_day_receipt_exit_and_separate_head_days(self):
        rows = {row.scope_id: row for row in self.daily if row.period_end == date(2024, 3, 10)}
        yard = rows[YARD[1]]
        self.assertEqual((yard.opening_head, yard.receipts, yard.sales, yard.closing_head, yard.animal_days),
                         (5, 1, 1, 5, 6))
        self.assertEqual((rows[R].closing_head, rows[R].animal_days, rows[H].closing_head, rows[H].animal_days),
                         (0, 1, 0, 1))
        self.assertEqual(sum(rows[key].animal_days for key in (A, B, H, R)), 8)

    def test_split_and_compatible_lots_mixed_in_one_pen(self):
        states = {row.animal_id: row for row in self.result.states}
        first_lot = [states[animal_id(n)] for n in (2, 3)]
        self.assertEqual({row.lot_id for row in first_lot}, {"SYN-LOT-1"})
        self.assertEqual({row.location_id for row in first_lot}, {A, B})
        self.assertEqual({row.lot_id for row in states.values() if row.location_id == A},
                         {"SYN-LOT-1", "SYN-LOT-2", "SYN-LOT-3"})

    def test_leap_day_year_end_and_quiet_days_have_separate_rows(self):
        yard = {row.period_end: row for row in self.daily if row.scope_type == "yard"}
        month_closes = [row.period_end for row in self.monthly if row.scope_type == "yard"]
        self.assertEqual(month_closes, [date(2023, 12, 31), date(2024, 1, 31), date(2024, 2, 29), END])
        for left, right in ((date(2023, 12, 31), date(2024, 1, 1)),
                            (date(2024, 2, 28), date(2024, 2, 29)),
                            (date(2024, 2, 29), date(2024, 3, 1))):
            self.assertEqual(yard[left].closing_head, yard[right].opening_head)
        self.assertEqual((yard[date(2024, 2, 28)].opening_head, yard[date(2024, 2, 28)].receipts), (3, 0))
        self.assertEqual((yard[date(2024, 2, 29)].opening_head, yard[date(2024, 2, 29)].receipts), (3, 3))

    def test_interval_boundary_and_end_of_day_match_ledger_at_every_cutoff(self):
        from simulator_v2.stage1.model import midnight
        for row in self.daily:
            if row.scope_type != "location":
                continue
            cut = midnight(row.period_end + timedelta(days=1))
            present = {interval.animal_id for interval in self.result.intervals
                       if interval.location_id == row.scope_id and interval.start_at < cut
                       and (interval.end_at is None or interval.end_at >= cut)}
            self.assertEqual(len(present), row.closing_head, (row.scope_id, row.period_end))
        mar12 = [row for row in self.result.intervals if row.animal_id == animal_id(12)]
        self.assertEqual([row.location_id for row in mar12], [R, B])
        self.assertEqual(mar12[0].end_at, mar12[1].start_at)

    def test_fixture_replays_with_valid_transitions_at_every_availability_boundary(self):
        report = validation_checks(self.ledger)
        self.assertEqual(len(report), 49)
        self.assertFalse(any(c.failed_count for c in report), report)
        self.assertIn({"cutoffs": 25, "violations": 0}, [c.actual for c in report])


class SnapshotTest(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ledger = fixture()
        self.store = SnapshotStore(self.root, self.ledger)
        self.approval = RevisionApproval("SYN-APPROVAL-TEST", "SYN-TEST-REVIEWER",
                                         local("2024-01-04 11:00"), "Approve corrected December")

    def test_unapproved_revision_and_alternate_original_are_blocked(self):
        original, snapshot_id = self.store.publish(START, START, ORIGINAL_CUTOFF)
        with self.assertRaisesRegex(ValidationError, "REVISION_APPROVAL"):
            self.store.publish(START, START, REVISED_CUTOFF, revises=snapshot_id)
        with self.assertRaisesRegex(ValidationError, "SNAPSHOT_LOCKED"):
            self.store.publish(START, START, REVISED_CUTOFF)
        self.assertEqual(self.store.metadata(original)["snapshot_id"], snapshot_id)
        self.assertFalse((original.parent / "revisions").exists())

    def test_revised_snapshot_preserves_bytes_and_links_to_parent(self):
        original, parent = self.store.publish(START, START, ORIGINAL_CUTOFF)
        old = {path.name: path.read_bytes() for path in original.iterdir()}
        revised, child = self.store.publish(START, START, REVISED_CUTOFF, revises=parent,
                                            approval=self.approval)
        self.assertNotEqual(parent, child)
        self.assertEqual(self.store.metadata(revised)["revises_snapshot_id"], parent)
        self.assertEqual(self.store.metadata(revised)["approval"]["approval_id"], self.approval.approval_id)
        self.assertEqual({path.name: path.read_bytes() for path in original.iterdir()}, old)
        row = lambda path: next(r for r in pq.read_table(path / "daily_soh.parquet").to_pylist() if r["scope_id"] == A)
        self.assertEqual((row(original)["closing_head"], row(revised)["closing_head"]), (3, 1))
        self.assertEqual(self.store.publish(START, START, REVISED_CUTOFF, revises=parent,
                                            approval=self.approval), (revised, child))
        self.assertEqual(self.store.publish(START, START, ORIGINAL_CUTOFF), (original, parent))

    def test_conflicting_revision_and_nonadvancing_cutoff_are_blocked(self):
        _, parent = self.store.publish(START, START, ORIGINAL_CUTOFF)
        with self.assertRaisesRegex(ValidationError, "REVISION_CUTOFF"):
            self.store.publish(START, START, ORIGINAL_CUTOFF, revises=parent, approval=self.approval)
        _, child = self.store.publish(START, START, REVISED_CUTOFF, revises=parent, approval=self.approval)
        next_cutoff = local("2024-01-04 10:15")
        with self.assertRaisesRegex(ValidationError, "SNAPSHOT_LOCKED"):
            self.store.publish(START, START, next_cutoff, revises=parent, approval=self.approval)
        path, _ = self.store.publish(START, START, next_cutoff, revises=child, approval=self.approval)
        self.assertEqual(self.store.metadata(path)["revises_snapshot_id"], child)

    def test_failed_replay_blocks_publication(self):
        self.ledger.ingest([movement("BAD", 2, EventKind.TRANSFER, A, R)])
        with self.assertRaisesRegex(ValidationError, "TRANSFER_ROUTE"):
            self.store.publish(START, END, FINAL_CUTOFF)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cold_runs_byte_identical_and_exports_can_be_replayed(self):
        builds = [self.root / name for name in ("a", "b", "different_seed")]
        for directory, seed, hash_seed in zip(builds, (42, 42, 43), ("1", "2", "3"), strict=True):
            subprocess.run([sys.executable, "-m", "simulator_v2.stage1", "--output", str(directory),
                            "--seed", str(seed)], env={**os.environ, "PYTHONHASHSEED": hash_seed},
                           check=True, capture_output=True, text=True)
        first, second, different = builds
        hashes = json.loads((first / "hashes.json").read_text())
        self.assertEqual((first / "hashes.json").read_bytes(), (second / "hashes.json").read_bytes())
        for file, checksum in hashes["files"].items():
            expected = (first / file).read_bytes()
            self.assertEqual(sha256(expected), checksum)
            self.assertEqual(expected, (second / file).read_bytes(), file)
        schema = pq.read_schema(first / "animal_events.parquet")
        self.assertEqual(schema.field("effective_at").type, pa.timestamp("us", tz="UTC"))
        self.assertEqual(schema.field("business_date").type, pa.date32())
        self.assertEqual(pq.read_schema(first / "animals.parquet").field("rfid").type, pa.string())
        reloaded = load_ledger(first)
        self.assertEqual(reloaded.events, self.ledger.events)
        self.assertEqual(calculate_soh(reloaded, START, END, FINAL_CUTOFF),
                         calculate_soh(self.ledger, START, END, FINAL_CUTOFF))
        self.assertNotEqual(dict(reloaded.animals), dict(load_ledger(different).animals))
        (first / "animal_events.parquet").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValidationError, "EXPORT_HASH"):
            load_ledger(first)
