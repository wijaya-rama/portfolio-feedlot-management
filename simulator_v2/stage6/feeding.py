"""Phase dispatch and timed intake with one published allocation method."""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import timedelta
from pickle import Pickler, Unpickler
from types import SimpleNamespace

from ..stage1.provenance import stable_id
from ..stage3.allocation import DEFAULT_METHOD, Allocation, BunkTicket, _scores, _weight, feed_plan, settle
from ..stage3.ration import MixIssue, MixOrder, TruckTicket, dispatch, mix_feed
from ..stage3.units import BPS, half_up, seconds, split
from ..stage3.warehouse import Kind
from ..stage3_5.feeding import TimedAllocation
from .livestock import TICK
from .warehouse import doc

ALLOCATION_VERSION = "stage6a-timed-metabolic.1"


@dataclass(frozen=True)
class PostingAllocationLink:
    posting_allocation_id: str
    release_allocation_id: str


def for_accounting(result):
    allocations, links = [], []
    by_animal = defaultdict(list)
    for row in result.allocations:
        by_animal[row.animal_id].append(row)
    for key, rows in by_animal.items():
        identifier = stable_id("FEED-POSTING-ALLOCATION", [result.row.settlement_id, key, DEFAULT_METHOD])
        if any(previous.access_end != following.access_start for previous, following in zip(rows, rows[1:])):
            raise ValueError("posting aggregation requires contiguous access at this delivery")
        amounts = {name: sum(getattr(row, name) for row in rows)
                   for name in ("duration_seconds", "g_dm", "energy_kj", "cp_g", "cents")}
        allocations.append(replace(rows[0], allocation_id=identifier, access_end=rows[-1].access_end, **amounts))
        links.extend(PostingAllocationLink(identifier, row.allocation_id) for row in rows)
    return replace(result, weights=(), allocations=tuple(allocations)), links


def empty_documents():
    return SimpleNamespace(mixes=[], mix_inputs=[], deliveries=[], settlements=[],
                           schedule=SimpleNamespace(bunk_tickets=[]))


class SelectedAllocation(TimedAllocation):
    """One score and one exposure per animal in each generated release slice."""

    def allocate(self, settlement, delivery, plan, exposures, weights, slices):
        scores = _scores(weights, DEFAULT_METHOD)
        scores = {key: value * self.intake_bps.get(key, BPS) for key, value in scores.items()}
        for first, last, eligible, pool in slices:
            if not eligible:
                continue
            active = [exposures[index] for index in eligible]
            drivers = {row.animal_id: scores[row.animal_id] for row in active}
            if len(drivers) != len(active):
                raise ValueError("duplicate active access in one release")
            dm = split(pool.g_dm, drivers)
            energy = split(pool.kj, dm)
            protein = split(pool.cp_g, dm)
            cost = split(pool.cents, dm if pool.g_dm else drivers)
            for row in active:
                key = row.animal_id
                weight = weights[key]
                yield Allocation(
                    stable_id("FEED-ALLOCATION", [row.exposure_id, DEFAULT_METHOD, self.version, first, last]),
                    settlement.settlement_id, row.exposure_id, delivery.delivery_id, delivery.mix_id,
                    key, row.lot_id, delivery.pen_id, delivery.window_start, delivery.window_end, first, last,
                    seconds(first, last), weight.weight_input_id, weight.estimate_id, plan.decision_at,
                    DEFAULT_METHOD, f"{self.version}.{DEFAULT_METHOD}", scores[key], dm[key],
                    energy[key], protein[key], cost[key], settlement.finalized_at, settlement.available_at)


