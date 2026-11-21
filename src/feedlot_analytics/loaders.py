"""Load the original files at their native grains and inventory their schemas."""

from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path

import pandas as pd

from .contracts import BOOK, CSV, DATE_BOUNDS, SCHEMA_VERSION, SOURCE_BASELINE, TEXT_FIELDS

TEXT_DTYPES = {name: "string" for name in (*TEXT_FIELDS, *DATE_BOUNDS)}
NA_OPTIONS = {"keep_default_na": False, "na_values": [""]}


@dataclass
class Sources:
    flat: pd.DataFrame
    sheets: dict[str, pd.DataFrame]
    manifest: dict


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def calendar_dates(values: pd.Series) -> pd.Series:
    """Convert source calendar labels to timezone-naive midnight timestamps."""
    if not values.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False).all():
        raise ValueError(f"Expected ISO calendar dates in {values.name}")
    return pd.to_datetime(values, format="%Y-%m-%d")


def schema(frame: pd.DataFrame) -> dict:
    return {
        "rows": len(frame),
        "columns": {
            name: {"dtype": str(values.dtype), "nulls": int(values.isna().sum())}
            for name, values in frame.items()
        },
    }


def load_sources(root: Path) -> Sources:
    """Return raw frames. Date labels stay strings until the analytical layer."""
    csv_path, book_path = root / CSV, root / BOOK
    hashes = {CSV: sha256(csv_path), BOOK: sha256(book_path)}
    flat = pd.read_csv(csv_path, dtype=TEXT_DTYPES, float_precision="round_trip", **NA_OPTIONS)
    with pd.ExcelFile(book_path, engine="openpyxl") as workbook:
        sheets = {
            name: workbook.parse(name, dtype=TEXT_DTYPES, **NA_OPTIONS)
            for name in workbook.sheet_names
        }
    if hashes != {CSV: sha256(csv_path), BOOK: sha256(book_path)}:
        raise ValueError("Source files changed while reading; retry against an immutable snapshot.")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "phase1_baseline": SOURCE_BASELINE,
        "parsers": {
            "csv": "pandas.read_csv, round-trip floats",
            "xlsx": "pandas.ExcelFile, openpyxl",
            "identity_and_operational_dates": "strings",
            "missing": "empty cells only",
        },
        "files": {
            CSV: {"sha256": hashes[CSV], "bytes": csv_path.stat().st_size, **schema(flat)},
            BOOK: {"sha256": hashes[BOOK], "bytes": book_path.stat().st_size,
                   "sheets": {name: schema(frame) for name, frame in sheets.items()}},
        },
    }
    for frame, profile in [(flat, manifest["files"][CSV]), *(
        (frame, manifest["files"][BOOK]["sheets"][name]) for name, frame in sheets.items()
    )]:
        profile["calendar_labels"] = {
            col: {"first": str(frame[col].min()), "last": str(frame[col].max())}
            for col in frame.columns.intersection(DATE_BOUNDS)
        }
    return Sources(flat, sheets, manifest)


def typed_dates(frame: pd.DataFrame) -> pd.DataFrame:
    """Build a typed copy for transformations without changing the loaded frame."""
    return frame.assign(**{
        name: calendar_dates(frame[name]) for name in frame.columns.intersection(DATE_BOUNDS)
    })
