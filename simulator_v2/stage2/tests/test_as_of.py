import unittest
from dataclasses import replace
from datetime import timedelta

from simulator_v2.stage1.fixture import A, B, animal_id, local
from simulator_v2.stage1.ledger import Ledger
from simulator_v2.stage2.estimation import Estimator, Model, assess_draft, operational_health
from simulator_v2.stage2.fixture import build_fixture, draft_example
from simulator_v2.stage2.health import Action
from simulator_v2.stage2.observations import Kind, Observations, correct

EPSILON = timedelta(microseconds=1)


class AsOfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = build_fixture()
        cls.animal = animal_id(5)
        cls.ticket = next(row for row in cls.f.observations.records
                          if row.animal_id == cls.animal and row.kind == Kind.FOLLOW_UP
                          and row.corrects_observation_id is None)
        cls.correction = next(row for row in cls.f.observations.records
                               if row.corrects_observation_id == cls.ticket.observation_id)

    def build_estimator(self, records):
        observed = Observations(self.f.timeline, records, self.f.config)
        return Estimator(self.f.ledger, observed, operational_health(self.f.health), self.f.config)

    def estimates(self, stamp, estimator=None, animal=None):
        estimator = estimator or self.f.estimator
        return estimator.estimates(stamp, animal_id=animal or self.animal)[1]

    def test_scale_chronology_and_kind_coverage(self):
        rows = self.f.observations.records
        self.assertEqual({row.kind for row in rows}, set(Kind))
        self.assertTrue(all(row.measured_at <= row.posted_at <= row.available_at for row in rows))
        for row in rows:
            if row.kind == Kind.FINAL_SALE:
                sale = self.f.timeline.exits[row.animal_id]
                self.assertLess(row.measured_at, sale.effective_at)
                self.assertGreaterEqual(row.available_at, sale.available_at)

    def test_invalid_posting_and_availability_rejected(self):
        for altered in (replace(self.ticket, posted_at=self.ticket.measured_at - EPSILON),
                        replace(self.ticket, available_at=self.ticket.posted_at - EPSILON)):
            with self.assertRaisesRegex(ValueError, "invalid scale record"):
                self.build_estimator((altered,))

    def test_future_late_ticket_value_cannot_change_estimate_before_availability(self):
        modified = self.build_estimator(
            replace(row, measured_weight_kg=619.0) if row == self.ticket else row
            for row in self.f.observations.records)
        for when in (self.ticket.measured_at + EPSILON, self.ticket.posted_at,
                     self.ticket.available_at - EPSILON):
            self.assertEqual(self.f.estimator.estimates(when), modified.estimates(when))
        self.assertNotEqual(self.estimates(self.ticket.available_at),
                            self.estimates(self.ticket.available_at, modified))

    def test_exact_availability_updates_anchor_and_both_models(self):
        before = self.estimates(self.ticket.available_at - EPSILON)
        after = self.estimates(self.ticket.available_at)
        self.assertEqual(before[0].estimated_liveweight_kg, 449.3)
        self.assertEqual(after[0].estimated_liveweight_kg, self.ticket.measured_weight_kg)
        self.assertEqual({row.last_observation_id for row in after}, {self.ticket.observation_id})
        self.assertNotEqual(before[1].estimated_liveweight_kg, after[1].estimated_liveweight_kg)

    def test_correction_creates_versioned_retrospective_view(self):
        origin = self.correction.available_at - timedelta(hours=1)
        original, before = self.f.estimator.estimates(origin)
        with self.assertRaisesRegex(ValueError, "requires a revision reason"):
            self.f.estimator.estimates(origin, self.correction.available_at)
        revised, after = self.f.estimator.estimates(
            origin, self.correction.available_at, revision_reason="SYN-TEST-REVISION")
        self.assertNotEqual(revised.snapshot_id, original.snapshot_id)
        self.assertEqual(revised.revises_snapshot_id, original.snapshot_id)
        self.assertEqual(self.f.estimator.estimates(origin), (original, before))
        weights = [row for row in after if row.animal_id == self.animal]
        self.assertTrue(all(row.last_observation_id == self.correction.observation_id for row in weights))
        self.assertEqual(weights[0].estimated_liveweight_kg, 457.8)

    def test_correction_cannot_branch_or_change_the_measurement_context(self):
        fork = correct(self.ticket, source_id="SYN-WEIGHT-FORK",
                       posted_at=self.correction.posted_at,
                       available_at=self.correction.available_at + EPSILON, measured_weight_kg=450.0)
        with self.assertRaisesRegex(ValueError, "invalid weighing correction"):
            self.build_estimator((*self.f.observations.records, fork))
        changed = replace(self.correction, measured_at=self.correction.measured_at + EPSILON)
        with self.assertRaisesRegex(ValueError, "invalid weighing correction"):
            self.build_estimator((self.ticket, changed))

    def test_new_rejection_drops_corrected_anchor_without_erasing_it(self):
        rejection = correct(self.correction, source_id="SYN-WEIGHT-REJECTION",
                            posted_at=self.correction.available_at + EPSILON,
                            available_at=self.correction.available_at + 2 * EPSILON,
                            measured_weight_kg=self.correction.measured_weight_kg, rejected=True)
        modified = self.build_estimator((*self.f.observations.records, rejection))
        self.assertEqual(self.estimates(rejection.available_at - EPSILON, modified)[0].last_observation_id,
                         self.correction.observation_id)
        self.assertEqual(self.estimates(rejection.available_at, modified)[0].estimated_liveweight_kg, 449.3)

    def test_cutoff_equal_to_measurement_excludes_it_even_if_already_posted(self):
        receiving = next(row for row in self.f.observations.records
                         if row.animal_id == self.animal and row.kind == Kind.RECEIVING)
        time = local("2024-01-29 12:00")
        draft = next(row for row in self.f.observations.records
                     if row.animal_id == self.animal and row.kind == Kind.DRAFTING)
        estimator = self.build_estimator(
            (receiving, replace(draft, posted_at=time, available_at=time)))
        self.assertEqual(self.estimates(time, estimator)[0].last_observation_id, receiving.observation_id)
        self.assertEqual(self.estimates(time + EPSILON, estimator)[0].last_observation_id, draft.observation_id)

    def test_missing_scale_attempt_and_no_anchor_fallback(self):
        entry = next(row for row in self.f.attempts if row.animal_id == animal_id(11)
                     and row.kind == Kind.RECEIVING)
        self.assertEqual(entry.status, "missing")
        self.assertIsNone(entry.observation_id)
        rows = self.estimates(local("2024-03-06 08:00"), animal=entry.animal_id)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNone(row.estimated_liveweight_kg)
            self.assertEqual(row.fallback_flag, "missing_anchor")
            self.assertEqual(row.confidence_status, "unavailable")

    def test_stale_anchor_has_bounded_projection_and_low_confidence(self):
        rows = self.estimates(local("2024-02-28 12:00"), animal=animal_id(2))
        first, second = rows
        self.assertGreater(second.days_since_last_weighing, 35)
        self.assertEqual(second.confidence_status, "low_stale")
        self.assertEqual(second.fallback_flag, "projection_capped")
        self.assertAlmostEqual(second.estimated_liveweight_kg - first.estimated_liveweight_kg,
                               second.adg_prior_kg * 35, places=2)

    def test_estimate_location_replays_late_stage1_transfer_at_cutoff(self):
        before = local("2024-01-02 07:59")
        after = local("2024-01-02 08:00")
        self.assertEqual(self.estimates(before)[0].location_id, A)
        self.assertEqual(self.estimates(after)[0].location_id, B)
        self.assertEqual(self.estimates(before)[0].lot_id, self.estimates(after)[0].lot_id)

    def test_future_terminal_scale_value_cannot_change_earlier_operational_decision(self):
        modified = self.build_estimator(
            replace(row, measured_weight_kg=row.measured_weight_kg + 155)
            if row.kind == Kind.FINAL_SALE else row for row in self.f.observations.records)
        cutoff = local("2024-01-31 10:59")
        self.assertEqual(self.f.estimator.estimates(cutoff), modified.estimates(cutoff))
        self.assertEqual(draft_example(self.f.estimator), draft_example(modified))
        self.assertEqual(self.estimates(local("2024-01-31 11:01"), modified), ())

    def test_future_terminal_outcome_removed_does_not_change_past(self):
        baseline = self.f.ledger
        death = self.f.timeline.exits[animal_id(1)]
        ledger = Ledger(baseline.config, baseline.lots.values(), baseline.animals.values(),
                        baseline.location_versions.values())
        ledger.ingest(event for event in baseline.events if event.event_id != death.event_id)
        changed = build_fixture(ledger=ledger)
        cutoff = local("2024-01-30 15:30")
        self.assertNotEqual(self.f.timeline.snapshot_id, changed.timeline.snapshot_id)
        self.assertEqual(self.f.estimator.estimates(cutoff), changed.estimator.estimates(cutoff))
        self.assertEqual(draft_example(self.f.estimator), draft_example(changed.estimator))
        later = local("2024-02-01 07:00")
        self.assertEqual(self.estimates(later, animal=death.animal_id), ())
        self.assertTrue(self.estimates(later, changed.estimator, animal=death.animal_id))

    def test_future_recovery_change_cannot_change_earlier_estimate(self):
        inputs = tuple(replace(row, effective_at=row.effective_at + timedelta(days=3))
                       if row.animal_id == self.animal and row.action == Action.RECOVER else row
                       for row in self.f.clinical_inputs)
        changed = build_fixture(clinical=inputs)
        for when in ("2024-01-20 12:00", "2024-01-23 18:00"):
            cutoff = local(when)
            self.assertEqual(self.f.estimator.estimates(cutoff), changed.estimator.estimates(cutoff))
        later = local("2024-01-25 12:00")
        self.assertEqual(self.estimates(later)[1].clinical_status, "recovered")
        self.assertEqual(self.estimates(later, changed.estimator)[1].clinical_status, "ill")
        self.assertNotEqual(self.f.biology.weight_at(self.animal, later),
                            changed.biology.weight_at(self.animal, later))

    def test_late_first_observation_is_invisible_even_after_its_effective_time(self):
        available = local("2024-01-21 08:30")
        inputs = tuple(replace(row, posted_at=available - timedelta(minutes=10), available_at=available)
                       if row.animal_id == self.animal and row.action == Action.PULL else row
                       for row in self.f.clinical_inputs)
        changed = build_fixture(clinical=inputs)
        reference = Estimator(changed.ledger, changed.observations,
                              (row for row in operational_health(changed.health)
                               if not (row.animal_id == self.animal and row.available_at >= available)),
                              changed.config)
        self.assertEqual(reference.estimates(available - EPSILON),
                         changed.estimator.estimates(available - EPSILON))
        eligible = self.estimates(available, changed.estimator)[1]
        self.assertEqual(eligible.clinical_status, "ill")
        self.assertEqual(assess_draft(eligible, 1).reason, "observed_health")

    def test_future_weather_perturbation_does_not_change_origin_features_or_forecast(self):
        future = self.f.weather[0]
        changed = build_fixture(weather=tuple(
            replace(row, scenario="hot") if row == future else row for row in self.f.weather))
        origin = future.observed_at - timedelta(minutes=10)
        target = origin + timedelta(days=7)
        self.assertEqual(self.f.estimator.estimates(origin, estimate_for=target),
                         changed.estimator.estimates(origin, estimate_for=target))
        self.assertEqual(self.f.biology.weight_at(self.animal, origin),
                         changed.biology.weight_at(self.animal, origin))
        self.assertNotEqual(self.f.biology.weight_at(self.animal, future.observed_at + timedelta(hours=6)),
                            changed.biology.weight_at(self.animal, future.observed_at + timedelta(hours=6)))

    def test_forecast_target_uses_frozen_prior_and_only_changes_projection_duration(self):
        origin = local("2024-01-13 12:15")
        model_b = self.estimates(origin)[1]
        snapshot, rows = self.f.estimator.estimates(origin, estimate_for=origin + timedelta(days=7),
                                                   animal_id=self.animal, models=(Model.B,))
        forecast, = rows
        self.assertEqual(forecast.snapshot_id, model_b.snapshot_id)
        self.assertEqual(forecast.last_observation_id, model_b.last_observation_id)
        self.assertEqual(forecast.adg_prior_kg, model_b.adg_prior_kg)
        self.assertEqual(snapshot.knowledge_cutoff, origin)
