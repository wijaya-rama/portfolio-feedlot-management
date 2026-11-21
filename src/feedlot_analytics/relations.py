"""Relationship and numeric primitives shared by validation and rollups."""

import numpy as np
import pandas as pd


def require_key(frame: pd.DataFrame, key: tuple[str, ...], name: str) -> None:
    columns = list(key)
    if frame[columns].isna().any(axis=None) or frame.duplicated(columns).any():
        raise ValueError(f"{name} requires a unique, non-null key {key}")


def add_columns(left, right, *, key, cardinality, require_match=True):
    """Attach only new columns, retaining each left row exactly once."""
    if cardinality not in ("one_to_one", "many_to_one"):
        raise ValueError("Only row-preserving relationships are supported")
    shared = set(left) & set(right) - set(key)
    if shared:
        raise ValueError(f"Columns already present: {sorted(shared)}")
    require_key(right, key, "lookup")
    if left[list(key)].isna().any(axis=None):
        raise ValueError(f"Missing key in left table: {key}")
    joined = left.merge(right, on=list(key), how="left", validate=cardinality, indicator=True)
    if require_match and joined["_merge"].ne("both").any():
        raise ValueError(f"Missing lookup records for {key}")
    return joined.drop(columns="_merge")


def cents(values):
    """Convert validated two-decimal source CAD to integer cents."""
    return (values * 100).round().astype("int64")


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Keep missing and nonpositive denominators unavailable."""
    return numerator.div(denominator.where(denominator.gt(0)))


def within(actual, expected, tolerance):
    return np.isclose(actual, expected, atol=tolerance, rtol=0)
