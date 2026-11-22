import json
import unittest
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from simulator_v2.stage1.fixture import animal_id, fixture, local
from simulator_v2.stage1.ledger import Ledger
from simulator_v2.stage1.model import EventKind, midnight
from simulator_v2.stage2.health import Action
from simulator_v2.stage3.allocation import Method
from simulator_v2.stage1.provenance import canonical, sha256
from simulator_v2.stage5.__main__ import build, write_verified_table
from simulator_v2.stage5.diagnostics import cross_stage, decision_digest, financials, metrics, outcomes
from simulator_v2.stage5.fixture import build_operations, changed_scenario, replay_growth, settings, weather_scenario
from simulator_v2.stage5.pilot import capacity, plan
from simulator_v2.stage5.weather import Forecast, Weather, coverage, load_archive

HOUR = timedelta(hours=1)


class WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive, cls.manifest = load_archive()
        cls.temperatures = settings()["stress"]["fallback_c_by_month"]

    def test_archive_units_dates_model_and_missing_metadata(self):
        self.assertEqual(len(self.archive), 704)
        self.assertEqual(self.archive[0].day, date(2024, 1, 1))
        self.assertEqual(self.archive[-1].day, date(2025, 12, 4))
        self.assertIn(date(2024, 2, 29), {row.day for row in self.archive})
        self.assertTrue(all(len(row.values) == 9 for row in self.archive))
        self.assertIsNone(self.manifest["acquisition"]["response_model"])

    def test_exact_utc_interval_boundaries_and_dst(self):
        forcing = Weather("retrospective", self.temperatures, archive=self.archive)
        winter = date(2024, 1, 2)
        self.assertEqual(forcing.at(midnight(winter) - 2 * HOUR).source_id, self.archive[0].source_id)
        self.assertEqual(forcing.at(midnight(winter) - HOUR).source_id, self.archive[1].source_id)
        self.assertEqual(midnight(date(2024, 3, 11)) - midnight(date(2024, 3, 10)), 23 * HOUR)
        self.assertEqual(midnight(date(2024, 11, 4)) - midnight(date(2024, 11, 3)), 25 * HOUR)
        self.assertEqual(forcing.at(midnight(date(2024, 7, 2))).kind, "archive_reanalysis")

    def test_gap_is_labeled_without_daily_archive_fill(self):
        report = coverage(Weather("retrospective", self.temperatures, archive=self.archive))
        self.assertEqual(len(report["missing_date_labels"]), 27)
        self.assertEqual(report["mixed_business_days"]["2025-12-04"],
                         {"archive_reanalysis": 23, "seasonal_fallback": 1})
        self.assertEqual(report["hours_by_source"], {"archive_reanalysis": 16895, "seasonal_fallback": 649})

    def test_forecast_uses_only_day_open_vintages(self):
        day = date(2024, 1, 10)
        cutoff = midnight(day)
        observed = Forecast("forecast-available", day, cutoff - HOUR, cutoff, -15)
        late = Forecast("forecast-late", day, cutoff - HOUR, cutoff + HOUR, 20)
        forcing = Weather("operational_as_of", self.temperatures, forecasts=(late, observed))
        self.assertEqual(forcing.at(cutoff).source_id, observed.source_id)
        self.assertEqual(forcing.at(cutoff + 8 * HOUR).kind, "issued_forecast")
        self.assertEqual(forcing.at(cutoff - HOUR).kind, "seasonal_fallback")
        with self.assertRaisesRegex(ValueError, "incompatible"):
            Weather("operational_as_of", self.temperatures, archive=self.archive)

    def test_reject_corrupted_archive(self):
        from simulator_v2.stage5.weather import ARCHIVE
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for src in ARCHIVE.iterdir():
                (dest / src.name).write_bytes(src.read_bytes())
            (dest / "open_meteo_raw.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "digest"):
                load_archive(dest)


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = settings()
        cls.ops, cls.scale = build_operations(42, weather_scenario(cls.settings), cls.settings)
        cls.archive = load_archive()[0]
        cls.retro = Weather("retrospective", cls.settings["stress"]["fallback_c_by_month"], archive=cls.archive)
        cls.model = replay_growth(cls.ops, cls.retro, cls.settings)

    def test_cross_stage_and_accounting(self):
        checks = cross_stage(self.ops, self.scale, self.model)
        self.assertGreaterEqual(len(checks), 70)
        result, evidence, _ = financials(self.ops)
        self.assertEqual(result["journal_net_cents"], 0)
        self.assertEqual(result["modeled_consumed_g_dm"], sum(row.consumed_g_dm for row in self.model.steps))
        self.assertGreater(result["ending_wip_cents"], 0)
        self.assertTrue(len(evidence["invoice_routes"]))
        self.assertEqual(result["feed_cost_bridge"]["gross_issue_cents"],
                         sum(result["feed_cost_bridge"][key] for key in (
                             "wip_and_released_feed_cents", "recoverable_cents", "abnormal_process_cents",
                             "pending_cents")))

    def test_future_archive_perturbation_has_no_operational_path(self):
        first = decision_digest(self.ops)
        archive = tuple(replace(row, values={**row.values, "temperature_2m_mean": -30})
                        if row.day >= date(2024, 1, 10) else row for row in self.archive)
        alternative = replay_growth(
            self.ops, Weather("retrospective", self.retro.fallback, archive=archive), self.settings)
        self.assertNotEqual(self.model.steps, alternative.steps)
        self.assertEqual(first, decision_digest(self.ops))
        self.assertEqual(sum(row.consumed_g_dm for row in alternative.steps),
                         sum(row.consumed_g_dm for row in self.model.steps))
        with self.assertRaisesRegex(ValueError, "cannot use retrospective"):
            build_operations(42, self.retro, self.settings)

    def test_shift_unreleased_movement_correction_preserves_prefix(self):
        base = fixture()
        changed = Ledger(base.config, base.lots.values(), base.animals.values(), base.location_versions.values())
        document = "SYN-FIX-DEC"
        moved = local("2024-01-04 13:00")
        changed.ingest(tuple(replace(row, available_at=moved) if row.source.document_id == document else row
                             for row in base.events))
        other, _ = build_operations(42, weather_scenario(self.settings), self.settings, ledger=changed)
        prefix = local("2024-01-04 10:00")
        self.assertEqual(decision_digest(self.ops, prefix), decision_digest(other, prefix))
        for profile in self.ops.profiles:
            animal = profile.animal_id
            self.assertEqual(self.ops.biology.weight_at(animal, prefix - HOUR),
                             other.biology.weight_at(animal, prefix - HOUR))
        self.assertNotEqual(self.ops.biology.timeline.intervals[animal_id(3)],
                            other.biology.timeline.intervals[animal_id(3)])

    def test_future_exit_inside_window_does_not_change_a_prior_weight(self):
        base = fixture()
        changed = Ledger(base.config, base.lots.values(), base.animals.values(), base.location_versions.values())
        move_exit = local("2024-02-29 16:15")
        changed.ingest(tuple(
            replace(row, effective_at=move_exit, posted_at=move_exit, available_at=move_exit)
            if row.kind == EventKind.SALE and row.animal_id == animal_id(7) else row for row in base.events))
        other, _ = build_operations(42, weather_scenario(self.settings), self.settings, ledger=changed)
        cutoff = local("2024-02-29 16:00")
        measured = local("2024-02-29 15:47")
        self.assertEqual(decision_digest(self.ops, cutoff), decision_digest(other, cutoff))
        self.assertAlmostEqual(self.ops.biology.weight_at(animal_id(7), measured),
                               other.biology.weight_at(animal_id(7), measured), places=10)
        self.assertIsNone(self.ops.biology.weight_at(animal_id(7), cutoff + timedelta(minutes=1)))
        self.assertIsNotNone(other.biology.weight_at(animal_id(7), cutoff + timedelta(minutes=1)))

    def test_cold_and_clinical_effects_at_identical_consumption(self):
        normal = replay_growth(self.ops, weather_scenario(self.settings, 10), self.settings)
        cold = replay_growth(self.ops, weather_scenario(self.settings, -25), self.settings)
        self.assertEqual(sum(row.consumed_g_dm for row in normal.steps),
                         sum(row.consumed_g_dm for row in cold.steps))
        self.assertGreater(sum(row.maintenance_required_me_mj for row in cold.steps),
                           sum(row.maintenance_required_me_mj for row in normal.steps))
        healthy = tuple(replace(row, burden=0) for row in self.ops.health)
        no_burden = replay_growth(self.ops, weather_scenario(self.settings, 10), self.settings, health=healthy)
        sick_animal = animal_id(10)
        self.assertGreater(no_burden.steps_by_animal[sick_animal][-1].end_weight_kg,
                           normal.steps_by_animal[sick_animal][-1].end_weight_kg)

    def test_dmi_allocation_effect_and_accounting_classification(self):
        equal = replay_growth(self.ops, self.retro, self.settings, method=Method.EQUAL)
        self.assertEqual(sum(row.consumed_g_dm for row in equal.steps),
                         sum(row.consumed_g_dm for row in self.model.steps))
        self.assertNotEqual([row.consumed_g_dm for row in equal.steps],
                            [row.consumed_g_dm for row in self.model.steps])
        standard, _, _ = financials(self.ops)
        alternative, _, _ = financials(self.ops, loss_policy="consumption_only")
        self.assertEqual(standard["modeled_consumed_g_dm"], alternative["modeled_consumed_g_dm"])
        self.assertEqual(standard["revenue_cents"], alternative["revenue_cents"])
        self.assertGreater(standard["ending_wip_cents"], alternative["ending_wip_cents"])
        self.assertGreater(alternative["feed_variance_cents"], standard["feed_variance_cents"])

    def test_mortality_without_treatment_is_not_a_sale(self):
        terminal = outcomes(self.ops, self.model, self.settings)
        dead = [row for row in terminal if row["outcome"] == EventKind.DEATH]
        self.assertEqual(len(dead), 2)
        self.assertTrue(any(row["first_treatments"] == 0 for row in dead))
        for row in dead:
            self.assertIsNone(row["hcw_kg_scenario"])
            self.assertIsNone(row["quality_grade"])
            self.assertIsNone(row["illustrative_grid_only_cents"])
        sold = [row for row in terminal if row["outcome"] == EventKind.SALE]
        self.assertTrue(all(.58 <= row["dressing_fraction_scenario"] <= .64 for row in sold))
        self.assertTrue(all(row["grade_status"] == "grade_evidence_missing" for row in sold))
        self.assertTrue(any(row.action == Action.REPEAT for row in self.ops.health))

    def test_feed_only_becomes_metabolically_available_at_interval_close(self):
        row = next(row for row in self.ops.biology.steps if row.energy_mj > 0)
        self.assertEqual(row.starting_me_mj, 0)
        self.assertEqual(row.gain_kg, 0)
        self.assertGreater(row.ending_me_mj, 0)
        self.assertLessEqual(self.ops.biology.weight_at(row.animal_id, row.end_at), row.start_weight_kg)
        stats = metrics(self.model, outcomes(self.ops, self.model, self.settings))
        self.assertEqual(stats["dmi_bw_pct_animal_business_day"]["over_3_pct"], 0)

    def test_starvation_and_excess_reserves_respect_growth_limits(self):
        model = self.ops.biology
        rates = (50, 0.3)
        self.assertEqual(model._fluxes(400, 0.5, 2.4, rates, (0, 0)), (0, 0, 0, 0.4))
        self.assertEqual(model._fluxes(400, 0.5, 2.4, rates, (1000, 10)), (25, 0.15, 1.2, 0))
        self.assertEqual(model._fluxes(900, 0.5, 2.4, rates, (1000, 10))[2], 0)
        self.assertEqual(model._fluxes(180, 0.5, 2.4, rates, (0, 0))[3], 0)

    def test_high_distribution_loss_conserves_rounding_and_increases_abnormal_cost(self):
        seasonal = weather_scenario(self.settings)
        changed, scale = build_operations(42, seasonal, self.settings,
                                          scenario=changed_scenario(self.settings, "elevated_distribution_loss"))
        model = replay_growth(changed, seasonal, self.settings)
        checks = cross_stage(changed, scale, model)
        self.assertTrue(any(row.check_id == "CAUSAL_FEED_RELEASE" for row in checks))
        normal, _, _ = financials(self.ops)
        stressful, _, _ = financials(changed)
        self.assertLess(stressful["modeled_consumed_g_dm"], normal["modeled_consumed_g_dm"])
        self.assertGreater(stressful["feed_variance_cents"], normal["feed_variance_cents"])
        self.assertEqual(stressful["journal_net_cents"], 0)


class ReleaseTests(unittest.TestCase):
    def test_pilot_is_only_a_capacity_plan(self):
        config = plan()
        result = capacity(config)
        self.assertEqual(config["state"], "planned_only")
        self.assertEqual(config["placements"], 1500)
        self.assertEqual(result["calendar_days"], 731)
        self.assertEqual(result["opening_head"], 350)
        for row in result["capacity_scenarios"]:
            self.assertLess(row["peak_concurrent_yard_head"], config["placements"])
            self.assertEqual(row["carry_out_head"] + row["completed_outcomes"], 1850)

    def test_evaluation_protocol_is_frozen_with_three_horizons(self):
        path = Path(__file__).resolve().parents[1] / "evaluation.json"
        config = json.loads(path.read_bytes())
        self.assertTrue(config["frozen_before_pilot"])
        self.assertEqual(config["horizons_elapsed_days"], [7, 30, 60])
        self.assertEqual(config["acceptance"]["hard_gate_failures_allowed"], 0)

    def test_published_output_cannot_be_overwritten(self):
        with TemporaryDirectory() as tmp, self.assertRaisesRegex(FileExistsError, "already exists"):
            build(Path(tmp))

    def test_canonical_digest_matches_the_published_numeric_type(self):
        @dataclass(frozen=True)
        class Weight:
            kg: float

        with TemporaryDirectory() as tmp:
            result = write_verified_table(Path(tmp), "weights", Weight, (Weight(400),), "fixture")
        self.assertEqual(result["canonical_sha256"], sha256(canonical({"run_id": "fixture", "kg": 400.0})))
