"""Release only the current time slice's feed to animals with physical access."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise

from ..stage1.provenance import stable_id
from ..stage3.allocation import _allocate
from ..stage3.ration import EMPTY, FeedAmount, add_amounts, partition
from ..stage3.units import seconds, whole
from ..stage3.warehouse import Kind, Warehouse, _Projection


@dataclass(frozen=True)
class FeedRelease:
    release_id: str
    settlement_id: str
    delivery_id: str
    start_at: datetime
    end_at: datetime
    eligible_head: int
    g_af: int
    g_dm: int
    energy_kj: int
    cp_g: int
    cents: int


def growth_clock(windows, timeline, weather, health, config, release_minutes):
    stride = timedelta(minutes=whole(release_minutes, "release interval", minimum=1))
    adaptation = timedelta(days=config["biology"]["adaptation_days"])
    natural = {
        *(row.start_at for rows in timeline.intervals.values() for row in rows),
        *(row.effective_at for row in timeline.exits.values()),
        *(row.effective_at + adaptation for row in timeline.entries.values()),
        *(row.effective_at for row in health),
        *(row.observed_at for row in weather),
    }
    clock = {}
    for start, end in windows:
        scheduled = (start + i * stride for i in range(1, (end - start) // stride + 1))
        clock[start, end] = tuple(sorted({point for point in (*natural, *scheduled) if start < point < end}))
    return clock


def _released(pool, elapsed, duration):
    if not pool.g_af:
        return EMPTY
    af = pool.g_af * elapsed // duration
    dm = pool.g_dm * af // pool.g_af
    kj = pool.kj * dm // pool.g_dm if pool.g_dm else 0
    cp = pool.cp_g * dm // pool.g_dm if pool.g_dm else 0
    return FeedAmount(af, dm, kj, cp, pool.cents * af // pool.g_af)


def _difference(after, before):
    return FeedAmount(after.g_af - before.g_af, after.g_dm - before.g_dm, after.kj - before.kj,
                      after.cp_g - before.cp_g, after.cents - before.cents)


class TimedAllocation:
    def __init__(self, clock, version, clinical_intake_bps=None):
        self.clock = clock
        self.version = version
        self.clinical_intake_bps = clinical_intake_bps or {}
        self.intake_bps = {}

    def bind_clinical(self, estimates):
        self.intake_bps = {row.animal_id: self.clinical_intake_bps[row.clinical_status]
                           for row in estimates if row.clinical_status in self.clinical_intake_bps}

    def release(self, delivery, intervals, amounts):
        start, end = delivery.window_start, delivery.window_end
        boundaries = {start, end, *self.clock[start, end]}
        for _, _, first, last, _, _ in intervals:
            boundaries.update((first, last))
        duration = seconds(start, end)
        cumulative = EMPTY
        slices = []
        for first, last in pairwise(sorted(boundaries)):
            next_amount = _released(amounts["consumption"], seconds(start, last), duration)
            pool = _difference(next_amount, cumulative)
            cumulative = next_amount
            eligible = tuple(index for index, (_, _, entry, exit, _, _) in enumerate(intervals)
                             if entry <= first < last <= exit)
            slices.append((first, last, eligible, pool))
        consumed = add_amounts(pool for _, _, eligible, pool in slices if eligible)
        unused = add_amounts(pool for _, _, eligible, pool in slices if not eligible)
        return {**amounts, "consumption": consumed,
                "refusal": add_amounts((amounts["refusal"], unused))}, tuple(slices)

    def allocate(self, settlement, delivery, plan, exposures, weights, slices):
        intake_bps = None if plan.status == "scripted_dispatch" else self.intake_bps
        for first, last, eligible, pool in slices:
            if not eligible:
                continue
            access = (replace(exposures[index], first_at=first, end_at=last,
                              duration_seconds=seconds(first, last)) for index in eligible)
            yield from _allocate(settlement, delivery, plan, access, weights, pool=pool,
                                 model_version=self.version, intake_bps=intake_bps)

    def evidence(self, settlement, delivery, ticket):
        amounts = partition(delivery.delivered, {
            "refusal": ticket.observed_refusal_g_af, "bunk_loss": ticket.bunk_loss_g_af,
            "consumption": delivery.delivered.g_af - ticket.observed_refusal_g_af - ticket.bunk_loss_g_af,
        })
        intervals = tuple((row.animal_id, row.lot_id, row.first_at, row.end_at,
                           row.movement_in_id, row.movement_out_id) for row in settlement.exposures)
        _, slices = self.release(delivery, intervals, amounts)
        for first, last, eligible, pool in slices:
            yield FeedRelease(stable_id("FEED-RELEASE", [settlement.row.settlement_id, first, last]),
                              settlement.row.settlement_id, delivery.delivery_id, first, last,
                              len(eligible), pool.g_af, pool.g_dm, pool.kj, pool.cp_g, pool.cents)


@dataclass(frozen=True)
class WindowIssues:
    entries: tuple


class IssueBook:
    """Resolve FIFO with documents known at service time, then cross-check closing replay."""

    def __init__(self, masters, transactions):
        self.documents = iter(sorted(Warehouse(masters, transactions).transactions, key=lambda row: (
            row.available_at, row.effective_at, row.sequence, row.record_id)))
        self.pending = next(self.documents, None)
        self.state = _Projection(masters)

    def issue(self, cutoff, rows):
        while self.pending is not None and self.pending.available_at <= cutoff:
            self.state.apply(self.pending)
            self.pending = next(self.documents, None)
        first = len(self.state.entries)
        for row in rows:
            if row.kind != Kind.ISSUE or row.available_at != cutoff:
                raise ValueError("only current-window issues can enter the FIFO issue book")
            self.state.apply(row)
        return WindowIssues(tuple(self.state.entries[first:]))
