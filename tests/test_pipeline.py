import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from feedlot_analytics import build
from feedlot_analytics.contracts import BOOK, CSV, FINISHED, MORTALITY
from feedlot_analytics.exports import write_build
from feedlot_analytics.loaders import load_sources
from feedlot_analytics.metrics import aggregate_closeout, aggregate_pen_feed, select_period
from feedlot_analytics.pipeline import TABLES
from feedlot_analytics.relations import add_columns
from feedlot_analytics.validation import Controls, ValidationError, validate_sources
from feedlot_analytics.weather import fetch_snapshot

from test_weather import as_json, example_response

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASHES = {
    CSV: "80e5534d1342343f600b125bd7406864d5ff9636aaaf2a83133c304dbabdc618",
    BOOK: "d2e15c6bda9bdab65612d2ed0a7c808ebb840dd3e8db6f7f134d86d2b92d81c5",
}


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = load_sources(ROOT)
        with patch("feedlot_analytics.pipeline.load_sources", return_value=cls.sources):
            cls.result = build(ROOT)
        cls.tables = cls.result.tables
        cls.animals = cls.tables["animal_closeout"]
        cls.health = cls.tables["animal_health_summary"]
        cls.lots = cls.tables["lot_closeout"]
        cls.summary = cls.result.reconciliation["summary"]
        cls.overall = aggregate_closeout(cls.animals, cls.health).iloc[0]

    def test_source_manifest_native_types_and_untreated_encoding(self):
        self.assertEqual(len(self.sources.sheets), 10)
        for file, expected in SOURCE_HASHES.items():
            self.assertEqual(self.result.source_manifest["files"][file]["sha256"], expected)
        flat = self.sources.flat
        excel = self.sources.sheets["Feedlot_Flat_15000"]
        self.assertEqual(str(flat.rfid_tag.dtype), "string")
        self.assertTrue(flat.rfid_tag.str.fullmatch(r"\d{15}").all())
        self.assertEqual(str(flat.entry_date.dtype), "string")
        self.assertEqual(str(self.animals.entry_date.dtype), "datetime64[ns]")
        for column in ("primary_diagnosis", "primary_drug_protocol"):
            self.assertEqual(flat[column].eq("None").sum(), 12900)
            self.assertEqual(excel[column].isna().sum(), 12900)
        self.assertEqual(flat.quality_grade.isna().sum(), 240)
        self.assertEqual(self.summary["checks_failed"], 0)

    def test_population_and_independent_source_duplicate_controls(self):
        self.assertEqual(self.animals.animal_id.nunique(), 15000)
        self.assertEqual(self.animals.exit_type.eq(FINISHED).sum(), 14760)
        self.assertEqual(self.animals.exit_type.eq(MORTALITY).sum(), 240)
        self.assertEqual(len(self.lots), 90)
        self.assertEqual(len(self.sources.sheets["Dim_Pen"]), 40)
        self.assertEqual(self.health.treated.sum(), 2100)
        self.assertEqual(self.health.treatment_events.sum(), 2220)
        for table, contract in TABLES.items():
            frame = self.tables[table]
            self.assertFalse(frame.duplicated(list(contract.key)).any(), table)
            self.assertFalse(frame[list(contract.key)].isna().any(axis=None), table)
            self.assertEqual(self.result.transformation_manifest["tables"][table]["rows"], len(frame))

    def test_bad_fact_key_is_rejected(self):
        name = "Fact_Health_Treatments"
        health = self.sources.sheets[name].copy()
        health.loc[1, "treatment_id"] = health.loc[0, "treatment_id"]
        sources = replace(self.sources, sheets={**self.sources.sheets, name: health})
        with self.assertRaisesRegex(ValidationError, r"Fact_Health_Treatments.primary_key"):
            validate_sources(sources, Controls())

    def test_bad_fact_foreign_key_is_rejected(self):
        name = "Fact_Health_Treatments"
        health = self.sources.sheets[name].copy()
        health.loc[0, "animal_id"] = "DOES-NOT-EXIST"
        sources = replace(self.sources, sheets={**self.sources.sheets, name: health})
        with self.assertRaisesRegex(ValidationError, r"Fact_Health_Treatments.animal_fk"):
            validate_sources(sources, Controls())

    def test_parity_regression_is_rejected(self):
        flat = self.sources.flat.copy()
        flat.loc[0, "entry_weight_kg"] += 1
        with self.assertRaisesRegex(ValidationError, r"flat_vs_Feedlot_Flat_15000.entry_weight_kg.parity"):
            validate_sources(replace(self.sources, flat=flat), Controls())

    def test_exact_row_ledger_and_mortality_bridge(self):
        totals = self.overall
        self.assertEqual(totals.sold_only_margin_cents, 489418763)
        self.assertEqual(totals.mortality_loss_cents, 51219464)
        self.assertEqual(totals.all_outcome_margin_cents, 438199299)
        self.assertEqual(totals.sold_only_margin_cents - totals.mortality_loss_cents, totals.all_outcome_margin_cents)
        self.assertEqual(totals.gross_revenue_cents - totals.production_cost_cents, totals.all_outcome_margin_cents)
        ledger = self.summary["modeled_ledger_cad"]
        self.assertEqual(ledger["all_outcomes"]["production_cost_cad"], 41328195.32)
        self.assertEqual(ledger["all_outcomes"]["gross_revenue_cad"], 45710188.31)
        self.assertEqual(ledger["mortality"]["production_cost_cad"], 512194.64)
        self.assertEqual(ledger["mortality"]["gross_revenue_cad"], 0)

    def test_margin_head_denominators(self):
        self.assertAlmostEqual(self.overall.all_outcome_margin_per_head_placed, 4381992.99 / 15000)
        self.assertAlmostEqual(self.overall.all_outcome_margin_per_head_sold, 4381992.99 / 14760)
        self.assertAlmostEqual(self.overall.sold_only_margin_per_head_sold, 4894187.63 / 14760)

    def test_biology_ratios_and_separate_individual_means(self):
        sold = self.animals.loc[self.animals.exit_type.eq(FINISHED)]
        self.assertEqual(self.overall.head_adg_eligible, len(sold))
        self.assertAlmostEqual(self.overall.sold_adg_kg_per_day, sold.total_gain_kg.sum() / sold.financial_dof.sum())
        self.assertAlmostEqual(self.overall.sold_fcr, sold.allocated_dmi_kg.sum() / sold.total_gain_kg.sum())
        self.assertAlmostEqual(self.overall.sold_feed_cog, sold.allocated_feed_cost_cad.sum() / sold.total_gain_kg.sum())
        self.assertAlmostEqual(self.overall.mean_individual_sold_adg, sold.lifetime_adg_kg.mean())
        self.assertAlmostEqual(self.overall.mean_individual_sold_fcr, sold.fcr.mean())
        self.assertNotAlmostEqual(self.overall.sold_fcr, self.overall.mean_individual_sold_fcr, places=4)

    def test_invalid_gain_removes_both_metric_components(self):
        sold = self.animals.loc[self.animals.exit_type.eq(FINISHED)].iloc[:2].copy()
        eligible = sold.iloc[1]
        sold.loc[sold.index[0], "total_gain_kg"] = 0
        result = aggregate_closeout(sold, self.health).iloc[0]
        self.assertEqual(result.head_sold, 2)
        self.assertEqual(result.head_fcr_eligible, 1)
        self.assertAlmostEqual(result.sold_fcr, eligible.allocated_dmi_kg / eligible.total_gain_kg)

    def test_zero_denominator_and_missing_metrics(self):
        deaths = self.animals.loc[self.animals.exit_type.eq(MORTALITY)]
        death_metrics = aggregate_closeout(deaths, self.health).iloc[0]
        self.assertTrue(pd.isna(death_metrics.sold_fcr))
        self.assertTrue(pd.isna(death_metrics.dressing_yield))
        self.assertTrue(pd.isna(death_metrics.all_outcome_margin_per_head_sold))
        self.assertEqual(death_metrics.head_dressing_eligible, 0)
        self.assertEqual(death_metrics.all_outcome_margin_cents, -51219464)
        empty = aggregate_closeout(self.animals.iloc[:0], self.health).iloc[0]
        self.assertEqual(empty.head_placed, 0)
        self.assertTrue(pd.isna(empty.all_outcome_margin_per_head_placed))
        self.assertTrue(pd.isna(empty.recorded_morbidity_rate))

    def test_carcass_eligibility_and_grade_coverage(self):
        sold = self.animals.loc[self.animals.exit_type.eq(FINISHED)]
        self.assertEqual(self.overall.head_graded, 14760)
        self.assertEqual(self.overall.head_prime_aaa, 11302)
        self.assertAlmostEqual(self.overall.prime_aaa_share, 11302 / 14760)
        self.assertAlmostEqual(self.overall.dressing_yield, sold.hot_carcass_weight_kg.sum() / sold.exit_weight_kg.sum())
        a = sold.iloc[:2].copy()
        a.loc[a.index[0], "quality_grade"] = pd.NA
        metrics = aggregate_closeout(a, self.health).iloc[0]
        self.assertEqual(metrics.head_graded, 1)
        self.assertEqual(metrics.head_ungraded_sold, 1)
        self.assertEqual(metrics.head_dressing_eligible, 2)

    def test_health_uses_head_and_event_denominators(self):
        self.assertAlmostEqual(self.overall.recorded_morbidity_rate, 2100 / 15000)
        self.assertAlmostEqual(self.overall.repeat_treatment_rate, 120 / 2100)
        self.assertAlmostEqual(self.overall.first_pull_by_day30_share, 1632 / 2100)
        self.assertEqual(self.overall.direct_treatment_cost_cents, 14319484)
        self.assertAlmostEqual(self.overall.direct_vet_cad_per_event, 143194.84 / 2220)
        self.assertTrue(self.health.base_vet_cost_cad.eq(18).all())
        self.assertEqual(self.health.loc[~self.health.treated, "first_treatment_date"].notna().sum(), 0)

    def test_scale_and_financial_day_conventions(self):
        scale = self.tables["animal_scale_stage"]
        self.assertTrue(self.animals.financial_dof.eq(self.animals.elapsed_exit_days + 1).all())
        arrival = scale.loc[scale.weigh_stage.eq("Arrival")]
        self.assertTrue(arrival.interval_adg_kg.isna().all())
        day35 = scale.loc[scale.weigh_stage.eq("Day 35")]
        self.assertEqual(len(day35), 14882)
        self.assertTrue(day35.elapsed_interval_days.eq(34).all())
        self.assertTrue(day35.inclusive_stage_days.eq(35).all())
        delta = day35.interval_gain_kg / 34 - day35.interval_adg_kg
        self.assertTrue(delta.abs().lt(1e-10).all())

    def test_feed_bridge_and_pen_day_rollup(self):
        feed = self.tables["lot_feed_reconciliation"]
        pen_day = self.tables["pen_day_feed"]
        self.assertTrue(feed.within_rounding_bound.all())
        self.assertEqual(feed.recorded_head_days.sum(), 2650584)
        self.assertEqual(feed.financial_head_days.sum(), 2650584)
        self.assertAlmostEqual(feed.dm_delivered_less_allocated_kg.sum(), .40)
        self.assertAlmostEqual(feed.cost_delivered_less_allocated_cad.sum(), -.57)
        self.assertTrue(pen_day.recorded_occupancy_fraction.le(1).all())
        monthly = aggregate_pen_feed(pen_day, by=("feed_month",))
        self.assertAlmostEqual(monthly.delivered_dm_kg.sum(), 28544013.42)
        self.assertAlmostEqual(monthly.delivered_feed_cost_cad.sum(), 10219542.92)
        dec = monthly.loc[monthly.feed_month.eq("2025-12")].iloc[0]
        self.assertAlmostEqual(dec.delivered_dm_kg / dec.recorded_head_days, dec.delivered_dm_per_head_day)
        with self.assertRaisesRegex(ValueError, "Unsupported pen-day"):
            aggregate_pen_feed(pen_day, by=("breed",))

    def test_breed_is_individual_and_lot_totals_remain_additive(self):
        individual = self.sources.sheets["Dim_Cattle"].set_index("animal_id").breed
        self.assertTrue(self.animals.breed.eq(self.animals.animal_id.map(individual)).all())
        self.assertEqual(self.animals.breed.ne(self.animals.predominant_breed).sum(), 1447)
        by_breed = aggregate_closeout(self.animals, self.health, by=("lot_id", "breed"))
        self.assertGreater(len(by_breed), 90)
        per_lot = by_breed.groupby("lot_id").all_outcome_margin_cents.sum()
        self.assertTrue(per_lot.eq(self.lots.set_index("lot_id").all_outcome_margin_cents).all())
        self.assertEqual(per_lot.sum(), 438199299)
        with self.assertRaisesRegex(ValueError, "Unsupported animal grouping"):
            aggregate_closeout(self.animals, self.health, by=("predominant_breed",))

    def test_date_role_filters_change_cohort_and_preserve_rollups(self):
        placed = select_period(self.animals, date_role="entry_date", start="2024-01-01", end="2024-03-31")
        closed = select_period(self.animals, date_role="exit_date", start="2024-01-01", end="2024-03-31")
        self.assertGreater(len(placed), len(closed))
        total = aggregate_closeout(placed, self.health).iloc[0]
        breakdown = aggregate_closeout(placed, self.health, by=("breed", "treated"))
        self.assertEqual(total.head_placed, len(placed))
        self.assertEqual(breakdown.all_outcome_margin_cents.sum(), total.all_outcome_margin_cents)
        rebuilt_adg = breakdown.adg_gain_kg.sum() / breakdown.adg_financial_days.sum()
        self.assertAlmostEqual(rebuilt_adg, total.sold_adg_kg_per_day)

    def test_health_and_scale_fanout_rejected(self):
        health = self.sources.sheets["Fact_Health_Treatments"][["animal_id", "treatment_id"]]
        scales = self.tables["animal_scale_stage"][["animal_id", "weigh_id"]]
        expanded = self.animals.merge(health, on="animal_id", how="left").merge(scales, on="animal_id", how="left")
        self.assertEqual(len(expanded), 74783)
        self.assertGreater(expanded.net_margin_cad.sum(), self.animals.net_margin_cad.sum())
        with self.assertRaisesRegex(ValueError, "unique, non-null key"):
            aggregate_closeout(expanded, self.health)
        with self.assertRaisesRegex(ValueError, "unique, non-null key"):
            add_columns(self.animals, health, key=("animal_id",), cardinality="one_to_one")
        with self.assertRaisesRegex(ValueError, "row-preserving"):
            add_columns(self.animals, scales, key=("animal_id",), cardinality="many_to_many")

    def test_feed_fanout_rejected_before_a_financial_join(self):
        feed = self.sources.sheets["Fact_Feed_Daily"]
        lots = feed.groupby("lot_id").size()
        self.assertEqual(self.animals.lot_id.map(lots).sum(), 2680547)
        with self.assertRaisesRegex(ValueError, "unique, non-null key"):
            add_columns(self.animals, feed[["lot_id", "feed_date"]], key=("lot_id",), cardinality="many_to_one")

    def test_source_cattle_values_survive_canonical_and_weather_mapping(self):
        columns = ["animal_id", "allocated_dmi_kg", "lifetime_adg_kg", "fcr", "net_margin_cad"]
        source = self.sources.sheets["Fact_Closeout_Sales"][columns].sort_values("animal_id", ignore_index=True)
        assert_frame_equal(self.animals[columns], source)
        exposure = self.tables["animal_weather_exposure"]
        self.assertEqual(len(exposure), len(self.animals))
        self.assertTrue(exposure.expected_exposure_days.eq(self.animals.financial_dof).all())
        self.assertFalse(set(columns[1:]) & set(exposure))

    def test_full_weather_enrichment_with_a_technical_fixture(self):
        raw = as_json(example_response())
        with TemporaryDirectory() as work:
            with patch("feedlot_analytics.weather._download", return_value=raw):
                snapshot = fetch_snapshot(Path(work))
            with patch("feedlot_analytics.pipeline.load_sources", return_value=self.sources):
                enriched = build(ROOT, weather_snapshot=snapshot)
        for name in ("animal_closeout", "animal_health_summary", "animal_scale_stage",
                     "lot_closeout", "lot_feed_reconciliation", "pen_day_feed"):
            assert_frame_equal(self.tables[name], enriched.tables[name])
        for name in ("animal_weather_exposure", "lot_weather_exposure"):
            exposure = enriched.tables[name]
            self.assertTrue(exposure.weather_date_count.eq(exposure.expected_exposure_days).all())
            self.assertTrue(exposure.cold_days.eq(exposure.expected_exposure_days).all())
            self.assertTrue(exposure.dtypes.sort_index().equals(self.tables[name].dtypes.sort_index()))

    def test_export_reproducibility_and_checked_in_summary(self):
        checked_in = json.loads((ROOT / "phase2a/reconciliation.json").read_text(encoding="utf-8"))
        self.assertEqual(checked_in, self.summary)
        with TemporaryDirectory() as work:
            left, right = Path(work) / "one", Path(work) / "two"
            write_build(self.result, left)
            write_build(self.result, left)
            write_build(self.result, right)
            self.assertEqual(
                {file.name: file.read_bytes() for file in left.iterdir()},
                {file.name: file.read_bytes() for file in right.iterdir()},
            )
            (left / "weather_daily.csv").write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different build"):
                write_build(self.result, left)
