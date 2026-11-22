"""Ration versions, measured mixing inputs and as-fed/DM/cost bridges."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from ..stage1.model import business_date
from ..stage1.provenance import stable_id
from .units import BPS, half_up, split, whole
from .warehouse import Document, Equipment, Ingredient, Kind, _version


@dataclass(frozen=True)
class FeedAmount:
    g_af: int
    g_dm: int
    kj: int
    cp_g: int
    cents: int

    def __post_init__(self):
        for value in (self.g_af, self.g_dm, self.kj, self.cp_g, self.cents):
            whole(value, "feed amount")
        if not self.cp_g <= self.g_dm <= self.g_af or (not self.g_dm and self.kj):
            raise ValueError("invalid as-fed, DM, protein or energy basis")


EMPTY = FeedAmount(0, 0, 0, 0, 0)


def add_amounts(amounts):
    totals = [0, 0, 0, 0, 0]
    for amount in amounts:
        for index, value in enumerate((amount.g_af, amount.g_dm, amount.kj, amount.cp_g, amount.cents)):
            totals[index] += value
    return FeedAmount(*totals)


def partition(amount, as_fed):
    """Split a homogeneous pool on AF, then distribute nutrients on its apportioned DM."""
    if sum(as_fed.values()) != amount.g_af:
        raise ValueError("as-fed split does not conserve mass")
    dm = split(amount.g_dm, as_fed)
    kj, cp = split(amount.kj, dm), split(amount.cp_g, dm)
    cents = split(amount.cents, as_fed)
    return {key: FeedAmount(grams, dm[key], kj[key], cp[key], cents[key])
            for key, grams in as_fed.items()}


@dataclass(frozen=True)
class Recipe(Document):
    ration_id: str
    eligible_stages: str
    target_kj_per_kg_dm: int
    target_cp_bps_dm: int


@dataclass(frozen=True)
class Component:
    component_id: str
    ration_version_id: str
    ingredient_id: str
    target_dm_bps: int
    assumed_dm_bps: int
    substitute_ingredient_id: str | None = None
    max_substitute_bps_af: int = 0


@dataclass(frozen=True)
class MixOrder(Document):
    ration_version_id: str
    mixer_version_id: str
    planned_g_dm: int
    loss_g_af: int


@dataclass(frozen=True)
class MixIssue:
    transaction_id: str
    mix_id: str
    component_id: str
    substitution_reason: str | None = None


@dataclass(frozen=True)
class MixInput:
    mix_input_id: str
    mix_id: str
    component_id: str
    issue_transaction_id: str
    layer_entry_id: str
    layer_id: str
    batch_id: str
    ingredient_id: str
    ingredient_version_id: str
    assay_id: str | None
    dm_bps: int
    substitution_reason: str | None
    amount: FeedAmount


@dataclass(frozen=True)
class FormulaComparison:
    mix_id: str
    component_id: str
    assumed_dm_bps: int
    target_dm_bps: int
    expected_g_dm: int
    expected_g_af: int
    actual_g_dm: int
    actual_g_af: int
    substitute_g_af: int


@dataclass(frozen=True)
class Mix:
    mix_id: str
    ration_version_id: str
    mixer_version_id: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    input: FeedAmount
    produced: FeedAmount
    loss: FeedAmount


@dataclass(frozen=True)
class TruckTicket(Document):
    mix_id: str
    delivery_plan_id: str
    truck_version_id: str
    loaded_g_af: int
    loss_g_af: int


@dataclass(frozen=True)
class Delivery:
    delivery_id: str
    plan_id: str
    mix_id: str
    truck_version_id: str
    pen_id: str
    window_start: datetime
    window_end: datetime
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    loaded: FeedAmount
    delivered: FeedAmount
    delivery_loss: FeedAmount


class Formulas:
    def __init__(self, masters, recipes, components):
        self.recipes = tuple(recipes)
        self.components = tuple(components)
        self.versions = {row.record_id: row for row in self.recipes}
        self.lines = defaultdict(list)
        keys = set()
        for row in self.components:
            if row.component_id in keys or row.ration_version_id not in self.versions:
                raise ValueError("duplicate formula component or unknown recipe version")
            keys.add(row.component_id)
            recipe = self.versions[row.ration_version_id]
            masters.get("ingredients", "ingredient_id", row.ingredient_id, recipe)
            if row.substitute_ingredient_id:
                masters.get("ingredients", "ingredient_id", row.substitute_ingredient_id, recipe)
            if not (0 < row.target_dm_bps <= BPS and 0 < row.assumed_dm_bps <= BPS
                    and 0 <= row.max_substitute_bps_af <= BPS
                    and bool(row.substitute_ingredient_id) == bool(row.max_substitute_bps_af)
                    and row.ingredient_id != row.substitute_ingredient_id):
                raise ValueError("invalid ration component proportions")
            self.lines[row.ration_version_id].append(row)
        if len(self.versions) != len(self.recipes):
            raise ValueError("duplicate ration version")
        for recipe in self.recipes:
            stages = set(recipe.eligible_stages.split(","))
            lines = self.lines[recipe.record_id]
            whole(recipe.target_kj_per_kg_dm, "ration energy", minimum=1)
            if (not stages <= {"adaptation", "finishing", "receiving", "hospital"}
                    or not 0 < recipe.target_cp_bps_dm <= BPS
                    or sum(row.target_dm_bps for row in lines) != BPS
                    or len({row.ingredient_id for row in lines}) != len(lines)):
                raise ValueError("invalid ration targets or eligibility")

    def at(self, ration_id, cutoff):
        recipe = _version(self.recipes, "ration_id", ration_id, cutoff, cutoff)
        if recipe is None:
            raise ValueError(f"no available recipe: {ration_id}")
        return recipe

    def targets(self, ration_version_id, planned_g_dm):
        lines = self.lines[ration_version_id]
        dm = split(planned_g_dm, {line.component_id: line.target_dm_bps for line in lines})
        return {line.component_id: (dm[line.component_id],
                                   half_up(dm[line.component_id] * BPS, line.assumed_dm_bps))
                for line in lines}


def mix_feed(masters, formulas, snapshot, orders, links):
    order_by_id = {row.record_id: row for row in orders}
    if len(order_by_id) != len(orders):
        raise ValueError("duplicate mix order")
    issues = defaultdict(list)
    for entry in snapshot.entries:
        if entry.kind == Kind.ISSUE:
            issues[entry.transaction_id].append(entry)
    inputs, comparisons, mixes = [], [], []
    linked = set()
    by_mix = defaultdict(list)
    for link in links:
        if link.transaction_id in linked or link.transaction_id not in issues or link.mix_id not in order_by_id:
            raise ValueError("missing or duplicated issue-to-mix link")
        linked.add(link.transaction_id)
        by_mix[link.mix_id].append(link)
    if linked != issues.keys():
        raise ValueError("ingredient issue missing a mix")
    for order in orders:
        recipe = formulas.versions[order.ration_version_id]
        if (formulas.at(recipe.ration_id, order.effective_at) != recipe
                or not order.effective_at <= order.posted_at):
            raise ValueError(f"mix used an ineligible formula or timestamp: {order.record_id}")
        mixer = masters.reference(order.mixer_version_id, Equipment, order.effective_at, order.effective_at)
        targets = formulas.targets(recipe.record_id, whole(order.planned_g_dm, "target DM", minimum=1))
        components = {row.component_id: row for row in formulas.lines[recipe.record_id]}
        actual = defaultdict(list)
        substitution = defaultdict(int)
        for link in by_mix[order.record_id]:
            component = components.get(link.component_id)
            if component is None:
                raise ValueError("issue linked to a component outside the mix formula")
            for entry in issues[link.transaction_id]:
                if (entry.effective_at > order.effective_at or entry.available_at > order.effective_at
                        or business_date(entry.effective_at) != business_date(order.effective_at)):
                    raise ValueError("issue must be available by mixing on the same business date")
                ingredient = masters.reference(entry.ingredient_version_id, Ingredient,
                                               entry.effective_at, entry.available_at)
                substituted = entry.ingredient_id != component.ingredient_id
                if substituted:
                    if (entry.ingredient_id != component.substitute_ingredient_id
                            or not (link.substitution_reason or "").strip()):
                        raise ValueError("unapproved ingredient substitution")
                    substitution[link.component_id] -= entry.g_af
                elif link.substitution_reason:
                    raise ValueError("substitution reason on regular ingredient")
                dm = -entry.g_dm
                amount = FeedAmount(-entry.g_af, dm, half_up(dm * ingredient.energy_kj_per_kg_dm, 1000),
                                    half_up(dm * ingredient.cp_bps_dm, BPS), -entry.cents)
                actual[link.component_id].append(amount)
                inputs.append(MixInput(
                    stable_id("MIX-INPUT", entry.entry_id), order.record_id, link.component_id,
                    link.transaction_id, entry.entry_id, entry.layer_id, entry.batch_id,
                    entry.ingredient_id, entry.ingredient_version_id, entry.assay_id, entry.dm_bps,
                    link.substitution_reason, amount))
        for component_id, component in components.items():
            expected_dm, expected_af = targets[component_id]
            observed = add_amounts(actual[component_id])
            substituted = substitution[component_id]
            if substituted * BPS > observed.g_af * component.max_substitute_bps_af:
                raise ValueError("mix exceeded substitution limit")
            comparisons.append(FormulaComparison(order.record_id, component_id, component.assumed_dm_bps,
                                                  component.target_dm_bps, expected_dm, expected_af,
                                                  observed.g_dm, observed.g_af, substituted))
        total = add_amounts(amount for values in actual.values() for amount in values)
        loss_g = whole(order.loss_g_af, "mix loss")
        if mixer.kind != "mixer" or not loss_g < total.g_af <= mixer.capacity_g_af:
            raise ValueError("empty mix, invalid loss or mixer capacity exceeded")
        amounts = partition(total, {"produced": total.g_af - loss_g, "mix_loss": loss_g})
        mixes.append(Mix(order.record_id, recipe.record_id, mixer.record_id, order.effective_at,
                         order.posted_at, order.available_at, total, amounts["produced"], amounts["mix_loss"]))
    return tuple(mixes), tuple(inputs), tuple(comparisons)


def dispatch(masters, mixes, tickets, plans):
    by_mix = defaultdict(list)
    seen = set()
    mix_ids = {mix.mix_id for mix in mixes}
    for ticket in tickets:
        if ticket.record_id in seen or ticket.mix_id not in mix_ids:
            raise ValueError("duplicate truck ticket or unknown mix")
        seen.add(ticket.record_id)
        by_mix[ticket.mix_id].append(ticket)
    for mix in mixes:
        rows = by_mix[mix.mix_id]
        portions = partition(mix.produced, {row.record_id: row.loaded_g_af for row in rows})
        for row in rows:
            plan = plans[row.delivery_plan_id]
            truck = masters.reference(row.truck_version_id, Equipment, row.effective_at, row.effective_at)
            if (truck.kind != "truck" or not 0 < row.loaded_g_af <= truck.capacity_g_af
                    or not 0 <= row.loss_g_af <= row.loaded_g_af
                    or not mix.available_at <= row.effective_at <= row.posted_at
                    or row.effective_at != plan.window_start
                    or business_date(mix.effective_at) != business_date(row.effective_at)
                    or plan.ration_version_id != mix.ration_version_id):
                raise ValueError("invalid mix dispatch timing, lineage or truck load")
            loaded = portions[row.record_id]
            outcome = partition(loaded, {"delivered": row.loaded_g_af - row.loss_g_af,
                                         "delivery_loss": row.loss_g_af})
            yield Delivery(row.record_id, plan.plan_id, mix.mix_id, truck.record_id, plan.pen_id,
                           plan.window_start, plan.window_end, row.effective_at, row.posted_at,
                           row.available_at, loaded, outcome["delivered"], outcome["delivery_loss"])
