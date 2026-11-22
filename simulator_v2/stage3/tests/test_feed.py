from dataclasses import replace
from unittest import TestCase

from simulator_v2.stage1.fixture import A, B, H, R, animal_id, local
from simulator_v2.stage3.allocation import Method, settle
from simulator_v2.stage3.fixture import stage3_fixture
from simulator_v2.stage3.ration import FeedAmount, add_amounts, mix_feed, partition
from simulator_v2.stage3.reconciliation import feed_bridges, wip_candidates
from simulator_v2.stage3.units import split
from simulator_v2.stage3.validation import validate


DEMO = "SYN-DELIVERY-202312311500-PEN-A"


class FeedTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = stage3_fixture()
        cls.results = {row.row.delivery_id: row for row in cls.fixture.active_settlements}
        cls.plans = {row.plan_id: row for row in cls.fixture.schedule.plans}

    def delivery(self, time, pen):
        return next(row for row in self.fixture.deliveries if row.window_start == local(time) and row.pen_id == pen)

    def result(self, time, pen):
        return self.results[self.delivery(time, pen).delivery_id]

    def test_worked_example_three_methods(self):
        settled = self.results[DEMO]
        delivery = next(row for row in self.fixture.deliveries if row.delivery_id == DEMO)
        self.assertEqual(delivery.delivered, FeedAmount(8000, 4000, 40000, 480, 260))
        self.assertEqual(settled.row.refusal, FeedAmount(2000, 1000, 10000, 120, 65))
        self.assertEqual(settled.row.modeled_consumption, FeedAmount(6000, 3000, 30000, 360, 195))
        expected = {
            Method.EQUAL: [(1286, 83), (857, 56), (857, 56)],
            Method.BODYWEIGHT: [(1361, 88), (856, 56), (783, 51)],
            Method.METABOLIC: [(1342, 87), (857, 56), (801, 52)],
        }
        for method, amounts in expected.items():
            rows = [row for row in settled.allocations if row.method == method]
            self.assertEqual([row.animal_id for row in rows], [animal_id(1), animal_id(2), animal_id(5)])
            self.assertEqual([(row.g_dm, row.cents) for row in rows], amounts)

    def test_actual_composition_with_assays_and_substitution(self):
        fixture = self.fixture
        assay_versions = {row.dm_bps for row in fixture.mix_inputs if row.batch_id == "SYN-SILAGE-NEW"}
        self.assertEqual(assay_versions, {4600, 4550})
        early = self.delivery("2024-01-14 08:00", A).mix_id
        late = self.delivery("2024-01-15 08:00", A).mix_id
        samples = {key: {row.assay_id for row in fixture.mix_inputs if row.mix_id == key
                         and row.batch_id == "SYN-SILAGE-NEW"} for key in (early, late)}
        self.assertEqual(samples[early], {"SYN-SILAGE-NEW-DM-1"})
        self.assertEqual(samples[late], {"SYN-SILAGE-NEW-DM-2"})
        mix_id = self.delivery("2024-01-16 08:00", A).mix_id
        selected = next(row for row in fixture.comparisons if row.mix_id == mix_id and row.substitute_g_af)
        self.assertGreater(selected.substitute_g_af, 0)
        self.assertEqual(selected.actual_g_af, selected.expected_g_af)
        self.assertNotEqual(selected.actual_g_dm, selected.expected_g_dm)
        link = next(row for row in fixture.schedule.mix_issues if row.mix_id == mix_id and row.substitution_reason)
        links = [replace(row, substitution_reason=None) if row == link else row
                 for row in fixture.schedule.mix_issues]
        with self.assertRaisesRegex(ValueError, "unapproved ingredient substitution"):
            mix_feed(fixture.warehouse.masters, fixture.formulas, fixture.warehouse_snapshots[0],
                     fixture.schedule.mix_orders, links)

    def test_mixing_truck_and_empty_bunk_losses(self):
        delivery = self.delivery("2024-01-06 08:00", H)
        result = self.results[delivery.delivery_id]
        self.assertEqual(delivery.delivery_loss.g_af, 100)
        self.assertEqual(result.row.roster_status, "empty_no_access")
        self.assertEqual(result.row.refusal, delivery.delivered)
        self.assertEqual(result.row.inferred_unconsumed_g_af, delivery.delivered.g_af)
        self.assertEqual(result.exposures, ())
        self.assertEqual(result.allocations, ())
        mix = next(row for row in self.fixture.mixes if row.mix_id == self.delivery("2024-02-29 08:00", R).mix_id)
        self.assertEqual(mix.loss.g_af, 100)
        self.assertEqual(add_amounts((mix.produced, mix.loss)), mix.input)
        february = self.result("2024-02-29 08:00", R)
        self.assertEqual([row.duration_seconds for row in february.exposures], [3600, 3600, 3600])
        self.assertEqual(february.row.bunk_loss.g_af, 50)

    def test_physical_access_handles_same_day_exit_and_hospital_transfer(self):
        morning = self.result("2023-12-31 08:00", A)
        animal2 = next(row for row in morning.exposures if row.animal_id == animal_id(2))
        self.assertEqual(animal2.end_at, local("2023-12-31 10:00"))
        self.assertEqual(animal2.duration_seconds, 7200)
        self.assertIn(animal_id(4), {row.animal_id for row in self.result("2023-12-31 15:00", B).exposures})
        for pen, sold in ((A, 6), (B, 5)):
            self.assertIn(animal_id(sold), {row.animal_id for row in self.result("2024-01-31 08:00", pen).exposures})
            self.assertNotIn(animal_id(sold), {row.animal_id for row in self.result("2024-01-31 15:00", pen).exposures})
        self.assertIn(animal_id(8), {row.animal_id for row in self.result("2024-01-01 08:00", B).exposures})
        self.assertNotIn(animal_id(8), {row.animal_id for row in self.result("2024-01-01 15:00", B).exposures})
        dies = next(row for row in self.result("2024-01-31 15:00", A).exposures if row.animal_id == animal_id(1))
        self.assertEqual(dies.end_at, local("2024-01-31 16:00"))
        self.assertIn(animal_id(12), {row.animal_id for row in self.result("2024-03-10 15:00", B).exposures})

    def test_restatement_freezes_weights_and_explicitly_handles_incomplete_roster(self):
        current = self.results[DEMO]
        initial = next(row for row in self.fixture.settlements if row.row.settlement_id == current.row.revises_settlement_id)
        self.assertEqual(initial.row.decision_snapshot_id, current.row.decision_snapshot_id)
        self.assertEqual(initial.row.modeled_consumption, current.row.modeled_consumption)
        self.assertEqual({row.animal_id for row in initial.exposures},
                         {animal_id(1), animal_id(2), animal_id(3), animal_id(5)})
        self.assertEqual({row.animal_id for row in current.exposures},
                         {animal_id(1), animal_id(2), animal_id(5)})
        reasons = {row.fallback_reason for result in self.fixture.active_settlements for row in result.weights}
        self.assertTrue({"stale_anchor", "missing_anchor", "unknown_at_decision"} <= reasons)
        entrant = next(row for row in current.weights if row.animal_id == animal_id(5))
        self.assertEqual((entrant.estimate_id, entrant.score_weight_g, entrant.fallback_reason),
                         (None, 400_000, "unknown_at_decision"))
        delivery = self.delivery("2023-12-31 08:00", A)
        ticket = next(row for row in self.fixture.schedule.bunk_tickets if row.delivery_id == DEMO)
        plan = self.plans[delivery.plan_id]
        frozen = self.fixture.schedule.frozen_weights[delivery.window_start]
        with self.assertRaisesRegex(ValueError, "invalid bunk evidence"):
            settle(self.fixture.ledger, delivery, plan, ticket, frozen, 400_000, parent=initial)

    def test_largest_remainder_tie_and_conservation(self):
        self.assertEqual(split(195, {"SYN-A02": 1, "SYN-A01": 1}), {"SYN-A02": 97, "SYN-A01": 98})
        self.assertEqual(split(3, {"b": 1, "a": 1}), {"b": 1, "a": 2})
        amount = FeedAmount(7, 3, 30, 1, 11)
        pieces = partition(amount, {"A": 2, "B": 2, "C": 3})
        self.assertEqual(add_amounts(pieces.values()), amount)
        self.assertEqual(pieces["A"].g_dm, 1)
        with self.assertRaisesRegex(ValueError, "does not conserve"):
            partition(amount, {"short": 6})

    def test_all_hard_gates_and_active_cost_basis(self):
        candidates = wip_candidates(self.fixture)
        bridges = feed_bridges(self.fixture, candidates)
        checks = validate(self.fixture, bridges)
        self.assertGreater(len(checks), 49)
        self.assertFalse(any(row.failed_count for row in checks))
        self.assertEqual(len({row.allocation_id for row in candidates}), len(candidates))
        amounts = next(row for row in bridges if row.period == "horizon")
        self.assertEqual(sum(row.provisional_cents for row in candidates), amounts.consumed.cents)
