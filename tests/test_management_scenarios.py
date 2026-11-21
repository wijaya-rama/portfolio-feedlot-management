import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from feedlot_analytics.contracts import COSTS, FINISHED, MORTALITY
from feedlot_analytics.feed_growth import load_analysis
from feedlot_analytics.management_scenarios import ADDITIVE, OUTCOME_MONEY, ScenarioEngine
from feedlot_analytics.scenario_config import AdditionalDeaths, AdditionalSurvivors, PriceShocks, Scenario, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "phase2b/04_MANAGEMENT_SCENARIOS_CONFIG.json"


class ScenarioConfigurationTest(unittest.TestCase):
    def test_invalid_parameters_fail_clearly(self):
        cases = [
            (lambda: PriceShocks(purchase_cad_per_live_kg=float("inf")), "finite"),
            (lambda: PriceShocks(feed_fraction=True), "finite"),
            (lambda: PriceShocks(feed_fraction=-1.01), "feed_fraction"),
            (lambda: PriceShocks(carcass_fraction=-1.01), "carcass_fraction"),
            (lambda: PriceShocks(feed_phase_fractions={"Unmapped": .2}), "feed_phase_fractions"),
            (lambda: PriceShocks(feed_component_fractions={"concentrate": -.2j}), "finite"),
            (lambda: PriceShocks(carcass_cad_per_hcw_kg=.1, carcass_fraction=.1), "either"),
            (lambda: AdditionalDeaths(.5, .2, .2, 0, 0), "positive integer"),
            (lambda: AdditionalDeaths(1, .2, 1.1, 0, 0), "avoidable_yardage"),
            (lambda: AdditionalSurvivors(1, 180, 600, 1.1, 8, 4, .6, 0, 0), "dressing_fraction"),
            (lambda: AdditionalSurvivors(1, 180, 600, .60, 8, -1, .6, 0, 0), "feed_cad"),
            (lambda: Scenario("", PriceShocks()), "nonempty"),
        ]
        for create, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                create()

    def test_json_rejects_typos_duplicates_and_wrong_shapes(self):
        cases = [
            ('[{"name":"a","prices":{"feed_percent":0.1}}]', "feed_percent"),
            ('[{"name":"a","prices":{"feed_fraction":0.1,"feed_fraction":0.2}}]', "duplicate field"),
            ('[{"name":"a"},{"name":"a"}]', "unique"),
            ('[{"name":"a","mortality":{"direction":"other"}}]', "mortality.direction"),
            ('{"name":"a"}', "nonempty JSON array"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scenarios.json"
            for input_json, message in cases:
                path.write_text(input_json, encoding="utf-8")
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    load_scenarios(path)

    def test_editable_input_is_defensively_copied(self):
        phases = {"Finisher": .2}
        prices = PriceShocks(feed_phase_fractions=phases)
        phases["Finisher"] = .5
        self.assertEqual(prices.feed_phase_fractions["Finisher"], .2)
        with self.assertRaises(TypeError):
            prices.feed_phase_fractions["Finisher"] = .3


class ScenarioSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build, cls.delivery = load_analysis(ROOT)
        cls.animals = cls.build.tables["animal_closeout"].set_index("animal_id")
        cls.engine = ScenarioEngine(cls.build, cls.delivery)
        cls.scenarios = {entry.name: entry for entry in load_scenarios(CONFIG)}
        cls.results = {name: cls.engine.evaluate(scenario) for name, scenario in cls.scenarios.items()}
        cls.base = cls.results["Booked base"].summarize().iloc[0]

    def test_zero_shocks_reproduce_exact_source_cents_and_placed_denominator(self):
        base = self.base
        self.assertEqual((base.head_placed, base.head_sold, base.head_mortality, base.head_hcw_eligible),
                         (15000, 14760, 240, 14760))
        expected = {
            "revenue_cad": 4571018831, "total_cost_cad": 4132819532, "margin_cad": 438199299,
            "booked_mortality_burden_cad": 51219464, "purchase_cost_cad": 2910510659,
            "allocated_feed_cost_cad": 1021954349, "yardage_cost_cad": 159035040,
            "vet_cost_cad": 41319484,
        }
        for key, cents in expected.items():
            self.assertEqual(round(base[key] * 100), cents)
        self.assertEqual(base.classification, "observed booked")
        self.assertEqual(base.loss_making_lots, 0)
        self.assertEqual(round(base.margin_cad_per_head_placed, 2), 292.13)
        zero = self.engine.evaluate(Scenario("Zero", PriceShocks(feed_phase_fractions={"Finisher": 0})))
        pd.testing.assert_frame_equal(zero.lots, self.results["Booked base"].lots, check_exact=True)
        self.assertTrue(zero.mortality_bridge.empty)

    def test_every_scenario_reconciles_at_lot_and_portfolio_grains(self):
        for name, result in self.results.items():
            with self.subTest(name=name):
                lots, totals = result.lots, result.summarize()
                total = totals.iloc[0]
                self.assertEqual(len(lots), 90)
                self.assertEqual(total.head_sold + total.head_mortality, total.head_placed)
                self.assertEqual(total.loss_making_lots, lots.margin_cad.round(2).lt(0).sum())
                self.assertAlmostEqual(total.loss_making_lot_share, total.loss_making_lots / len(lots))
                for row in (lots, totals):
                    np.testing.assert_allclose(row.revenue_cad - row.total_cost_cad, row.margin_cad, atol=1e-7, rtol=0)
                    np.testing.assert_allclose(row[list(COSTS)].sum(axis=1) + row.other_incremental_cost_cad,
                                               row.total_cost_cad, atol=1e-7, rtol=0)
                    np.testing.assert_allclose(row.margin_cad / row.head_placed, row.margin_cad_per_head_placed,
                                               atol=1e-10, rtol=0)
                np.testing.assert_allclose(lots[list(ADDITIVE)].sum().astype(float),
                                           total[list(ADDITIVE)].astype(float), atol=1e-7, rtol=0)

    def test_shocks_use_eligible_placed_kg_sold_hcw_and_sold_revenue(self):
        a = self.animals
        placed_kg = a.entry_weight_kg.sum()
        sold = a.loc[a.exit_type.eq(FINISHED) & a.hot_carcass_weight_kg.gt(0)]
        self.assertAlmostEqual(self.base.placement_weight_kg, placed_kg)
        self.assertAlmostEqual(self.base.hcw_kg, sold.hot_carcass_weight_kg.sum())
        comparisons = [
            ("Higher feeder basis", .25 * placed_kg, "purchase_cost_cad", -1),
            ("Lower carcass CAD/kg", -.35 * sold.hot_carcass_weight_kg.sum(), "revenue_cad", 1),
            ("Lower carcass percentage", -.05 * sold.gross_revenue_cad.sum(), "revenue_cad", 1),
            ("Higher allocated feed", .1 * a.allocated_feed_cost_cad.sum(), "allocated_feed_cost_cad", -1),
        ]
        for name, expected, field, direction in comparisons:
            with self.subTest(name=name):
                candidate = self.results[name].summarize().iloc[0]
                self.assertEqual(candidate.classification, "fixed-volume accounting")
                self.assertAlmostEqual(candidate[field] - self.base[field], expected, places=7)
                self.assertAlmostEqual(candidate.margin_change_cad, direction * expected, places=7)
                for unchanged in ("head_placed", "head_sold", "head_mortality", "hcw_kg"):
                    self.assertEqual(candidate[unchanged], self.base[unchanged])

    def test_phase_and_component_shocks_are_reconciled_once_at_delivery_grain(self):
        prices = PriceShocks(feed_fraction=.10, feed_phase_fractions={"Finisher": .15},
                             feed_component_fractions={"concentrate": .20})
        lot_id = self.delivery.lot_id.iloc[0]
        delivery = self.delivery.loc[self.delivery.lot_id.eq(lot_id)]
        component_costs = delivery[["forage_cost_cad", "concentrate_cost_cad", "supplement_cost_cad"]]
        ratio = (component_costs.concentrate_cost_cad / component_costs.sum(axis=1)).fillna(0)
        daily_factor = 1.10 * (1 + .15 * delivery.ration_phase.eq("Finisher")) * (1 + .20 * ratio)
        delivered_cost = delivery.delivered_feed_cost_cad
        lot_result = self.engine.evaluate(Scenario("Combined feed", prices)).select([lot_id]).lots.iloc[0]
        booked = self.animals.loc[self.animals.lot_id.eq(lot_id), "allocated_feed_cost_cad"].sum()
        expected = booked * (delivered_cost * daily_factor).sum() / delivered_cost.sum()
        self.assertAlmostEqual(lot_result.allocated_feed_cost_cad, expected, places=8)
        detail = self.engine.feed_cost_detail(prices)
        self.assertAlmostEqual(detail.booked_feed_exposure_cad.sum(), self.base.allocated_feed_cost_cad)
        self.assertAlmostEqual(detail.scenario_feed_exposure_cad.sum(),
                               self.engine.evaluate(Scenario("Combined feed", prices)).lots.allocated_feed_cost_cad.sum())
        with self.assertRaisesRegex(ValueError, "unique"):
            ScenarioEngine(self.build, pd.concat([self.delivery, self.delivery.iloc[[0]]]))
        changed = self.delivery.assign(delivered_feed_cost_cad=self.delivery.delivered_feed_cost_cad + .01)
        with self.assertRaisesRegex(ValueError, "delivered lot ledger"):
            ScenarioEngine(self.build, changed)

    def test_survivor_bridge_retains_booked_cost_and_uses_incremental_expense(self):
        name = "Lower mortality, conservative finish"
        assumptions = self.scenarios[name].mortality
        result = self.results[name]
        bridge, total = result.mortality_bridge, result.summarize().iloc[0]
        self.assertEqual((total.head_mortality, total.head_sold, bridge.animal_id.nunique()), (180, 14820, 60))
        self.assertTrue(bridge.original_outcome.eq(MORTALITY).all())
        originals = self.animals.loc[bridge.animal_id].reset_index()
        np.testing.assert_array_equal(bridge.extra_financial_days,
                                      assumptions.finish_financial_dof - originals.financial_dof)
        np.testing.assert_allclose(bridge.booked_death_burden_cad, originals[list(COSTS)].sum(axis=1))
        hcw = assumptions.finish_live_kg * assumptions.dressing_fraction
        expected = (hcw * assumptions.price_cad_per_hcw_kg
                    - bridge.extra_financial_days * (assumptions.feed_cad_per_extra_day
                                                     + assumptions.yardage_cad_per_extra_day)
                    - assumptions.vet_cad_per_head - assumptions.other_cad_per_head)
        np.testing.assert_allclose(bridge.incremental_margin_cad, expected)
        self.assertEqual(total.purchase_cost_cad, self.base.purchase_cost_cad)
        self.assertEqual(total.booked_mortality_burden_cad, self.base.booked_mortality_burden_cad)
        self.assertAlmostEqual(total.margin_change_cad, expected.sum())
        self.assertAlmostEqual(total.hcw_kg - self.base.hcw_kg, hcw * 60)
        self.assertEqual(total.classification, "hypothetical operational")

    def test_combination_reprices_marginal_revenue_and_feed_once(self):
        stress = self.results["Adverse prices"]
        combined = self.results["Adverse prices and higher mortality"]
        bridge = combined.mortality_bridge
        rows = self.animals.loc[bridge.animal_id].reset_index()
        self.assertTrue(bridge.original_outcome.eq(FINISHED).all())
        self.assertEqual(combined.lots.head_mortality.sum(), 300)
        self.assertEqual(combined.lots.purchase_cost_cad.sum(), stress.lots.purchase_cost_cad.sum())
        np.testing.assert_allclose(bridge.revenue_delta_cad, -(rows.gross_revenue_cad - .4 * rows.hot_carcass_weight_kg))
        np.testing.assert_allclose(bridge.feed_delta_cad, -.20 * 1.15 * rows.allocated_feed_cost_cad)
        np.testing.assert_allclose(bridge.yardage_delta_cad, -.20 * rows.yardage_cost_cad)
        np.testing.assert_allclose(bridge.hcw_delta_kg, -rows.hot_carcass_weight_kg)
        self.assertAlmostEqual(combined.lots.margin_cad.sum() - stress.lots.margin_cad.sum(),
                               bridge.revenue_delta_cad.sum() - bridge[list(OUTCOME_MONEY[1:])].sum().sum())
        survival = self.scenarios["Lower mortality, favorable finish"]
        priced = self.engine.evaluate(replace(survival, prices=PriceShocks(carcass_fraction=-.05, feed_fraction=.1)))
        plain = self.results[survival.name].mortality_bridge
        np.testing.assert_allclose(priced.mortality_bridge.revenue_delta_cad, plain.revenue_delta_cad * .95)
        np.testing.assert_allclose(priced.mortality_bridge.feed_delta_cad, plain.feed_delta_cad * 1.1)

    def test_scope_validation_and_physical_survivor_inputs(self):
        survival = self.scenarios["Lower mortality, favorable finish"]
        for change, message in [
            ({"head": 241}, "exceeds"), ({"finish_financial_dof": 1}, "recorded death DOF"),
            ({"finish_live_kg": 200}, "entry weight"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.engine.evaluate(replace(survival, mortality=replace(survival.mortality, **change)))
        for prices, message in [
            (PriceShocks(purchase_cad_per_live_kg=-8), "individual purchase"),
            (PriceShocks(carcass_cad_per_hcw_kg=-9), "eligible sale price"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.engine.evaluate(Scenario("Invalid", prices))
        with self.assertRaisesRegex(ValueError, "hypothetical survivor price"):
            self.engine.evaluate(replace(survival, mortality=replace(survival.mortality, price_cad_per_hcw_kg=0),
                                         prices=PriceShocks(carcass_cad_per_hcw_kg=-.40)))

    def test_filters_are_equivalent_and_replay_is_deterministic(self):
        name = "Adverse prices and higher mortality"
        expected = self.results[name]
        reordered = self.engine.evaluate(load_scenarios(CONFIG)[-1])
        pd.testing.assert_frame_equal(expected.lots, reordered.lots, check_exact=True)
        pd.testing.assert_frame_equal(expected.mortality_bridge, reordered.mortality_bridge, check_exact=True)
        region = expected.lots.origin_region.iloc[0]
        group = expected.summarize(by=("origin_region",))
        group = group.loc[group.origin_region.eq(region)].drop(columns="origin_region").reset_index(drop=True)
        ids = expected.lots.loc[expected.lots.origin_region.eq(region), "lot_id"]
        direct = expected.select(ids.iloc[::-1]).summarize()
        pd.testing.assert_frame_equal(group, direct, check_exact=False, atol=1e-8, rtol=0)
        with self.assertRaisesRegex(ValueError, "known, complete lot"):
            expected.select(["unknown"])

    def test_break_even_thresholds_and_two_way_frontier_hit_zero_margin(self):
        point = self.engine.break_even().iloc[0]
        for prices in [
            PriceShocks(purchase_cad_per_live_kg=point.purchase_headroom_cad_per_live_kg),
            PriceShocks(carcass_cad_per_hcw_kg=-point.carcass_headroom_cad_per_hcw_kg),
            PriceShocks(carcass_fraction=point.carcass_fraction_at_break_even),
            PriceShocks(feed_fraction=point.feed_fraction_at_break_even),
        ]:
            with self.subTest(prices=prices):
                self.assertAlmostEqual(self.engine.evaluate(Scenario("Break-even", prices)).lots.margin_cad.sum(), 0)
        line = self.engine.break_even_frontier([.30], feed_fraction=.15).iloc[0]
        prices = PriceShocks(purchase_cad_per_live_kg=.30, feed_fraction=.15,
                             carcass_cad_per_hcw_kg=line.break_even_carcass_cad_per_hcw_kg)
        self.assertTrue(line.nonnegative_eligible_prices)
        self.assertAlmostEqual(self.engine.evaluate(Scenario("Frontier", prices)).lots.margin_cad.sum(), 0)
        self.assertEqual(len(self.engine.break_even(by=("lot_id",))), 90)
