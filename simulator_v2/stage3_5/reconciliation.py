"""Reconcile dry matter at movement assays and at each reported inventory vintage."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..stage3.units import BPS, half_up
from ..stage3.warehouse import Kind


@dataclass(frozen=True)
class StockDMBridge:
    snapshot_id: str
    period_start: datetime
    period_end: datetime
    bin_id: str
    layer_id: str
    batch_id: str
    opening_assay_id: str | None
    closing_assay_id: str | None
    opening_g_dm: int
    receipts_g_dm: int
    transfers_g_dm: int
    issues_g_dm: int
    adjustments_g_dm: int
    spoilage_g_dm: int
    returns_g_dm: int
    assay_revaluation_g_dm: int
    rounding_g_dm: int
    closing_g_dm: int


def dm_bridges(fixture):
    masters = fixture.warehouse.masters
    for snapshot in fixture.warehouse_snapshots:
        periods = sorted({(row.period_start, row.period_end) for row in fixture.stock_bridges
                          if row.snapshot_id == snapshot.snapshot_id})
        groups = defaultdict(list)
        for entry in snapshot.entries:
            groups[entry.bin_id, entry.layer_id, entry.batch_id, entry.ingredient_id].append(entry)
        for (bin_id, layer_id, batch, ingredient_id), entries in sorted(groups.items()):
            for start, end in periods:
                if entries[0].effective_at >= end:
                    continue
                before = [row for row in entries if row.effective_at < start or row.kind == Kind.OPENING]
                movement = [row for row in entries if start <= row.effective_at < end and row.kind != Kind.OPENING]
                af = sum(row.g_af for row in before)
                open_basis, open_assay = _basis(masters, batch, ingredient_id,
                                                start - timedelta(microseconds=1), snapshot.knowledge_cutoff)
                close_basis, close_assay = _basis(masters, batch, ingredient_id,
                                                  end - timedelta(microseconds=1), snapshot.knowledge_cutoff)
                opening_dm = _dm(af, open_basis)
                basis, revalued, rounding = open_basis, 0, 0
                amounts = defaultdict(int)
                for row in movement:
                    expected = _dm(abs(row.g_af), row.dm_bps) * (-1 if row.g_af < 0 else 1)
                    if row.g_dm != expected:
                        raise ValueError(f"invalid ledger DM at {row.entry_id}")
                    if row.kind == Kind.INVOICE:
                        continue
                    revalued += _dm(af, row.dm_bps) - _dm(af, basis)
                    basis = row.dm_bps
                    rounding += _dm(af + row.g_af, basis) - _dm(af, basis) - row.g_dm
                    af += row.g_af
                    amounts[row.kind] += row.g_dm
                closing = _dm(af, close_basis)
                revalued += closing - _dm(af, basis)
                yield StockDMBridge(
                    snapshot.snapshot_id, start, end, bin_id, layer_id, batch, open_assay, close_assay,
                    opening_dm, amounts[Kind.RECEIPT], amounts["transfer_in"] + amounts["transfer_out"],
                    amounts[Kind.ISSUE], amounts[Kind.ADJUST], amounts[Kind.SPOILAGE], amounts[Kind.RETURN],
                    revalued, rounding, closing)


def _basis(masters, batch, ingredient_id, instant, knowledge_cutoff):
    assay, ingredient = masters.nutrition(batch, ingredient_id, instant, min(instant, knowledge_cutoff))
    return (assay.dm_bps, assay.record_id) if assay else (ingredient.standard_dm_bps, None)


def _dm(af, bps):
    return half_up(af * bps, BPS)


def stock_summary(fixture, dry_matter):
    closing = fixture.warehouse_snapshots[0]
    first = min(row.period_start for row in dry_matter if row.snapshot_id == closing.snapshot_id)
    full = [row for row in dry_matter if row.snapshot_id == closing.snapshot_id
            and (row.period_start, row.period_end) == (first, closing.effective_before)]
    fields = ("opening_g_dm", "receipts_g_dm", "transfers_g_dm", "issues_g_dm", "adjustments_g_dm",
              "spoilage_g_dm", "returns_g_dm", "assay_revaluation_g_dm", "rounding_g_dm", "closing_g_dm")
    af = [row for row in fixture.stock_bridges if row.snapshot_id == closing.snapshot_id
          and (row.period_start, row.period_end) == (first, closing.effective_before)]
    af_fields = ("opening_g_af", "receipt_g_af", "transfer_in_g_af", "transfer_out_g_af", "issue_g_af",
                 "adjustment_g_af", "spoilage_g_af", "return_g_af", "closing_g_af", "opening_cents",
                 "receipt_cents", "issue_cents", "transfer_in_cents", "transfer_out_cents", "adjustment_cents",
                 "spoilage_cents", "return_cents", "invoice_cents", "closing_cents")
    return {**{key: sum(getattr(row, key) for row in full) for key in fields},
            **{key: sum(getattr(row, key) for row in af) for key in af_fields}}
