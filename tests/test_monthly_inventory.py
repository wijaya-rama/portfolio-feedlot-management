import unittest
from pathlib import Path

import pandas as pd

from feedlot_analytics.contracts import FINISHED, MORTALITY
from feedlot_analytics.inventory_market import CAD_PER_CWT_LIVE, KG_PER_CWT, market_quotes
from feedlot_analytics.monthly_inventory import _inventory_tables, build_monthly_inventory
from feedlot_analytics.relations import cents

ROOT = Path(__file__).resolve().parents[1]
JAN = pd.Timestamp("2024-01-31")
FEB = pd.Timestamp("2024-02-29")


def fixture():
    animals = pd.DataFrame([
        ("A", "L1", "P1", "Hereford", "Steer", "2024-01-31", "2024-02-29", FINISHED, 100., 30., 18., 20.),
        ("B", "L1", "P1", "Black Angus", "Heifer", "2024-01-30", "2024-01-31", MORTALITY, 80., 1., 1.2, 19.25),
        ("C", "L1", "P1", "Hereford", "Heifer", "2024-01-31", "2024-01-31", FINISHED, 120., .40, .60, 18.),
    ], columns=("animal_id", "lot_id", "pen_id", "breed", "sex", "entry_date", "exit_date", "exit_type",
                "purchase_cost_cad", "allocated_feed_cost_cad", "yardage_cost_cad", "vet_cost_cad"))
    animals["production_cost_cents"] = animals.iloc[:, -4:].apply(cents).sum(axis=1)
    animals[["entry_date", "exit_date"]] = animals[["entry_date", "exit_date"]].apply(pd.to_datetime)
    treatments = pd.DataFrame(
        [("T1", "B", JAN, 1.25), ("T2", "A", pd.Timestamp("2024-02-01"), 2.)],
        columns=("treatment_id", "animal_id", "treatment_date", "vet_cost_cad"),
    )
    dates = pd.date_range("2024-01-30", FEB)
    delivery = pd.DataFrame({
        "lot_id": "L1", "pen_id": "P1", "feed_date": dates, "recorded_head_days": [1, 3, *([1] * 29)],
        "delivered_feed_cost_cad": [.99, 1, *([.99] * 29)], "delivered_as_fed_kg": 1., "delivered_dm_kg": .5,
    })
    scales = pd.DataFrame(
        [("A", JAN, 300.), ("A", pd.Timestamp("2024-02-01"), 350.)],
        columns=("animal_id", "weigh_date", "weight_kg"),
    )
    return animals, treatments, delivery, scales


def quote(**overrides):
    # Synthetic quotation solely for testing the valuation calculation and its cutoff.
    return {
        "quote_id": "test", "month_end": "2024-01-31", "observed_on": "2024-01-26",
        "published_on": "2024-01-29", "sex": "Steer", "animal_class": "test feeder",
        "geography": "test region", "min_live_kg": 300., "max_live_kg": 350.,
        "price": KG_PER_CWT * 4, "unit": CAD_PER_CWT_LIVE, "reference": "test fixture",
        "usage_rights": "synthetic fixture", "costs_to_sell_cad_per_head": 10.,
        **overrides,
    }


def report(inputs=None, quotes=(), age=45):
    if inputs is None:
        inputs = fixture()
    return _inventory_tables(*inputs, market_quotes(quotes), max_weight_age_days=age)[0]


