"""Post the physical feed chain and classify cents independently of intake."""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime

from ..stage1.provenance import stable_id
from ..stage3.units import BPS, split
from .ledger import Account, Action, TICK

CONSUMED = "feed_consumption"
MIX_NORMAL = "mix_normal"
DISTRIBUTION_NORMAL = "distribution_normal"
REFUSAL_NORMAL = "refusal_normal"
NORMAL_COMPONENTS = {MIX_NORMAL, DISTRIBUTION_NORMAL, REFUSAL_NORMAL}


def apportioned(cents, weights):
    if not any(weights.values()):
        if cents:
            raise ValueError("cost pool has no allocation basis")
        return dict.fromkeys(weights, 0)
    sign = -1 if cents < 0 else 1
    return {key: sign * amount for key, amount in split(abs(cents), weights).items()}


def qualifies(loss_af, total_af, limit):
    return loss_af * BPS <= total_af * limit


@dataclass(frozen=True)
class LossPolicy:
    version: str
    mix_bps: dict
    distribution_bps: int
    refusal_bps: int
    refusal_evidence: str
    recovery: dict

    def __post_init__(self):
        tolerances = (*self.mix_bps.values(), self.distribution_bps, self.refusal_bps)
        if ("default" not in self.mix_bps
                or any(type(value) is not int or not 0 <= value <= BPS for value in tolerances)
                or any(type(value) is not int or value <= 0 for value in self.recovery.values())
                or self.refusal_evidence not in {"synthetic_observed", "unclassified"}):
            raise ValueError("invalid feed loss policy")

    def mix_is_normal(self, mix):
        limit = self.mix_bps.get(mix.ration_version_id, self.mix_bps["default"])
        return qualifies(mix.loss.g_af, mix.input.g_af, limit)

    def distribution_is_normal(self, delivery):
        return qualifies(delivery.delivery_loss.g_af, delivery.loaded.g_af, self.distribution_bps)

    def refusal_parts(self, settled, delivery):
        row = settled.row
        recovery = self.recovery.get(row.bunk_ticket_id, 0)
        observed = row.observed_refusal_g_af
        inferred = row.inferred_unconsumed_g_af
        if recovery > observed or observed + inferred != row.refusal.g_af:
            raise ValueError(f"unreconciled refusal evidence: {row.settlement_id}")
        if self.refusal_evidence == "unclassified":
            return {"refusal_recovery": recovery, REFUSAL_NORMAL: 0,
                    "refusal_excess": 0, "refusal_no_access": inferred,
                    "refusal_pending": observed - recovery}
        allowance = delivery.delivered.g_af * self.refusal_bps // BPS
        normal = min(observed - recovery, allowance)
        return {"refusal_recovery": recovery, REFUSAL_NORMAL: normal,
                "refusal_excess": observed - recovery - normal,
                "refusal_no_access": inferred, "refusal_pending": 0}


@dataclass(frozen=True)
class FeedSink:
    component: str
    target: Account
    weight: int
    cents: int
    animal_id: str | None
    lot_id: str | None
    effective_at: datetime
    allocation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedCost:
    delivery_id: str
    settlement_id: str
    service_at: datetime
    available_at: datetime
    mix_loss_cents: int
    distribution_loss_cents: int
    refusal_cents: int
    bunk_loss_cents: int
    consumption_cents: int
    normal_mix_cents: int
    normal_distribution_cents: int
    normal_refusal_cents: int
    recoverable_cents: int
    abnormal_cents: int
    pending_cents: int
    mix_loss_g_af: int
    mix_loss_g_dm: int
    distribution_loss_g_af: int
    distribution_loss_g_dm: int
    refusal_g_af: int
    refusal_g_dm: int
    bunk_loss_g_af: int
    bunk_loss_g_dm: int
    consumed_g_af: int
    consumed_g_dm: int
    recoverable_g_af: int
    recoverable_g_dm: int


