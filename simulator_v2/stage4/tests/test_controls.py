"""Manually specified Stage 4 accounting and as-of controls."""

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from simulator_v2.stage1.fixture import FINAL_CUTOFF, START, fixture as livestock, local
from simulator_v2.stage1.provenance import canonical
from simulator_v2.stage3_5.fixture import integrated_fixture
from simulator_v2.stage4.close import close_month
from simulator_v2.stage4.export import build, verify_source
from simulator_v2.stage4.feed import CONSUMED, LossPolicy, apportioned, qualifies
from simulator_v2.stage4.fixture import Fixture, settings, yardage_day
from simulator_v2.stage4.ledger import Account, Action, Book, Sources, TICK, accounting_month, balance, periods
from simulator_v2.stage4.market import Quote, quote_for, valuation
from simulator_v2.stage4.recovery import Disposition, RecoveryLot, dispose
from simulator_v2.stage4.report import (close_series, feed_bridge, invoice_impact, invoice_routes,
                                        journal_sets, recoverable, sensitivity, warehouse_vintages)


class JournalExamples(unittest.TestCase):
    def setUp(self):
        self.when = local("2023-12-31 10:00")
        self.exit = local("2023-12-31 18:00")
        self.after = local("2024-01-05 10:00")
        self.calendar = periods(date(2023, 12, 31), date(2024, 1, 31))
        self.sources = Sources()
        self.book = Book(self.sources, self.calendar, version="example", policy="manual.1", yard="yard")

    def source(self, key, when, available=None, *, kind=None, parents=(), system="test"):
        return self.sources.add(system, key, key, when, available or when, available or when,
                                [key, kind], parents, event_kind=kind)

    def action(self, key, when, component, account, cents, *, available=None, route=True):
        return Action(key, self.source(key, when, available), when, component, Account.WIP,
                      account, cents, "A", "LOT", route_cost=route)

    def example(self, outcome):
        opening = self.action("open", self.when, "opening_wip", Account.OPENING, 10_000, route=False)
        feed = self.action("feed", self.when, CONSUMED, Account.DISTRIBUTION, 180)
        yard = self.action("yard", self.when, "yardage", Account.YARDAGE, 120)
        vet = self.action("treat", self.when, "vet_direct", Account.VET, 80)
        kind = "sale" if outcome == Account.COGS else "death"
        exit_id = self.source("exit", self.exit, kind=kind, system="livestock/movement_events")
        sale = Action("exit", exit_id, self.exit, "principal_release", outcome, Account.WIP, 0,
                      "A", "LOT", release=True)
        late = self.action("adjustment", self.when, "invoice_feed_consumption", Account.INVOICE, 25,
                           available=self.after)
        return opening, feed, yard, vet, sale, late

    def test_opening_vet_yardage_sale_and_after_lock_invoice(self):
        rows = self.example(Account.COGS)
        before = self.book.run((*rows, rows[0]), self.exit)
        self.assertEqual(balance(before, Account.COGS), 10_380)
        all_rows = self.book.run(rows, self.after)
        self.assertEqual(balance(all_rows, Account.COGS), 10_405)
        self.assertEqual(balance(all_rows, Account.WIP), 0)
        self.assertEqual(balance(all_rows, Account.MORTALITY), 0)
        self.assertEqual((all_rows[-1].service_date, all_rows[-1].accounting_month),
                         (date(2023, 12, 31), "2024-01"))
        self.assertEqual(self.book.run(rows, self.after), all_rows)
        self.assertEqual(tuple(row for row in all_rows if row.accounting_month == "2023-12"), before)

    def test_mortality_release_late_invoice_and_invalid_second_exit(self):
        rows = self.example(Account.MORTALITY)
        journal = self.book.run(rows, self.after)
        self.assertEqual(balance(journal, Account.MORTALITY), 10_405)
        self.assertEqual(balance(journal, Account.COGS), 0)
        self.assertEqual(balance(journal, Account.WIP), 0)
        duplicate_source = self.source("exit-retry", self.exit, self.after + TICK, kind="death",
                                       system="livestock/movement_events")
        duplicate = replace(rows[-2], key="duplicate", source_id=duplicate_source)
        with self.assertRaisesRegex(ValueError, "duplicate principal release"):
            self.book.run((*rows, duplicate), self.after + TICK)

    def test_cost_after_death_and_before_receipt_rejected(self):
        rows = self.example(Account.MORTALITY)
        charge = self.action("late-invalid", self.exit + TICK, "vet_direct", Account.VET, 80)
        with self.assertRaisesRegex(ValueError, "after exit"):
            self.book.run((*rows, charge), self.after)
        missing = Book(self.sources, self.calendar, version="other", policy="manual.1", yard="yard")
        with self.assertRaisesRegex(ValueError, "no known opening"):
            missing.run((rows[1],), self.after)

    def test_approved_reversal_after_exit_preserves_original(self):
        rows = self.example(Account.COGS)
        service = rows[1]
        approval = self.source("approval", self.after, system="stage4/approvals")
        source = self.source("correction", self.when, self.after, parents=(service.source_id, approval))
        reverse = replace(service, key="reversal", source_id=source, cents=-180, approval_id="approval",
                          reverses=service.key, restate_at=self.when + TICK)
        booked = self.book.run((*rows, reverse), self.after)
        self.assertEqual(balance(booked, Account.COGS), 10_225)
        self.assertEqual(balance(booked, Account.WIP), 0)
        prior = next(row for row in booked if row.component == CONSUMED and row.accounting_month == "2023-12")
        reversed_row = next(row for row in booked if row.reverses_journal_id)
        self.assertEqual(reversed_row.reverses_journal_id, prior.journal_id)
        self.assertEqual((reversed_row.credit_account, reversed_row.amount_cents), (Account.COGS, 180))
        restated = Book(self.sources, self.calendar, version="restated", policy="manual.1", yard="yard",
                        restatement="approval").run((*rows, reverse), self.after)
        self.assertEqual(next(row.amount_cents for row in restated if row.principal_release), 10_200)
        self.assertEqual(balance(restated, Account.COGS), 10_225)

    def test_restatement_rechecks_the_current_approval(self):
        self.source("approval", self.when, system="stage4/approvals")
        book = Book(self.sources, self.calendar, version="restated", policy="manual.1", yard="yard",
                    restatement="approval")
        book.run((), self.when)
        book.restatement = "unapproved"
        with self.assertRaisesRegex(ValueError, "available controller approval"):
            book.run((), self.after)

    def test_invalid_source_approval_attempt_and_conflicting_retry(self):
        rows = self.example(Account.COGS)
        with self.assertRaisesRegex(ValueError, "conflicting journal retry"):
            self.book.run((rows[0], replace(rows[0], cents=10_001)), self.after)
        future = self.source("future", self.after)
        with self.assertRaisesRegex(ValueError, "future source"):
            self.source("early", self.when, parents=(future,))
        with self.assertRaisesRegex(ValueError, "source-linked approval"):
            self.book.run((rows[0], replace(rows[-1], approval_id="unapproved")), self.after)

    def test_accounting_month_boundary_and_hash_locked_output(self):
        at_lock = self.calendar[0].locked_at
        self.assertEqual(accounting_month(self.when, at_lock, self.calendar), "2023-12")
        self.assertEqual(accounting_month(self.when, at_lock + TICK, self.calendar), "2024-01")
        with tempfile.TemporaryDirectory() as output:
            marker = Path(output) / "already-published"
            marker.write_text("untouched")
            with self.assertRaises(FileExistsError):
                build(output)
            self.assertEqual(marker.read_text(), "untouched")

    def test_recovery_partial_disposition_carries_remaining_cents(self):
        lot = RecoveryLot("refusal", "delivery-1", "bunk", "settlement", "pen", self.when, 500, 250, 16, 1)
        used = Disposition("reuse", "refusal", "source", "approval", self.exit, 200, "delivery-2")
        action = dispose(lot, used)
        self.assertEqual((action.cents, action.debit, action.credit), (7, Account.DISTRIBUTION, Account.RECOVERY))
        discarded = replace(used, document_id="discard", g_af=300, next_delivery_id=None)
        action = dispose(lot, discarded, prior_g_af=200, prior_cents=7)
        self.assertEqual((action.cents, action.debit), (10, Account.OTHER_VARIANCE))
        with self.assertRaisesRegex(ValueError, "invalid recoverable"):
            dispose(lot, discarded, prior_g_af=201, prior_cents=7)

    def test_exact_tolerance_and_signed_rounding(self):
        self.assertTrue(qualifies(11, 1_000, 110))
        self.assertFalse(qualifies(12, 1_000, 110))
        self.assertTrue(qualifies(6, 1_000, 60))
        self.assertFalse(qualifies(7, 1_000, 60))
        self.assertEqual(apportioned(-17, {"first": 2, "second": 3}), {"first": -7, "second": -10})

    def test_live_quote_eligibility(self):
        cutoff = local("2024-01-01 00:00")
        observed = local("2023-12-31 12:00")
        good = Quote("eligible", "AB", "steer", "CAD_cents_per_kg_live", observed, observed, 350)
        collection = (good, replace(good, quote_id="wrong-region", region="ON"),
                      replace(good, quote_id="wrong-class", category="heifer"),
                      replace(good, quote_id="carcass-price", unit="CAD_cents_per_kg_carcass"),
                      replace(good, quote_id="future", available_at=cutoff + TICK),
                      replace(good, quote_id="stale", observed_at=local("2023-12-01 00:00")))
        kwargs = {"cutoff": cutoff, "category": "steer", "region": "AB", "maximum_age_days": 14}
        self.assertEqual(quote_for(collection, **kwargs), good)
        self.assertIsNone(quote_for(collection[1:], **kwargs))


class IntegratedExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ops = integrated_fixture()
        cls.fixture = Fixture(cls.ops, settings(), "selected")
        cls.journals = journal_sets(cls.fixture)
        cls.closes = close_series(cls.fixture, cls.journals)
        cls.restated = close_series(cls.fixture, journal_sets(cls.fixture, corrected=True), originals=cls.closes)
        cls.invoices = tuple(invoice_routes(cls.fixture, cls.journals))

    def test_archived_input_tables_verified(self):
        self.assertEqual(verify_source(self.ops)["run_id"], "SYN-STAGE35-RUN-7068353c4e7979888dd59b07")

    def test_opening_and_purchase_source_independent(self):
        first = self.closes[0][1]
        cattle = {row.animal_id: row for row in first}
        self.assertEqual((cattle["SYN-A01"].opening_cents, cattle["SYN-A02"].opening_cents), (100000, 110000))
        self.assertEqual(tuple(cattle[f"SYN-A0{i}"].acquisition_cents for i in (3, 4, 5)),
                         (120000, 125000, 130000))
        self.assertEqual([row.veterinary_cents for row in first if row.animal_id == "SYN-A02"], [4500])
        self.assertEqual(balance(self.journals, Account.VET), -29000)

    def test_hand_fifo_refusal_recovery_normal_absorption_and_abnormal(self):
        delivery = "SYN-DELIVERY-202312311500-PEN-A"
        mix_id = self.fixture.feed.deliveries[delivery].mix_id
        fifo = sorted((row.g_af, row.cents) for row in self.fixture.warehouse
                      if any(item.mix_id == mix_id and item.layer_entry_id == row.entry_id
                             for item in self.ops.mix_inputs))
        self.assertEqual(fifo, [(-6000, -180), (-2000, -80)])
        ticket = next(row for row in self.fixture.active_feed if row.delivery_id == delivery)
        self.assertEqual((ticket.consumption_cents, ticket.consumed_g_af, ticket.consumed_g_dm), (195, 6000, 3000))
        # 65 cents × 500/2000, 400/2000 and 1100/2000. The last cent goes to excess.
        self.assertEqual((ticket.refusal_cents, ticket.recoverable_cents, ticket.normal_refusal_cents,
                          ticket.abnormal_cents), (65, 16, 13, 36))
        self.assertEqual((ticket.recoverable_g_af, ticket.recoverable_g_dm), (500, 250))
        hospital = next(row for row in self.fixture.active_feed
                        if row.delivery_id == "SYN-DELIVERY-202312312200-HOSPITAL")
        self.assertEqual((hospital.normal_mix_cents, hospital.normal_distribution_cents,
                          hospital.normal_refusal_cents, hospital.abnormal_cents), (2, 1, 9, 6))
        self.assertEqual(hospital.consumption_cents + 2 + 1 + 9 + 6, 190)

    def test_unclassified_observed_refusal_is_held(self):
        row = next(row for row in self.ops.active_settlements
                   if row.row.delivery_id == "SYN-DELIVERY-202312311500-PEN-A")
        policy = LossPolicy("missing.1", {"default": 0}, 0, 500, "unclassified",
                            {row.row.bunk_ticket_id: 500})
        self.assertEqual(policy.refusal_parts(row, self.fixture.feed.deliveries[row.row.delivery_id]),
                         {"refusal_recovery": 500, "refusal_normal": 0, "refusal_excess": 0,
                          "refusal_no_access": 0, "refusal_pending": 1500})

    def test_pending_refusal_posts_to_dated_exception(self):
        config = settings()
        config["loss_policies"]["selected"]["refusal_evidence"] = "unclassified"
        fixture = Fixture(self.ops, config, "selected")
        journal = journal_sets(fixture)
        december = close_month(fixture, fixture.calendar[0], journal)
        example = next(row for row in december[5] if row.pool_id == "SYN-DELIVERY-202312311500-PEN-A")
        self.assertEqual((example.open_cents, example.account, example.month), (49, Account.PENDING, "2023-12"))
        self.assertEqual(example.reason, "Refusal classification evidence missing")

    def test_observed_and_inferred_refusals_are_distinct_without_consumption(self):
        example = next(row for row in self.ops.active_settlements
                       if row.row.delivery_id == "SYN-DELIVERY-202401061500-HOSPITAL")
        parts = self.fixture.feed.parts[example.row.settlement_id]
        self.assertIn("refusal_no_access", {component for component, _, _ in parts})
        self.assertIn("refusal_normal_without_consumption", {component for component, _, _ in parts})
        categories = [component for component, _, _ in parts]
        self.assertEqual(len(categories), len(set(categories)))

    def test_yardage_same_day_and_transfer(self):
        cattle = livestock()
        tariffs = settings()["yardage_tariffs"]
        day = yardage_day(date(2024, 1, 1), cattle, tariffs)
        self.assertEqual((len(day), sum(row.cents for row in day)), (7, 840))
        self.assertEqual([row.animal_id for row in day].count("SYN-A08"), 1)
        same_day = yardage_day(date(2024, 3, 10), cattle, tariffs)
        self.assertEqual([row.cents for row in same_day if row.animal_id in {"SYN-A10", "SYN-A12"}], [130, 130])
        self.assertEqual(len(self.fixture.yardage), 338)

    def test_death_before_and_during_feeding_late_ticket(self):
        january = [row for row in self.fixture.active_feed if row.service_at == local("2024-01-01 17:00")]
        self.assertTrue(january)
        for selected in self.ops.active_settlements:
            if selected.row.delivery_id in {row.delivery_id for row in january}:
                self.assertNotIn("SYN-A08", {alloc.animal_id for alloc in selected.allocations})
        a01_end = local("2024-01-31 16:00")
        a01_last = [row for row in self.journals if row.animal_id == "SYN-A01"
                    and row.component == CONSUMED and row.effective_at == a01_end]
        self.assertEqual(len(a01_last), 1)
        self.assertEqual(a01_last[0].debit_account, Account.MORTALITY)
        self.assertGreater(a01_last[0].available_at, a01_end)

    def test_partial_sale_proceeds_packer_credit_and_exit_zero(self):
        releases = [row for row in self.journals if row.document_id == "SYN-SALE-JAN" and row.principal_release]
        self.assertEqual({row.animal_id for row in releases}, {"SYN-A05", "SYN-A06"})
        january = self.closes[1]
        self.assertEqual(next(row.closing_head for row in january[2] if row.scope_id == "SYN-LOT-2"), 1)
        self.assertEqual((january[6].provisional_revenue_cents, january[6].packer_adjustments_cents,
                          january[6].net_sales_cents), (365000, -250, 364750))
        self.assertEqual(balance(self.journals, Account.RECEIVABLE), 935750)
        self.assertEqual(len([row for row in self.journals if row.principal_release]), 7)
        self.assertTrue(all(not row.closing_cents for row in self.closes[-1][1] if row.status != "active"))

    def test_supplier_invoice_economic_destinations_and_stock_adjustment(self):
        from collections import Counter
        by_account = Counter()
        for row in invoice_impact(self.invoices, self.journals):
            by_account[row.horizon_account] += row.net_cents
        self.assertEqual(dict(by_account), {Account.WAREHOUSE: 13, Account.SPOILAGE: 2,
                                           Account.WIP: 2, Account.COGS: 2, Account.MORTALITY: 4,
                                           Account.RECOVERY: 1, Account.ABNORMAL: 1})
        self.assertEqual(balance(self.journals, Account.STOCK_COUNT), 6)
        self.assertEqual(balance(self.journals, Account.SPOILAGE), 22)
        lot, = recoverable(self.fixture, self.invoices)
        self.assertEqual(lot.provisional_cents + lot.invoice_cents, 17)
        self.assertEqual(balance(self.journals, Account.WAREHOUSE), 145441)

    def test_late_receipt_and_backdated_approved_restatement(self):
        full, early, corrected = warehouse_vintages(self.fixture)
        self.assertEqual(corrected.revises_snapshot_id, early.snapshot_id)
        self.assertEqual((corrected.g_af - early.g_af, corrected.cents - early.cents), (6000000, 147000))
        self.assertEqual(full.cents, 145441)
        dec, january, february, march = self.closes
        expected = (466034, 429617, 771784, 813701)
        self.assertEqual(tuple(row[6].closing_wip_cents for row in self.closes), expected)
        self.assertEqual(tuple(row[6].closing_wip_cents for row in self.restated),
                         (466168, 429381, 771575, 813701))
        self.assertEqual(self.restated[0][0].replaces_close_id, dec[0].close_id)
        before = close_month(self.fixture, self.fixture.calendar[0],
                             journal_sets(self.fixture, cutoff=dec[0].locked_at))
        self.assertEqual(canonical(before), canonical(dec))
        original = {row.animal_id: row.closing_location_id for row in dec[1]}
        revised = {row.animal_id: row.closing_location_id for row in self.restated[0][1]}
        self.assertEqual((original["SYN-A03"], revised["SYN-A03"]), ("SYN-PEN-A", "SYN-PEN-B"))
        self.assertEqual((january[6].clearing_cents, february[6].clearing_cents, march[6].clearing_cents), (0, 0, 0))

    def test_policy_sensitivity_with_unchanged_physical_intake_and_total_cost(self):
        other = Fixture(self.ops, settings(), "consumption_only")
        other_journal = journal_sets(other)
        other_close = close_series(other, other_journal)
        horizon = tuple(feed_bridge(self.fixture))[-1]
        comparison = tuple(feed_bridge(other))[-1]
        self.assertEqual((horizon.original_consumed_g_af, horizon.original_consumed_g_dm),
                         (4882099, 2924400))
        self.assertEqual((comparison.original_consumed_g_af, comparison.original_consumed_g_dm),
                         (4882099, 2924400))
        self.assertEqual((horizon.gross_issue_cents, horizon.wip_and_released_feed_cents,
                          horizon.absorbed_normal_cents, horizon.abnormal_process_cents),
                         (161646, 156515, 10275, 5115))
        main = tuple(sensitivity(self.fixture, self.journals, self.closes))[-1]
        ref = tuple(sensitivity(other, other_journal, other_close))[-1]
        self.assertEqual(main.modeled_yard_contribution_cents - ref.modeled_yard_contribution_cents, 5222)
        self.assertEqual(main.cumulative_accounted_cost_cents, 1867764)
        self.assertEqual(ref.cumulative_accounted_cost_cents, 1867764)

    def test_market_view_has_no_fictional_coverage(self):
        _, market = valuation(self.fixture)
        self.assertEqual(sum(row.month == "2023-12" and row.estimated_value_cents is not None for row in market), 4)
        self.assertEqual(sum(row.month == "2024-02" and row.estimated_value_cents is not None for row in market), 0)
        self.assertTrue(all(row.weight_available_at <= row.knowledge_cutoff for row in market
                            if row.weight_available_at is not None))


if __name__ == "__main__":
    unittest.main()
