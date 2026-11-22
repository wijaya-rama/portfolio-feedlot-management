import unittest
from dataclasses import replace
from datetime import timedelta

from simulator_v2.stage1.fixture import A, B, H, R, animal_id, local
from simulator_v2.stage1.model import AnimalStatus, business_date
from simulator_v2.stage2.biology import Biology
from simulator_v2.stage2.fixture import build_fixture
from simulator_v2.stage2.health import Action, build_health
from simulator_v2.stage2.observations import Kind, WeighPlan, simulate_observations


class BiologyHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = build_fixture()

    def test_replay_deterministic_with_reversed_inputs(self):
        replay = build_fixture(clinical=reversed(self.f.clinical_inputs), weather=reversed(self.f.weather))
        self.assertEqual(self.f.biology.steps, replay.biology.steps)
        self.assertEqual(self.f.health, replay.health)
        self.assertEqual(self.f.observations.records, replay.observations.records)

    def test_seed_changes_biological_variation_and_same_lot_shares_lot_effect(self):
        alternate = build_fixture(43)
        self.assertNotEqual(self.f.biology.profiles[animal_id(1)].individual_factor,
                            alternate.biology.profiles[animal_id(1)].individual_factor)
        profiles = self.f.biology.profiles
        self.assertEqual(profiles[animal_id(1)].lot_factor, profiles[animal_id(2)].lot_factor)
        self.assertNotEqual(profiles[animal_id(1)].lot_factor, profiles[animal_id(5)].lot_factor)
        self.assertNotEqual(profiles[animal_id(1)].individual_factor, profiles[animal_id(2)].individual_factor)
        self.assertEqual(self.f.timeline.result.states, alternate.timeline.result.states)

    def test_daily_weight_progression_stays_in_synthetic_bounds(self):
        bio = self.f.biology
        low, high = self.f.config["biology"]["gain_bounds_kg_per_day"]
        for rows in bio.steps_by_animal.values():
            by_day = {}
            for row in rows:
                self.assertLessEqual(bio.bounds[0], row.end_weight_kg)
                self.assertLessEqual(row.end_weight_kg, bio.bounds[1])
                by_day.setdefault(business_date(row.start_at), []).append(row)
            for daily in by_day.values():
                gain = daily[-1].end_weight_kg - daily[0].start_weight_kg
                self.assertGreaterEqual(gain, low - 0.034)  # 25-hour local day tolerance
                self.assertLessEqual(gain, high)

    def test_forward_replay_carries_weight_and_identity_over_transfer(self):
        key = animal_id(5)
        rows = self.f.biology.steps_by_animal[key]
        move = local("2023-12-31 15:00")
        old = next(row for row in rows if row.end_at == move)
        new = next(row for row in rows if row.start_at == move)
        self.assertEqual((old.location_id, new.location_id), (A, B))
        self.assertEqual(old.end_weight_kg, new.start_weight_kg)
        self.assertEqual((old.animal_id, old.lot_id), (new.animal_id, new.lot_id))
        self.assertNotEqual(old.location_event_id, new.location_event_id)

    def test_exit_stops_biology_and_uses_existing_stage1_outcome(self):
        timeline = self.f.timeline
        for key, exit in timeline.exits.items():
            steps = self.f.biology.steps_by_animal[key]
            self.assertEqual(steps[-1].end_at, exit.effective_at)
            self.assertIsNone(self.f.biology.weight_at(key, exit.effective_at + timedelta(microseconds=1)))
            self.assertIn(timeline.states[key].status, (AnimalStatus.DEAD, AnimalStatus.SOLD))

    def test_live_measurements_at_or_after_death_are_rejected(self):
        key = animal_id(8)
        death = self.f.timeline.exits[key].effective_at
        for time_delta in (timedelta(0), timedelta(minutes=1)):
            plan = WeighPlan("SYN-IMPOSSIBLE-MEASUREMENT", key, Kind.FOLLOW_UP, death + time_delta)
            with self.subTest(time_delta=time_delta), self.assertRaisesRegex(ValueError, "outside active"):
                simulate_observations(self.f.timeline, self.f.biology, (plan,), self.f.config)

    def test_feed_window_is_split_and_not_a_head_day(self):
        key = animal_id(5)
        feed_at = local("2023-12-31 08:00")
        rows = [row for row in self.f.biology.steps_by_animal[key] if row.window_start_at == feed_at]
        self.assertEqual([row.location_id for row in rows], [R, A])
        self.assertEqual([row.access_fraction for row in rows], [0.25, 0.25])
        self.assertEqual([row.demand_g_dm for row in rows], [1850, 2200])
        self.assertTrue(all(0 < row.consumed_g_dm <= row.demand_g_dm for row in rows))

    def test_feeding_has_no_effect_until_segment_closes(self):
        key = animal_id(5)
        start = local("2024-01-10 08:00")
        rows = self.f.biology.steps_by_animal[key]
        row = next(row for row in rows if row.window_start_at == start)
        just_before = self.f.biology.weight_at(key, row.end_at - timedelta(microseconds=1))
        self.assertAlmostEqual(just_before, row.weight_before_feed_kg, places=7)
        self.assertGreater(self.f.biology.weight_at(key, row.end_at), just_before)

    def test_feed_adapter_is_replaceable(self):
        class NoFeed:
            version = "test-no-feed"

            def consume(adapter_self, **kwargs):
                default = self.f.biology.adapter.consume(**kwargs)
                return replace(default, consumed_g_dm=0, energy_mj=0.0, protein_kg=0.0,
                               adapter_version=adapter_self.version)

        alternative = Biology(self.f.timeline, self.f.profiles, self.f.health, self.f.weather,
                              self.f.config, adapter=NoFeed())
        day = local("2024-01-12 00:00")
        self.assertLess(alternative.weight_at(animal_id(5), day), self.f.biology.weight_at(animal_id(5), day))
        self.assertTrue(all(row.feed_adapter_version == "test-no-feed" for row in alternative.steps))

    def test_hospital_admission_return_and_treatment_chain(self):
        key = animal_id(10)
        events = [row for row in self.f.health if row.animal_id == key]
        self.assertEqual(len({row.episode_id for row in events}), 1)
        self.assertEqual([row.action for row in events], [
            Action.ONSET, Action.PULL, Action.ADMIT, Action.TREAT, Action.REASSESS,
            Action.REPEAT, Action.REASSESS, Action.RECOVER, Action.RETURN,
        ])
        for before, after in zip(events, events[1:]):
            self.assertEqual(after.previous_health_event_id, before.health_event_id)
            self.assertLess(before.effective_at, after.effective_at)
        self.assertEqual(events[2].location_id, H)
        self.assertEqual(events[-1].location_id, B)
        for index in (2, -1):
            move = self.f.timeline.events[events[index].movement_event_id]
            self.assertEqual(events[index].effective_at, move.effective_at)
        hospital = [row for row in self.f.biology.steps_by_animal[key] if row.location_id == H]
        self.assertEqual(sum((row.end_at - row.start_at for row in hospital), timedelta()),
                         timedelta(hours=16, minutes=55))

    def test_paths_include_death_with_and_without_treatment_and_unresolved(self):
        for num, treat in ((1, True), (8, False)):
            rows = [row for row in self.f.health if row.animal_id == animal_id(num)]
            self.assertEqual(rows[-1].action, Action.DEATH)
            self.assertEqual(any(row.action == Action.TREAT for row in rows), treat)
        chronic = [row for row in self.f.health if row.animal_id == animal_id(9)][-1]
        self.assertEqual(chronic.action, Action.CHRONIC)
        self.assertEqual(self.f.timeline.states[chronic.animal_id].status, AnimalStatus.ACTIVE)

    def test_illegal_clinical_transition_is_rejected(self):
        inputs = tuple(row for row in self.f.clinical_inputs if not (
            row.animal_id == animal_id(10) and row.action == Action.PULL))
        with self.assertRaisesRegex(ValueError, "invalid clinical order"):
            build_health(self.f.timeline, inputs, self.f.config)

    def test_after_death_clinical_onset_fails(self):
        original = next(row for row in self.f.clinical_inputs if row.animal_id == animal_id(8))
        fabricated = replace(original, source_id="SYN-IMPOSSIBLE-ONSET",
                             effective_at=local("2024-01-01 19:00"))
        with self.assertRaisesRegex(ValueError, "invalid clinical order"):
            build_health(self.f.timeline, (*self.f.clinical_inputs, fabricated), self.f.config)
