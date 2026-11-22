"""Private disk-backed staging for journal input, output and source lineage."""

from collections import OrderedDict
from collections.abc import Mapping
from itertools import groupby
from pickle import dumps, loads
from sqlite3 import connect

from ..stage4.ledger import Sources

CACHE_ROWS = 4096


class StoredRecords(Mapping):
    def __init__(self, database, name):
        self.database, self.name = database, name
        database.execute(f"CREATE TABLE {name} (key TEXT UNIQUE NOT NULL, data BLOB NOT NULL)")
        self.length = 0
        self.cache = OrderedDict()

    def __len__(self):
        return self.length

    def __iter__(self):
        return (key for key, in self.database.execute(f"SELECT key FROM {self.name} ORDER BY rowid"))

    def __getitem__(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        result = self.database.execute(f"SELECT data FROM {self.name} WHERE key = ?", (key,)).fetchone()
        if result is None:
            raise KeyError(key)
        value = loads(result[0])
        self.remember(key, value)
        return value

    def values(self):
        rows = self.database.execute(f"SELECT data FROM {self.name} ORDER BY rowid")
        yield from (loads(data) for data, in rows)

    def __setitem__(self, key, value):
        self.database.execute(f"INSERT INTO {self.name} VALUES (?, ?)", (key, dumps(value, protocol=5)))
        self.length += 1
        self.remember(key, value)

    def remember(self, key, value):
        self.cache[key] = value
        if len(self.cache) > CACHE_ROWS:
            self.cache.popitem(last=False)


class SourceLinks:
    def __init__(self, emit):
        self.emit = emit

    def update(self, links):
        self.emit("financial_source_links", sorted(links, key=lambda row: (row.source_id, row.parent_id)))


class FinanceStore:
    def __init__(self, path, emit):
        self.database = db = connect(path)
        self.emit = emit
        db.executescript("""
            CREATE TABLE actions (key TEXT PRIMARY KEY, as_known TEXT NOT NULL,
                                  restated TEXT NOT NULL, data BLOB NOT NULL);
        """)
        self.sources = Sources()
        self.sources.rows = StoredRecords(db, "sources")
        self.sources.parents = StoredRecords(db, "source_parents")
        self.sources.links = SourceLinks(emit)

    def append(self, action):
        if action.reverses:
            raise ValueError("Stage 6 staging supports immutable signed deltas only")
        source = self.sources.rows[action.source_id]
        known = source.available_at
        restated = action.restate_at or known
        self.database.execute("INSERT INTO actions VALUES (?, ?, ?, ?)",
                              (action.key, known.date().isoformat(), restated.date().isoformat(),
                               dumps(action, protocol=5)))

    def extend(self, actions):
        for row in actions:
            self.append(row)

    def batches(self, view):
        if view not in {"as_known", "restated"}:
            raise ValueError(f"unknown accounting view {view}")
        self.database.execute(f"CREATE INDEX actions_{view} ON actions ({view})")
        rows = self.database.execute(f"SELECT {view}, data FROM actions ORDER BY {view}, rowid")
        for _, group in groupby(rows, key=lambda row: row[0]):
            yield (loads(data) for _, data in group)

    def close(self):
        self.database.close()
