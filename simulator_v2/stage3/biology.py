"""Apply versioned feed consumption to the existing Stage 2 growth equations."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from ..stage1.provenance import stable_id
from ..stage2.biology import Biology
from ..stage2.feed import FeedSegment
from .allocation import Method
from .units import seconds


@dataclass(frozen=True)
class GrowthInput:
    growth_input_id: str
    allocation_id: str
    animal_id: str
    pen_id: str
    step_start: datetime
    step_end: datetime
    g_dm: int
    energy_kj: int
    cp_g: int
    allocation_available_at: datetime


class LedgerFeed:
    version = "ledger-consumption.1"

    def __init__(self, allocations, method, windows_per_day):
        self.method = Method(method)
        self.windows_per_day = windows_per_day
        grouped = defaultdict(list)
        for row in allocations:
            if row.method == self.method:
                grouped[row.animal_id, row.pen_id, row.window_start, row.window_end].append(row)
        self.index = {key: tuple(rows) for key, rows in grouped.items()}

    def sources(self, animal, pen, start, end, window):
        for row in self.index.get((animal, pen, *window), ()):
            first, last = max(start, row.access_start), min(end, row.access_end)
            if first >= last:
                continue
            dm_before = row.g_dm * seconds(row.access_start, first) // row.duration_seconds
            dm_after = row.g_dm * seconds(row.access_start, last) // row.duration_seconds
            energy = protein = 0
            if row.g_dm:
                energy = row.energy_kj * dm_after // row.g_dm - row.energy_kj * dm_before // row.g_dm
                protein = row.cp_g * dm_after // row.g_dm - row.cp_g * dm_before // row.g_dm
            yield GrowthInput(
                stable_id("GROWTH-FEED", [row.allocation_id, start, end]), row.allocation_id,
                animal, pen, start, end, dm_after - dm_before, energy, protein, row.available_at)

    def consume_for(self, animal, pen, *, start, end, window):
        if not window[0] <= start < end <= window[1]:
            raise ValueError("feed segment outside feeding window")
        sources = tuple(self.sources(animal, pen, start, end, window))
        dm = sum(row.g_dm for row in sources)
        share = seconds(start, end) / seconds(*window) / self.windows_per_day
        # Stage 2 calls the first amount "demand". In the ledger scenario it is
        # the supplied pool; plan demand is recorded separately by pen.
        return FeedSegment(start, end, share, dm, dm, sum(row.energy_kj for row in sources) / 1000,
                           sum(row.cp_g for row in sources) / 1000, self.version)

    def growth_inputs(self, biology):
        return tuple(source for row in biology.steps if row.window_start_at is not None
                     for source in self.sources(row.animal_id, row.location_id, row.start_at, row.end_at,
                                                (row.window_start_at, row.window_end_at)))


class LedgerBiology(Biology):
    def __init__(self, timeline, profiles, health, weather, config, *, adapter):
        if not isinstance(adapter, LedgerFeed):
            raise TypeError("Stage 3 growth requires a ledger-backed feed adapter")
        super().__init__(timeline, profiles, health, weather, config, adapter=adapter)

    def _consume_feed(self, animal_id, location_id, *, start, end, window, stage,
                      start_weight_kg, health_burden, weather):
        # Latent weight, weather and health still affect metabolism in Biology.
        # They cannot change the immutable grams supplied by the operational ledger.
        return self.adapter.consume_for(animal_id, location_id, start=start, end=end, window=window)