class Feed:
    def __init__(self, fixture, policy, method, sources, references):
        self.policy = policy
        self.method = method
        self.sources = sources
        self.refs = references
        self.mixes = {row.mix_id: row for row in fixture.mixes}
        self.deliveries = {row.delivery_id: row for row in fixture.deliveries}
        self.by_mix = defaultdict(list)
        self.by_delivery = defaultdict(list)
        self.parts = {}
        self.actions_by_settlement = {}
        self.costs = {}
        self.mix_loss = {}
        self.mix_loss_af = {}
        self.mix_loss_dm = {}
        for delivery in self.deliveries.values():
            self.by_mix[delivery.mix_id].append(delivery)
        for mix_id, group in self.by_mix.items():
            mix = self.mixes[mix_id]
            if (sum(d.loaded.cents for d in group) != mix.produced.cents
                    or sum(d.loaded.g_af for d in group) != mix.produced.g_af):
                raise ValueError(f"unreconciled mix dispatch: {mix_id}")
            basis = {d.delivery_id: d.delivered.g_af for d in group}
            if not any(basis.values()):
                basis = {d.delivery_id: d.loaded.g_af for d in group}
            if not any(basis.values()):
                basis = dict.fromkeys(basis, 1)
            self.mix_loss.update(apportioned(mix.loss.cents, basis))
            self.mix_loss_af.update(apportioned(mix.loss.g_af, basis))
            loss_basis = {d.delivery_id: self.mix_loss_af[d.delivery_id] for d in group}
            self.mix_loss_dm.update(apportioned(mix.loss.g_dm, loss_basis))
        if set(self.mixes) != set(self.by_mix):
            raise ValueError("undispatched mix has no financial disposition")
        for settled in sorted(fixture.settlements, key=lambda item: (
                item.row.available_at, item.row.settlement_id)):
            self.by_delivery[settled.row.delivery_id].append(settled)

    def _by_animal(self, settled):
        groups = defaultdict(list)
        for row in settled.allocations:
            if row.method == self.method:
                groups[row.animal_id].append(row)
        first = {key: group[0] for key, group in groups.items()}
        weights = {key: sum(row.g_dm for row in group) for key, group in groups.items()}
        ends = {key: max(row.access_end for row in group) for key, group in groups.items()}
        costs = {key: sum(row.cents for row in group) for key, group in groups.items()}
        row = settled.row
        if (sum(costs.values()) != row.modeled_consumption.cents
                or sum(weights.values()) != row.modeled_consumption.g_dm):
            raise ValueError(f"consumption cost or DM mismatch: {row.settlement_id}")
        return groups, first, weights, ends, costs

    def targets(self, settled):
        row = settled.row
        delivery = self.deliveries[row.delivery_id]
        mix = self.mixes[delivery.mix_id]
        groups, first, weights, ends, costs = self._by_animal(settled)
        funded = any(weights.values())
        refusal_parts = self.policy.refusal_parts(settled, delivery)
        refusal_cost = apportioned(row.refusal.cents, refusal_parts)
        parts = [
            (CONSUMED, row.modeled_consumption.g_af, row.modeled_consumption.cents, Account.WIP),
            (MIX_NORMAL if self.policy.mix_is_normal(mix) else "mix_abnormal",
             self.mix_loss_af[delivery.delivery_id], self.mix_loss[delivery.delivery_id], Account.NORMAL),
            (DISTRIBUTION_NORMAL if self.policy.distribution_is_normal(delivery) else "distribution_abnormal",
             delivery.delivery_loss.g_af, delivery.delivery_loss.cents, Account.NORMAL),
            ("bunk_abnormal", row.bunk_loss.g_af, row.bunk_loss.cents, Account.ABNORMAL),
        ]
        for category, grams in refusal_parts.items():
            target = {"refusal_recovery": Account.RECOVERY, REFUSAL_NORMAL: Account.NORMAL,
                      "refusal_pending": Account.PENDING}.get(category, Account.ABNORMAL)
            parts.append((category, grams, refusal_cost[category], target))
        for component, grams, cents, target in parts:
            if target == Account.NORMAL and component not in NORMAL_COMPONENTS:
                target = Account.ABNORMAL
            if target == Account.NORMAL and not funded:
                component = f"{component}_without_consumption"
                target = Account.ABNORMAL
            if target in {Account.WIP, Account.NORMAL}:
                amounts = costs if component == CONSUMED else apportioned(cents, weights)
                sinks = tuple(FeedSink(component, Account.WIP, weights[key], amounts[key], key,
                                       first[key].lot_id, ends[key],
                                       tuple(row.allocation_id for row in groups[key]))
                              for key in sorted(weights) if weights[key] or amounts[key])
            else:
                sinks = (FeedSink(component, target, grams, cents, None, None, delivery.window_end),)
            yield component, grams, sinks
        recovered_dm = apportioned(row.refusal.g_dm, refusal_parts)["refusal_recovery"]
        self.costs[row.settlement_id] = FeedCost(
            row.delivery_id, row.settlement_id, delivery.window_end, row.available_at,
            self.mix_loss[delivery.delivery_id], delivery.delivery_loss.cents,
            row.refusal.cents, row.bunk_loss.cents, row.modeled_consumption.cents, 0, 0, 0,
            refusal_cost["refusal_recovery"], 0, refusal_cost["refusal_pending"],
            self.mix_loss_af[delivery.delivery_id], self.mix_loss_dm[delivery.delivery_id],
            delivery.delivery_loss.g_af, delivery.delivery_loss.g_dm,
            row.refusal.g_af, row.refusal.g_dm, row.bunk_loss.g_af, row.bunk_loss.g_dm,
            row.modeled_consumption.g_af, row.modeled_consumption.g_dm,
            refusal_parts["refusal_recovery"], recovered_dm)

    def _line(self, settled, sink, component, debit, credit, cents, *, namespace, effective=None,
              extra_parents=(), previous=None, approval=None, restate_at=None):
        row = settled.row
        delivery = self.deliveries[row.delivery_id]
        effective = sink.effective_at if effective is None else effective
        parents = [self.refs[row.settlement_id], *(self.refs[key] for key in sink.allocation_ids),
                   *extra_parents]
        if previous is not None:
            parents.append(previous.source_id)
        if approval:
            parents.append(self.refs[approval])
        clock = [self.sources.rows[key] for key in parents]
        posted_at = max(item.posted_at for item in clock)
        available_at = max(item.available_at for item in clock)
        line = stable_id("FEED-COST-LINE", [namespace, row.settlement_id, component,
                                          sink.component, sink.animal_id,
                                          previous.key if previous else None])
        source_id = self.sources.add("stage4/feed_cost", namespace, line, effective,
                                     max(effective, posted_at), available_at,
                                     [self.policy.version, debit, credit, cents], parents)
        return Action(line, source_id, effective, component, debit, credit, cents, sink.animal_id,
                      sink.lot_id, delivery.pen_id, delivery.delivery_id, approval,
                      previous.key if previous else None, debit == Account.WIP, restate_at=restate_at)

    def postings(self):
        for delivery_id, versions in self.by_delivery.items():
            delivery = self.deliveries[delivery_id]
            mix = self.mixes[delivery.mix_id]
            yield Action(delivery_id, self.refs[delivery_id], delivery.effective_at, "distribution_load",
                         Account.DISTRIBUTION, Account.MIX, delivery.loaded.cents,
                         location_id=delivery.pen_id, pool_id=mix.mix_id)
            # Move the load to an individual delivery clearing bucket, preserving both control legs.
            # The outbound mix leg above uses the mix ID. Its distribution leg is associated with
            # the delivery in the close using the originating source document.
            if self.mix_loss[delivery_id]:
                yield Action(f"{delivery_id}/mix-bridge", self.refs[delivery_id], delivery.effective_at,
                             "mix_loss_transfer", Account.NORMAL, Account.MIX, self.mix_loss[delivery_id],
                             location_id=delivery.pen_id, pool_id=mix.mix_id)
            if delivery.delivery_loss.cents:
                yield Action(f"{delivery_id}/delivery-bridge", self.refs[delivery_id], delivery.effective_at,
                             "distribution_loss_transfer", Account.NORMAL, Account.DISTRIBUTION,
                             delivery.delivery_loss.cents, location_id=delivery.pen_id, pool_id=delivery_id)
            prior = None
            for revision, version in enumerate(versions):
                row = version.row
                parts = tuple(self.targets(version))
                self.parts[row.settlement_id] = parts
                costs = self.costs[row.settlement_id]
                amounts = defaultdict(int)
                for _, _, sinks in parts:
                    for sink in sinks:
                        amounts[sink.component, sink.target] += sink.cents
                self.costs[row.settlement_id] = replace(
                    costs, normal_mix_cents=amounts[MIX_NORMAL, Account.WIP],
                    normal_distribution_cents=amounts[DISTRIBUTION_NORMAL, Account.WIP],
                    normal_refusal_cents=amounts[REFUSAL_NORMAL, Account.WIP],
                    abnormal_cents=sum(cents for (_, target), cents in amounts.items()
                                       if target == Account.ABNORMAL))
                approval = row.revision_approval_id
                original_at = versions[0].row.available_at + revision * TICK if prior else None
                if prior:
                    if row.revises_settlement_id != prior.row.settlement_id or not approval:
                        raise ValueError(f"invalid settlement revision chain: {row.settlement_id}")
                    for sink, action in self.actions_by_settlement[prior.row.settlement_id]:
                        yield self._line(version, sink, action.component, action.debit, action.credit,
                                         -action.cents, namespace=delivery_id, previous=action,
                                         approval=approval, restate_at=original_at)
                lines = []
                for component, _, sinks in parts:
                    clearing = (Account.NORMAL if component.startswith(("mix_", "distribution_"))
                                else Account.DISTRIBUTION)
                    for sink in sinks:
                        if not sink.cents:
                            continue
                        action = self._line(version, sink, component, sink.target, clearing, sink.cents,
                                            namespace=delivery_id, approval=approval, restate_at=original_at)
                        lines.append((sink, action))
                        yield action
                self.actions_by_settlement[row.settlement_id] = lines
                prior = version

    def invoice(self, invoice_split, transaction, mix_input):
        """Replay the adjusted layer cents through the same loss and allocation rules."""
        mix = self.mixes[mix_input.mix_id]
        group = self.by_mix[mix.mix_id]
        cents = invoice_split.delta_cents
        parent = self.refs[invoice_split.split_id]
        mixed = apportioned(cents, {"loss": mix.loss.g_af, "produced": mix.produced.g_af})
        loaded = apportioned(mixed["produced"], {d.delivery_id: d.loaded.g_af for d in group})
        lost = apportioned(mixed["loss"], {d.delivery_id: self.mix_loss_af[d.delivery_id] for d in group})
        for delivery in group:
            did = delivery.delivery_id
            distributed = apportioned(loaded[did], {"loss": delivery.delivery_loss.g_af,
                                                   "delivered": delivery.delivered.g_af})
            previous_lines = []
            previous = None
            for revision, version in enumerate(self.by_delivery[did]):
                row = version.row
                parts = self.parts[row.settlement_id]
                # Only one settlement version per original invoice cutoff.
                versions = self.by_delivery[did]
                if row.available_at <= transaction.available_at and any(
                        row.available_at < item.row.available_at <= transaction.available_at for item in versions):
                    continue
                approval = row.revision_approval_id if previous is not None else None
                restate_at = (max(transaction.available_at, versions[0].row.available_at) + revision * TICK
                              if previous else None)
                for sink, action in previous_lines:
                    yield self._line(version, sink, action.component, action.debit, action.credit,
                                     -action.cents, namespace=invoice_split.split_id,
                                     extra_parents=(parent,), previous=action, approval=approval,
                                     restate_at=restate_at)
                weights = {component: grams for component, grams, _ in parts
                           if not component.startswith(("mix_", "distribution_"))}
                part_costs = apportioned(distributed["delivered"], weights)
                current = []
                for component, _, sinks in parts:
                    if component.startswith("mix_"):
                        amount = lost[did]
                    elif component.startswith("distribution_"):
                        amount = distributed["loss"]
                    else:
                        amount = part_costs[component]
                    if not amount:
                        continue
                    # When a physically consumed pool has rounded to zero DM, use original
                    # nonzero consumption-cost shares rather than creating intake.
                    basis = {i: sink.weight for i, sink in enumerate(sinks)}
                    if not any(basis.values()):
                        basis = {i: abs(sink.cents) for i, sink in enumerate(sinks)}
                    if not any(basis.values()) and len(sinks) == 1:
                        basis = {0: 1}
                    for i, allocated in apportioned(amount, basis).items():
                        if not allocated:
                            continue
                        sink = sinks[i]
                        # Source-effective service of historical inventory is the original
                        # delivery. The supplier document retains its own invoice date.
                        action = self._line(
                            version, sink, f"invoice_{component}", sink.target, Account.INVOICE,
                            allocated, namespace=invoice_split.split_id, extra_parents=(parent,),
                            approval=approval, restate_at=restate_at)
                        current.append((sink, action))
                        yield action
                previous = version
                previous_lines = current
