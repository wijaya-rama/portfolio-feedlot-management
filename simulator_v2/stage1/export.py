"""Typed Parquet exports with canonical, format-independent row hashes."""

import json
from pathlib import Path

from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import get_args, get_type_hints

import pyarrow as pa
import pyarrow.parquet as pq

from .ledger import Ledger
from .model import Animal, AnimalEvent, EventKind, LocationKind, LocationVersion, Lot, RunConfig, Source
from .model import business_date
from .provenance import canonical, sha256, stable_id
from .validation import require

ARROW_TYPES = {
    str: pa.string(), int: pa.int64(), bool: pa.bool_(),
    date: pa.date32(), datetime: pa.timestamp("us", tz="UTC"),
}


def arrow_field(name, annotation):
    args = get_args(annotation)
    nullable = type(None) in args
    if nullable:
        annotation = next(arg for arg in args if arg is not type(None))
    if is_dataclass(annotation):
        datatype = pa.struct(arrow_fields(annotation))
    elif issubclass(annotation, StrEnum):
        datatype = pa.string()
    else:
        datatype = ARROW_TYPES[annotation]
    return pa.field(name, datatype, nullable=nullable)


def arrow_fields(record_type):
    annotations = get_type_hints(record_type)
    return [arrow_field(field.name, annotations[field.name]) for field in fields(record_type)]


def write_table(folder, name, record_type, records, run_id, snapshot_id=None, *, jsonl=False):
    schema = [pa.field("run_id", pa.string(), nullable=False)]
    context = {"run_id": run_id}
    if snapshot_id is not None:
        schema.append(pa.field("snapshot_id", pa.string(), nullable=False))
        context["snapshot_id"] = snapshot_id
    schema.extend(arrow_fields(record_type))
    rows = [{**context, **asdict(record)} for record in records]
    if record_type is AnimalEvent:
        schema.append(pa.field("business_date", pa.date32(), nullable=False))
        for row in rows:
            row["business_date"] = business_date(row["effective_at"])

    canonical_rows = b"".join(map(canonical, rows))
    file = folder / f"{name}.parquet"
    table = pa.Table.from_pylist(rows, schema=pa.schema(schema))
    pq.write_table(table, file, compression="zstd", version="2.6")
    hashes = {file.name: sha256(file.read_bytes())}
    if jsonl:
        file = folder / f"{name}.jsonl"
        file.write_bytes(canonical_rows)
        hashes[file.name] = sha256(canonical_rows)
    return {"rows": len(rows), "canonical_sha256": sha256(canonical_rows), "files": hashes,
            "synthetic": True}


def load_ledger(folder):
    """Verify and reload the source tables from a completed, immutable build."""
    folder = Path(folder)
    manifest = json.loads((folder / "run_manifest.json").read_bytes())
    hashes_bytes = (folder / "hashes.json").read_bytes()
    require(sha256(hashes_bytes) == manifest["hashes_sha256"], "EXPORT_HASH", "run",
            manifest["hashes_sha256"], sha256(hashes_bytes), "hashes.json")
    hashes = json.loads(hashes_bytes)
    settings = manifest["config"]
    require(sha256(canonical(settings)) == manifest["config_sha256"], "EXPORT_HASH", "run",
            manifest["config_sha256"], sha256(canonical(settings)), "config")
    config = RunConfig(**{**settings, "start_date": date.fromisoformat(settings["start_date"]),
                          "end_date": date.fromisoformat(settings["end_date"])})
    run_id = stable_id("RUN", config)
    require(run_id == manifest["run_id"] == hashes["run_id"], "EXPORT_RUN", "run",
            run_id, (manifest["run_id"], hashes["run_id"]))

    def rows(name):
        file = folder / f"{name}.parquet"
        expected = hashes["files"][file.name]
        data = file.read_bytes()
        actual = sha256(data)
        require(actual == expected, "EXPORT_HASH", name, expected, actual, file.name)
        records = pq.read_table(pa.BufferReader(data)).to_pylist()
        for record in records:
            recorded_run = record.pop("run_id")
            require(recorded_run == run_id, "EXPORT_RUN", name, run_id, recorded_run)
        return records

    ledger = Ledger(config, (Lot(**row) for row in rows("lots")),
                    (Animal(**row) for row in rows("animals")),
                    (LocationVersion(**{**row, "kind": LocationKind(row["kind"])})
                     for row in rows("locations")))
    events = []
    for row in rows("animal_events"):
        day = row.pop("business_date")
        require(day == business_date(row["effective_at"]), "EXPORT_BUSINESS_DATE", "event",
                business_date(row["effective_at"]), day, row["event_id"])
        events.append(AnimalEvent(**{**row, "kind": EventKind(row["kind"]), "source": Source(**row["source"])}))
    ledger.ingest(events)
    return ledger
