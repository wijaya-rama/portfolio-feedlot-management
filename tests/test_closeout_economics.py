import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from feedlot_analytics import build
from feedlot_analytics.closeout_economics import (
    MARGIN, REVENUE_AND_COSTS, audit_summary, cohort_economics, cost_structure,
    downside_summary, lot_composition, lot_heterogeneity, lot_peer_review,
    lot_procurement_inputs, price_break_even, procurement_slopes, sold_duration_association, sold_performance_slopes,
)
from feedlot_analytics.contracts import FINISHED, MORTALITY
from feedlot_analytics.metrics import aggregate_closeout


class CloseoutEconomicsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tables = build(Path(__file__).resolve().parents[1]).tables
        cls.animals = tables["animal_closeout"]
        cls.health = tables["animal_health_summary"]
        cls.lots = tables["lot_closeout"]
        cls.exceptions = tables["audit_exceptions"]
        cls.feed_bridge = tables["lot_feed_reconciliation"]
        cls.overall = aggregate_closeout(cls.animals, cls.health)

    def test_audit_review_ties_to_all_original_rules_and_residuals(self):
        counts, residuals = audit_summary(self.exceptions, self.feed_bridge)
        self.assertEqual(counts.groupby("severity")["size"].sum().to_dict(), {"high": 2, "low": 161, "medium": 1})
        residuals = residuals.set_index("rule")
        self.assertEqual(residuals.affected_lots.to_dict(), {"feed_dm_rounding": 77, "feed_cost_rounding": 83})
        self.assertAlmostEqual(residuals.loc["feed_dm_rounding", "net_residual"], .40)
        self.assertAlmostEqual(residuals.loc["feed_cost_rounding", "net_residual"], -.57)
        self.assertTrue(residuals.max_share_of_bound.lt(1).all())
        incomplete = self.exceptions.drop(self.exceptions.index[0])
        with self.assertRaisesRegex(ValueError, "Feed exception keys disagree"):
            audit_summary(incomplete, self.feed_bridge)

    def test_cost_structure_includes_mortality_once(self):
        by_outcome = aggregate_closeout(self.animals, self.health, by=("exit_type",)).set_index("exit_type")
        result = cost_structure(self.overall.iloc[0], by_outcome)
        self.assertAlmostEqual(result.all_outcomes_cad.sum(), 41328195.32)
        self.assertAlmostEqual(result.mortality_cad.sum(), 512194.64)
        self.assertAlmostEqual(result.share_of_modeled_cost.sum(), 1)
        self.assertAlmostEqual(result.cad_per_placed.sum(), 41328195.32 / 15000)
        self.assertTrue(cost_structure(self.overall.iloc[0], by_outcome.drop(MORTALITY)).mortality_cad.eq(0).all())

    def test_cohort_costs_and_loss_burden_reconcile_across_region_and_quarter(self):
        by = ("origin_region", "placement_quarter")
        summary = cohort_economics(self.animals, self.health, by=by)
        self.assertEqual(summary.head_placed.sum(), 15000)
        self.assertEqual(summary.lot_count.sum(), 90)
        self.assertEqual(summary.head_mortality.sum(), 240)
        self.assertEqual(summary.all_outcome_margin_cents.sum(), 438199299)
        self.assertEqual(summary.loss_head.sum(), self.animals.net_margin_cad.lt(0).sum())
        losses = self.animals.loc[self.animals.net_margin_cad.lt(0), "net_margin_cad"]
        self.assertAlmostEqual(summary.gross_loss_cents.sum() / 100, -losses.sum())
        self.assertAlmostEqual((summary.production_cost_cad_per_placed * summary.head_placed).sum(), 41328195.32)
        with self.assertRaisesRegex(ValueError, "Unsupported animal grouping"):
            cohort_economics(self.animals, self.health, by=("predominant_breed",))

    def test_lot_ranking_uses_full_same_quarter_peers_and_additive_bridge(self):
        peers = lot_peer_review(self.lots)
        self.assertEqual(len(peers), 90)
        reported = peers.iloc[0]
        quarter = peers[peers.placement_quarter.eq(reported.placement_quarter)]
        rest = quarter[quarter.lot_id.ne(reported.lot_id)]
        self.assertEqual(reported.rank_all_outcome_per_placed, 1)
        self.assertEqual(reported.peer_head_placed, rest.head_placed.sum())
        expected = reported[MARGIN] - rest.all_outcome_margin_cents.sum() / (100 * rest.head_placed.sum())
        self.assertAlmostEqual(reported.all_outcome_margin_contribution_cad_per_placed, expected)
        components = [field.replace("_cents", "_contribution_cad_per_placed") for field in REVENUE_AND_COSTS]
        np.testing.assert_allclose(peers[components].sum(axis=1), peers.all_outcome_margin_contribution_cad_per_placed)
        invalid = quarter.iloc[:5].copy()
        invalid.loc[invalid.index[0], "head_count_in"] += 1
        self.assertTrue(lot_peer_review(invalid).empty)
        self.assertEqual(len(lot_peer_review(invalid, min_lots=4)), 4)

    def test_lot_quartiles_are_unweighted_but_pooled_economics_use_head(self):
        lots = pd.DataFrame({
            "lot_id": ["a", "b"], "group": ["same", "same"],
            "head_placed": [1, 3], "head_sold": [1, 3], "production_cost_cents": [100, 900],
            "all_outcome_margin_cents": [-100, 300], MARGIN: [-1., 1.],
        })
        result = lot_heterogeneity(lots, by=("group",)).loc["same"]
        self.assertEqual(result[MARGIN], .5)
        self.assertEqual(result.lot_margin_median_cad_per_placed, 0)
        self.assertEqual(result.lot_margin_p25_cad_per_placed, -.5)
        self.assertEqual(result.pooled_cost_cad_per_placed, 2.5)
        self.assertEqual(result.loss_lots, 1)

    def test_downside_ties_zero_and_empty(self):
        result = downside_summary(pd.Series([-500, -500, 0, 10000]), quantile=.25)
        self.assertEqual(result.tail_cutoff_cad, -5)
        self.assertEqual(result.tail_units, 2)
        self.assertEqual(result.tail_net_cad, -10)
        self.assertEqual(result.loss_share, .5)
        self.assertEqual(result.gross_loss_cad, 10)
        empty = downside_summary(pd.Series([], dtype=int))
        self.assertEqual(empty.units, 0)
        self.assertTrue(pd.isna(empty.tail_mean_cad))
        with self.assertRaisesRegex(ValueError, "complete margin"):
            downside_summary(pd.Series([1, np.nan]))

    def test_lot_composition_counts_individual_breeds_and_requires_full_coverage(self):
        shares = lot_composition(self.animals, self.lots)
        np.testing.assert_allclose(shares.sum(axis=1), 1)
        self.assertEqual(len(shares), 90)
        self.assertTrue(shares.gt(0).sum(axis=1).gt(1).all())
        lot_id = shares.index[0]
        lot_breed = self.animals.loc[self.animals.lot_id.eq(lot_id), "breed"].value_counts(normalize=True)
        pd.testing.assert_series_equal(shares.loc[lot_id].reindex(lot_breed.index), lot_breed.astype(float), check_names=False)
        with self.assertRaisesRegex(ValueError, "all placement animals"):
            lot_composition(self.animals.iloc[1:], self.lots)

    def test_break_even_closes_exact_ledger_and_holds_other_side_fixed(self):
        result = price_break_even(self.overall).iloc[0]
        ledger = self.overall.iloc[0]
        margin = ledger.all_outcome_margin_cents / 100
        self.assertAlmostEqual(result.purchase_headroom_cad_per_live_kg * ledger.placement_weight_kg, margin)
        self.assertAlmostEqual(result.carcass_headroom_cad_per_hcw_kg * ledger.hcw_kg, margin)
        self.assertAlmostEqual(result.margin_delta_cad_per_10c_purchase_increase, -.1 * ledger.placement_weight_kg)
        self.assertAlmostEqual(result.margin_delta_cad_per_10c_carcass_decrease, -.1 * ledger.hcw_kg)
        fixed_other_revenue = self.overall.copy()
        fixed_other_revenue["gross_revenue_cents"] += 10000
        adjusted = price_break_even(fixed_other_revenue).iloc[0]
        self.assertAlmostEqual((result.min_carcass_cad_per_hcw_kg - adjusted.min_carcass_cad_per_hcw_kg)
                               * ledger.hcw_kg, 100)

    def test_break_even_discloses_missing_carcass_exposure_and_no_sale_case(self):
        missing = self.overall.assign(head_hcw_eligible=self.overall.head_sold - 1)
        self.assertTrue(price_break_even(missing).min_carcass_cad_per_hcw_kg.isna().all())
        death_only = aggregate_closeout(self.animals.loc[self.animals.exit_type.eq(MORTALITY)], self.health)
        result = price_break_even(death_only).iloc[0]
        self.assertTrue(pd.isna(result.min_carcass_cad_per_hcw_kg))
        self.assertLess(result.max_purchase_cad_per_live_kg, 0)

    def test_procurement_slopes_condition_on_quarter_and_keep_lot_grain(self):
        inputs = lot_procurement_inputs(self.lots)
        self.assertEqual(len(inputs), 90)
        row = self.lots.iloc[0]
        self.assertAlmostEqual(inputs.iloc[0].mean_entry_weight_kg, row.placement_weight_kg / row.head_placed)
        sample = pd.DataFrame({
            "lot_id": ["a", "b", "c", "d"],
            "placement_quarter": ["q1", "q1", "q2", "q2"],
            "head_placed": [100, 200, 150, 200],
            "lot_sex": ["s", "s", "h", "s"],
            "feeder_purchase_price_per_kg": [1., 2., 3., 4.],
            "mean_entry_weight_kg": [400., 400., 400., 400.],
            MARGIN: [30., 20., 130., 120.],
        })
        result = procurement_slopes(sample)
        price = result.loc["feeder_purchase_price_per_kg"]
        self.assertEqual(price.lots, 4)
        self.assertEqual(price.placed_head, 650)
        self.assertGreater(price.pooled_slope_cad, 0)
        self.assertAlmostEqual(price.within_quarter_slope_cad, -1)
        self.assertAlmostEqual(price.leave_one_lot_out_low, -1)
        self.assertAlmostEqual(price.leave_one_lot_out_high, -1)
        self.assertAlmostEqual(price.within_quarter_and_sex_slope_cad, -1)
        self.assertTrue(pd.isna(result.loc["mean_entry_weight_kg", "within_quarter_slope_cad"]))

    def test_sold_duration_reports_lot_level_sensitivity_when_duration_is_shared(self):
        result = sold_duration_association(self.animals).iloc[0]
        self.assertEqual(result.lots, 90)
        self.assertEqual(result.sold_head, 14760)
        self.assertTrue(np.isfinite(result.within_quarter_slope_cad))
        head_level = sold_performance_slopes(self.animals, draws=50).loc["financial_dof"]
        self.assertEqual(head_level.lots_with_within_variation, 0)
        self.assertTrue(pd.isna(head_level.within_lot_cad_per_sold))

    def test_within_lot_slopes_exclude_deaths_and_resample_lots_reproducibly(self):
        a = pd.DataFrame({
            "animal_id": list("abcde"), "lot_id": ["a", "a", "b", "b", "b"],
            "exit_type": [FINISHED] * 4 + [MORTALITY],
            "total_gain_kg": [50] * 4 + [0], "allocated_dmi_kg": [300] * 5,
            "financial_dof": [100, 110, 100, 110, 10],
            "lifetime_adg_kg": [1., 2., 1., 2., 0.], "fcr": [7., 6., 7., 6., 0.],
            "net_margin_cad": [10., 30., 110., 130., -100.],
        })
        result = sold_performance_slopes(a, draws=50)
        pd.testing.assert_frame_equal(result, sold_performance_slopes(a, draws=50))
        self.assertTrue(result.sold_head.eq(4).all())
        self.assertTrue(result.lots_with_within_variation.eq(2).all())
        self.assertAlmostEqual(result.loc["lifetime_adg_kg", "within_lot_cad_per_sold"], 2)
        self.assertAlmostEqual(result.loc["fcr", "within_lot_cad_per_sold"], -20)
        self.assertAlmostEqual(result.loc["financial_dof", "lot_bootstrap_low"], 20)
        self.assertAlmostEqual(result.loc["financial_dof", "lot_bootstrap_high"], 20)


if __name__ == "__main__":
    unittest.main()