class MonthlyInventoryBoundaryTest(unittest.TestCase):
    def test_month_end_entry_exit_and_same_day_sale(self):
        tables = report()
        month = tables["monthly_yard"].set_index("month_end")
        heads = ["opening_head", "placed_head", "sold_head", "mortality_head", "closing_head"]
        self.assertEqual(month.loc[JAN, heads].tolist(), [0, 3, 1, 1, 1])
        self.assertEqual(month.loc[FEB, heads].tolist(), [1, 0, 1, 0, 0])
        animals = tables["animal_month"].set_index(["animal_id", "month_end"])
        self.assertEqual(animals.loc[("C", JAN), "production_head_days"], 1)
        self.assertEqual(animals.loc[("B", JAN), "direct_vet_cents"], 125)
        self.assertIs(pd.isna(animals.loc[("A", JAN), "exit_type"]), True)
        self.assertEqual(animals.loc[("A", FEB), "exit_date"], FEB)

    def test_release_once_by_correct_outcome_and_period(self):
        month = report()["monthly_yard"].set_index("month_end")
        self.assertEqual(month.estimated_sold_cogs_cents.tolist(), [12093, 14905])
        self.assertEqual(month.estimated_mortality_loss_cents.tolist(), [8377, 0])
        self.assertEqual(month.source_sold_release_cents.tolist(), [12000, 10200])
        self.assertEqual(month.source_mortality_release_cents.tolist(), [8125, 0])
        self.assertTrue(month.actual_sold_cogs_cents.isna().all())
        self.assertTrue(pd.isna(month.loc[JAN, "actual_mortality_loss_cents"]))
        self.assertEqual(month.loc[FEB, "actual_mortality_loss_cents"], 0)

    def test_feed_cent_conservation_and_balances(self):
        tables = report()
        ledger = tables["animal_month"].set_index(["animal_id", "month_end"])
        self.assertEqual([ledger.loc[(animal, JAN), "estimated_feed_cents"] for animal in ("A", "B", "C")],
                         [34, 132, 33])
        month = tables["monthly_yard"].set_index("month_end")
        self.assertEqual(month.estimated_feed_cents.tolist(), [199, 2871])
        self.assertEqual(month.estimated_opening_wip_cents.tolist(), [0, 10094])
        self.assertEqual(month.estimated_closing_wip_cents.tolist(), [10094, 0])
        self.assertEqual(month.source_closing_wip_cents.tolist(), [10000, 0])
        self.assertTrue(pd.isna(month.loc[JAN, "actual_closing_wip_cents"]))
        audit = tables["lifetime_closeout_audit"]
        self.assertEqual(audit.undated_vet_base_cents.sum(), 5400)
        self.assertNotIn("undated_vet_base_cents", month)
        self.assertFalse(ledger.reset_index().duplicated(["animal_id", "month_end"]).any())
        self.assertFalse(audit.animal_id.duplicated().any())

    def test_future_events_and_booked_allocations_cannot_change_january(self):
        original = report()["animal_month"].loc[lambda frame: frame.month_end.eq(JAN)]
        animals, treatments, delivery, scales = fixture()
        animals.loc[0, ["allocated_feed_cost_cad", "production_cost_cents"]] += [100, 10000]
        animals.loc[0, ["vet_cost_cad", "production_cost_cents"]] += [50, 5000]
        treatments.loc[1, "vet_cost_cad"] += 50
        delivery.loc[delivery.feed_date.gt(JAN), "delivered_feed_cost_cad"] += 50
        scales.loc[1, "weight_kg"] += 100
        revised = report((animals, treatments, delivery, scales))["animal_month"]
        pd.testing.assert_frame_equal(original, revised.loc[revised.month_end.eq(JAN)], check_exact=True)

    def test_incomplete_source_events_fail_instead_of_assuming_expense_zero(self):
        animals, treatments, delivery, scales = fixture()
        with self.assertRaisesRegex(ValueError, "Incomplete dated feed"):
            report((animals, treatments, delivery.drop(index=1), scales))
        with self.assertRaisesRegex(ValueError, "exit.undated_vet_base"):
            report((animals, treatments.iloc[:0], delivery, scales))

    def test_duplicate_source_events_are_rejected(self):
        animals, treatments, delivery, scales = fixture()
        with self.assertRaisesRegex(ValueError, "dated treatments"):
            report((animals, pd.concat([treatments, treatments]), delivery, scales))
        with self.assertRaisesRegex(ValueError, "dated feed"):
            report((animals, treatments, pd.concat([delivery, delivery]), scales))


