"""Translate authoritative operations and explicit synthetic charges into source-linked actions."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from ..stage1.fixture import END, FINAL_CUTOFF, START, local
from ..stage1.model import EventKind, business_date, midnight
from ..stage1.replay import replay
from ..stage1.soh import calendar_days
from ..stage1.validation import reject_failures
from ..stage2.health import Action as ClinicalAction
from ..stage3.warehouse import Kind
from .feed import Feed, LossPolicy
from .ledger import Account, Action, Sources, TICK, accounting_month, periods

POLICY_PATH = Path(__file__).with_name("policy.json")
ENTRY = {EventKind.OPENING, EventKind.RECEIPT}
EXIT = {EventKind.SALE, EventKind.DEATH}


def settings():
    return json.loads(POLICY_PATH.read_bytes())


@dataclass(frozen=True)
class Approval:
    approval_id: str
    source_id: str
    approved_by: str
    approved_at: datetime
    reason: str


@dataclass(frozen=True)
class WarehouseMovement:
    source_id: str
    entry_id: str
    transaction_id: str
    layer_id: str
    bin_id: str
    ingredient_id: str
    kind: str
    effective_at: datetime
    available_at: datetime
    accounting_month: str
    g_af: int
    g_dm_at_movement: int
    cents: int


@dataclass(frozen=True)
class YardageDay:
    date: date
    animal_id: str
    lot_id: str
    location_id: str
    movement_event_id: str
    service_at: datetime
    tariff_id: str
    cents: int


def yardage_day(day, ledger, tariffs):
    start, end = midnight(day), midnight(day + timedelta(days=1))
    known = replay(ledger, end, end)
    reject_failures(known.checks)
    tariff = max((row for row in tariffs if row["from"] <= day.isoformat()), key=lambda row: row["from"])
    eligible = {}
    for interval in known.intervals:
        after = interval.end_at
        if (after is not None and after <= start
                and not (interval.start_at == start == after)):
            continue
        if interval.start_at >= end:
            continue
        event = next((event for event in known.events if event.event_id == interval.end_event_id), None)
        exit_event = event if event is not None and event.kind in EXIT else None
        anchor = exit_event.event_id if exit_event else interval.start_event_id
        service = exit_event.effective_at if exit_event else end - TICK
        eligible[interval.animal_id] = YardageDay(day, interval.animal_id, interval.lot_id,
                                                  interval.location_id, anchor, service,
                                                  tariff["id"], tariff["cents"])
    return tuple(eligible[key] for key in sorted(eligible))


class Fixture:
    def __init__(self, operations, config, policy_name):
        self.operations = operations
        self.config = config
        self.policy_name = policy_name
        self.calendar = periods(START, END)
        self.sources = Sources()
        self.refs = {}
        self.actions = []
        self.warehouse = []
        self.approvals = []
        self.yardage = []
        self.active_feed = ()
        self.all_feed = ()
        self.restated = config["restatement"]["id"]
        if (operations.scenario["version"] != config["source_scenario"]
                or operations.scenario["method"] != config["method"]
                or len(operations.timeline.animals) != 12 or config["currency"] != "CAD"
                or config["warehouse_normal_allowance_bps"] != 0):
            raise ValueError("unexpected scenario or unsupported warehouse policy")
        policy = LossPolicy(f'{config["version"]}/{policy_name}',
                            **config["loss_policies"][policy_name], recovery=config["refusal_recovery_g_af"])
        self._feed_sources()
        self.feed = Feed(operations, policy, config["method"], self.sources, self.refs)
        self.actions.extend(self.feed.postings())
        active_ids = {row.row.settlement_id for row in operations.active_settlements}
        self.all_feed = tuple(self.feed.costs.values())
        self.active_feed = tuple(row for row in self.all_feed if row.settlement_id in active_ids)
        self._warehouse_actions()
        self._cattle()
        self._yardage()
        self._vet()
        self._approval(self.restated, FINAL_CUTOFF, config["restatement"]["reason"])

    def _register(self, key, system, row, effective, posted, available, parents=(), document=None, line=None, event_kind=None):
        source = self.sources.add(system, document or key, line or key, effective, posted,
                                  available, row, parents, event_kind=event_kind)
        if self.refs.setdefault(key, source) != source:
            raise ValueError(f"duplicate source key: {key}")
        return source

    def _dated(self, key, system, row, effective, parents=(), *, posted=None, available=None, document=None):
        return self._register(key, system, row, effective, posted or effective,
                              available or posted or effective, parents, document=document)

    def _approval(self, key, when, reason, by="SYN-FINANCIAL-CONTROLLER"):
        if not reason.strip() or not by.startswith("SYN-"):
            raise ValueError("invalid synthetic controller approval")
        source = self._dated(key, "stage4/approvals", [by, reason], when)
        self.approvals.append(Approval(key, source, by, when, reason))
        return source

    def _feed_sources(self):
        for row in sorted(self.operations.ledger.events, key=lambda event: (event.available_at, event.order)):
            key = row.event_id
            # Preserve the Stage 1 document and line identifiers verbatim.
            self._register(key, "livestock/movement_events", row, row.effective_at, row.posted_at,
                           row.available_at, (self.refs[row.supersedes_event_id],) if row.supersedes_event_id else (),
                           document=row.source.document_id, line=row.source.line_id, event_kind=row.kind)
        for approval in self.operations.approvals:
            self._approval(approval.approval_id, approval.approved_at, approval.reason, approval.approved_by)
        for row in self.operations.warehouse.transactions:
            self._dated(row.record_id, "warehouse/transactions", row, row.effective_at,
                        posted=row.posted_at, available=row.available_at)
        for row in self.operations.warehouse_snapshots[0].entries:
            self._dated(row.entry_id, "warehouse/inventory_movements", row, row.effective_at,
                        (self.refs[row.transaction_id],), posted=row.posted_at, available=row.available_at,
                        document=row.transaction_id)
        by_mix = defaultdict(list)
        for row in self.operations.mix_inputs:
            source = self.sources.rows[self.refs[row.layer_entry_id]]
            self._dated(row.mix_input_id, "feed/mix_inputs", row, source.effective_at, (source.source_id,),
                        posted=source.posted_at, available=source.available_at, document=row.mix_id)
            by_mix[row.mix_id].append(self.refs[row.mix_input_id])
        for row in self.operations.mixes:
            self._dated(row.mix_id, "feed/mix_batches", row, row.effective_at, by_mix[row.mix_id],
                        posted=row.posted_at, available=row.available_at)
        for row in self.operations.deliveries:
            self._dated(row.delivery_id, "feed/deliveries", row, row.effective_at,
                        (self.refs[row.mix_id],), posted=row.posted_at, available=row.available_at)
        for row in self.operations.schedule.bunk_tickets:
            self._dated(row.record_id, "feed/bunk_tickets", row, row.effective_at,
                        (self.refs[row.delivery_id],), posted=row.posted_at, available=row.available_at)
        for version in sorted(self.operations.settlements, key=lambda x: (
                x.row.available_at, x.row.settlement_id)):
            row = version.row
            ticket = self.sources.rows[self.refs[row.bunk_ticket_id]]
            parent = [ticket.source_id]
            if row.revises_settlement_id:
                parent.extend(self.refs[key] for key in (row.revises_settlement_id, row.revision_approval_id))
            self._dated(row.settlement_id, "feed/bunk_settlements", row, ticket.effective_at, parent,
                        posted=row.finalized_at, available=row.available_at)
            exposures = {}
            for item in version.exposures:
                parents = [self.refs[row.settlement_id], self.refs[item.movement_in_id]]
                if item.movement_out_id is not None:
                    parents.append(self.refs[item.movement_out_id])
                exposures[item.exposure_id] = self._dated(
                    item.exposure_id, "feed/exposures", item, item.end_at, parents,
                    posted=row.finalized_at, available=row.available_at, document=row.settlement_id)
            for allocation in version.allocations:
                if allocation.method != self.config["method"]:
                    continue
                self._dated(allocation.allocation_id, "feed/allocations", allocation, allocation.access_end,
                            (exposures[allocation.exposure_id],), posted=allocation.finalized_at,
                            available=allocation.available_at, document=row.settlement_id)

    def _warehouse_actions(self):
        closing = self.operations.warehouse_snapshots[0]
        mix_inputs = {item.layer_entry_id: item for item in self.operations.mix_inputs}
        entries = {row.entry_id: row for row in closing.entries}
        transactions = {row.record_id: row for row in self.operations.warehouse.transactions}
        sink = {Kind.OPENING: Account.OPENING, Kind.RECEIPT: Account.FEED_RECEIPT,
                Kind.ISSUE: Account.MIX, Kind.ADJUST: Account.STOCK_COUNT,
                Kind.SPOILAGE: Account.SPOILAGE, Kind.RETURN: Account.FEED_RECEIPT,
                Kind.INVOICE: Account.INVOICE}
        reasons = self.config["warehouse_adjustment_reasons"]
        adjustment_accounts = {
            "stock_count": Account.STOCK_COUNT, "warehouse_shrink": Account.WAREHOUSE_SHRINK,
            "warehouse_damage": Account.WAREHOUSE_DAMAGE, "receiving_correction": Account.FEED_RECEIPT,
        }
        def destination(row):
            if row.kind == Kind.ADJUST:
                reason = transactions[row.transaction_id].reason
                category = reasons.get(reason)
                if category not in adjustment_accounts:
                    raise ValueError(f"warehouse adjustment lacks approved classification: {row.transaction_id}")
                return adjustment_accounts[category]
            return sink[row.kind]

        for row in closing.entries:
            kind, effective, source = row.kind, row.effective_at, self.refs[row.entry_id]
            self.warehouse.append(WarehouseMovement(
                source, row.entry_id, row.transaction_id, row.layer_id, row.bin_id, row.ingredient_id,
                kind, effective, row.available_at,
                accounting_month(effective, row.available_at, self.calendar),
                row.g_af, row.g_dm, row.cents))
            if kind in {"transfer_in", "transfer_out"}:
                # One warehouse GL control. Both bin/layer legs are retained in the subledger.
                continue
            pool = mix_inputs[row.entry_id].mix_id if kind == Kind.ISSUE else None
            self.actions.append(Action(row.entry_id, source, effective, f"warehouse_{kind}",
                                       Account.WAREHOUSE, destination(row), row.cents,
                                       location_id=row.bin_id, pool_id=pool))
        delta_by_document = defaultdict(int)
        for row in closing.invoice_splits:
            transaction = transactions[row.invoice_transaction_id]
            delta_by_document[transaction.record_id] += row.delta_cents
            historical = entries.get(row.historical_entry_id)
            parents = [self.refs[transaction.record_id], self.refs[transaction.reference_id]]
            if historical:
                parents.append(self.refs[historical.entry_id])
                if historical.entry_id in mix_inputs:
                    parents.append(self.refs[mix_inputs[historical.entry_id].mix_input_id])
            if row.inventory_entry_id:
                parents.append(self.refs[row.inventory_entry_id])
            source = self._dated(row.split_id, "warehouse/invoice_splits", row, transaction.effective_at, parents,
                                 posted=transaction.posted_at, available=transaction.available_at,
                                 document=transaction.record_id)
            if not historical or not row.delta_cents:
                continue
            if historical.kind == Kind.ISSUE:
                self.actions.extend(self.feed.invoice(row, transaction, mix_inputs[historical.entry_id]))
            else:
                self.actions.append(Action(row.split_id, source, historical.effective_at,
                                           f"invoice_{historical.kind}", destination(historical),
                                           Account.INVOICE, row.delta_cents, location_id=row.bin_id))
        if delta_by_document != {row.record_id: row.amount_cents
                                 for row in transactions.values() if row.kind == Kind.INVOICE}:
            raise ValueError("supplier invoice does not tie to receiving and historical sinks")

    def _cattle(self):
        active = self.operations.timeline.events
        animal_master = self.operations.timeline.animals
        ids = defaultdict(set)
        for event in active.values():
            animal, kind = event.animal_id, event.kind
            lot = animal_master[animal].lot_id
            when, available = event.effective_at, event.available_at
            location = event.to_location_id or event.from_location_id
            parent = self.refs[event.event_id]
            if kind in ENTRY:
                opening = kind == EventKind.OPENING
                component = "opening_wip" if opening else "acquisition"
                cents = self.config["opening_wip_cents" if opening else "purchase_cents"][animal]
                ids[component].add(animal)
                key = f'{event.event_id}/{component}'
                source = self._dated(key, f"stage4/{component}", [animal, cents], when, (parent,),
                                     posted=event.posted_at, available=available)
                self.actions.append(Action(key, source, when, component, Account.WIP,
                                           Account.OPENING if opening else Account.ACQUISITION,
                                           cents, animal, lot, location))
            elif kind in EXIT:
                outcome = Account.COGS if kind == EventKind.SALE else Account.MORTALITY
                self.actions.append(Action(event.event_id, parent, when, "principal_release",
                                           outcome, Account.WIP, 0, animal, lot, location, release=True))
                if kind == EventKind.SALE:
                    ids["sale_provisional"].add(animal)
                    self._sale(event, animal, lot, location, parent)
        for component, field in (("opening_wip", "opening_wip_cents"), ("acquisition", "purchase_cents"),
                                 ("sale_provisional", "sale_provisional_cents")):
            if ids[component] != self.config[field].keys():
                raise ValueError(f"synthetic document scope mismatch: {component}")

    def _sale(self, event, animal, lot, location, parent):
        provisional = self.config["sale_provisional_cents"][animal]
        final = self.config["packer_final"]
        key = f"{event.event_id}/PROVISIONAL"
        source = self._dated(key, "stage4/packer_settlements", [animal, provisional], event.effective_at,
                             (parent,), available=event.available_at, document=event.source.document_id)
        self.actions.append(Action(key, source, event.effective_at, "sale_provisional",
                                   Account.RECEIVABLE, Account.REVENUE, provisional, animal, lot, location))
        if final["animal_id"] == animal:
            available = local(final["available_local"])
            if available < event.available_at:
                raise ValueError("final packer settlement predates shipment")
            key = final["id"]
            document = self._dated(key, "stage4/packer_settlements", final, event.effective_at, (source,),
                                   posted=available, available=available)
            self.actions.append(Action(key, document, event.effective_at, "packer_final_adjustment",
                                       Account.RECEIVABLE, Account.PACKER, final["final_cents"] - provisional,
                                       animal, lot, location))

    def _yardage(self):
        tariffs = self.config["yardage_tariffs"]
        for tariff in tariffs:
            when = midnight(date.fromisoformat(tariff["from"]))
            self._dated(tariff["id"], "stage4/yardage_tariffs", tariff, when)
        correction = self.config["yardage_correction"]
        corrected_day = date.fromisoformat(correction["service_date"])
        arrived = local(correction["available_local"])
        approval = self._approval(correction["approval"], arrived, correction["reason"])
        for day in calendar_days(START, END):
            for row in yardage_day(day, self.operations.ledger, tariffs):
                self.yardage.append(row)
                key = f"{row.tariff_id}/{day}/{row.animal_id}"
                movement = self.sources.rows[self.refs[row.movement_event_id]]
                when = row.service_at
                posted = max(when, movement.posted_at)
                available = max(posted, movement.available_at)
                source = self._dated(key, "stage4/yardage_services", row, when,
                                     (movement.source_id, self.refs[row.tariff_id]),
                                     posted=posted, available=available, document=row.tariff_id)
                self.actions.append(Action(key, source, when, "yardage", Account.WIP, Account.YARDAGE,
                                           row.cents, row.animal_id, row.lot_id, row.location_id, route_cost=True))
                if day == corrected_day:
                    key = f'{correction["id"]}/{row.animal_id}'
                    adjustment = self._dated(key, "stage4/yardage_corrections", correction, when,
                                              (source, approval), posted=arrived, available=arrived,
                                              document=correction["id"])
                    self.actions.append(Action(key, adjustment, when, "yardage_correction",
                                               Account.WIP, Account.YARDAGE, correction["delta_cents"],
                                               row.animal_id, row.lot_id, row.location_id,
                                               approval_id=correction["approval"], route_cost=True,
                                               restate_at=available))

    def _vet(self):
        charges = self.config["vet_services_cents"]
        seen = set()
        for row in self.operations.health:
            if row.action not in {ClinicalAction.TREAT, ClinicalAction.REPEAT}:
                continue
            key = row.source_event_id
            if key in seen or self.operations.timeline.location_at(row.animal_id, row.effective_at) is None:
                raise ValueError(f"duplicate or inactive clinical service: {key}")
            seen.add(key)
            provenance = self._dated(row.health_event_id, "diagnostic/health_events", row, row.effective_at,
                                     posted=row.posted_at, available=row.available_at)
            document = self._dated(key, "stage4/vet_services", [key, charges[key]], row.effective_at,
                                   (provenance,), posted=row.posted_at, available=row.available_at)
            self.actions.append(Action(key, document, row.effective_at, "vet_direct", Account.WIP,
                                       Account.VET, charges[key], row.animal_id, row.lot_id, row.location_id,
                                       route_cost=True))
        if seen != charges.keys():
            raise ValueError("synthetic veterinary charge lacks a dated treatment")
