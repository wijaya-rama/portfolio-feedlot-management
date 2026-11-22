from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest import TestCase

from simulator_v2.stage1.fixture import A, B, END, FINAL_CUTOFF, H, R, START, animal_id, fixture, local
from simulator_v2.stage1.ledger import Ledger
from simulator_v2.stage1.model import UTC, AnimalEvent, AnimalStatus, EventKind, Source, business_date, midnight
from simulator_v2.stage1.replay import replay
from simulator_v2.stage1.validation import ValidationError


def copy_ledger(ledger, *, lots=None, versions=None, config=None, empty=False):
    copy = Ledger(config or ledger.config, ledger.lots.values() if lots is None else lots,
                  ledger.animals.values(), ledger.location_versions.values() if versions is None else versions)
    if not empty:
        copy.ingest(ledger.events)
    return copy


def event(ledger, doc, number):
    return next(row for row in ledger.events
                if row.source.document_id == "SYN-" + doc and row.animal_id == animal_id(number))


def movement(line, number, kind, source=None, target=None, *,
             when="2024-03-11 08:00", sequence=100):
    instant = local(when)
    return AnimalEvent(f"SYN-EXTRA-{line}", animal_id(number), kind, instant, instant, instant,
                       sequence, Source("SYN-TEST", "SYN-DOC", line), source, target)


class LedgerTest(TestCase):
    def setUp(self):
        self.ledger = fixture()

    def failure(self, check_id, records):
        before = self.ledger.events
        with self.assertRaises(ValidationError) as raised:
            self.ledger.ingest(records)
        self.assertEqual(raised.exception.checks[0].check_id, check_id)
        self.assertEqual(self.ledger.events, before)

    def test_idempotent_retry_even_with_corrections(self):
        self.assertEqual(self.ledger.ingest((*self.ledger.events, *self.ledger.events)), 0)
        self.assertEqual(len(self.ledger.events), 37)

    def test_duplicate_event_id_rejected(self):
        row = event(self.ledger, "PLACE-DEC", 4)
        self.failure("DUPLICATE_EVENT_ID", [replace(row, sequence=200)])

    def test_duplicate_source_row_rejected(self):
        row = event(self.ledger, "PLACE-DEC", 4)
        self.failure("DUPLICATE_SOURCE_KEY", [replace(row, event_id="SYN-ALTERNATE")])

    def test_atomic_batch_and_invalid_location_fk(self):
        valid = movement("OK", 2, EventKind.TRANSFER, A, H)
        invalid = movement("BAD", 3, EventKind.TRANSFER, B, "SYN-UNKNOWN")
        self.failure("LOCATION_FK", [valid, invalid])

    def test_receipt_wrong_location_or_invalid_event_endpoints(self):
        self.failure("RECEIPT_TARGET", [movement("BAD", 2, EventKind.RECEIPT, target=A)])
        self.failure("EVENT_ENDPOINTS", [movement("BAD", 2, EventKind.SALE, A, B)])
        self.failure("TRANSFER_SELF", [movement("BAD", 2, EventKind.TRANSFER, A, A)])

    def test_invalid_clock_and_synthetic_flag(self):
        row = movement("BAD", 2, EventKind.TRANSFER, A, H)
        self.failure("TIMESTAMPS", [replace(row, available_at=row.posted_at - timedelta(seconds=1))])
        self.failure("TIMESTAMPS", [replace(row, effective_at=row.effective_at.replace(tzinfo=None))])
        self.failure("SYNTHETIC", [replace(row, synthetic=False)])

    def test_repeated_and_stale_reversal(self):
        reversal = event(self.ledger, "VOID-JAN", 1)
        self.assertEqual(self.ledger.ingest([reversal]), 0)
        clock = reversal.available_at + timedelta(seconds=1)
        another = replace(reversal, event_id="SYN-DOUBLE-VOID", posted_at=clock, available_at=clock,
                          source=replace(reversal.source, revision=2))
        self.failure("CORRECTION_BRANCH", [another])
        self.failure("CORRECTION_TARGET", [replace(another, supersedes_event_id=reversal.event_id)])

    def test_correction_clock_and_reversal_effective_time(self):
        row = event(self.ledger, "PLACE-JAN", 6)
        reversal = movement("BAD", 6, EventKind.REVERSAL)
        reversal = replace(reversal, supersedes_event_id=row.event_id, reason="TEST")
        self.failure("REVERSAL_TIME", [reversal])
        self.failure("CORRECTION_CLOCK", [replace(reversal, effective_at=row.effective_at,
                                                  available_at=row.available_at, posted_at=row.posted_at)])

    def test_invalid_rfid_and_duplicate_location_boundary(self):
        animals = list(self.ledger.animals.values())
        versions = list(self.ledger.location_versions.values())
        animals[-1] = replace(animals[-1], rfid=animals[0].rfid)
        with self.assertRaisesRegex(ValidationError, "RFID"):
            Ledger(self.ledger.config, self.ledger.lots.values(), animals, versions)
        with self.assertRaisesRegex(ValidationError, "LOCATION_VERSION"):
            copy_ledger(self.ledger, versions=[*versions, replace(versions[0], location_version_id="SYN-COPY")])


