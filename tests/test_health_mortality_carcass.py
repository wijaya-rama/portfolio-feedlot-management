import unittest
from pathlib import Path

import pandas as pd

from feedlot_analytics.carcass import carcass_bands, lot_health_review, sold_carcasses
from feedlot_analytics.contracts import FINISHED, MORTALITY
from feedlot_analytics.health_growth import (
    growth_landmark, intervals_with_treatments, persistent_growth, treatment_growth_pairs,
)
from feedlot_analytics.health_mortality import (
    animal_history, daily_risk, load_health_analysis, protocol_review, risk_contrasts, risk_segments,
    treatment_events, treatment_followup,
)
from feedlot_analytics.health_statistics import cohort_difference, within_lot_slope, with_entry_band
from feedlot_analytics.metrics import aggregate_closeout
from feedlot_analytics.transformations import animal_scale_stage

ROOT = Path(__file__).resolve().parents[1]


class TimingLogicTest(unittest.TestCase):
    def test_same_day_event_death_and_repeat_conserve_head_days(self):
        dates = pd.to_datetime
        history = pd.DataFrame({
            "animal_id": ["A", "B"], "lot_id": ["L", "L"], "pen_id": ["P", "P"],
            "entry_date": dates(["2025-01-01", "2025-01-01"]),
            "exit_date": dates(["2025-01-03", "2025-01-04"]),
            "exit_type": [MORTALITY, MORTALITY],
            "first_treatment_date": dates(["2025-01-03", "2025-01-02"]),
            "second_treatment_date": dates([None, "2025-01-03"]),
        })
        segments = risk_segments(history)
        daily = daily_risk(segments)
        self.assertEqual(daily.groupby("state").head_days.sum().to_dict(), {0: 5, 1: 1, 2: 1})
        self.assertEqual(daily.groupby("state").deaths.sum().to_dict(), {0: 1, 1: 0, 2: 1})
        same_day = daily_risk(risk_segments(history, include_event_day=True))
        self.assertEqual(same_day.groupby("state").deaths.sum().to_dict(), {0: 0, 1: 1, 2: 1})
        followup = treatment_followup(history)
        self.assertEqual(followup.index_day_death.tolist(), [True, False])
        self.assertEqual(followup.later_death_in_window.tolist(), [False, True])
        self.assertEqual(followup.repeat_in_window.tolist(), [False, True])

    def test_treatment_on_scale_boundaries_and_interior(self):
        dates = pd.to_datetime
        animals = pd.DataFrame({
            "animal_id": ["A"], "lot_id": ["L"], "pen_id": ["P"],
            "entry_date": dates(["2025-01-01"]), "exit_date": dates(["2025-04-15"]),
            "exit_type": [FINISHED], "breed": ["B"], "sex": ["S"], "frame_score": ["M"],
            "financial_dof": [105], "net_margin_cad": [9.], "entry_weight_kg": [320.],
        })
        treatments = pd.DataFrame({
            "treatment_id": ["7", "2", "1", "5", "4"], "animal_id": ["A"] * 5,
            "lot_id": ["L"] * 5, "pen_id": ["P"] * 5, "dof_at_treatment": [71, 1, 1, 70, 43],
            "treatment_date": dates(["2025-03-12", "2025-01-01", "2025-01-01", "2025-03-11", "2025-02-12"]),
            "vet_cost_cad": [40.] * 5,
        })
        rows = treatment_events(treatments, animals)
        self.assertEqual(rows.treatment_id.tolist(), ["1", "2", "4", "5", "7"])
        with self.assertRaisesRegex(ValueError, "inclusive DOF"):
            treatment_events(treatments.assign(dof_at_treatment=1), animals)
        with self.assertRaisesRegex(ValueError, "unique"):
            treatment_events(pd.concat([treatments, treatments.iloc[:1]]), animals)
        with self.assertRaisesRegex(ValueError, "Missing lookup"):
            treatment_events(treatments.assign(pen_id="Q"), animals)
        weights = pd.DataFrame({
            "animal_id": ["A"] * 4, "lot_id": ["L"] * 4, "pen_id": ["P"] * 4,
            "weigh_id": ["1", "2", "3", "4"], "weigh_stage": ["Arrival", "Day 35", "Day 70", "Day 105"],
            "weigh_date": dates(["2025-01-01", "2025-02-04", "2025-03-11", "2025-04-15"]),
            "weight_kg": [320., 350., 400., 440.],
        })
        linked = intervals_with_treatments(animal_scale_stage(animals, weights), animals, rows)
        self.assertEqual(linked[["prior_events", "events_on_start", "events_inside", "events_on_end"]].values.tolist(),
                         [[0, 2, 0, 0], [2, 0, 1, 1], [3, 1, 1, 0]])
        history = animals.assign(first_treatment_date=pd.Timestamp("2025-02-12"))
        landmark = growth_landmark(history, linked).iloc[0]
        self.assertFalse(landmark.prior_treatment)
        self.assertTrue(landmark.new_first_in_window)
        self.assertAlmostEqual(landmark.next_adg, 50 / 35)
        paired = treatment_growth_pairs(history, linked).iloc[0]
        self.assertEqual((paired.pre_weigh_stage, paired.post_weigh_stage), ("Day 35", "Day 105"))

    def test_common_support_excludes_solo_cells_and_uses_exposed_weights(self):
        sample = pd.DataFrame({
            "animal_id": list("abcdefg"), "lot_id": ["L"] * 3 + ["M"] * 3 + ["N"],
            "pen_id": ["P"] * 3 + ["Q"] * 4, "exposed": [True, False, False, True, True, False, True],
            "y": [1., 1., 0., 1., 0., 0., 0.],
        })
        result = cohort_difference(sample, exposed="exposed", outcome="y", strata=())
        self.assertEqual((result["exposed_eligible"], result["exposed_supported"]), (4, 3))
        self.assertAlmostEqual(result["difference"], .5)
        self.assertEqual(result["pens"], 2)


