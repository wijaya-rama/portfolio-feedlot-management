"""Advance the Stage 2 equations only through the current integration boundary."""

from collections import defaultdict

from ..stage3.biology import LedgerBiology, LedgerFeed


class ChronologicalFeed(LedgerFeed):
    version = "chronological-ledger-consumption.1"

    def __init__(self, method, windows_per_day):
        super().__init__((), method, windows_per_day)
        self.index = defaultdict(list)

    def add(self, allocations):
        for row in allocations:
            if row.method == self.method:
                self.index[row.animal_id, row.pen_id, row.window_start, row.window_end].append(row)


class ChronologicalBiology(LedgerBiology):
    def __init__(self, timeline, profiles, health, weather, config, *, adapter, clock):
        self.timeline = timeline
        self.clock = clock
        self.streams = self._growth_streams(timeline, profiles, health, weather, config, adapter)
        self.steps_by_animal = {key: [] for key in self.streams}
        self.start_times = {key: [] for key in self.streams}
        self.through = None

    def _additional_growth_points(self, windows):
        return (point for window in windows for point in self.clock.get(window, ()))

    def advance(self, through):
        if self.through is not None and through < self.through:
            raise ValueError("biological clock cannot run backward")
        for animal_id, stream in self.streams.items():
            steps = self.steps_by_animal[animal_id]
            cursor = steps[-1].end_at if steps else self.timeline.entries[animal_id].effective_at
            stop = min(through, self.timeline.stop_at(animal_id))
            while cursor < stop:
                row = next(stream)
                if row.start_at != cursor or row.end_at > stop:
                    raise ValueError("advance must end on a biological boundary")
                steps.append(row)
                self.start_times[animal_id].append(row.start_at)
                cursor = row.end_at
        self.through = through

    def weight_at(self, animal_id, instant):
        if self.through is None or instant > self.through:
            raise ValueError("weight requested ahead of the biological clock")
        entry = self.timeline.entries[animal_id].effective_at
        if instant == entry:
            return self.profiles[animal_id].entry_weight_kg
        return super().weight_at(animal_id, instant)

    @property
    def steps(self):
        return tuple(row for rows in self.steps_by_animal.values() for row in rows)
