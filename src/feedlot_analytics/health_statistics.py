"""Uncertainty and common-support comparisons for the Phase 2B-3 review."""

import numpy as np
import pandas as pd

from .relations import require_key

ENTRY_COHORT = ("lot_id", "sex", "breed", "frame_score", "entry_weight_band")


def with_entry_band(frame, *, width=20):
    """Use fixed live-weight bands chosen before comparing outcomes."""
    return frame.assign(entry_weight_band=(frame.entry_weight_kg // width) * width)


def pen_rate_interval(pens, *, scale=1.0, draws=2000, seed=20261121):
    """Resample whole pens, preserving the additive numerator and denominator."""
    counts = pens[["numerator", "denominator"]].to_numpy(dtype=float)
    if len(counts) < 2:
        return np.nan, np.nan
    sample = np.random.default_rng(seed).integers(len(counts), size=(draws, len(counts)))
    numerator, denominator = counts[sample].sum(axis=1).T
    valid = denominator > 0
    if not valid.any():
        return np.nan, np.nan
    return tuple(np.quantile(scale * numerator[valid] / denominator[valid], [.025, .975]))


def supported_difference(cells, *, scale=1.0):
    """Average within-stratum differences using eligible exposed denominators as weights."""
    matched = cells.loc[cells.exposed_n.gt(0) & cells.reference_n.gt(0)].copy()
    matched["numerator"] = matched.exposed_total - matched.exposed_n * (
        matched.reference_total / matched.reference_n
    )
    matched["denominator"] = matched.exposed_n
    pens = matched.groupby("pen_id", observed=True)[["numerator", "denominator"]].sum()
    low, high = pen_rate_interval(pens, scale=scale)
    exposed_n = matched.exposed_n.sum()
    reference_expected = (matched.exposed_n * matched.reference_total / matched.reference_n).sum()
    return {
        "exposed_eligible": int(cells.exposed_n.sum()),
        "reference_eligible": int(cells.reference_n.sum()),
        "exposed_supported": int(exposed_n),
        "reference_supported": int(matched.reference_n.sum()),
        "exposed_events_or_sum": matched.exposed_total.sum(),
        "reference_events_or_sum": matched.reference_total.sum(),
        "strata": len(matched),
        "lots": matched.lot_id.nunique(),
        "pens": len(pens),
        "exposed_value": scale * matched.exposed_total.sum() / exposed_n if exposed_n else np.nan,
        "standardized_reference": scale * reference_expected / exposed_n if exposed_n else np.nan,
        "difference": scale * matched.numerator.sum() / exposed_n if exposed_n else np.nan,
        "pen_low": low,
        "pen_high": high,
    }


def cohort_difference(frame, *, exposed, outcome, strata=ENTRY_COHORT, scale=1.0):
    """Compare unique animals in cells with both groups and observed outcomes."""
    require_key(frame, ("animal_id",), "cohort contrast")
    keys = list(dict.fromkeys(["pen_id", "lot_id", *strata]))
    eligible = frame.dropna(subset=[*keys, exposed, outcome])
    cells = eligible.groupby([*keys, exposed], observed=True)[outcome].agg(["size", "sum"]).unstack(exposed)
    cells = cells.reindex(columns=pd.MultiIndex.from_product([["size", "sum"], [False, True]])).fillna(0)
    cells.columns = ["reference_n", "exposed_n", "reference_total", "exposed_total"]
    return supported_difference(cells.reset_index(), scale=scale)


def within_lot_slope(frame, *, predictor, outcome, increment, numeric=(), categorical=()):
    """Estimate a mix-adjusted within-lot slope with whole-pen clustered scores."""
    require_key(frame, ("animal_id",), "within-lot association")
    columns = list(dict.fromkeys(["lot_id", "pen_id", predictor, outcome, *numeric, *categorical]))
    data = frame[columns].dropna()
    result = {"eligible": len(data), "lots": data.lot_id.nunique(), "pens": data.pen_id.nunique()}
    variables = pd.concat([
        data[[predictor, outcome, *numeric]].astype(float),
        pd.get_dummies(data[list(categorical)].astype("category"), drop_first=True, dtype=float),
    ], axis=1)
    centered = variables - variables.groupby(data.lot_id, observed=True).transform("mean")
    x, y = centered.iloc[:, :2].to_numpy().T
    controls = centered.iloc[:, 2:].to_numpy()
    coefs, _, rank, _ = np.linalg.lstsq(controls, np.column_stack((x, y)), rcond=None)
    x, y = (np.column_stack((x, y)) - controls @ coefs).T
    xx = x @ x
    groups = result["pens"]
    df = len(data) - result["lots"] - rank - 1
    if xx <= 1e-12 or groups < 2 or df <= 0:
        return {**result, "slope": np.nan, "pen_low": np.nan, "pen_high": np.nan}
    beta = (x @ y) / xx
    scores = pd.Series(x * (y - beta * x), index=data.index).groupby(data.pen_id).sum()
    variance = scores.pow(2).sum() / xx**2 * groups / (groups - 1) * (len(data) - 1) / df
    half_width = 1.96 * abs(increment) * np.sqrt(variance)
    slope = beta * increment
    return {**result, "slope": slope, "pen_low": slope - half_width, "pen_high": slope + half_width}