class Phase2B3SnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.events = load_health_analysis(ROOT)
        tables = cls.result.tables
        cls.animals = tables["animal_closeout"]
        cls.health = tables["animal_health_summary"]
        cls.history = animal_history(cls.animals, cls.health, cls.events)
        cls.intervals = intervals_with_treatments(tables["animal_scale_stage"], cls.animals, cls.events)

    def test_cardinality_cost_and_protocol_ledger(self):
        self.assertEqual(len(self.history), 15000)
        self.assertEqual((self.events.animal_id.nunique(), self.events.treatment_id.nunique()), (2100, 2220))
        self.assertEqual(self.history.treatment_events.value_counts().to_dict(), {0: 12900, 1: 1980, 2: 120})
        self.assertEqual(self.events.direct_cost_cents.sum(), 14319484)
        self.assertEqual(self.history.direct_treatment_cost_cents.sum(), 14319484)
        self.assertTrue(self.history.base_vet_cost_cad.eq(18).all())
        self.assertAlmostEqual(self.history.vet_cost_cad.sum(), 413194.84)
        event, first = protocol_review(self.events, self.history, self.health)
        self.assertEqual(event.events.sum(), 2220)
        self.assertEqual(event.repeat_events.sum(), 120)
        self.assertEqual(event.unique_animals.max(), 586)
        self.assertEqual(first.start_head.sum(), 2100)
        self.assertEqual(first.head_sold.sum(), 1947)
        self.assertEqual(first.repeat_days_1_30.sum(), 120)
        self.assertEqual(first.day0_deaths.sum(), 26)

    def test_temporal_risk_and_mortality_cost(self):
        days = daily_risk(risk_segments(self.history))
        self.assertEqual(days.head_days.sum(), 2650584)
        self.assertEqual(days.groupby("state").deaths.sum().to_dict(), {0: 113, 1: 108, 2: 19})
        self.assertTrue(days.deaths.le(days.head_days).all())
        support = risk_contrasts(days, max_dof=105)
        self.assertTrue(support.exposed_supported.eq(support.exposed_eligible).all())
        self.assertEqual(support.exposed_events_or_sum.tolist(), [126, 18])
        ledger = aggregate_closeout(self.animals, self.health, by=("exit_type",)).set_index("exit_type")
        dead = ledger.loc[MORTALITY]
        self.assertEqual(dead.head_mortality, 240)
        self.assertEqual(dead.mortality_loss_cents, 51219464)
        self.assertEqual(dead.production_cost_cents, dead.mortality_loss_cents)
        self.assertEqual(dead.gross_revenue_cents, 0)
        self.assertEqual(ledger.all_outcome_margin_cents.sum(), 438199299)
        lots = lot_health_review(self.result.tables["lot_closeout"], self.animals)
        self.assertEqual((len(lots), int(lots.head_mortality.sum())), (90, 240))
        self.assertTrue((lots.sold_margin_contribution_per_placed - lots.death_burden_per_placed
                         - lots.all_outcome_margin_per_head_placed).abs().lt(1e-9).all())

    def test_scale_alignment_and_landmark_cohorts(self):
        self.assertEqual(len(self.intervals), 59268)
        self.assertFalse(self.intervals.duplicated(["animal_id", "weigh_stage"]).any())
        self.assertTrue(self.intervals.previous_weigh_date.lt(self.intervals.weigh_date).all())
        pairs = treatment_growth_pairs(self.history, self.intervals)
        self.assertEqual((len(pairs), pairs.adg_change.count()), (2100, 350))
        self.assertTrue(pairs.loc[pairs.adg_change.notna(), "mortality"].eq(False).all())
        landmark = growth_landmark(self.history, self.intervals)
        self.assertEqual((len(landmark), landmark.same_day_first.sum()), (14882, 7))
        self.assertEqual(landmark.death_through_end.sum(), 52)
        main = persistent_growth(self.history, self.intervals)
        baseline = persistent_growth(self.history, self.intervals, landmark_ranks=False)
        self.assertEqual((len(main), len(baseline)), (14794, 14794))
        self.assertEqual((main.persistent_low.sum(), baseline.persistent_low.sum()), (165, 162))
        fresh = main.loc[main.at_risk_next_day & ~main.prior_treatment & ~main.same_day_first]
        self.assertEqual(fresh.loc[fresh.persistent_low, "new_first_in_window"].sum(), 1)

    def test_sold_grade_yield_and_bands(self):
        sold = sold_carcasses(self.history)
        self.assertEqual(len(sold), 14760)
        table = aggregate_closeout(sold, self.health).iloc[0]
        self.assertEqual(table.head_hcw_eligible, 14760)
        self.assertEqual(table.head_dressing_eligible, 14760)
        self.assertEqual(table.head_graded, 14760)
        self.assertEqual([table[f"head_grade_{grade}"] for grade in ("prime", "aaa", "aa", "b_discount")],
                         [1239, 10063, 3002, 456])
        self.assertAlmostEqual(table.dressing_yield, sold.hot_carcass_weight_kg.sum() / sold.exit_weight_kg.sum())
        self.assertAlmostEqual(table.realized_carcass_price_cad_per_kg,
                               sold.gross_revenue_cad.sum() / sold.hot_carcass_weight_kg.sum())
        bands = carcass_bands(sold, self.health)
        self.assertEqual(bands.groupby("weight").head_sold.sum().tolist(), [14760, 14760])
        self.assertEqual(bands.groupby("weight").gross_revenue_cents.sum().tolist(), [4571018831] * 2)
        contrast = cohort_difference(with_entry_band(sold.assign(treated=sold.treatment_events.gt(0))),
                                     exposed="treated", outcome="eligible_hcw_kg")
        self.assertLess(contrast["difference"], 0)
        fit = within_lot_slope(sold, predictor="exit_weight_kg", outcome="eligible_hcw_kg",
                               increment=10, numeric=("entry_weight_kg",), categorical=("breed", "frame_score"))
        self.assertEqual((fit["eligible"], fit["lots"], fit["pens"]), (14760, 90, 40))
        self.assertAlmostEqual(fit["slope"], 6.08735, places=4)
