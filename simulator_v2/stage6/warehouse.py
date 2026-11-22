"""Prospective purchasing and FIFO execution using the Stage 3 warehouse projection."""

from collections import defaultdict

from ..stage3.ration import Component, Formulas, Recipe
from ..stage3.units import BPS, half_up
from ..stage3.warehouse import (Assay, Batch, Bin, Equipment, Ingredient, Kind, Masters, Price,
                                PurchaseOrder, Supplier, Transaction, Warehouse, WarehouseLocation,
                                _Projection, _version)
from .config import at
from .livestock import DAY, ExceptionRow
from ..stage1.provenance import stable_id


class IndexedMasters(Masters):
    def __init__(self, **tables):
        super().__init__(**tables)
        self.index = {}
        for name, attribute in (("bins", "bin_id"), ("warehouses", "warehouse_id"),
                                ("ingredients", "ingredient_id"), ("suppliers", "supplier_id"),
                                ("batches", "batch_id"), ("orders", "po_line_id"), ("assays", "batch_id")):
            versions = defaultdict(list)
            for row in getattr(self, name):
                versions[getattr(row, attribute)].append(row)
            self.index[name] = versions
            setattr(self, name, list(getattr(self, name)))

    def add(self, table, key, row):
        if row.record_id in self.records:
            raise ValueError(f"duplicate warehouse master: {row.record_id}")
        self.index[table][key].append(row)
        self.records[row.record_id] = row
        getattr(self, table).append(row)

    def get(self, table, attr, key, document):
        if not hasattr(self, "index"):
            return super().get(table, attr, key, document)
        rows = self.index.get(table, {}).get(key, ())
        row = _version(rows, attr, key, document.effective_at, document.available_at)
        if row is None:
            raise ValueError(f"unavailable {table} reference: {key}")
        return row

    def nutrition(self, batch_id, ingredient_id, effective, knowledge):
        assay = _version(self.index["assays"][batch_id], "batch_id", batch_id, effective, knowledge)
        ingredient = _version(self.index["ingredients"][ingredient_id], "ingredient_id", ingredient_id,
                              effective, knowledge)
        if ingredient is None:
            raise ValueError(f"unavailable nutrient specification: {ingredient_id}")
        return assay, ingredient


class ActiveProjection(_Projection):
    def _entry(self, row, kind, bin_id, layer, quantity, cents, from_id=None):
        result = super()._entry(row, kind, bin_id, layer, quantity, cents, from_id)
        if self.balances[bin_id, layer.layer_id] == (0, 0):
            self.bin_layers[bin_id].remove(layer.layer_id)
            del self.balances[bin_id, layer.layer_id]
        return result


def doc(key, when):
    return key, key, when, when, when