class Feeding:
    def __init__(self, yard, supply, weights, config, calibration, emit, spool):
        self.yard, self.supply, self.weights, self.emit = yard, supply, weights, emit
        self.config = config
        self.p = config["warehouse"]
        self.planning = {"version": "stage6a-window-plan.1", "fallback_weight_g": 400000,
                         "clinical_intake_bps": calibration["clinical_intake_bps"],
                         "stage_dm_g_per_window": {
                             stage: round(row["dm_kg_per_day"] * 500)
                             for stage, row in yard.bio["rations"].items()},
                         "intake_limit_bps_per_window": 120}
        self.access_ids = set()
        self.stride = timedelta(minutes=config["release_minutes"])
        self.documents = empty_documents()
        self.spool = spool
        min_dm = max(1, min(item.standard_dm_bps for item in supply.masters.ingredients) - 175)
        capacity = min(supply.mixer.capacity_g_af, supply.truck.capacity_g_af)
        self.max_load_dm = capacity * min_dm // BPS - len(supply.masters.ingredients)
        if self.max_load_dm < 1:
            raise ValueError("equipment cannot mix the minimum ration quantity")

    def window(self, start, end):
        snapshot, estimates = self.weights.freeze(start, self.yard.active.values())
        pens = defaultdict(dict)
        clinical = {key: row.clinical_status for key, row in estimates.items()}
        fallback_g = self.planning["fallback_weight_g"]
        for key, estimate in estimates.items():
            pens[estimate.location_id][key] = _weight(key, start, snapshot.snapshot_id, fallback_g, estimate)
        for rows in pens.values():
            self.emit("feeding_weight_inputs", rows.values(), start)
        count = (end - start - TICK) // self.stride
        clock = tuple(start + (i + 1) * self.stride for i in range(count))
        policy = SelectedAllocation({(start, end): clock}, ALLOCATION_VERSION, self.planning["clinical_intake_bps"])
        policy.bind_clinical(estimates.values())
        allocations = []
        for pen, frozen in sorted(pens.items()):
            stages = {row.production_stage for row in frozen.values()}
            stage = "adaptation" if "adaptation" in stages else next(iter(stages))
            ration = f"SYN-RATION-{stage.upper()}"
            plan = feed_plan(pen, start, end, snapshot, frozen, self.supply.formulas, ration, self.planning,
                             clinical_statuses=clinical)
            self.emit("feed_plans", [plan], start)
            intervals = tuple(replace(self.yard.active[key].interval, end_at=end) for key in frozen)
            event_ids = sorted({row.start_event_id for row in intervals})
            replay = SimpleNamespace(effective_before=end + TICK, knowledge_cutoff=end, animals=(),
                                     lots=(), location_versions=(),
                                     events=tuple(self.yard.events[key] for key in event_ids), states=(),
                                     intervals=intervals)
            remaining, part = plan.planned_g_dm, 1
            while remaining:
                target = min(remaining, self.max_load_dm)
                allocations.extend(self.load(plan, frozen, replay, policy, part, target))
                remaining -= target
                part += 1
        return tuple(allocations), clock

    def load(self, plan, frozen, replay, policy, part, target_dm):
        supply, p = self.supply, self.p
        start, end = plan.window_start, plan.window_end
        mix_id = f"{plan.plan_id}-M{part:03d}"
        components = supply.formulas.lines[plan.ration_version_id]
        targets = supply.formulas.targets(plan.ration_version_id, target_dm)
        requests = []
        for row in components:
            dm = targets[row.component_id][0]
            if not dm:
                continue
            grams = supply.grams_for_dm(row.ingredient_id, dm, start)
            if grams is None:
                supply.shortage(start, mix_id, row.ingredient_id, dm)
                return ()
            requests.append((row, grams))
        total = sum(amount for _, amount in requests)
        entries, links = [], []
        for row, grams in requests:
            key = row.ingredient_id
            source, legs = supply.apply(Kind.ISSUE, start, supply.main[key], key, grams)
            entries.extend(legs)
            links.append(MixIssue(source.record_id, mix_id, row.component_id))
        draw = self.yard.draw
        # Physical randomness uses intrinsic operating coordinates, independent of the
        # configuration hash, financial policy, and identifiers derived from snapshot identity.
        random_key = (plan.pen_id, start.isoformat(), part)
        mix_loss = draw.integer("feed/mix-loss", 0, p["max_mix_loss_bps"], *random_key)
        order = MixOrder(*doc(mix_id, start), plan.ration_version_id, supply.mixer.record_id,
                         target_dm, half_up(total * mix_loss, BPS))
        mixes, inputs, comparisons = mix_feed(supply.masters, supply.formulas,
                                              SimpleNamespace(entries=entries), (order,), links)
        mix = mixes[0]
        distribution_loss = draw.integer("feed/distribution-loss", 0, p["max_distribution_loss_bps"], *random_key)
        load = TruckTicket(*doc(f"{mix_id}-TRUCK", start), mix_id, plan.plan_id, supply.truck.record_id,
                           mix.produced.g_af, half_up(mix.produced.g_af * distribution_loss, BPS))
        delivery, = dispatch(supply.masters, mixes, (load,), {plan.plan_id: plan})
        ref_bps = draw.integer("feed/refusal", *p["refusal_bps"], *random_key)
        bunk_bps = draw.integer("feed/bunk-loss", 0, p["max_bunk_loss_bps"], *random_key)
        ticket = BunkTicket(*doc(f"{delivery.delivery_id}-BUNK", end), delivery.delivery_id,
                            half_up(delivery.delivered.g_af * ref_bps, BPS),
                            half_up(delivery.delivered.g_af * bunk_bps, BPS))
        result = settle(None, delivery, plan, ticket, frozen, self.planning["fallback_weight_g"],
                        replay=replay, allocation_policy=policy)
        if result.access.access_snapshot_id not in self.access_ids:
            self.emit("feed_access_snapshots", [result.access], start)
            self.access_ids.add(result.access.access_snapshot_id)
        self.documents.mixes.append(mix)
        self.documents.mix_inputs.extend(inputs)
        self.documents.deliveries.append(delivery)
        self.documents.schedule.bunk_tickets.append(ticket)
        posting, links_to_releases = for_accounting(result)
        self.documents.settlements.append(posting)
        for table, rows in (
            ("mix_orders", [order]), ("mix_issue_links", links), ("mixes", mixes), ("mix_inputs", inputs),
            ("formula_comparisons", comparisons), ("truck_tickets", [load]), ("feed_deliveries", [delivery]),
            ("bunk_tickets", [ticket]), ("bunk_settlements", [result.row]),
            ("feed_exposures", result.exposures), ("feed_allocations", result.allocations),
            ("accounting_feed_allocations", posting.allocations), ("posting_allocation_links", links_to_releases),
            ("feed_releases", policy.evidence(result, delivery, ticket)),
        ):
            self.emit(table, rows, start)
        return result.allocations

    def checkpoint(self):
        if self.documents.deliveries:
            with self.spool.open("ab") as stream:
                Pickler(stream, protocol=5).dump(self.documents)
        self.documents = empty_documents()
        self.access_ids.clear()

    def read_checkpoints(self):
        if not self.spool.exists():
            return
        with self.spool.open("rb") as stream:
            while stream.peek(1):
                yield Unpickler(stream).load()
