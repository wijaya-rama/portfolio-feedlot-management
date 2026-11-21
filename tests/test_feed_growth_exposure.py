import json
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from feedlot_analytics.contracts import FINISHED
from feedlot_analytics.feed_growth import (
    delivery_rows, feed_rollup, growth_events, growth_variability, load_analysis, lot_efficiency_review,
    matched_growth, recorded_occupancy, sold_efficiency, stage_coverage, stage_summary, verify_build,
)
from feedlot_analytics.metrics import aggregate_pen_feed
from feedlot_analytics.transformations import animal_scale_stage
from feedlot_analytics.weather_associations import (
    COST, DM, TEMPERATURE, association, daily_feed_associations, exposure_summary, feed_calendar, feed_mix_by_date,
    growth_weather_inputs, interval_exposure, lot_associations, paired_pen_weather, sold_weather_inputs,
    weather_calendar, weather_rollup, weather_spells, within_lot_performance,
)

ROOT = Path(__file__).resolve().parents[1]


class ExposureCalculationsTest(unittest.TestCase):
    def test_months_thresholds_and_runs_use_actual_calendar(self):
        dates = pd.date_range("2024-02-01", "2024-03-03").delete(1)
        temperatures = np.zeros(len(dates))
        temperatures[[0, 1, 2, -2, -1]] = -1
        daily = weather_calendar(pd.DataFrame({
            "date": dates, TEMPERATURE: temperatures,
            "temperature_2m_min": np.where(temperatures < 0, -20, -1),
        }))
        self.assertFalse(daily.full_month.any())
        self.assertEqual(int(daily.cold.sum()), 5)
        self.assertEqual(int(daily.extreme_cold.sum()), 5)
        self.assertEqual(weather_spells(daily, "cold").days.tolist(), [1, 2, 2])
        self.assertEqual(weather_spells(daily, "cold").touches_archive_edge.tolist(), [True, False, True])
        self.assertTrue(daily.loc[daily.date.eq("2024-02-29"), "season"].eq("DJF").all())

    def test_within_month_slope_controls_and_hac_with_hand_calculated_score(self):
        dates = pd.date_range("2024-01-01", periods=8)
        x = np.tile([-1., 1., -1., 1.], 2)
        nuisance = np.repeat([0., 1.], 4)
        residual = np.tile([1., 1., -1., -1.], 2)
        data = pd.DataFrame({"x": x + 5 * nuisance, "y": 2 * x + 8 * nuisance + residual,
                             "block": nuisance, "date": dates})
        fit = association(data.iloc[::-1], predictor="x", outcome="y", fixed=("block",), increment=10,
                          daily_date="date", hac_lags=(0, 1), exclude_by=("block",))
        self.assertAlmostEqual(fit["effect"], 20.)
        self.assertAlmostEqual(fit["block_low"], 20.)
        self.assertAlmostEqual(fit["block_high"], 20.)
        score = x * residual / 8
        for lag, extra in [(0, 0), (1, np.dot(score[:-1], score[1:]))]:
            expected = 20 + 19.6 * np.sqrt(np.dot(score, score) + extra)
            self.assertAlmostEqual(fit[f"hac{lag}_high"], expected)
        with self.assertRaisesRegex(ValueError, "consecutive"):
            association(data.drop(3), predictor="x", outcome="y", daily_date="date", hac_lags=(1,))
        with self.assertRaisesRegex(ValueError, "unique"):
            association(pd.concat([data, data]), predictor="x", outcome="y", daily_date="date")
        self.assertTrue(np.isnan(association(data, predictor="block", outcome="y", fixed=("block",))["effect"]))

    def test_interval_weather_uses_elapsed_days_and_excludes_previous_weigh_date(self):
        stamp = pd.to_datetime
        animals = pd.DataFrame({
            "animal_id": ["A"], "entry_date": stamp(["2024-01-01"]), "exit_type": [FINISHED],
            "entry_weight_kg": [300.], "breed": ["Black Angus"], "sex": ["Heifer"], "frame_score": ["Medium"],
            "financial_dof": [9], "net_margin_cad": [12.],
        })
        scale = pd.DataFrame({
            "animal_id": ["A", "A"], "lot_id": ["L", "L"], "pen_id": ["P", "P"],
            "weigh_id": ["1", "2"], "weigh_stage": ["Arrival", "Closeout"],
            "weigh_date": stamp(["2024-01-01", "2024-01-03"]), "weight_kg": [300., 304.],
        })
        weather = pd.DataFrame({
            "date": stamp(["2024-01-01", "2024-01-02", "2024-01-03"]),
            TEMPERATURE: [-40., 10., 20.], "wind_speed_10m_max": [1., 2., 3.], "snowfall_sum": [0., 0., 0.],
        })
        events = growth_events(animal_scale_stage(animals, scale), animals)
        lots = pd.DataFrame({"lot_id": ["L"], "pen_type": ["Standard Open Dirt"], "pen_id": ["P"],
                             "arrival_date": stamp(["2024-01-01"])})
        aligned = interval_exposure(events, weather, lots)
        row = aligned.iloc[0]
        self.assertEqual(len(aligned), 1)
        self.assertEqual(row.expected_exposure_days, 2)
        self.assertEqual(row.weigh_day_temperature_c, 20.)
        self.assertEqual(row.mean_temperature_c, 15.)
        self.assertEqual(row.cold_day_proportion, 0.)
        self.assertEqual(row.interval_adg_kg, 2.)
        self.assertEqual(row.elapsed_cumulative_adg_kg, 2.)
        self.assertEqual(growth_weather_inputs(aligned, lots).iloc[0].interval_adg, 2.)
        with self.assertRaisesRegex(ValueError, "exact, complete"):
            interval_exposure(events, weather.drop(1), lots)

    def test_pen_denominators_occupancy_and_overlap(self):
        pen_days = pd.DataFrame({
            "pen_id": ["A", "A", "B"], "feed_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-01"]),
            "pen_type": ["Open"] * 3, "recorded_head_days": [4, 10, 30], "capacity_head": [10, 10, 20],
            "recorded_occupancy_fraction": [.4, 1, 1.5], "recorded_lots": [1, 1, 2],
        })
        row = recorded_occupancy(pen_days, by=("pen_type",)).iloc[0]
        self.assertEqual(row.nominal_capacity_observed_pens, 30)
        self.assertEqual(row.observed_capacity_days, 40)
        self.assertEqual(row.recorded_occupancy, 1.1)
        self.assertEqual(row.at_capacity_days, 2)
        self.assertEqual(row.above_capacity_days, 1)
        self.assertEqual(row.overlapping_lot_days, 1)
        with self.assertRaisesRegex(ValueError, "one nominal capacity"):
            recorded_occupancy(pen_days.assign(capacity_head=[10, 11, 20]), by=("pen_type",))

    def test_matched_changes_exclude_missing_animals_and_use_pen_intervals(self):
        records = [
            ("A", "L1", "P1", "Day 35", 2.), ("A", "L1", "P1", "Day 70", 3.),
            ("B", "L2", "P2", "Day 35", 8.), ("B", "L2", "P2", "Day 70", np.nan),
            ("C", "L2", "P2", "Day 35", 3.), ("C", "L2", "P2", "Day 70", 5.),
        ]
        for stage in ("Day 105", "Closeout"):
            records.append(("B", "L2", "P2", stage, np.nan))
        frame = pd.DataFrame(records, columns=["animal_id", "lot_id", "pen_id", "weigh_stage", "interval_adg_kg"])
        _, pairs = matched_growth(frame, draws=400)
        row = pairs.iloc[0]
        self.assertEqual(row.matched_head, 2)
        self.assertEqual(row.pens, 2)
        self.assertAlmostEqual(row.paired_change, 1.5)
        self.assertEqual((row.pen_bootstrap_low, row.pen_bootstrap_high), (1., 2.))

    def test_window_summary_uses_both_window_and_day_weights(self):
        windows = pd.DataFrame({
            "pen_type": ["Open"] * 3, "expected_exposure_days": [2, 2, 6], "cold_days": [2, 2, 0],
            "mean_temperature_c": [-1., -1., 10.], "cold_day_proportion": [1., 1., 0.],
            "snowfall_exposure_cm": [1., 1., 0.], "maximum_wind_kmh": [10., 10., 15.],
            "entry_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-03"]),
            "exit_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-08"]),
        })
        row = exposure_summary(windows, by=("pen_type",)).iloc[0]
        self.assertEqual(row.windows, 3)
        self.assertEqual(row.distinct_windows, 2)
        self.assertAlmostEqual(row.mean_window_cold_share, 2 / 3)
        self.assertAlmostEqual(row.exposure_day_cold_share, .4)
        self.assertAlmostEqual(row.exposure_day_mean_c, 5.6)


