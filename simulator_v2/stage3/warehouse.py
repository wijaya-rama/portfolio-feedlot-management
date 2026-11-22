"""As-of warehouse projection with provisional FIFO and landed-cost lineage."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise

from ..stage1.model import business_date, is_utc
from ..stage1.provenance import stable_id
from ..stage1.snapshots import RevisionApproval
from .units import BPS, GRAMS_PER_UNIT, half_up, split, whole

FIFO_VERSION = "fifo-by-ingredient-bin.1"


@dataclass(frozen=True)
class Document:
    record_id: str
    document_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime

    def __post_init__(self):
        if (not self.record_id.startswith("SYN-") or not self.document_id.startswith("SYN-")
                or not all(map(is_utc, (self.effective_at, self.posted_at, self.available_at)))
                or self.posted_at > self.available_at):
            raise ValueError(f"invalid document metadata: {self.record_id}")


@dataclass(frozen=True)
class Ingredient(Document):
    ingredient_id: str
    name: str
    standard_dm_bps: int
    energy_kj_per_kg_dm: int
    cp_bps_dm: int


@dataclass(frozen=True)
class Supplier(Document):
    supplier_id: str
    name: str


@dataclass(frozen=True)
class WarehouseLocation(Document):
    warehouse_id: str
    name: str


@dataclass(frozen=True)
class Bin(Document):
    bin_id: str
    warehouse_id: str
    capacity_g_af: int


@dataclass(frozen=True)
class Batch(Document):
    batch_id: str
    ingredient_id: str
    supplier_id: str
    supplier_batch_id: str


@dataclass(frozen=True)
class Assay(Document):
    batch_id: str
    dm_bps: int


@dataclass(frozen=True)
class Price(Document):
    ingredient_id: str
    supplier_id: str
    cents_per_unit: int
    unit: str
    currency: str = "CAD"


@dataclass(frozen=True)
class PurchaseOrder(Document):
    po_line_id: str
    supplier_id: str
    ingredient_id: str
    price_id: str
    ordered_g_af: int
    status: str = "open"


@dataclass(frozen=True)
class Equipment(Document):
    equipment_id: str
    kind: str
    capacity_g_af: int


class Kind(StrEnum):
    OPENING = "opening"
    RECEIPT = "receipt"
    TRANSFER = "transfer"
    ISSUE = "issue"
    COUNT = "count"
    ADJUST = "adjustment"
    SPOILAGE = "spoilage"
    RETURN = "supplier_return"
    INVOICE = "invoice_delta"


@dataclass(frozen=True)
class Transaction(Document):
    kind: Kind
    sequence: int
    bin_id: str
    ingredient_id: str
    quantity_g_af: int = 0
    batch_id: str | None = None
    target_bin_id: str | None = None
    po_line_id: str | None = None
    amount_cents: int | None = None
    freight_cents: int = 0
    reference_id: str | None = None
    reason: str | None = None
    invoice_date: date | None = None


@dataclass(frozen=True)
class ReceiptLine:
    receipt_id: str
    document_id: str
    po_line_version_id: str
    price_version_id: str
    supplier_id: str
    supplier_batch_id: str
    batch_id: str
    ingredient_id: str
    bin_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    pricing_unit: str
    cents_per_unit: int
    g_af: int
    commodity_cents: int
    freight_cents: int
    landed_cents: int


@dataclass(frozen=True)
class PurchaseStatus:
    po_line_id: str
    po_line_version_id: str
    ordered_g_af: int
    received_g_af: int
    remaining_g_af: int


@dataclass(frozen=True)
class Layer:
    layer_id: str
    origin_transaction_id: str
    batch_id: str
    ingredient_id: str
    acquired_at: datetime
    sequence: int
    origin_g_af: int
    origin_cents: int


@dataclass(frozen=True)
class Entry:
    entry_id: str
    transaction_id: str
    kind: str
    bin_id: str
    layer_id: str
    batch_id: str
    ingredient_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    g_af: int
    cents: int
    g_dm: int
    dm_bps: int
    assay_id: str | None
    ingredient_version_id: str
    transfer_from_entry_id: str | None = None


@dataclass(frozen=True)
class StockCount:
    count_id: str
    batch_id: str
    bin_id: str
    book_g_af: int
    counted_g_af: int
    difference_g_af: int


@dataclass(frozen=True)
class InvoiceSplit:
    split_id: str
    invoice_transaction_id: str
    layer_id: str
    bin_id: str
    basis_g_af: int
    delta_cents: int
    historical_entry_id: str | None
    inventory_entry_id: str | None


@dataclass(frozen=True)
class Balance:
    bin_id: str
    layer_id: str
    g_af: int
    cents: int


@dataclass(frozen=True)
class StockBridge:
    snapshot_id: str
    period_start: datetime
    period_end: datetime
    ingredient_id: str
    batch_id: str
    bin_id: str
    opening_g_af: int
    opening_cents: int
    receipt_g_af: int
    receipt_cents: int
    transfer_in_g_af: int
    transfer_in_cents: int
    issue_g_af: int
    issue_cents: int
    transfer_out_g_af: int
    transfer_out_cents: int
    adjustment_g_af: int
    adjustment_cents: int
    spoilage_g_af: int
    spoilage_cents: int
    return_g_af: int
    return_cents: int
    invoice_cents: int
    closing_g_af: int
    closing_cents: int


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    effective_before: datetime
    knowledge_cutoff: datetime
    revises_snapshot_id: str | None
    approval_id: str | None
    transaction_ids: tuple[str, ...]
    layers: tuple[Layer, ...]
    entries: tuple[Entry, ...]
    balances: tuple[Balance, ...]
    counts: tuple[StockCount, ...]
    receipts: tuple[ReceiptLine, ...]
    purchase_status: tuple[PurchaseStatus, ...]
    invoice_splits: tuple[InvoiceSplit, ...]


def _version(rows, attr, key, effective, knowledge):
    return max((row for row in rows if getattr(row, attr) == key
                and row.effective_at <= effective and row.available_at <= knowledge),
               key=lambda row: (row.effective_at, row.available_at, row.record_id), default=None)


class Masters:
    def __init__(self, *, ingredients, suppliers, warehouses, bins, batches, assays, prices, orders, equipment):
        self.ingredients, self.suppliers = tuple(ingredients), tuple(suppliers)
        self.warehouses, self.bins = tuple(warehouses), tuple(bins)
        self.batches, self.assays = tuple(batches), tuple(assays)
        self.prices, self.orders, self.equipment = tuple(prices), tuple(orders), tuple(equipment)
        self.records = {row.record_id: row for rows in vars(self).values() for row in rows}
        if len(self.records) != sum(len(rows) for key, rows in vars(self).items() if key != "records"):
            raise ValueError("duplicate warehouse master record ID")
        for row in self.ingredients:
            self._basis(row.standard_dm_bps)
            whole(row.energy_kj_per_kg_dm, "ingredient energy", minimum=1)
            self._basis(row.cp_bps_dm)
        for row in self.bins:
            self.get("warehouses", "warehouse_id", row.warehouse_id, row)
        for row in self.bins + self.equipment:
            whole(row.capacity_g_af, "storage/equipment capacity", minimum=1)
        if any(row.kind not in {"mixer", "truck"} for row in self.equipment):
            raise ValueError("invalid feed equipment kind")
        for row in self.batches:
            self.get("ingredients", "ingredient_id", row.ingredient_id, row)
            self.get("suppliers", "supplier_id", row.supplier_id, row)
        for row in self.assays:
            self._basis(row.dm_bps)
            self.get("batches", "batch_id", row.batch_id, row)
        for row in self.prices:
            if row.currency != "CAD" or row.unit not in GRAMS_PER_UNIT:
                raise ValueError("prices require CAD per supported as-fed unit")
            whole(row.cents_per_unit, "unit price")
            self.get("ingredients", "ingredient_id", row.ingredient_id, row)
            self.get("suppliers", "supplier_id", row.supplier_id, row)
        order_versions = defaultdict(list)
        for row in self.orders:
            price = self.reference(row.price_id, Price, row.effective_at, row.available_at)
            if (row.supplier_id, row.ingredient_id) != (price.supplier_id, price.ingredient_id):
                raise ValueError("purchase order price mismatch")
            whole(row.ordered_g_af, "ordered quantity", minimum=1)
            if row.status not in {"open", "closed"}:
                raise ValueError("invalid purchase order status")
            order_versions[row.po_line_id].append(row)
        for versions in order_versions.values():
            if len({(row.supplier_id, row.ingredient_id) for row in versions}) != 1:
                raise ValueError("purchase order versions must preserve supplier and ingredient")
        batch_keys = defaultdict(set)
        for row in self.batches:
            batch_keys[row.batch_id].add((row.ingredient_id, row.supplier_id, row.supplier_batch_id))
        if any(len(keys) != 1 for keys in batch_keys.values()):
            raise ValueError("batch versions must preserve physical lot identity")

    @staticmethod
    def _basis(value):
        if whole(value, "basis points", minimum=1) > BPS:
            raise ValueError("basis points exceed 100%")

    def get(self, table, attr, key, document):
        row = _version(getattr(self, table), attr, key, document.effective_at, document.available_at)
        if row is None:
            raise ValueError(f"unavailable {table} reference: {key} on {document.record_id}")
        return row

    def reference(self, key, record_type, effective, knowledge):
        row = self.records.get(key)
        if not isinstance(row, record_type) or row.effective_at > effective or row.available_at > knowledge:
            raise ValueError(f"unavailable master version: {key}")
        return row

    def nutrition(self, batch_id, ingredient_id, effective, knowledge):
        assay = _version(self.assays, "batch_id", batch_id, effective, knowledge)
        ingredient = _version(self.ingredients, "ingredient_id", ingredient_id, effective, knowledge)
        if ingredient is None:
            raise ValueError(f"unavailable nutrient specification: {ingredient_id}")
        return assay, ingredient


class Warehouse:
    def __init__(self, masters, transactions):
        self.masters = masters
        unique = {}
        for row in transactions:
            if unique.setdefault(row.record_id, row) != row:
                raise ValueError(f"conflicting transaction retry: {row.record_id}")
            whole(row.sequence, "warehouse sequence")
            if type(row.quantity_g_af) is not int:
                raise ValueError("as-fed quantity must be an integer")
            whole(row.freight_cents, "freight")
            if row.amount_cents is not None and type(row.amount_cents) is not int:
                raise ValueError("transaction value must be an integer")
            # Backdated credits can revise stock without re-selecting historical FIFO issues.
            late_credit = row.kind == Kind.RECEIPT or (row.kind == Kind.ADJUST and row.quantity_g_af > 0)
            if row.kind not in {Kind.OPENING, Kind.COUNT} and not late_credit:
                if row.effective_at != row.available_at:
                    raise ValueError(f"debit or valuation must be effective when available: {row.record_id}")
            if row.posted_at < row.effective_at:
                raise ValueError(f"transaction posted before physical occurrence: {row.record_id}")
        self.transactions = tuple(sorted(unique.values(), key=lambda row: (
            row.effective_at, row.sequence, row.record_id)))

    def snapshot(self, effective_before, knowledge_cutoff, *, parent=None, approval=None):
        if not is_utc(effective_before) or not is_utc(knowledge_cutoff):
            raise ValueError("warehouse cutoffs require UTC")
        if parent is not None:
            if (parent.effective_before != effective_before or parent.knowledge_cutoff >= knowledge_cutoff
                    or not isinstance(approval, RevisionApproval) or not approval.synthetic
                    or not approval.approval_id.startswith("SYN-") or not approval.approved_by.startswith("SYN-")
                    or not approval.reason.strip() or not is_utc(approval.approved_at)
                    or approval.approved_at < knowledge_cutoff):
                raise ValueError("warehouse revision requires same-period parent, later cutoff and approval")
        elif approval is not None:
            raise ValueError("warehouse revision approval requires a parent")
        rows = tuple(row for row in self.transactions if row.effective_at < effective_before
                     and row.available_at <= knowledge_cutoff)
        state = _Projection(self.masters)
        for row in rows:
            state.apply(row)
        layers = tuple(state.layers.values())
        entries = tuple(state.entries)
        balances = tuple(Balance(*key, *balance) for key, balance in sorted(state.balances.items()) if balance[0])
        counts, invoice_splits = tuple(state.counts.values()), tuple(state.invoice_splits)
        receipts = tuple(state.receipts)
        order_status = []
        for key in sorted({row.po_line_id for row in self.masters.orders}):
            version = _version(self.masters.orders, "po_line_id", key,
                               effective_before - timedelta(microseconds=1), knowledge_cutoff)
            if version:
                received = state.received[key]
                if received > version.ordered_g_af:
                    raise ValueError(f"order revision below received quantity: {key}")
                order_status.append(PurchaseStatus(key, version.record_id, version.ordered_g_af,
                                                   received, version.ordered_g_af - received))
        parent_id = parent.snapshot_id if parent else None
        approval_id = approval.approval_id if approval else None
        snapshot_id = stable_id("WAREHOUSE", [FIFO_VERSION, effective_before, knowledge_cutoff,
                                             parent_id, approval, rows, layers, entries, counts, receipts, order_status, invoice_splits])
        return Snapshot(snapshot_id, effective_before, knowledge_cutoff, parent_id, approval_id,
                        tuple(row.record_id for row in rows), layers, entries, balances, counts, receipts,
                        tuple(order_status), invoice_splits)


class _Projection:
    def __init__(self, masters):
        self.masters = masters
        self.layers = {}
        self.origins = {}
        self.availability = {}
        self.balances = {}
        self.bin_layers = defaultdict(set)
        self.bin_quantities = defaultdict(int)
        self.entries = []
        self.sinks = defaultdict(list)
        self.sink_deltas = defaultdict(int)
        self.invoice_splits = []
        self.counts = {}
        self.adjusted_counts = set()
        self.received = defaultdict(int)
        self.receipts = []

    def apply(self, row):
        storage_bin = self.masters.get("bins", "bin_id", row.bin_id, row)
        self.masters.get("warehouses", "warehouse_id", storage_bin.warehouse_id, row)
        self.masters.get("ingredients", "ingredient_id", row.ingredient_id, row)
        if row.batch_id:
            batch = self.masters.get("batches", "batch_id", row.batch_id, row)
            if batch.ingredient_id != row.ingredient_id:
                raise ValueError(f"ingredient/batch mismatch: {row.record_id}")
        kind = row.kind
        supported = set(Kind)
        if (kind not in supported
                or (row.target_bin_id is not None) != (kind == Kind.TRANSFER)
                or (row.po_line_id is not None) != (kind == Kind.RECEIPT)
                or (row.freight_cents and kind != Kind.RECEIPT)
                or (row.invoice_date is not None) != (kind == Kind.INVOICE)
                or (row.amount_cents is not None and kind not in {Kind.OPENING, Kind.ADJUST, Kind.INVOICE})
                or (row.reference_id is not None and kind not in {Kind.ADJUST, Kind.INVOICE})
                or (kind in {Kind.ADJUST, Kind.SPOILAGE, Kind.RETURN} and not (row.reason or "").strip())):
            raise ValueError(f"invalid warehouse transaction fields: {row.record_id}")
        if kind == Kind.COUNT:
            self._count(row)
        elif kind == Kind.INVOICE:
            self._invoice(row)
        else:
            if kind == Kind.ADJUST:
                self._check_adjustment(row)
            if kind in {Kind.OPENING, Kind.RECEIPT} or (kind == Kind.ADJUST and row.quantity_g_af > 0):
                self._credit(row)
            else:
                self._debit(row)

    def _count(self, row):
        if not row.batch_id:
            raise ValueError(f"stock count requires a batch: {row.record_id}")
        whole(row.quantity_g_af, "counted quantity")
        book = sum(self.balances[row.bin_id, layer_id][0] for layer_id in self.bin_layers[row.bin_id]
                   if self.layers[layer_id].batch_id == row.batch_id
                   and self.availability[layer_id] <= row.available_at)
        self.counts[row.record_id] = StockCount(row.record_id, row.batch_id, row.bin_id, book,
                                               row.quantity_g_af, row.quantity_g_af - book)

    def _check_adjustment(self, row):
        if not row.batch_id or not row.quantity_g_af:
            raise ValueError(f"adjustment requires a batch and nonzero quantity: {row.record_id}")
        if row.quantity_g_af < 0 and row.amount_cents is not None:
            raise ValueError("negative quantity adjustments must use FIFO cost")
        if row.reference_id:
            count = self.counts.get(row.reference_id)
            if count is not None:
                if (row.reference_id in self.adjusted_counts
                        or (count.bin_id, count.batch_id, count.difference_g_af)
                        != (row.bin_id, row.batch_id, row.quantity_g_af)):
                    raise ValueError(f"adjustment does not clear a unique count discrepancy: {row.record_id}")
                self.adjusted_counts.add(row.reference_id)
            else:
                receipt = next((item for item in self.receipts if item.receipt_id == row.reference_id), None)
                if (receipt is None or receipt.available_at > row.available_at
                        or (receipt.bin_id, receipt.batch_id) != (row.bin_id, row.batch_id)):
                    raise ValueError(f"adjustment lacks valid count or receipt lineage: {row.record_id}")

    def _credit(self, row):
        if not row.batch_id:
            raise ValueError(f"credit requires a batch: {row.record_id}")
        quantity = whole(row.quantity_g_af, "credit quantity", minimum=1)
        if row.kind == Kind.RECEIPT:
            order = self.masters.get("orders", "po_line_id", row.po_line_id, row)
            batch = self.masters.get("batches", "batch_id", row.batch_id, row)
            price = self.masters.reference(order.price_id, Price, row.effective_at, row.available_at)
            self.received[order.po_line_id] += quantity
            if (order.status != "open" or order.ingredient_id != row.ingredient_id
                    or order.supplier_id != batch.supplier_id
                    or self.received[order.po_line_id] > order.ordered_g_af):
                raise ValueError(f"receipt outside purchase order terms: {row.record_id}")
            commodity = half_up(quantity * price.cents_per_unit, GRAMS_PER_UNIT[price.unit])
            value = commodity + row.freight_cents
            self.receipts.append(ReceiptLine(
                row.record_id, row.document_id, order.record_id, price.record_id, order.supplier_id,
                batch.supplier_batch_id, row.batch_id, row.ingredient_id, row.bin_id, row.effective_at,
                row.posted_at, row.available_at, price.unit, price.cents_per_unit, quantity, commodity,
                row.freight_cents, value))
        else:
            value = whole(row.amount_cents, "opening or adjustment cost")
        layer_id = stable_id("LAYER", row.record_id)
        layer = Layer(layer_id, row.record_id, row.batch_id, row.ingredient_id, row.effective_at,
                      row.sequence, quantity, value)
        self.layers[layer_id] = layer
        self.origins[row.record_id] = layer
        self.availability[layer_id] = row.available_at
        self._entry(row, row.kind, row.bin_id, layer, quantity, value)

    def _debit(self, row):
        if row.kind == Kind.ADJUST:
            quantity = -row.quantity_g_af
        else:
            quantity = row.quantity_g_af
        whole(quantity, "debit quantity", minimum=1)
        if row.kind == Kind.TRANSFER:
            if row.bin_id == row.target_bin_id:
                raise ValueError("warehouse transfer must change bins")
            self.masters.get("bins", "bin_id", row.target_bin_id, row)
        candidates = sorted((self.layers[layer_id] for layer_id in self.bin_layers[row.bin_id]
                             if self.layers[layer_id].ingredient_id == row.ingredient_id
                             and (row.batch_id is None or self.layers[layer_id].batch_id == row.batch_id)
                             and self.availability[layer_id] <= row.available_at),
                            key=lambda layer: (layer.acquired_at, layer.sequence, layer.layer_id))
        if quantity > sum(self.balances[row.bin_id, layer.layer_id][0] for layer in candidates):
            raise ValueError(f"negative or unavailable FIFO stock: {row.record_id}")
        for layer in candidates:
            available, value = self.balances[row.bin_id, layer.layer_id]
            taken = min(available, quantity)
            if not taken:
                continue
            cost = value * taken // available  # the remaining piece retains fractional cents
            if row.kind == Kind.TRANSFER:
                source = self._entry(row, "transfer_out", row.bin_id, layer, -taken, -cost)
                self._entry(row, "transfer_in", row.target_bin_id, layer, taken, cost, source.entry_id)
            else:
                source = self._entry(row, row.kind, row.bin_id, layer, -taken, -cost)
                self.sinks[layer.layer_id].append(source)
            quantity -= taken
            if not quantity:
                break

    def _invoice(self, row):
        layer = self.origins.get(row.reference_id)
        if (layer is None or row.quantity_g_af or not row.amount_cents or not row.invoice_date
                or row.invoice_date > business_date(row.effective_at)
                or layer.batch_id != row.batch_id or layer.ingredient_id != row.ingredient_id
                or not any(item.receipt_id == row.reference_id and item.bin_id == row.bin_id
                           for item in self.receipts)
                or self.availability[layer.layer_id] > row.available_at):
            raise ValueError(f"invalid final invoice adjustment: {row.record_id}")
        current = {bin_id: balance[0] for (bin_id, layer_id), balance in self.balances.items()
                   if layer_id == layer.layer_id and balance[0]}
        prior = {entry.entry_id: entry for entry in self.sinks[layer.layer_id]}
        weights = {**current, **{key: -entry.g_af for key, entry in prior.items()}}
        if sum(weights.values()) != layer.origin_g_af:
            raise ValueError(f"invoice layer basis does not conserve quantity: {row.record_id}")
        for key, amount in split(abs(row.amount_cents), weights).items():
            delta = amount if row.amount_cents > 0 else -amount
            history = prior.get(key)
            bin_id = history.bin_id if history else key
            entry_id = None
            if history:
                self.sink_deltas[key] += delta
                if self.sink_deltas[key] < history.cents:
                    raise ValueError(f"invoice credit exceeds historical cost: {row.record_id}")
            elif delta:
                entry_id = self._entry(row, Kind.INVOICE, bin_id, layer, 0, delta).entry_id
            self.invoice_splits.append(InvoiceSplit(stable_id("INVOICE-SPLIT", [row.record_id, key]),
                                                    row.record_id, layer.layer_id, bin_id, weights[key],
                                                    delta, history.entry_id if history else None, entry_id))

    def _entry(self, row, kind, bin_id, layer, quantity, cents, from_id=None):
        key = bin_id, layer.layer_id
        on_hand, value = self.balances.get(key, (0, 0))
        on_hand += quantity
        value += cents
        capacity = self.masters.get("bins", "bin_id", bin_id, row).capacity_g_af
        self.bin_quantities[bin_id] += quantity
        if (on_hand < 0 or value < 0 or (not on_hand and value)
                or not 0 <= self.bin_quantities[bin_id] <= capacity):
            raise ValueError(f"invalid warehouse balance or storage capacity: {row.record_id}")
        self.balances[key] = (on_hand, value)
        self.bin_layers[bin_id].add(layer.layer_id)
        assay, ingredient = self.masters.nutrition(layer.batch_id, layer.ingredient_id,
                                                   row.effective_at, row.available_at)
        dm_bps = assay.dm_bps if assay else ingredient.standard_dm_bps
        dm = half_up(abs(quantity) * dm_bps, BPS)
        entry = Entry(stable_id("LAYER-ENTRY", [row.record_id, kind, bin_id, layer.layer_id]),
                      row.record_id, kind, bin_id, layer.layer_id, layer.batch_id, layer.ingredient_id,
                      row.effective_at, row.posted_at, row.available_at, quantity, cents,
                      dm if quantity >= 0 else -dm, dm_bps, assay.record_id if assay else None,
                      ingredient.record_id, from_id)
        self.entries.append(entry)
        return entry


def bridges(snapshot, boundaries):
    """Summarize warehouse legs per ingredient, batch, bin and half-open period."""
    bounds = tuple(boundaries)
    if (len(bounds) < 2 or any(not is_utc(point) for point in bounds)
            or any(first >= end for first, end in pairwise(bounds)) or bounds[-1] > snapshot.effective_before):
        raise ValueError("invalid warehouse bridge boundaries")
    groups = defaultdict(list)
    for row in snapshot.entries:
        if row.effective_at < bounds[-1]:
            groups[row.ingredient_id, row.batch_id, row.bin_id].append(row)
    for first, end in pairwise(bounds):
        for key, rows in sorted(groups.items()):
            amounts = defaultdict(lambda: [0, 0])
            running = [0, 0]
            for row in rows:
                if row.effective_at >= end:
                    break
                category = "opening" if row.effective_at < first or row.kind == Kind.OPENING else row.kind
                amounts[category][0] += row.g_af
                amounts[category][1] += row.cents
                running[0] += row.g_af
                running[1] += row.cents
            yield StockBridge(snapshot.snapshot_id, first, end, *key, *amounts["opening"],
                              *amounts[Kind.RECEIPT], *amounts["transfer_in"], *amounts[Kind.ISSUE],
                              *amounts["transfer_out"], *amounts[Kind.ADJUST], *amounts[Kind.SPOILAGE],
                              *amounts[Kind.RETURN], amounts[Kind.INVOICE][1], *running)
