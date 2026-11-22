from dataclasses import replace
from unittest import TestCase

from simulator_v2.stage1.fixture import FINAL_CUTOFF, local
from simulator_v2.stage1.snapshots import RevisionApproval
from simulator_v2.stage3.fixture import load_scenario, same_day_meta, stage3_fixture, warehouse_inputs
from simulator_v2.stage3.warehouse import Kind, Transaction, Warehouse


class WarehouseTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = stage3_fixture()
        cls.closing, cls.original, cls.revised = cls.fixture.warehouse_snapshots

    def test_opening_partial_receipts_and_po_has_no_stock_effect(self):
        ledger = self.fixture.warehouse
        before_opening = ledger.snapshot(local("2023-12-30 00:00"), local("2023-12-30 00:00"))
        opening = ledger.snapshot(local("2023-12-31 06:00"), local("2023-12-31 06:00"))
        self.assertEqual(before_opening.balances, ())
        self.assertEqual(sum(row.g_af for row in opening.balances), 3_660_000)
        self.assertEqual(sum(row.cents for row in opening.balances), 142_400)
        self.assertEqual({row.received_g_af for row in opening.purchase_status}, {0})
        bulk = [row for row in self.closing.receipts if row.batch_id.startswith("SYN-SILAGE")]
        self.assertEqual([(row.g_af, row.commodity_cents, row.freight_cents, row.landed_cents)
                          for row in bulk], [(700_000, 16_800, 700, 17_500),
                                            (6_000_000, 144_000, 3_000, 147_000)])
        self.assertEqual({row.po_line_version_id for row in bulk}, {"SYN-SILAGE-PO-V1"})
        self.assertEqual({row.pricing_unit for row in bulk}, {"t"})

    def test_fifo_transfer_draw_and_independent_closing(self):
        ledger = self.fixture.warehouse
        close = ledger.snapshot(local("2024-01-01 00:00"), local("2024-01-01 00:00"))
        rows = [row for row in close.entries if row.transaction_id == "SYN-HAND-T1"]
        self.assertEqual([(row.g_af, row.g_dm, row.cents) for row in rows],
                         [(-4000, -2000, -120), (4000, 2000, 120)])
        self.assertEqual(rows[0].layer_id, rows[1].layer_id)
        self.assertEqual(rows[0].entry_id, rows[1].transfer_from_entry_id)
        issue = [row for row in close.entries if row.kind == Kind.ISSUE and row.bin_id == "SYN-DEMO-1"]
        self.assertEqual([(row.batch_id, row.g_af, row.cents) for row in issue],
                         [("SYN-HAND-OLD", -6000, -180), ("SYN-HAND-NEW", -2000, -80)])
        balances = {row.bin_id: (row.g_af, row.cents) for row in close.balances
                    if row.bin_id.startswith("SYN-DEMO-")}
        self.assertEqual(balances, {"SYN-DEMO-1": (3000, 120), "SYN-DEMO-2": (4000, 120)})

    def test_transferred_layer_keeps_precedence_over_younger_stock(self):
        masters, transactions = warehouse_inputs(load_scenario())
        transactions = [row for row in transactions if row.effective_at < local("2024-01-01 00:00")]
        newer = Transaction(*same_day_meta("SYN-NEWER-ADJUST", local("2023-12-31 06:30")),
                            Kind.ADJUST, 500, "SYN-DEMO-2", "SYN-HAND-SILAGE", 3000,
                            "SYN-HAND-NEW", amount_cents=120, reason="fixture added layer")
        issue = Transaction(*same_day_meta("SYN-TEST-ISSUE", local("2023-12-31 09:00")),
                            Kind.ISSUE, 501, "SYN-DEMO-2", "SYN-HAND-SILAGE", 5000)
        snapshot = Warehouse(masters, [*transactions, newer, issue]).snapshot(FINAL_CUTOFF, FINAL_CUTOFF)
        self.assertEqual([(row.batch_id, row.g_af, row.cents) for row in snapshot.entries
                          if row.transaction_id == issue.record_id],
                         [("SYN-HAND-OLD", -4000, -120), ("SYN-HAND-NEW", -1000, -40)])

    def test_stock_count_adjustment_spoilage_and_invoice_cost_delta(self):
        self.assertEqual([(row.book_g_af, row.counted_g_af, row.difference_g_af)
                          for row in self.closing.counts], [(4000, 3800, -200)])
        entries = {row.transaction_id: row for row in self.closing.entries
                   if row.transaction_id in {"SYN-HAND-A1", "SYN-HAND-S1", "SYN-HAND-I1"}}
        self.assertEqual([(entries[key].g_af, entries[key].cents) for key in
                          ("SYN-HAND-A1", "SYN-HAND-S1", "SYN-HAND-I1")],
                         [(-200, -6), (-500, -20), (0, 13)])
        self.assertEqual(sorted((row.basis_g_af, row.delta_cents, bool(row.historical_entry_id))
                                for row in self.closing.invoice_splits),
                         [(500, 2, True), (2000, 10, True), (2500, 13, False)])
        invoice = next(row for row in self.fixture.warehouse.transactions if row.kind == Kind.INVOICE)
        self.assertEqual(invoice.invoice_date.isoformat(), "2024-01-03")
        self.assertEqual(invoice.effective_at, local("2024-01-04 09:00"))

    def test_late_receipt_revises_balance_without_repricing_older_issues(self):
        self.assertNotIn("SYN-SILAGE-R2", self.original.transaction_ids)
        self.assertIn("SYN-SILAGE-R2", self.revised.transaction_ids)
        self.assertEqual(self.revised.revises_snapshot_id, self.original.snapshot_id)
        self.assertEqual(self.revised.approval_id, "SYN-APPROVE-LATE-RECEIPT")
        self.assertEqual(sum(row.g_af for row in self.revised.balances)
                         - sum(row.g_af for row in self.original.balances), 6_000_000)
        self.assertEqual(sum(row.cents for row in self.revised.balances)
                         - sum(row.cents for row in self.original.balances), 147_000)
        self.assertEqual(self.original.entries, tuple(row for row in self.revised.entries
                                                      if row.transaction_id != "SYN-SILAGE-R2"))
        with self.assertRaisesRegex(ValueError, "requires same-period"):
            self.fixture.warehouse.snapshot(self.original.effective_before, FINAL_CUTOFF, parent=self.original)
        approval = RevisionApproval("SYN-TEST-AUTH", "SYN-STOCK-CONTROLLER", self.original.knowledge_cutoff,
                                    "Synthetic cutoff test")
        with self.assertRaisesRegex(ValueError, "requires same-period"):
            self.fixture.warehouse.snapshot(self.original.effective_before, FINAL_CUTOFF,
                                            parent=self.original, approval=approval)

    def test_future_receipt_cannot_fund_negative_issue_and_retry_is_idempotent(self):
        ledger = self.fixture.warehouse
        issue = next(row for row in ledger.transactions if row.kind == Kind.ISSUE)
        overdraw = replace(issue, quantity_g_af=90_000_000)
        rows = [row for row in ledger.transactions if row.record_id != issue.record_id]
        with self.assertRaisesRegex(ValueError, "negative or unavailable FIFO"):
            Warehouse(ledger.masters, [*rows, overdraw]).snapshot(FINAL_CUTOFF, FINAL_CUTOFF)
        with self.assertRaisesRegex(ValueError, "conflicting transaction retry"):
            Warehouse(ledger.masters, [*rows, issue, overdraw])
        retry = Warehouse(ledger.masters, [*ledger.transactions, issue]).snapshot(FINAL_CUTOFF, FINAL_CUTOFF)
        self.assertEqual(retry, self.closing)
        self.assertEqual(ledger.snapshot(FINAL_CUTOFF, FINAL_CUTOFF), self.closing)

    def test_late_positive_correction_preserves_original_document(self):
        masters, transactions = warehouse_inputs(load_scenario())
        correction = Transaction("SYN-RECEIPT-FIX", "SYN-FREIGHT-DOC", local("2023-12-31 06:01"),
                                 local("2024-01-06 08:00"), local("2024-01-06 09:00"), Kind.ADJUST,
                                 500, "SYN-DEMO-1", "SYN-HAND-SILAGE", 100, "SYN-HAND-NEW",
                                 amount_cents=4, reference_id="SYN-HAND-R1", reason="ticket physical correction")
        ledger = Warehouse(masters, [*transactions, correction])
        report_end = local("2024-01-01 00:00")
        old = ledger.snapshot(report_end, report_end)
        new = ledger.snapshot(report_end, local("2024-01-06 09:00"))
        self.assertEqual(old.receipts, new.receipts)
        self.assertEqual([(row.g_af, row.cents) for row in new.entries if row.transaction_id == correction.record_id],
                         [(100, 4)])
        self.assertNotIn(correction.record_id, old.transaction_ids)
