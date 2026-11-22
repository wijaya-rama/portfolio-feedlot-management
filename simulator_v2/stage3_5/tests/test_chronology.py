"""Independent numeric expectations and cross-stage temporal perturbations."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from simulator_v2.stage1.fixture import A, B, END, FINAL_CUTOFF, START, animal_id, fixture, local
from simulator_v2.stage1.ledger import Ledger
from simulator_v2.stage1.model import EventKind, business_date
from simulator_v2.stage1.provenance import canonical, sha256
from simulator_v2.stage1.soh import calculate_soh
from simulator_v2.stage2.biology import make_profile
from simulator_v2.stage2.config import load_config
from simulator_v2.stage2.health import Action, ClinicalInput, build_health
from simulator_v2.stage2.observations import Kind, WeighPlan
from simulator_v2.stage2.timeline import PhysicalTimeline
from simulator_v2.stage3.allocation import BunkTicket, Method, Plan, settle
from simulator_v2.stage3.ration import EMPTY, Delivery, FeedAmount
from simulator_v2.stage3.reconciliation import wip_candidates
from simulator_v2.stage3_5.biology import ChronologicalBiology, ChronologicalFeed
from simulator_v2.stage3_5.feeding import TimedAllocation, growth_clock
from simulator_v2.stage3_5.fixture import integrated_fixture, load_scenario
from simulator_v2.stage3_5.observations import ScaleBook

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


def ticket(fixture, source_id):
    return next(row for row in fixture.observations if row.source_event_id == source_id)


def plan_at(fixture, pen, cutoff):
    return next(row for row in fixture.schedule.plans if row.pen_id == pen and row.decision_at == cutoff)


def manual(grams, ill=False):
    """One animal at 400 kg with a manually specified half-hour nutrient credit."""
    base = fixture()
    key = animal_id(1)
    animal = base.animals[key]
    ledger = Ledger(base.config, (base.lots[animal.lot_id],), (animal,),
                    (base.location_versions[f"{A}-V1"],))
    opening = next(row for row in base.events if row.animal_id == key and row.kind == EventKind.OPENING)
    ledger.ingest((opening,))
    start = local("2023-12-31 08:00")
    end = start + 2 * HOUR
    timeline = PhysicalTimeline(ledger, end, end)
    config = load_config()
    config["feed_windows_local"] = [[8, 10]]
    config["biology"].update(
        individual_variation=0, lot_variation=0, maturity_floor=1, reference_adg_kg=1,
        maintenance_mj_at_reference=40, gain_mj_per_kg=24, deficit_kg_per_mj=0,
    )
    config["rations"]["adaptation"]["potential_factor"] = 1
    config["biology"]["frame_factor"]["large"] = 1
    config["health"].update(gain_penalty=0.5, maintenance_surcharge=0)
    config["health"]["severity"]["moderate"] = 0.5
    config["weather"]["cold"]["maintenance_factor"] = 1
    config["weighing"]["precision_kg"] = 0.000001
    for scale in config["weighing"]["scales"].values():
        scale.update(bias_kg=0, error_half_width_kg=0)
    profile = make_profile(timeline, config, key, breed="Angus-cross", sex="steer", frame="large",
                           entry_weight_kg=400, entry_age_days=365)
    events = (ClinicalInput("SYN-CONTROLLED-ONSET", key, Action.ONSET, start, severity="moderate"),) if ill else ()
    health = build_health(timeline, events, config)
    clock = growth_clock(((start, end),), timeline, (), health, config, 30)
    adapter = ChronologicalFeed(Method.METABOLIC, 1)
    biology = ChronologicalBiology(timeline, (profile,), health, (), config, adapter=adapter, clock=clock)
    matched = FeedAmount(grams, grams, grams * 8, grams // 10, grams // 20)
    plan = Plan("SYN-PLAN", A, start, end, start, "SYN-EST", "SYN-FORMULA", grams, 0, "test", "test")
    delivery = Delivery("SYN-DELIVERY", plan.plan_id, "SYN-MIX", "SYN-TRUCK", A, start, end,
                        start, start, start, matched, matched, EMPTY)
    bunk = BunkTicket("SYN-BUNK", "SYN-BUNK-DOC", end, end, end, delivery.delivery_id, 0)
    result = settle(ledger, delivery, plan, bunk, {}, 400_000,
                    allocation_policy=TimedAllocation(clock, "manual-test"))
    adapter.add(result.allocations)
    biology.advance(start)
    samples_at = (start + 15 * MINUTE, start + 30 * MINUTE)
    scales = ScaleBook(timeline, biology, tuple(WeighPlan(
        f"SYN-MANUAL-{i}", key, Kind.FOLLOW_UP, measured, missing_probability=0)
        for i, measured in enumerate(samples_at)), config, ())
    biology.advance(samples_at[-1])
    scales.observe_through(samples_at[-1])
    return biology, scales.finish().records, result


class ManualTests(unittest.TestCase):
    def test_a_exact_no_error_mid_slice_and_after_credit(self):
        biology, rows, result = manual(8000)
        self.assertEqual([row.measured_weight_kg for row in rows], [400.0, 400.25])
        for row in rows:
            self.assertAlmostEqual(biology.weight_at(row.animal_id, row.measured_at),
                                   row.measured_weight_kg, delta=0.0000005)
        self.assertEqual(result.row.modeled_consumption, FeedAmount(8000, 8000, 64000, 800, 400))
        with self.assertRaisesRegex(ValueError, "ahead"):
            biology.weight_at(rows[0].animal_id, rows[-1].measured_at + MINUTE)

    def test_b_feed_reduction_crosses_maintenance_threshold(self):
        rich, rich_scale, _ = manual(8000)
        short, short_scale, _ = manual(4000)
        self.assertEqual((rich.steps[-1].consumed_g_dm, short.steps[-1].consumed_g_dm), (2000, 1000))
        self.assertEqual((rich.steps[-1].end_weight_kg, short.steps[-1].end_weight_kg), (400.25, 400))
        self.assertEqual((rich_scale[-1].measured_weight_kg, short_scale[-1].measured_weight_kg), (400.25, 400))

    def test_c_illness_changes_gain_with_same_feed(self):
        healthy, healthy_scale, _ = manual(8000)
        sick, sick_scale, _ = manual(8000, ill=True)
        self.assertEqual(healthy.steps[-1].consumed_g_dm, sick.steps[-1].consumed_g_dm)
        self.assertEqual(sick.steps[-1].health_burden, 0.5)
        self.assertEqual(sick.steps[-1].end_weight_kg, 400.1875)
        self.assertEqual((healthy_scale[-1].measured_weight_kg, sick_scale[-1].measured_weight_kg),
                         (400.25, 400.1875))


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normal = integrated_fixture()

    def test_d_e_delayed_tickets_change_only_eligible_estimates_and_plans(self):
        scenario = load_scenario()
        scenario["extra_weighing_plans"] = []
        without = integrated_fixture(scenario=scenario)
        delayed = ticket(self.normal, "SYN-SCALE-03-JAN10-IN-WINDOW")
        just_before = local("2024-01-11 15:00")
        self.assertEqual(delayed.measured_at, local("2024-01-10 09:45"))
        self.assertEqual(delayed.available_at, local("2024-01-12 08:00"))
        self.assertEqual(tuple(p for p in self.normal.schedule.plans if p.decision_at <= just_before),
                         tuple(p for p in without.schedule.plans if p.decision_at <= just_before))
        now = self.normal.schedule.frozen_weights[delayed.available_at][animal_id(3)]
        self.assertEqual(now.anchor_observation_id, delayed.observation_id)
        self.assertNotEqual(now.estimated_kg,
                            without.schedule.frozen_weights[delayed.available_at][animal_id(3)].estimated_kg)
        after = local("2024-01-14 15:00")
        self.assertNotEqual(plan_at(self.normal, B, after).planned_g_dm, plan_at(without, B, after).planned_g_dm)

    def test_f_changed_future_sale_cannot_change_prefix_in_same_window(self):
        ledger = fixture()
        later = Ledger(ledger.config, ledger.lots.values(), ledger.animals.values(),
                       ledger.location_versions.values())
        cutoff = local("2024-02-29 16:00")
        later.ingest(tuple(
            replace(row, effective_at=cutoff + 15 * MINUTE, posted_at=cutoff + 15 * MINUTE,
                    available_at=cutoff + 15 * MINUTE)
            if row.animal_id == animal_id(7) and row.kind == EventKind.SALE else row
            for row in ledger.events))
        scenario = load_scenario()
        scenario["extra_weighing_plans"].append({
            "source_id": "SYN-SCALE-BEFORE-SALE", "animal_id": animal_id(7), "kind": "follow_up",
            "observed_local": "2024-02-29 15:45", "posted_local": "2024-02-29 15:50",
            "available_local": "2024-02-29 15:55", "missing_probability": 0,
        })
        original = integrated_fixture(scenario=scenario)
        alternative = integrated_fixture(scenario=scenario, ledger=later)
        self.assertEqual([p for p in original.schedule.plans if p.decision_at < cutoff],
                         [p for p in alternative.schedule.plans if p.decision_at < cutoff])
        view = lambda f: [replace(row, physical_snapshot_id="diagnostic-only")
                          for row in f.observations if row.measured_at < cutoff]
        self.assertEqual(view(original), view(alternative))
        observed = ticket(original, "SYN-SCALE-BEFORE-SALE")
        self.assertEqual(original.biology.weight_at(observed.animal_id, observed.measured_at),
                         alternative.biology.weight_at(observed.animal_id, observed.measured_at))
        self.assertEqual(original.timeline.stop_at(animal_id(7)), cutoff)
        self.assertIsNone(original.biology.weight_at(animal_id(7), cutoff + MINUTE))
        self.assertNotEqual(original.biology.weight_at(animal_id(3), cutoff + 30 * MINUTE),
                            alternative.biology.weight_at(animal_id(3), cutoff + 30 * MINUTE))

    def test_g_authorized_scale_revision_preserves_parent_decision(self):
        scenario = load_scenario()
        scenario["scale_corrections"] = []
        unrevised = integrated_fixture(scenario=scenario)
        revision, = self.normal.scale_revisions
        child, = self.normal.restated_snapshots
        old = plan_at(unrevised, B, revision.restated_origin_at)
        saved = canonical(old)
        current = plan_at(self.normal, B, revision.restated_origin_at)
        self.assertEqual(saved, canonical(current))
        self.assertEqual(current.decision_snapshot_id, child.revises_snapshot_id)
        self.assertNotEqual(child.snapshot_id, child.revises_snapshot_id)
        self.assertEqual(child.knowledge_cutoff, revision.knowledge_cutoff)
        row = next(row for row in self.normal.restated_estimates if row.animal_id == animal_id(5))
        self.assertEqual(row.last_observation_id, revision.observation_id)
        live = self.normal.schedule.frozen_weights[local("2024-01-19 15:00")][animal_id(5)]
        self.assertEqual(live.anchor_observation_id, revision.observation_id)
        self.assertEqual(unrevised.schedule.frozen_weights[revision.restated_origin_at][animal_id(5)],
                         self.normal.schedule.frozen_weights[revision.restated_origin_at][animal_id(5)])

    def test_h_allocation_method_changes_growth_with_fixed_delivery_pool(self):
        scenario = load_scenario()
        scenario["method"] = Method.EQUAL.value
        equal = integrated_fixture(scenario=scenario)
        first = "SYN-DELIVERY-202312311500-PEN-A"
        selected = lambda f: next(row for row in f.active_settlements if row.row.delivery_id == first)
        lhs, rhs = selected(self.normal), selected(equal)
        self.assertEqual(lhs.row, rhs.row)
        totals = {method: [0, 0, 0, 0] for method in Method}
        for row in lhs.allocations:
            for i, amount in enumerate((row.g_dm, row.energy_kj, row.cp_g, row.cents)):
                totals[row.method][i] += amount
        self.assertEqual(list(totals.values()), [[3000, 30000, 360, 195]] * len(Method))
        access_end = local("2023-12-31 11:00")
        self.assertNotEqual(equal.biology.weight_at(animal_id(1), access_end),
                            self.normal.biology.weight_at(animal_id(1), access_end))

    def test_i_decision_lineage_and_stage1_yardage(self):
        snapshots = {row.snapshot_id: row for row in self.normal.schedule.snapshots}
        for row in self.normal.decision_sources:
            self.assertLessEqual(row.available_at, snapshots[row.snapshot_id].knowledge_cutoff)
        records = {row.observation_id: row for row in self.normal.observations}
        for row in self.normal.schedule.estimates:
            if row.last_observation_id:
                anchor = records[row.last_observation_id]
                self.assertEqual(anchor.animal_id, row.animal_id)
                self.assertLess(anchor.measured_at, row.effective_before)
                self.assertLessEqual(anchor.available_at, row.knowledge_cutoff)
                self.assertNotEqual(anchor.kind, Kind.FINAL_SALE)
        _, daily, monthly, _ = calculate_soh(self.normal.ledger, START, END, FINAL_CUTOFF)
        deaths = {x.animal_id: x.effective_at for x in self.normal.timeline.exits.values() if x.kind == EventKind.DEATH}
        self.assertEqual(len(deaths), 2)
        for row in self.normal.observations:
            if row.animal_id in deaths:
                self.assertLess(row.measured_at, deaths[row.animal_id])
        for row in wip_candidates(self.normal):
            self.assertLessEqual(row.access_end, self.normal.timeline.stop_at(row.animal_id))
        yard_days = {row.period_start: row for row in daily if row.scope_type == "yard"}
        self.assertEqual(sum(row.animal_days for row in yard_days.values()), 338)
        self.assertEqual(sum(row.animal_days for row in monthly if row.scope_type == "yard"), 338)
        death_at = deaths[animal_id(8)]
        same_day = yard_days[business_date(death_at)]
        self.assertEqual((same_day.opening_head, same_day.receipts, same_day.deaths,
                          same_day.closing_head, same_day.animal_days), (4, 3, 1, 6, 7))
        self.assertFalse(any(row.animal_id == animal_id(8) and row.access_end > death_at
                             for row in wip_candidates(self.normal)))

    def test_death_cancels_scheduled_live_weigh(self):
        scenario = load_scenario()
        scenario["extra_weighing_plans"].append({
            "source_id": "SYN-NONLIVE-TEST", "animal_id": animal_id(8), "kind": "follow_up",
            "observed_local": "2024-01-01 16:00", "posted_local": "2024-01-01 16:10",
            "available_local": "2024-01-01 16:15", "missing_probability": 0,
        })
        trial = integrated_fixture(scenario=scenario)
        cancel, = trial.scale_cancellations
        self.assertEqual((cancel.source_id, cancel.reason), ("SYN-NONLIVE-TEST", "death"))
        self.assertFalse(any(row.source_event_id == cancel.source_id for row in trial.observations))


class PublishingTests(unittest.TestCase):
    def test_j_cold_runs_match_and_publication_is_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runs = (root / "one", root / "two")
            for salt, dest in enumerate(runs, 1):
                env = {**os.environ, "PYTHONHASHSEED": str(salt)}
                subprocess.run([sys.executable, "-m", "simulator_v2.stage3_5", "--output", str(dest)],
                               env=env, check=True, capture_output=True)
            first, second = (run.joinpath("hashes.json").read_bytes() for run in runs)
            self.assertEqual(first, second)
            for name, digest in json.loads(first)["files"].items():
                for run in runs:
                    self.assertEqual(sha256((run / name).read_bytes()), digest)
            attempted = subprocess.run(
                [sys.executable, "-m", "simulator_v2.stage3_5", "--output", str(runs[0])],
                check=False, capture_output=True)
            self.assertNotEqual(attempted.returncode, 0)
            self.assertEqual((runs[0] / "hashes.json").read_bytes(), first)