class Phase2B2SnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.delivery = load_analysis(ROOT)
        cls.tables = cls.result.tables
        cls.animals = cls.tables["animal_closeout"]
        cls.lots = cls.tables["lot_closeout"]
        cls.pens = cls.tables["pen_day_feed"]
        cls.sold = sold_efficiency(cls.animals, cls.tables["animal_health_summary"])
        cls.events = growth_events(cls.tables["animal_scale_stage"], cls.animals)
        cls.weather = weather_calendar(cls.tables["weather_daily"])

    def test_rejects_changed_baseline_hashes_or_window_coverage(self):
        result = self.result
        baseline = json.loads((ROOT / "phase2a/reconciliation.json").read_text())
        verify_build(result, baseline)
        with self.assertRaisesRegex(ValueError, "Baseline reconciliation"):
            verify_build(result, {**baseline, "mortality_loss_cad": 0})
        with self.assertRaisesRegex(ValueError, "Incomplet"):
            altered = result.tables["lot_weather_exposure"].iloc[:-1]
            verify_build(replace(result, tables={**result.tables, "lot_weather_exposure": altered}), baseline)
        original = result.source_manifest["files"]
        changed = {name: {**profile, "sha256": "invalid"} for name, profile in original.items()}
        with self.assertRaisesRegex(ValueError, "source hash"):
            verify_build(replace(result, source_manifest={**result.source_manifest, "files": changed}), baseline)

    def test_native_feed_and_lot_review_reconcile_without_duplicate_facts(self):
        native = self.delivery
        overall = aggregate_pen_feed(self.pens).iloc[0]
        groups = feed_rollup(native, by=("ration_phase",))
        self.assertEqual(len(native), 16085)
        self.assertAlmostEqual(groups.delivered_dm_kg.sum(), overall.delivered_dm_kg)
        self.assertAlmostEqual(groups.delivered_feed_cost_cad.sum(), overall.delivered_feed_cost_cad)
        self.assertEqual(groups.recorded_head_days.sum(), overall.recorded_head_days)
        self.assertTrue(np.allclose(groups[["forage_dm_share", "concentrate_dm_share",
                                            "supplement_dm_share"]].sum(axis=1), 1., atol=1e-6))
        review = lot_efficiency_review(self.lots, native)
        self.assertEqual(len(review), 90)
        row = review.iloc[0]
        peers = review.loc[review.placement_quarter.eq(row.placement_quarter) & review.lot_id.ne(row.lot_id)]
        self.assertEqual(row.peer_lots, len(peers))
        self.assertAlmostEqual(row.peer_median_fcr, peers.sold_fcr.median())
        with self.assertRaisesRegex(ValueError, "unique"):
            delivery_rows(pd.concat([native, native.iloc[[0]]]), self.pens)

    def test_individual_stages_mortality_and_observation_windows(self):
        self.assertEqual(len(self.events), 74268)
        self.assertEqual(self.events.breed.tolist(), self.events.animal_id.map(
            self.animals.set_index("animal_id").breed).tolist())
        coverage = stage_coverage(self.events, self.animals)
        self.assertEqual(coverage.loc["Arrival", "recorded"], 15000)
        self.assertEqual(coverage.loc["Closeout", "recorded"], 14760)
        self.assertTrue(coverage.coverage_eligible.eq(1.).all())
        stats = stage_summary(self.events)
        self.assertEqual(stats.loc["Arrival", "interval_head"], 0)
        self.assertTrue(pd.isna(stats.loc["Arrival", "elapsed_weighted_interval_adg"]))
        self.assertEqual(stats.loc["Day 35", "mean_interval_days"], 34)
        wide, comparisons = matched_growth(self.events, draws=50)
        variance, low = growth_variability(wide)
        self.assertEqual(comparisons.matched_head.tolist(), coverage.recorded.iloc[2:].tolist())
        self.assertTrue(variance.between_lot_share_of_ss.between(0, 1).all())
        self.assertLessEqual(low.low_all_three, low.low_day35_and_day70)

    def test_weather_uses_704_days_and_models_use_calendar_units(self):
        daily, pen_type = feed_calendar(self.pens, self.weather)
        self.assertEqual(len(daily), 704)
        self.assertEqual(int(daily.full_month.sum()), 700)
        self.assertEqual(len(weather_rollup(self.weather, by=("month",))), 24)
        rounded_cost = round(daily.delivered_feed_cost_cad.sum(), 2)
        self.assertEqual(rounded_cost, 10219542.92)
        self.assertEqual(round(pen_type.delivered_feed_cost_cad.sum(), 2), rounded_cost)
        mix = feed_mix_by_date(self.delivery, self.animals)
        self.assertTrue(mix.filter(like="ration_phase_").sum(axis=1).sub(1).abs().lt(1e-10).all())
        fit = daily_feed_associations(daily, mix)
        self.assertEqual(len(fit), 18)
        self.assertTrue(fit.observations.eq(700).all())
        self.assertTrue(fit.effect.notna().all())
        paired = paired_pen_weather(pen_type)
        self.assertTrue(paired.common_dates.between(1, 700).all())
        self.assertEqual(set(paired.outcome), {DM, COST})

    def test_lifetime_and_interval_weather_reduce_to_appropriate_grains(self):
        self.assertEqual(len(self.sold), 14760)
        self.assertTrue(self.sold.exit_type.eq(FINISHED).all())
        self.assertTrue(self.sold.fcr_percentile.between(0, 1).all())
        within = within_lot_performance(self.sold)
        self.assertTrue(within.observations.eq(14760).all())
        self.assertTrue(within.pen_id_groups.eq(40).all())
        windows = sold_weather_inputs(self.sold, self.tables["animal_weather_exposure"], self.lots)
        self.assertEqual(len(windows), 90)
        self.assertEqual(windows["head"].sum(), 14760)
        fit = lot_associations(windows, predictor="mean_temperature_c", outcomes=("sold_fcr",),
                               increment=10, controls=("mean_entry_weight_kg", "mean_financial_dof")).iloc[0]
        self.assertEqual(fit.observations, 90)
        self.assertEqual(fit.calendar_block_groups, 4)
        self.assertGreater(fit.calendar_block_identified, 0)
        aligned = interval_exposure(self.events, self.tables["weather_daily"], self.lots)
        self.assertEqual(len(aligned), 59268)
        aggregate = growth_weather_inputs(aligned, self.lots)
        self.assertEqual(len(aggregate), 360)
        self.assertEqual(aggregate["head"].sum(), len(aligned))


if __name__ == "__main__":
    unittest.main()