class MarketValuationTest(unittest.TestCase):
    def test_no_default_prices_and_no_future_scale(self):
        tables = report()
        animal = tables["animal_month"].set_index(["animal_id", "month_end"]).loc[("A", JAN)]
        self.assertEqual((animal.last_scale_date, animal.liveweight_proxy_kg), (JAN, 300))
        self.assertEqual(animal.market_status, "no_price_assumption")
        self.assertTrue(pd.isna(animal.estimated_market_value_cents))
        self.assertTrue(pd.isna(tables["monthly_yard"].iloc[0].estimated_market_value_cents))

    def test_live_cwt_conversion_and_separate_selling_costs(self):
        month = report(quotes=[quote()])["monthly_yard"].iloc[0]
        self.assertEqual(month.estimated_market_value_cents, 120000)
        self.assertEqual(month.indicative_market_less_costs_to_sell_cents, 119000)
        month = report(quotes=[quote(costs_to_sell_cad_per_head=None)])["monthly_yard"].iloc[0]
        self.assertTrue(pd.isna(month.indicative_market_less_costs_to_sell_cents))

    def test_quote_rejects_future_publication_carcass_and_overlapping_bands(self):
        for options, message in (
            ([quote(published_on="2024-02-01")], "published by"),
            ([quote(observed_on="2024-02-01")], "observed and published"),
            ([quote(unit="CAD/kg HCW")], "liveweight"),
            ([quote(), quote(quote_id="test-2", min_live_kg=349.99, max_live_kg=400)], "overlap"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                market_quotes(options)

    def test_missing_and_stale_weight_leave_quote_unapplied(self):
        animals, treatments, delivery, scales = fixture()
        for weighings, status in (
            (scales.iloc[1:], "missing_scale"),
            (scales.assign(weigh_date=lambda f: f.weigh_date - pd.Timedelta(days=2)), "stale_scale"),
        ):
            with self.subTest(status=status):
                table = report((animals, treatments, delivery, weighings), quotes=[quote()], age=0)
                row = table["animal_month"].set_index(["animal_id", "month_end"]).loc[("A", JAN)]
                self.assertEqual(row.weight_basis, status)
                self.assertTrue(pd.isna(row.estimated_market_value_cents))

    def test_partial_pricing_keeps_the_portfolio_total_unavailable(self):
        animals, treatments, delivery, scales = fixture()
        animals.loc[1, "exit_date"] += pd.Timedelta(days=1)
        animals.loc[1, "yardage_cost_cad"] += .60
        animals.loc[1, "production_cost_cents"] += 60
        delivery.loc[delivery.feed_date.eq("2024-02-01"), "recorded_head_days"] = 2
        month = report((animals, treatments, delivery, scales), quotes=[quote()])["monthly_yard"].iloc[0]
        self.assertEqual((month.closing_head, month.market_valued_head), (2, 1))
        self.assertTrue(pd.isna(month.estimated_market_value_cents))


class MonthlyInventorySnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_monthly_inventory(ROOT)
        cls.tables = cls.result.tables

    def test_baseline_and_monthly_controls_pass(self):
        summary = self.result.reconciliation["summary"]
        self.assertEqual((summary["baseline_checks_passed"], summary["weather_dates_verified"]), (661, 704))
        self.assertTrue(all(check["passed"] for check in self.result.reconciliation["controls"]))
        self.assertEqual(len(self.tables["monthly_yard"]), 24)
        lot = self.tables["monthly_lot"]
        pen = self.tables["monthly_recorded_pen"]
        yard = self.tables["monthly_yard"].set_index("month_end")
        heads = ["opening_head", "placed_head", "sold_head", "mortality_head", "closing_head"]
        for scoped in (lot, pen):
            pd.testing.assert_frame_equal(yard[heads], scoped.groupby("month_end")[heads].sum())

    def test_reference_reconciliation_and_annual_carry(self):
        annual = self.tables["annual_yard"].set_index("year")
        self.assertEqual(annual.closing_head.tolist(), [2887, 0])
        self.assertEqual(annual.estimated_closing_wip_cents.tolist(), [621360475, 0])
        self.assertEqual(annual.estimated_opening_wip_cents.tolist(), [0, 621360475])
        self.assertEqual(annual.estimated_sold_cogs_cents.sum(), 4053180620)
        self.assertEqual(annual.estimated_mortality_loss_cents.sum(), 52638855)
        audit = self.tables["lifetime_closeout_audit"]
        self.assertEqual(len(audit), 15000)
        self.assertEqual(audit.booked_lifetime_total_cents.sum(), 4132819532)
        self.assertEqual(audit.undated_vet_base_cents.sum(), 27000000)
        self.assertEqual(audit.booked_less_allocated_delivery_cents.sum(), 57)
        open_months = self.tables["monthly_yard"].loc[lambda table: table.closing_head.gt(0)]
        self.assertTrue(open_months.estimated_market_value_cents.isna().all())


if __name__ == "__main__":
    unittest.main()
