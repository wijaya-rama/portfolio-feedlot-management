"""Private disk-backed staging for journal input, output and source lineage."""

from collections import OrderedDict
from collections.abc import Mapping
from itertools import groupby
from pickle import dumps, loads
from sqlite3 import connect

from ..stage4.ledger import Sources

CACHE_ROWS = 32768
WRITE_BATCH = 4096


class StoredRecords(Mapping):
    def __init__(self, database, name, *, on_insert=None):
        self.database, self.name = database, name
        self._on_insert = on_insert
        database.execute(f"CREATE TABLE {name} (key TEXT UNIQUE NOT NULL, data BLOB NOT NULL)")
        self.length = 0
        self.keys_seen = set()
        self.cache = OrderedDict()
        self._pending = []

    def _flush_pending(self):
        if self._pending:
            self.database.executemany(f"INSERT INTO {self.name} VALUES (?, ?)", self._pending)
            self._pending.clear()

    def __len__(self):
        return self.length

    def __contains__(self, key):
        return key in self.keys_seen

    def __iter__(self):
        self._flush_pending()
        return (key for key, in self.database.execute(f"SELECT key FROM {self.name} ORDER BY rowid"))

    def __getitem__(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key not in self.keys_seen:
            raise KeyError(key)
        self._flush_pending()
        result = self.database.execute(f"SELECT data FROM {self.name} WHERE key = ?", (key,)).fetchone()
        if result is None:
            raise KeyError(key)
        value = loads(result[0])
        self.remember(key, value)
        return value

    def values(self):
        self._flush_pending()
        rows = self.database.execute(f"SELECT data FROM {self.name} ORDER BY rowid")
        yield from (loads(data) for data, in rows)

    def __setitem__(self, key, value):
        self._pending.append((key, dumps(value, protocol=5)))
        self.keys_seen.add(key)
        self.length += 1
        self.remember(key, value)
        if self._on_insert is not None:
            self._on_insert(value)
        if len(self._pending) >= WRITE_BATCH:
            self._flush_pending()

    def remember(self, key, value):
        self.cache[key] = value
        if len(self.cache) > CACHE_ROWS:
            self.cache.popitem(last=False)


class SourceLinks:
    def __init__(self, emit):
        self.emit = emit

    def update(self, links):
        ordered = sorted(links, key=lambda row: (row.source_id, row.parent_id))
        if ordered:
            self.emit("financial_source_links", ordered)


class IndexedSources(Sources):
    def __init__(self, database, emit):
        super().__init__()
        self._approvals = {}
        self._emit = emit

        def _on_source(value):
            if value.system == "stage4/approvals":
                earlier = self._approvals.get(value.document_id)
                if earlier is None or value.available_at < earlier:
                    self._approvals[value.document_id] = value.available_at
            emit("financial_sources", (value,), value.effective_at)

        self.rows = StoredRecords(database, "sources", on_insert=_on_source)
        self.parents = StoredRecords(database, "source_parents")
        self.links = SourceLinks(emit)

    def has_approval(self, document_id, cutoff):
        available = self._approvals.get(document_id)
        return available is not None and available <= cutoff


class FinanceStore:
    def __init__(self, path, emit):
        self.database = db = connect(path)
        self.emit = emit
        db.executescript("""
            PRAGMA synchronous = OFF;
            PRAGMA journal_mode = OFF;
            PRAGMA temp_store = MEMORY;
            PRAGMA cache_size = -64000;
            CREATE TABLE actions (key TEXT PRIMARY KEY, as_known TEXT NOT NULL,
                                  restated TEXT NOT NULL, data BLOB NOT NULL);
        """)
        self.sources = IndexedSources(db, emit)
        self._pending_actions = []

    def _flush_actions(self):
        if self._pending_actions:
            self.database.executemany("INSERT INTO actions VALUES (?, ?, ?, ?)", self._pending_actions)
            self._pending_actions.clear()

    def append(self, action):
        if action.reverses:
            raise ValueError("Stage 6 staging supports immutable signed deltas only")
        source = self.sources.rows[action.source_id]
        known = source.available_at
        restated = action.restate_at or known
        self._pending_actions.append((action.key, known.date().isoformat(), restated.date().isoformat(),
                                      dumps(action, protocol=5)))
        if len(self._pending_actions) >= WRITE_BATCH:
            self._flush_actions()

    def extend(self, actions):
        for row in actions:
            self.append(row)

    def batches(self, view):
        if view not in {"as_known", "restated"}:
            raise ValueError(f"unknown accounting view {view}")
        self._flush_actions()
        self.sources.rows._flush_pending()
        self.sources.parents._flush_pending()
        self.database.execute(f"CREATE INDEX IF NOT EXISTS actions_{view} ON actions ({view})")
        rows = self.database.execute(f"SELECT {view}, data FROM actions ORDER BY {view}, rowid")
        for _, group in groupby(rows, key=lambda row: row[0]):
            yield (loads(data) for _, data in group)

    def close(self):
        self.database.close()
