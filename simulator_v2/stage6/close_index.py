"""Period activation and exact ordered fingerprints for the Stage 4 close."""

from bisect import bisect_left
from collections import Counter
from hashlib import sha256

from ..stage1.model import business_date
from ..stage1.provenance import canonical
from ..stage3.warehouse import Balance
from ..stage4.close import JournalSummary


class JournalVisibility:
    def __init__(self, periods, cutoffs):
        self.months = tuple(period.month for period in periods)
        self.cutoffs = tuple(cutoffs)
        if len(self.months) != len(self.cutoffs) or tuple(sorted(self.cutoffs)) != self.cutoffs:
            raise ValueError("close visibility requires a nondecreasing cutoff by month")

    def first(self, month, available_at):
        return max(bisect_left(self.months, month), bisect_left(self.cutoffs, available_at))


class OrderedFingerprints:
    """Share SHA-256 state while ordered journal prefixes are identical."""

    def __init__(self, size):
        self.size = size
        self.starts = [0]
        self.groups = [(sha256(b"["), 0)]

    def add(self, first, encoded):
        index = bisect_left(self.starts, first)
        if index == len(self.starts) or self.starts[index] != first:
            digest, count = self.groups[index - 1]
            self.starts.insert(index, first)
            self.groups.insert(index, (digest.copy(), count))
        for i in range(index, len(self.groups)):
            digest, count = self.groups[i]
            if count:
                digest.update(b",")
            digest.update(encoded)
            self.groups[i] = digest, count + 1

    def results(self):
        for i, (digest, count) in enumerate(self.groups):
            finalized = digest.copy()
            finalized.update(b"]\n")
            result = finalized.hexdigest(), count
            stop = self.starts[i + 1] if i + 1 < len(self.starts) else self.size
            yield from (result for _ in range(self.starts[i], stop))


class CloseIndex:
    def __init__(self, periods, cutoffs):
        self.visibility = JournalVisibility(periods, cutoffs)
        self.moves = [JournalSummary() for _ in periods]
        self.fingerprints = OrderedFingerprints(len(periods))

    def add(self, journals):
        visible = []
        for row in journals:
            first = self.visibility.first(row.accounting_month, row.available_at)
            if first < len(self.moves):
                self.moves[first].add(row, self.visibility.months[first])
                visible.append((first, row))
        self.add_fingerprints(visible)

    def add_fingerprints(self, visible):
        for first, row in visible:
            self.fingerprints.add(first, canonical(vars(row))[:-1])

    def checkpoints(self):
        rolling = JournalSummary()
        for index, (digest, count) in enumerate(self.fingerprints.results()):
            rolling.roll_forward(self.moves[index])
            self.moves[index] = None
            yield rolling, digest, count


def immediate_warehouse_closes(snapshot, periods):
    """Reduce independently replayed FIFO entries at month end for immediate feeds."""
    if any(row.effective_at != row.available_at for row in snapshot.entries):
        return {}
    if any(previous.effective_at > row.effective_at for previous, row in zip(snapshot.entries, snapshot.entries[1:])):
        return {}
    entries = iter(snapshot.entries)
    row = next(entries, None)
    balances = {}
    closes = {}
    for period in periods:
        while row is not None and row.effective_at < period.effective_before:
            key = row.bin_id, row.layer_id
            grams, cents = balances.get(key, (0, 0))
            grams, cents = grams + row.g_af, cents + row.cents
            if grams or cents:
                balances[key] = grams, cents
            else:
                balances.pop(key, None)
            row = next(entries, None)
        closes[period.month] = tuple(Balance(*key, *amounts) for key, amounts in sorted(balances.items()))
    return closes


def yardage_by_month(rows):
    return Counter(business_date(row.service_at).strftime("%Y-%m") for row in rows)
