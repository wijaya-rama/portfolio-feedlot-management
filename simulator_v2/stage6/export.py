"""Atomic, date-partitioned Parquet publication with bounded table buffers."""

from collections import defaultdict
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from hashlib import file_digest
from typing import get_args, get_origin, get_type_hints

import pyarrow as pa
import pyarrow.parquet as pq

from ..stage1.export import ARROW_TYPES
from ..stage1.model import business_date
from .config import SCHEMA

BATCH_ROWS = 8192


def arrow_field(name, annotation):
    arguments = get_args(annotation)
    nullable = type(None) in arguments
    if nullable:
        annotation = next(value for value in arguments if value is not type(None))
    if is_dataclass(annotation):
        datatype = pa.struct(record_fields(annotation))
    elif annotation is float:
        datatype = pa.float64()
    elif get_origin(annotation) is tuple:
        datatype = pa.list_(arrow_field("item", get_args(annotation)[0]).type)
    elif issubclass(annotation, StrEnum):
        datatype = pa.string()
    else:
        datatype = ARROW_TYPES[annotation]
    return pa.field(name, datatype, nullable=nullable)


def record_fields(record_type):
    annotations = get_type_hints(record_type)
    return [arrow_field(field.name, annotations[field.name]) for field in fields(record_type)]


def record(row):
    return {field.name: value if not is_dataclass(value) else record(value)
            for field in fields(row) if (value := getattr(row, field.name)) is not None}


def digest(path):
    with path.open("rb") as data:
        return file_digest(data, "sha256").hexdigest()


class Output:
    def __init__(self, root, run_id):
        self.root, self.run_id = root, run_id
        self.schemas, self.partitions, self.writers, self.buffers = {}, {}, {}, defaultdict(list)

    def emit(self, table, rows, when=None, *, partition_by=None):
        for row in rows:
            if table not in self.schemas:
                self.schemas[table] = pa.schema([pa.field("run_id", pa.string(), nullable=False),
                                                *record_fields(type(row))],
                                               metadata={"schema_version": SCHEMA, "synthetic": "true"})
            stamp = getattr(row, partition_by) if partition_by else when
            if isinstance(stamp, datetime):
                stamp = business_date(stamp)
            month = stamp.strftime("%Y-%m") if isinstance(stamp, date) else None
            key = table, month
            self.buffers[key].append({"run_id": self.run_id, **record(row)})
            if len(self.buffers[key]) >= BATCH_ROWS:
                self.flush(key)

    def flush(self, key):
        rows = self.buffers.pop(key, [])
        if not rows:
            return
        name, month = key
        relative = f"{name}/month={month}/part.parquet" if month else f"{name}/part.parquet"
        path = self.root / relative
        if key not in self.writers:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.writers[key] = pq.ParquetWriter(path, self.schemas[name], compression="zstd", version="2.6")
            self.partitions[relative] = {"table": name, "month": month, "rows": 0}
        self.writers[key].write_table(pa.Table.from_pylist(rows, schema=self.schemas[name]))
        self.partitions[relative]["rows"] += len(rows)

    def finalize_months(self, before):
        """Close partitions older than a frontier after daily generation is finished for them."""
        for key in sorted(set(self.buffers) | set(self.writers), key=lambda x: (x[0], x[1] or "")):
            if key[1] and key[1] < before:
                self.flush(key)
                self.writers.pop(key).close()

    def finish(self):
        for key in sorted(self.buffers, key=lambda x: (x[0], x[1] or "")):
            self.flush(key)
        self.abort()
        for relative, details in sorted(self.partitions.items()):
            path = self.root / relative
            pq_file = pq.ParquetFile(path)
            if pq_file.metadata.num_rows != details["rows"]:
                raise ValueError(f"Parquet row count mismatch: {relative}")
            details.update(bytes=path.stat().st_size, sha256=digest(path))
        return self.partitions

    def abort(self):
        for writer in self.writers.values():
            writer.close()
        self.writers.clear()