class ReplayTest(TestCase):
    def setUp(self):
        self.ledger = fixture()

    def state(self, cutoff=FINAL_CUTOFF, effective_before=FINAL_CUTOFF):
        return replay(self.ledger, effective_before, cutoff)

    def location(self, number, **kwargs):
        return next(row.location_id for row in self.state(**kwargs).states if row.animal_id == animal_id(number))

    def rejected(self, check_id, row):
        self.ledger.ingest([row])
        result = self.state()
        self.assertNotIn(row.event_id, {valid.event_id for valid in result.events})
        self.assertIn(check_id, {check.check_id for check in result.checks if check.failed_count})

    def test_same_timestamp_sequence_then_id_independent_of_ingestion_order(self):
        winner = movement("A", 10, EventKind.TRANSFER, B, H)
        loser = movement("Z", 3, EventKind.TRANSFER, B, H)
        before_both = movement("M", 2, EventKind.TRANSFER, A, B, sequence=99)
        self.ledger.ingest([loser, winner, before_both])
        result = self.state()
        self.assertEqual([row for row in result.events if row.effective_at == winner.effective_at],
                         [before_both, winner])
        self.assertEqual(self.location(10), H)
        self.assertEqual(self.location(3), B)
        self.assertEqual(result.checks[0].sample_ids, (loser.event_id,))
        rebuilt = copy_ledger(self.ledger, empty=True)
        rebuilt.ingest(reversed(self.ledger.events))
        self.assertEqual(replay(rebuilt, FINAL_CUTOFF, FINAL_CUTOFF), result)

    def test_late_event_uses_availability_and_includes_exact_cutoff(self):
        row = event(self.ledger, "LATE-DEC", 5)
        for cutoff in (row.posted_at - timedelta(seconds=1), row.posted_at,
                       row.available_at - timedelta(microseconds=1)):
            self.assertEqual(self.location(5, cutoff=cutoff, effective_before=midnight(date(2024, 1, 1))), A)
        self.assertEqual(self.location(5, cutoff=row.available_at,
                                       effective_before=midnight(date(2024, 1, 1))), B)

    def test_backdated_supersession_keeps_source_and_respects_historical_cutoff(self):
        original = event(self.ledger, "PLACE-DEC", 3)
        fix = event(self.ledger, "FIX-DEC", 3)
        effective = midnight(date(2024, 1, 1))
        old = self.state(cutoff=fix.available_at - timedelta(microseconds=1), effective_before=effective)
        new = self.state(cutoff=fix.available_at, effective_before=effective)
        self.assertEqual(fix.supersedes_event_id, original.event_id)
        self.assertIn(original, old.events)
        self.assertIn(original, new.known_events)
        self.assertNotIn(original, new.events)
        self.assertIn(fix, new.events)
        self.assertEqual(self.location(3, cutoff=fix.available_at, effective_before=effective), B)

    def test_reversal_removes_transfer_without_creating_reentry(self):
        row = event(self.ledger, "VOID-JAN", 1)
        jan_close = midnight(date(2024, 1, 2))
        self.assertEqual(self.location(1, cutoff=row.available_at - timedelta(microseconds=1),
                                       effective_before=jan_close), B)
        result = self.state(cutoff=row.available_at, effective_before=jan_close)
        self.assertEqual(self.location(1, cutoff=row.available_at, effective_before=jan_close), A)
        self.assertNotIn(row, result.events)
        self.assertFalse(any(e.event_id == row.supersedes_event_id for e in result.events))

    def test_replacement_can_reschedule_a_prior_movement_past_effective_cutoff(self):
        base = event(self.ledger, "FIX-DEC", 3)
        revised = replace(base, event_id="SYN-RESCHEDULED", effective_at=local("2024-01-01 06:00"),
                          posted_at=local("2024-01-05 09:00"), available_at=local("2024-01-05 09:00"),
                          supersedes_event_id=base.event_id, source=replace(base.source, revision=2))
        self.ledger.ingest([revised])
        dec_close = midnight(date(2024, 1, 1))
        self.assertEqual(self.location(3, cutoff=revised.available_at, effective_before=dec_close), R)
        self.assertEqual(self.location(3, cutoff=revised.available_at,
                                       effective_before=revised.effective_at + timedelta(microseconds=1)), B)

    def test_transfer_after_sale_or_death_and_duplicate_exit(self):
        for row in (movement("SOLD-MOVE", 4, EventKind.TRANSFER, B, A),
                    movement("DEAD-MOVE", 8, EventKind.TRANSFER, B, A),
                    movement("DOUBLE-EXIT", 4, EventKind.DEATH, B)):
            self.rejected("ACTIVE_REQUIRED", row)
        states = {row.animal_id: row for row in self.state().states}
        for number, status in ((4, AnimalStatus.SOLD), (8, AnimalStatus.DEAD)):
            self.assertEqual((states[animal_id(number)].status, states[animal_id(number)].location_id),
                             (status, None))

    def test_wrong_source_and_illegal_route_do_not_change_location(self):
        self.rejected("SOURCE_STATE", movement("WRONG-SOURCE", 2, EventKind.TRANSFER, B, H))
        self.rejected("TRANSFER_ROUTE", movement("WRONG-TARGET", 2, EventKind.TRANSFER, A, R))
        self.assertEqual(self.location(2), A)

    def test_capacity_violation_keeps_animal_in_its_source(self):
        self.ledger.ingest([movement("FILL", 2, EventKind.TRANSFER, A, H, sequence=90)])
        self.rejected("CAPACITY", movement("OVER", 3, EventKind.TRANSFER, B, H))
        self.assertEqual((self.location(2), self.location(3)), (H, B))

    def test_capacity_version_checked_without_a_movement_at_its_boundary(self):
        versions = [replace(v, capacity_head=1) if v.location_version_id == f"{B}-V2" else v
                    for v in self.ledger.location_versions.values()]
        self.ledger = copy_ledger(self.ledger, versions=versions)
        before = midnight(date(2024, 2, 29))
        self.assertFalse(any(c.failed_count for c in self.state(effective_before=before).checks))
        checks = self.state(effective_before=before + timedelta(microseconds=1)).checks
        self.assertEqual([(c.check_id, c.actual) for c in checks], [("CAPACITY_VERSION", 2)])

    def test_location_master_must_be_effective_and_available(self):
        versions = [replace(v, available_at=FINAL_CUTOFF) if v.location_id == H else v
                    for v in self.ledger.location_versions.values()]
        self.ledger = copy_ledger(self.ledger, versions=versions)
        self.assertIn("LOCATION_EFFECTIVE", [c.check_id for c in self.state(
            cutoff=FINAL_CUTOFF - timedelta(seconds=1)).checks])
        self.assertFalse(any(c.failed_count for c in self.state().checks))

    def test_incompatible_lots_rejected_when_placed_together(self):
        lots = [replace(lot, compatibility_group="different") if lot.lot_id == "SYN-LOT-2" else lot
                for lot in self.ledger.lots.values()]
        self.ledger = copy_ledger(self.ledger, lots=lots)
        checks = self.state(effective_before=midnight(date(2024, 1, 1))).checks
        self.assertIn("LOT_COMPATIBILITY", [c.check_id for c in checks])

    def test_dst_fall_back_orders_two_visits_to_same_wall_clock(self):
        config = replace(self.ledger.config, end_date=date(2024, 11, 4))
        self.ledger = copy_ledger(self.ledger, config=config)
        fold_zero = local("2024-11-03 01:30", fold=0)
        fold_one = local("2024-11-03 01:30", fold=1)
        check_clock = midnight(date(2024, 11, 4))
        self.assertEqual(fold_one - fold_zero, timedelta(hours=1))
        self.assertEqual(check_clock - midnight(date(2024, 11, 3)), timedelta(hours=25))
        self.assertEqual(business_date(fold_one), date(2024, 11, 3))
        admit = movement("FALL-IN", 2, EventKind.TRANSFER, A, H, when="2024-11-03 01:30")
        release = movement("FALL-OUT", 2, EventKind.TRANSFER, H, A, when="2024-11-03 01:30")
        release = replace(release, effective_at=fold_one, posted_at=fold_one, available_at=fold_one)
        self.ledger.ingest([release, admit])
        self.assertEqual(self.location(2, cutoff=check_clock, effective_before=fold_one), H)
        self.assertEqual(self.location(2, cutoff=check_clock, effective_before=check_clock), A)

    def test_spring_transition_and_midnight_are_effective_cutoff_boundaries(self):
        start = midnight(date(2024, 3, 10))
        close = midnight(date(2024, 3, 11))
        self.assertEqual(close - start, timedelta(hours=23))
        self.assertEqual(start, datetime(2024, 3, 10, 7, tzinfo=UTC))
        self.assertNotIn(animal_id(12), {row.animal_id for row in self.state(effective_before=start).states})
        self.assertEqual(self.location(12, effective_before=start + timedelta(microseconds=1)), R)
        pre_gap, post_gap = local("2024-03-10 01:55"), local("2024-03-10 03:05")
        self.assertEqual(post_gap - pre_gap, timedelta(minutes=10))
        self.assertEqual(business_date(post_gap), date(2024, 3, 10))