class Supply:
    def __init__(self, config, first, design_head, draw, emit):
        self.policy = p = config["warehouse"]
        low, high = p["refusal_bps"]
        if (not 0 <= low <= high or high + p["max_bunk_loss_bps"] >= BPS
                or any(not 0 <= p[key] < BPS for key in (
                    "max_mix_loss_bps", "max_distribution_loss_bps", "max_bunk_loss_bps"))
                or p["opening_spoilage_g_af"] < 0):
            raise ValueError("loss and refusal bounds must leave a valid physical flow")
        self.first, self.draw, self.emit = first, draw, emit
        self.transactions, self.inbound = [], defaultdict(list)
        self.max_bin, self.order_reserved = defaultdict(int), defaultdict(int)
        opened = at(first - DAY, 12)
        warehouse = WarehouseLocation(*doc("SYN-FARM-WAREHOUSE-V1", opened), "SYN-FARM-WAREHOUSE", "Feed store")
        inbound = WarehouseLocation(*doc("SYN-INBOUND-WAREHOUSE-V1", opened), "SYN-INBOUND-WAREHOUSE", "Receiving dock")
        supplier = Supplier(*doc("SYN-FEED-SUPPLIER-V1", opened), "SYN-FEED-SUPPLIER", "Synthetic feed cooperative")
        self.supplier = supplier
        ingredients, bins, prices = [], [], []
        self.main, self.dock, self.prices = {}, {}, {}
        capacity = p["bin_grams_per_design_head"] * design_head
        self.opening = p["opening_grams_per_design_head"] * design_head
        self.target = p["ordered_grams_per_design_head"] * design_head
        if (not p["ingredients"] or not 0 <= self.opening <= capacity or not 1 <= self.target <= capacity
                or p["order_cycle_days"] < 1 or p["lead_days"] < 1 or p["split_receipt_delay_days"] < 1):
            raise ValueError("invalid warehouse supply or storage parameters")
        for row in p["ingredients"]:
            name = row["code"]
            key = f"SYN-ING-{name}"
            ingredient = Ingredient(*doc(f"{key}-V1", opened), key, name, row["dm_bps"],
                                    row["kj_per_kg_dm"], row["cp_bps"])
            price = Price(*doc(f"SYN-PRICE-{name}-V1", opened), key, supplier.supplier_id,
                          row["cents_per_tonne"], "t")
            main, dock = f"SYN-BIN-{name}", f"SYN-DOCK-{name}"
            bins.extend([Bin(*doc(f"{main}-V1", opened), main, warehouse.warehouse_id, capacity),
                         Bin(*doc(f"{dock}-V1", opened), dock, inbound.warehouse_id, capacity)])
            self.main[key], self.dock[key], self.prices[key] = main, dock, price
            ingredients.append(ingredient)
            prices.append(price)
        self.mixer = Equipment(*doc("SYN-MIXER-V1", opened), "SYN-MIXER", "mixer", p["equipment_g_af"])
        self.truck = Equipment(*doc("SYN-TRUCK-V1", opened), "SYN-TRUCK", "truck", p["equipment_g_af"])
        self.masters = IndexedMasters(ingredients=ingredients, suppliers=[supplier], warehouses=[warehouse, inbound],
                                      bins=bins, batches=[], assays=[], prices=prices, orders=[],
                                      equipment=[self.mixer, self.truck])
        self.state = ActiveProjection(self.masters)
        recipes, components = [], []
        for phase in ("receiving", "adaptation", "finishing", "hospital"):
            proportions = p["recipes"][phase]
            if len(proportions) != len(ingredients):
                raise ValueError(f"recipe ingredients and proportions differ: {phase}")
            stage_eligibility = "adaptation,finishing" if phase == "adaptation" else phase
            identifier = f"SYN-RATION-{phase.upper()}"
            recipe = Recipe(*doc(f"{identifier}-V1", opened), identifier, stage_eligibility,
                            half_up(sum(i.energy_kj_per_kg_dm * share for i, share in zip(ingredients, proportions)), BPS),
                            half_up(sum(i.cp_bps_dm * share for i, share in zip(ingredients, proportions)), BPS))
            for item, share in zip(ingredients, proportions):
                if share:
                    components.append(Component(f"{recipe.record_id}-{item.name}", recipe.record_id,
                                                item.ingredient_id, share, item.standard_dm_bps))
            recipes.append(recipe)
        self.formulas = Formulas(self.masters, recipes, components)
        self.emit("ration_versions", recipes)
        self.emit("ration_ingredients", components)
        for name in ("ingredients", "suppliers", "warehouses", "bins", "prices", "equipment"):
            self.emit(f"warehouse_{name}", getattr(self.masters, name))
        if self.opening:
            for key, price in self.prices.items():
                batch = self.batch(key, f"{key}-OPENING", opened)
                self.apply(Kind.OPENING, opened, self.main[key], key, self.opening, batch_id=batch,
                           amount_cents=half_up(self.opening * price.cents_per_unit, 1000000))
            spoil = min(self.opening, p["opening_spoilage_g_af"])
            if spoil:
                key = ingredients[0].ingredient_id
                self.apply(Kind.SPOILAGE, at(first, 5), self.main[key], key, spoil,
                           reason="synthetic_storage_damage_inspection")

    def batch(self, key, batch, when):
        master = Batch(*doc(f"{batch}-V1", when), batch, key, self.supplier.supplier_id, f"{batch}-VENDOR")
        std = self.masters.index["ingredients"][key][0].standard_dm_bps
        low, high = max(1, std - 175), min(BPS, std + 175)
        assay = Assay(*doc(f"{batch}-ASSAY1", when), batch, self.draw.integer("warehouse/assay", low, high, batch))
        self.masters.add("batches", batch, master)
        self.masters.add("assays", batch, assay)
        self.emit("warehouse_batches", [master], when)
        self.emit("warehouse_assays", [assay], when)
        return batch

    def apply(self, kind, when, bin_id, key, amount, **kw):
        seq = len(self.transactions) + 1
        identifier = f"SYN-WH-{seq:09d}"
        row = Transaction(*doc(identifier, when), kind, seq, bin_id, key, amount, **kw)
        before = len(self.state.entries)
        receipts_before = len(self.state.receipts)
        self.state.apply(row)
        self.transactions.append(row)
        self.emit("warehouse_transactions", [row], when)
        for bin_key in (row.bin_id, row.target_bin_id):
            if bin_key:
                self.max_bin[bin_key] = max(self.max_bin[bin_key], self.state.bin_quantities[bin_key])
        entries = self.state.entries[before:]
        self.emit("warehouse_entries", entries, when)
        self.emit("warehouse_receipts", self.state.receipts[receipts_before:], when)
        return row, entries

    def day(self, day):
        when = at(day, 5, 30)
        for key, order, amount, part in self.inbound.pop(day, ()):
            batch = self.batch(key, f"{order}-B{part}", when)
            self.apply(Kind.RECEIPT, when, self.dock[key], key, amount, batch_id=batch,
                       po_line_id=order, freight_cents=half_up(amount * 1500, 1000000))
            self.apply(Kind.TRANSFER, when, self.dock[key], key, amount, batch_id=batch,
                       target_bin_id=self.main[key])
            self.order_reserved[key] -= amount
        if (day - self.first).days % self.policy["order_cycle_days"]:
            return
        for key, bin_id in self.main.items():
            need = self.target - self.state.bin_quantities[bin_id] - self.order_reserved[key]
            if need < 2:
                continue
            order = f"{key}-PO-{day:%Y%m%d}"
            price = self.prices[key]
            row = PurchaseOrder(*doc(f"{order}-V1", when), order, self.supplier.supplier_id,
                                key, price.record_id, need)
            self.masters.add("orders", order, row)
            self.emit("warehouse_orders", [row], when)
            date1 = day + self.policy["lead_days"] * DAY
            date2 = date1 + self.policy["split_receipt_delay_days"] * DAY
            first = need * 3 // 5
            self.inbound[date1].append((key, order, first, 1))
            self.inbound[date2].append((key, order, need - first, 2))
            self.order_reserved[key] += need

    def grams_for_dm(self, key, target, when):
        bin_id = self.main[key]
        layers = sorted((self.state.layers[layer] for layer in self.state.bin_layers[bin_id]),
                        key=lambda layer: (layer.acquired_at, layer.sequence, layer.layer_id))
        total = 0
        for layer in layers:
            grams, _ = self.state.balances[bin_id, layer.layer_id]
            assay, ingredient = self.masters.nutrition(layer.batch_id, key, when, when)
            basis = assay.dm_bps if assay else ingredient.standard_dm_bps
            available = half_up(grams * basis, BPS)
            if available >= target:
                # Smallest AF mass whose rounded DM meets the integer target.
                return total + (target * BPS - BPS // 2 + basis - 1) // basis
            total += grams
            target -= available
        return None

    def shortage(self, when, plan, key, grams):
        identifier = stable_id("WAREHOUSE-SHORT", [plan, key, when])
        self.emit("exceptions", [ExceptionRow(identifier, when, "feed", "ingredient_shortage_load_cancelled",
                                              f"{plan}/{key}", grams, "g_dm")], when)

    def finish(self, end, knowledge):
        # Replay from the source transaction stream with the accepted independent projection.
        tables = {name: getattr(self.masters, name) for name in (
            "ingredients", "suppliers", "warehouses", "bins", "batches", "assays", "prices", "orders", "equipment")}
        Masters(**tables)  # Full master/PO integrity validation before publication.
        warehouse = Warehouse(self.masters, self.transactions)
        snapshot = warehouse.snapshot(end, knowledge)
        if snapshot.entries != tuple(self.state.entries):
            raise ValueError("live FIFO differs from independent replay")
        self.emit("warehouse_layers", snapshot.layers)
        self.emit("warehouse_balances", snapshot.balances)
        self.emit("warehouse_po_status", snapshot.purchase_status)
        return warehouse, snapshot
