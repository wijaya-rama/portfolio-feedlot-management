"""Atomic, date-partitioned Parquet publication with bounded table buffers."""

from collections import defaultdict
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from functools import cache
from hashlib import file_digest
from typing import get_args, get_origin, get_type_hints

import pyarrow as pa
import pyarrow.parquet as pq

from ..stage1.export import ARROW_TYPES
from ..stage1.model import business_date
from .config import SCHEMA

BATCH_ROWS = 8192
MAX_BUFFERED_ROWS = 65536


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


@cache
def field_names(record_type):
    return tuple(field.name for field in fields(record_type))


def _record_value(value):
    return {name: _record_value(v) if is_dataclass(type(v)) else v
            for name in field_names(type(value)) if (v := getattr(value, name)) is not None}


def record(row):
    return _record_value(row)


@cache
def _column_specs(record_type):
    """Precompute field extractors and nested-struct flags once per dataclass type."""
    annotations = get_type_hints(record_type)
    specs = []
    for field in fields(record_type):
        annotation = annotations[field.name]
        arguments = get_args(annotation)
        if type(None) in arguments:
            annotation = next(value for value in arguments if value is not type(None))
        pa_type = arrow_field(field.name, annotations[field.name]).type
        is_struct = is_dataclass(annotation)
        is_list_struct = (get_origin(annotation) is tuple and is_dataclass(get_args(annotation)[0]))
        specs.append((field.name, pa_type, is_struct, is_list_struct))
    return tuple(specs)


def _table_from_rows(rows, schema, run_id_scalar, specs):
    arrays = [pa.repeat(run_id_scalar, len(rows))]
    for name, pa_type, is_struct, is_list_struct in specs:
        if is_struct:
            values = [None if (v := getattr(r, name)) is None else _record_value(v) for r in rows]
        elif is_list_struct:
            values = [None if (v := getattr(r, name)) is None else [_record_value(item) for item in v] for r in rows]
        else:
            values = [getattr(r, name) for r in rows]
        arrays.append(pa.array(values, type=pa_type))
    return pa.Table.from_arrays(arrays, schema=schema)


def digest(path):
    with path.open("rb") as data:
        return file_digest(data, "sha256").hexdigest()


class Output:
    def __init__(self, root, run_id):
        self.root, self.run_id = root, run_id
        self._run_id_scalar = pa.scalar(run_id, type=pa.string())
        self.schemas, self._specs, self.partitions, self.writers, self.buffers = {}, {}, {}, {}, defaultdict(list)
        self.buffered_rows = 0
        self.sealed = set()

    def _register_table(self, table, row_type):
        self.schemas[table] = pa.schema([pa.field("run_id", pa.string(), nullable=False),
                                         *record_fields(row_type)],
                                        metadata={"schema_version": SCHEMA, "synthetic": "true"})
        self._specs[table] = _column_specs(row_type)

    def emit(self, table, rows, when=None, *, partition_by=None):
        if partition_by is None:
            if isinstance(when, datetime):
                month = business_date(when).isoformat()[:7]
            elif isinstance(when, date):
                month = when.isoformat()[:7]
            else:
                month = None
            key = table, month
            buf = None
            registered = table in self.schemas
            for row in rows:
                if buf is None:
                    if key in self.sealed:
                        raise ValueError(f"attempted to append to a finalized partition: {key}")
                    buf = self.buffers[key]
                if not registered:
                    self._register_table(table, type(row))
                    registered = True
                buf.append(row)
                self.buffered_rows += 1
                if len(buf) >= BATCH_ROWS:
                    self.flush(key)
                    buf = self.buffers[key]
                elif self.buffered_rows >= MAX_BUFFERED_ROWS:
                    self.flush(max(self.buffers, key=lambda partition: len(self.buffers[partition])))
                    buf = self.buffers[key]
            return

        registered = table in self.schemas
        for row in rows:
            if not registered:
                self._register_table(table, type(row))
                registered = True
            stamp = getattr(row, partition_by)
            if isinstance(stamp, datetime):
                stamp = business_date(stamp)
            month = stamp.isoformat()[:7] if isinstance(stamp, date) else None
            key = table, month
            if key in self.sealed:
                raise ValueError(f"attempted to append to a finalized partition: {key}")
            buf = self.buffers[key]
            buf.append(row)
            self.buffered_rows += 1
            if len(buf) >= BATCH_ROWS:
                self.flush(key)
            elif self.buffered_rows >= MAX_BUFFERED_ROWS:
                self.flush(max(self.buffers, key=lambda partition: len(self.buffers[partition])))

    def flush(self, key):
        rows = self.buffers.pop(key, [])
        if not rows:
            return
        self.buffered_rows -= len(rows)
        name, month = key
        relative = f"{name}/month={month}/part.parquet" if month else f"{name}/part.parquet"
        path = self.root / relative
        if key not in self.writers:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.writers[key] = pq.ParquetWriter(path, self.schemas[name], compression="zstd", version="2.6")
            self.partitions[relative] = {"table": name, "month": month, "rows": 0}
        self.writers[key].write_table(_table_from_rows(rows, self.schemas[name], self._run_id_scalar, self._specs[name]))
        self.partitions[relative]["rows"] += len(rows)

    def finalize_months(self, before):
        """Close partitions older than a frontier after daily generation is finished for them."""
        for key in sorted(set(self.buffers) | set(self.writers), key=lambda x: (x[0], x[1] or "")):
            if key[1] and key[1] < before:
                self.flush(key)
                self.writers.pop(key).close()
                self.sealed.add(key)

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
