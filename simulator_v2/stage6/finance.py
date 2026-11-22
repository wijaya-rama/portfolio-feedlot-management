"""Source-linked accounting with the Stage 4 posting and finance close engines."""

from calendar import monthrange
from types import SimpleNamespace

from ..stage1.model import EventKind, midnight
from ..stage3.allocation import DEFAULT_METHOD
from ..stage4.close import close_month, compare_closes
from ..stage4.feed import Feed, LossPolicy
from ..stage4.fixture import Fixture, YardageDay, settings
from ..stage4.ledger import Account, Action, Book, journal_lines, periods
from .close_index import CloseIndex, immediate_warehouse_closes, yardage_by_month
from .config import at
from .livestock import DAY
from .finance_store import FinanceStore

BOOK_VERSION = "stage6a-finance.1"
YARDAGE_TARIFF = "SYN-STAGE6-YARDAGE-TARIFF"


class Finance(Fixture):
    """Supply generalized Stage 6 sources to Stage 4 ledger and close controls."""

    def __init__(self, yard, operations, sales, yardage, config, first, last, cutoff, emit, feed_checkpoints, storage):
        self.operations, self.sales, self.emit = operations, sales, emit
        self.calendar = periods(first, last)
        self.book_calendar = periods(first, last.replace(day=monthrange(last.year, last.month)[1]))
        self.config = settings()
        self.finance = config["finance"]
        self.config.update(
            opening_wip_cents={row.animal_id: row.wip_cents for row in yard.opening},
            purchase_cents={key: value for key, value in yard.entry_costs.items()
                            if yard.entries[key].kind == EventKind.RECEIPT},
            sale_provisional_cents={key: row.provisional_cents for key, row in sales.settlements.items()},
            vet_services_cents={row.source_event_id: self.finance[
                "vet_cents" if row.action == "treatment" else "repeat_vet_cents"]
                for row in operations.health if row.action in {"treatment", "repeat_treatment"}},
        )
        self.store = FinanceStore(storage, emit)
        self.sources, self.actions = self.store.sources, self.store
        self.refs, self.warehouse, self.approvals = {}, [], []
        self.yardage = yardage
        self.restated = "SYN-STAGE6-CONTROLLER-RESTATEMENT"
        self._approval(self.restated, cutoff, "Approve the Stage 6A restated service-period view")
        self._feed_sources()
        policy = LossPolicy("stage6a-stage4-absorption.1", **self.config["loss_policies"]["selected"], recovery={})
        self.feed = SimpleNamespace(policy=policy, deliveries={}, by_delivery={})
        for documents in feed_checkpoints:
            documents.ledger = SimpleNamespace(events=())
            documents.warehouse = SimpleNamespace(transactions=())
            documents.warehouse_snapshots = (SimpleNamespace(entries=()),)
            documents.approvals = ()
            self.operations = documents
            self._feed_sources()
            feed = Feed(documents, policy, DEFAULT_METHOD, self.sources, self.refs)
            self.actions.extend(feed.postings())
            self.emit("feed_cost_bridge", feed.costs.values(), partition_by="service_at")
            # Only the warehouse-to-mix index and potential clearing evidence survive the checkpoint.
            operations.mix_inputs.extend(SimpleNamespace(layer_entry_id=row.layer_entry_id, mix_id=row.mix_id)
                                         for row in documents.mix_inputs)
            self.feed.deliveries.update((key, SimpleNamespace(effective_at=row.effective_at))
                                        for key, row in feed.deliveries.items())
            self.feed.by_delivery.update((key, [SimpleNamespace(row=versions[0].row)])
                                         for key, versions in feed.by_delivery.items())
        self.operations = operations
        self._warehouse_actions()
        self._cattle()
        self.register_yardage(first)
        self._vet()
        self.emit("financial_sources", self.sources.rows.values(), partition_by="effective_at")
        self.emit("financial_approvals", self.approvals, partition_by="approved_at")
        self.emit("warehouse_finance", self.warehouse, partition_by="effective_at")

    def _sale(self, event, animal, lot, location, parent):
        row = self.sales.settlements[animal]
        key = f"{event.event_id}/PROVISIONAL"
        source = self._dated(key, "stage4/packer_settlements", [animal, row.provisional_cents],
                             event.effective_at, (parent,), available=event.available_at,
                             document=event.source.document_id)
        self.actions.append(Action(key, source, event.effective_at, "sale_provisional",
                                   Account.RECEIVABLE, Account.REVENUE, row.provisional_cents, animal, lot, location))
        carcass = self.sales.carcasses[animal]
        carcass_source = self._dated(f"{event.event_id}/CARCASS", "diagnostic/carcass", carcass,
                                     carcass.effective_at, (parent,), posted=carcass.posted_at,
                                     available=carcass.available_at)
        settled = self._dated(row.settlement_id, "stage4/packer_settlements", row, event.effective_at,
                              (source, carcass_source),
                              posted=row.posted_at, available=row.available_at)
        self.actions.append(Action(row.settlement_id, settled, event.effective_at, "packer_final_adjustment",
                                   Account.RECEIVABLE, Account.PACKER, row.adjustment_cents, animal, lot, location))

    def register_yardage(self, first):
        tariff = self._dated(YARDAGE_TARIFF, "stage4/yardage_tariffs", self.finance["yardage_cents"], midnight(first))
        selected = next((row for row in self.yardage if len(self.calendar) > 1
                         and row.date == self.calendar[0].end), None)
        arrival = at(selected.date + 2 * DAY, 9) if selected else None
        delta = self.finance["late_yardage_delta_cents"]
        approval_id = "SYN-STAGE6-APPROVE-YARDAGE-DELTA"
        approval = self._approval(approval_id, arrival, "Correct one omitted synthetic yardage surcharge") if (
            selected and delta) else None
        for row in self.yardage:
            key = f"SYN-YARDAGE-{row.date}-{row.animal_id}"
            service = self._dated(key, "stage4/yardage_services", row, row.service_at,
                                  (self.refs[row.movement_event_id], tariff))
            self.actions.append(Action(key, service, row.service_at, "yardage", Account.WIP, Account.YARDAGE,
                                       row.cents, row.animal_id, row.lot_id, row.location_id, route_cost=True))
            if row is selected and approval:
                adjustment = self._dated(f"{key}/DELTA", "stage4/yardage_corrections", [row, delta], row.service_at,
                                         (service, approval), posted=arrival, available=arrival)
                # Reapply at the original service boundary only in the approved restated book.
                self.actions.append(Action(f"{key}/DELTA", adjustment, row.service_at, "yardage_correction",
                                           Account.WIP, Account.YARDAGE, delta, row.animal_id, row.lot_id,
                                           row.location_id, approval_id=approval_id, route_cost=True,
                                           restate_at=row.service_at))

    def books(self, cutoff):
        originals = []
        warehouse_closes = immediate_warehouse_closes(self.operations.warehouse_snapshots[0], self.calendar)
        yardage_days = yardage_by_month(self.yardage)
        for revised in (False, True):
            view = "restated" if revised else "as_known"
            book = Book(self.sources, self.book_calendar, version=f"{BOOK_VERSION}/{view}",
                        policy=self.feed.policy.version, yard=self.config["yard_id"],
                        restatement=self.restated if revised else None)
            cutoffs = [cutoff if revised else period.locked_at for period in self.calendar]
            journal_index = CloseIndex(self.calendar, cutoffs)
            for actions in self.store.batches(view):
                journals = book.run(actions, cutoff)
                journal_index.add(journals)
                clock = "period_routing_at" if revised else "posted_at"
                self.emit(f"journals_{view}", journals, partition_by=clock)
                if not revised:
                    for row in journals:
                        self.emit("journal_lines", journal_lines((row,)), row.posted_at)
                # SQL enforces action identity across batches. Journal IDs are derived from action keys.
                # Stage 6 corrections have
                # independent signed keys and use immutable source ancestry, so no reversal lookup is needed.
                book._actions.clear()
                book._journals.clear()
            del book
            prior = None
            for index, (period, checkpoint) in enumerate(zip(self.calendar, journal_index.checkpoints(), strict=True)):
                original = originals[index] if revised else None
                result = close_month(self, period, (), prior=prior, original=original[0] if original else None,
                                     knowledge=cutoff if revised else None, journal_checkpoint=checkpoint,
                                     warehouse_balances=warehouse_closes.get(period.month),
                                     yardage_days=yardage_days[period.month])
                prior = result[0]
                if not revised:
                    originals.append(result)
                for table, rows in zip(("finance_snapshots", "wip", "finance_soh", "warehouse_close", "trial_balance",
                                        "finance_exceptions", "finance_monthly"),
                                       ([result[0]], *result[1:6], [result[6]])):
                    self.emit(table, rows, midnight(period.start))
                self.emit("wip_components", checkpoint[0].animal_components(result), midnight(period.start))
                if revised:
                    self.emit("close_deltas", compare_closes(original, result), midnight(period.start))
                yield view, result
