"""Closeout comparisons and conditional price scenarios built on Phase 2A."""

import numpy as np
import pandas as pd

from .contracts import COSTS, FINISHED, MORTALITY
from .metrics import aggregate_closeout
from .relations import add_columns, cents, require_key, safe_ratio

COST_CENTS = tuple(name.removesuffix("_cad") + "_cents" for name in COSTS)
MARGIN = "all_outcome_margin_per_head_placed"
REVENUE_AND_COSTS = ("gross_revenue_cents", *COST_CENTS)
FINANCIAL_COMPONENTS = (*REVENUE_AND_COSTS, "production_cost_cents")


def audit_summary(exceptions, feed_bridge):
    """Count original exceptions and quantify the two rounding rules in their native units."""
    key = ("rule", "source_table", "source_key")
    require_key(exceptions, key, "audit_exceptions")
    require_key(feed_bridge, ("lot_id",), "lot_feed_reconciliation")
    counts = exceptions.groupby(["severity", "status", "rule"], as_index=False).size()
    bridge = feed_bridge.set_index("lot_id")
    residuals = []
    for rule, column, unit in (
        ("feed_dm_rounding", "dm_delivered_less_allocated_kg", "kg DM"),
        ("feed_cost_rounding", "cost_delivered_less_allocated_cad", "CAD"),
    ):
        keys = exceptions.loc[exceptions.rule.eq(rule), "source_key"]
        gaps = bridge.loc[keys, column]
        expected = bridge.index[bridge[column].ne(0)]
        if set(keys) != set(expected) or len(keys) != len(expected):
            raise ValueError(f"Feed exception keys disagree with the reconciliation for {rule}")
        residuals.append({
            "rule": rule, "unit": unit, "affected_lots": len(gaps),
            "net_residual": gaps.sum(), "max_absolute_residual": gaps.abs().max(),
            "max_share_of_bound": (
                gaps.abs() / bridge.loc[keys, "rounding_bound_per_metric"]
            ).max(),
        })
    return counts, pd.DataFrame(residuals)


def cost_structure(overall, by_outcome):
    """Return the four ledger costs, including the mortality subset of each."""
    costs = overall[list(COST_CENTS)].astype("int64")
    deaths = by_outcome.reindex([MORTALITY], fill_value=0)[list(COST_CENTS)].iloc[0]
    return pd.DataFrame({
        "all_outcomes_cad": costs / 100,
        "share_of_modeled_cost": costs / costs.sum() if costs.sum() > 0 else np.nan,
        "cad_per_placed": costs / (100 * overall.head_placed) if overall.head_placed > 0 else np.nan,
        "mortality_cad": deaths / 100,
    }).rename(index=lambda name: name.removesuffix("_cents"))


def cohort_economics(animals, health, *, by):
    """Retain Phase 2A economics and add head-level loss burden and lot coverage."""
    by = tuple(by)
    if not by or set(by) - set(animals):
        raise ValueError("Select one or more animal closeout dimensions")
    totals = aggregate_closeout(animals, health, by=by)
    margin = cents(animals.net_margin_cad)
    observations = animals[list(dict.fromkeys((*by, "lot_id")))].assign(
        loss_head=margin.lt(0), gross_loss_cents=-margin.clip(upper=0),
    )
    loss = observations.groupby(list(by), observed=True, dropna=False, as_index=False).agg(
        lot_count=("lot_id", "nunique"),
        loss_head=("loss_head", "sum"),
        gross_loss_cents=("gross_loss_cents", "sum"),
    )
    result = totals.merge(loss, on=list(by), validate="one_to_one", how="left")
    result["loss_head_share"] = safe_ratio(result.loss_head, result.head_placed)
    for field in FINANCIAL_COMPONENTS:
        result[field.replace("_cents", "_cad_per_placed")] = safe_ratio(result[field] / 100, result.head_placed)
    return result


def lot_peer_review(lots, *, min_placed=100, min_lots=5):
    """Rank completed lots within arrival quarter and bridge against all other eligible peers."""
    require_key(lots, ("lot_id",), "lot_closeout")
    if min_placed < 1 or min_lots < 2:
        raise ValueError("Lot review requires positive head coverage and at least two lots per cohort")
    complete = lots.head_placed.eq(lots.head_count_in) & lots.head_placed.eq(
        lots.head_sold + lots.head_mortality
    ) & lots.lot_closeout_date.notna() & lots.arrival_date.notna()
    result = lots.loc[complete & lots.head_placed.ge(min_placed)].copy()
    result["placement_quarter"] = result.arrival_date.dt.to_period("Q").astype("string")
    result["eligible_lots_in_quarter"] = result.groupby("placement_quarter").lot_id.transform("size")
    result = result.loc[result.eligible_lots_in_quarter.ge(min_lots)].copy()
    group = result.groupby("placement_quarter")
    result["rank_all_outcome_per_placed"] = group[MARGIN].rank(method="min", ascending=False).astype("Int64")
    result["rank_sold_only_per_sold"] = group.sold_only_margin_per_head_sold.rank(
        method="min", ascending=False
    ).astype("Int64")
    result["peer_head_placed"] = group.head_placed.transform("sum") - result.head_placed
    fields = [*REVENUE_AND_COSTS, "all_outcome_margin_cents"]
    for field in fields:
        observed = safe_ratio(result[field] / 100, result.head_placed)
        peers = safe_ratio((group[field].transform("sum") - result[field]) / 100, result.peer_head_placed)
        sign = -1 if field in COST_CENTS else 1
        result[field.replace("_cents", "_contribution_cad_per_placed")] = sign * (observed - peers)
    return result.sort_values(["placement_quarter", "rank_all_outcome_per_placed", "lot_id"])


def downside_summary(margins_cents, *, quantile=.05):
    """Describe a realized lower tail with one equal-weight observation per supplied unit."""
    if not 0 < quantile < 1:
        raise ValueError("Quantile must be between zero and one")
    if margins_cents.isna().any():
        raise ValueError("Downside summary requires a complete margin series")
    threshold = margins_cents.quantile(quantile)
    tail = margins_cents.loc[margins_cents.le(threshold)]
    losses = margins_cents.loc[margins_cents.lt(0)]
    return pd.Series({
        "units": len(margins_cents),
        "loss_units": len(losses),
        "loss_share": len(losses) / len(margins_cents) if len(margins_cents) else np.nan,
        "gross_loss_cad": -losses.sum() / 100,
        "minimum_cad": margins_cents.min() / 100,
        "median_cad": margins_cents.median() / 100,
        "p95_cad": margins_cents.quantile(.95) / 100,
        "tail_cutoff_cad": threshold / 100,
        "tail_units": len(tail),
        "tail_mean_cad": tail.mean() / 100,
        "tail_net_cad": tail.sum() / 100,
    })


def lot_composition(animals, lots, *, attribute="breed"):
    """Count recorded individual attributes and compare the actual within-lot shares."""
    if attribute not in {"breed", "sex", "frame_score"}:
        raise ValueError("Lot composition requires an individual attribute")
    require_key(animals, ("animal_id",), "animal_closeout")
    counts = animals.groupby(["lot_id", attribute], dropna=False, observed=True).size().unstack(fill_value=0)
    compare = add_columns(lots[["lot_id", "head_placed"]], counts.sum(axis=1).rename("observed").reset_index(),
                          key=("lot_id",), cardinality="one_to_one")
    if not compare.head_placed.eq(compare.observed).all() or len(compare) != len(counts):
        raise ValueError("Lot composition requires all placement animals for each selected lot")
    if animals[attribute].isna().any():
        raise ValueError(f"Lot composition requires recorded individual {attribute}")
    return counts.div(counts.sum(axis=1), axis=0)


def price_break_even(totals):
    """Reprice one side of the all-outcome ledger at snapshot volumes and other booked values."""
    nonpurchase = totals[list(COST_CENTS[1:])].sum(axis=1)
    result = totals[["head_placed", "head_sold", "head_hcw_eligible", "placement_weight_kg", "hcw_kg"]].copy()
    purchase = safe_ratio((totals.gross_revenue_cents - nonpurchase) / 100, totals.placement_weight_kg)
    complete_carcass = totals.head_sold.eq(totals.head_hcw_eligible)
    other_revenue = totals.gross_revenue_cents - totals.hcw_eligible_revenue_cents
    carcass = safe_ratio((totals.production_cost_cents - other_revenue) / 100, totals.hcw_kg)
    result["booked_purchase_cad_per_live_kg"] = totals.purchase_basis_cad_per_kg
    result["max_purchase_cad_per_live_kg"] = purchase
    result["purchase_headroom_cad_per_live_kg"] = purchase - totals.purchase_basis_cad_per_kg
    result["booked_revenue_cad_per_hcw_kg"] = totals.realized_carcass_price_cad_per_kg.where(complete_carcass)
    result["min_carcass_cad_per_hcw_kg"] = carcass.where(complete_carcass)
    result["carcass_headroom_cad_per_hcw_kg"] = (
        result.booked_revenue_cad_per_hcw_kg - result.min_carcass_cad_per_hcw_kg
    )
    result["margin_delta_cad_per_10c_purchase_increase"] = -.10 * totals.placement_weight_kg
    result["margin_delta_cad_per_10c_carcass_decrease"] = (-.10 * totals.hcw_kg).where(
        complete_carcass & totals.hcw_kg.gt(0)
    )
    return result


def lot_procurement_inputs(lots):
    """Expose purchase-time lot covariates and the all-outcome closeout response."""
    require_key(lots, ("lot_id",), "lot_closeout")
    return lots[["lot_id", "head_placed", "origin_region", "lot_sex", "feeder_purchase_price_per_kg", MARGIN]].assign(
        placement_quarter=lots.arrival_date.dt.to_period("Q").astype("string"),
        mean_entry_weight_kg=safe_ratio(lots.placement_weight_kg, lots.head_placed),
    )


def _slope(products):
    return products.xy.sum() / products.xx.sum() if products.xx.sum() > 0 else np.nan


def _centered_products(pairs, *, within=None):
    xy = pairs[["x", "y"]]
    means = xy.mean() if within is None else pairs.groupby(within, observed=True)[["x", "y"]].transform("mean")
    centered = xy - means
    return pd.DataFrame({"xx": centered.x ** 2, "xy": centered.x * centered.y})


def _lot_association(frame, *, predictor, response, increment):
    selected = frame[["placement_quarter", predictor, response]]
    eligible = selected.notna().all(axis=1)
    pairs = selected.loc[eligible].rename(columns={predictor: "x", response: "y"}).reset_index(drop=True)
    estimates = pd.Series([
        _slope(_centered_products(pairs.drop(index=index), within="placement_quarter")) * increment
        for index in pairs.index
    ], dtype=float)
    return {
        "lots": len(pairs),
        "quarters": pairs.placement_quarter.nunique(),
        "pooled_slope_cad": _slope(_centered_products(pairs)) * increment,
        "within_quarter_slope_cad": _slope(_centered_products(pairs, within="placement_quarter")) * increment,
        "leave_one_lot_out_low": estimates.min(),
        "leave_one_lot_out_high": estimates.max(),
    }, eligible


def procurement_slopes(lots):
    """Compare purchase-time attributes with closeout margin at lot grain."""
    require_key(lots, ("lot_id",), "lot procurement inputs")
    records = []
    for field, unit, increment in (
        ("feeder_purchase_price_per_kg", "CAD 0.10/kg live", .10),
        ("mean_entry_weight_kg", "5 kg live", 5),
    ):
        estimates, eligible = _lot_association(lots, predictor=field, response=MARGIN, increment=increment)
        sex_pairs = lots[["placement_quarter", "lot_sex", field, MARGIN]].dropna().rename(
            columns={field: "x", MARGIN: "y"}
        )
        sex_slope = _slope(_centered_products(sex_pairs, within=["placement_quarter", "lot_sex"])) * increment
        records.append({
            "measure": field, "increment": unit, "placed_head": lots.loc[eligible, "head_placed"].sum(), **estimates,
            "lots_in_quarter_and_sex_fit": len(sex_pairs),
            "within_quarter_and_sex_slope_cad": sex_slope,
        })
    return pd.DataFrame(records).set_index("measure")


def sold_duration_association(animals):
    """Treat inclusive duration as a lot attribute when sold duration is shared within lots."""
    require_key(animals, ("animal_id",), "animal_closeout")
    sold = animals.loc[animals.exit_type.eq(FINISHED) & animals.financial_dof.gt(0)].assign(
        margin_cents=lambda rows: cents(rows.net_margin_cad),
    )
    if sold.groupby("lot_id").placement_quarter.nunique().gt(1).any():
        raise ValueError("Sold duration comparison requires one placement quarter per lot")
    lots = sold.groupby(["lot_id", "placement_quarter"], as_index=False).agg(
        mean_financial_dof=("financial_dof", "mean"),
        sold_head=("animal_id", "size"),
        sold_margin_cents=("margin_cents", "sum"),
    )
    lots["margin_cad_per_sold"] = safe_ratio(lots.sold_margin_cents / 100, lots.sold_head)
    estimates, eligible = _lot_association(lots, predictor="mean_financial_dof", response="margin_cad_per_sold", increment=10)
    return pd.DataFrame([{
        "measure": "mean_financial_dof", "increment": "10 inclusive days",
        "sold_head": lots.loc[eligible, "sold_head"].sum(), **estimates,
    }]).set_index("measure")


def sold_performance_slopes(animals, *, draws=2000, seed=20261121):
    """Compare sold animals within lots and resample whole lots for sensitivity intervals."""
    require_key(animals, ("animal_id",), "animal_closeout")
    if draws < 1:
        raise ValueError("At least one bootstrap draw is required")
    sold = animals.loc[animals.exit_type.eq(FINISHED)]
    gain = sold.total_gain_kg.gt(0)
    rng = np.random.default_rng(seed)
    records = []
    for field, unit, increment, eligible in (
        ("lifetime_adg_kg", "0.10 kg/day", .10, gain & sold.financial_dof.gt(0)),
        ("fcr", "1 kg DM/kg gain", 1, gain & sold.allocated_dmi_kg.ge(0)),
        ("financial_dof", "10 inclusive days", 10, sold.financial_dof.gt(0)),
    ):
        pairs = sold.loc[eligible, ["lot_id", field, "net_margin_cad"]].dropna().rename(
            columns={field: "x", "net_margin_cad": "y"}
        )
        products = _centered_products(pairs, within="lot_id").groupby(pairs.lot_id).sum()
        values = products[["xx", "xy"]].to_numpy()
        informative_lots = int(products.xx.gt(0).sum())
        low, high = np.nan, np.nan
        if informative_lots >= 2:
            samples = rng.integers(len(values), size=(draws, len(values)))
            xx, xy = values[samples].sum(axis=1).T
            valid = xx > 0
            if valid.any():
                low, high = np.quantile(xy[valid] / xx[valid] * increment, [.025, .975])
        records.append({
            "measure": field, "increment": unit, "sold_head": len(pairs), "lots": len(products),
            "lots_with_within_variation": informative_lots,
            "pooled_cad_per_sold": _slope(_centered_products(pairs)) * increment,
            "within_lot_cad_per_sold": _slope(products) * increment,
            "lot_bootstrap_low": low, "lot_bootstrap_high": high,
        })
    return pd.DataFrame(records).set_index("measure")


def lot_heterogeneity(lots, *, by):
    """Show pooled per-head economics alongside equally weighted lot quartiles."""
    require_key(lots, ("lot_id",), "lot_closeout")
    frame = lots.assign(
        cost_cad_per_placed=safe_ratio(lots.production_cost_cents / 100, lots.head_placed),
    )
    grouped = frame.groupby(list(by), observed=True, dropna=False)
    totals = grouped.agg(
        lots=("lot_id", "size"),
        head_placed=("head_placed", "sum"),
        head_sold=("head_sold", "sum"),
        production_cost_cents=("production_cost_cents", "sum"),
        all_outcome_margin_cents=("all_outcome_margin_cents", "sum"),
        loss_lots=("all_outcome_margin_cents", lambda margin: margin.lt(0).sum()),
    )
    totals[MARGIN] = safe_ratio(totals.all_outcome_margin_cents / 100, totals.head_placed)
    totals["pooled_cost_cad_per_placed"] = safe_ratio(totals.production_cost_cents / 100, totals.head_placed)
    for label, metric in (("lot_margin", MARGIN), ("lot_cost", "cost_cad_per_placed")):
        quantiles = [.25, .5, .75]
        quartiles = grouped[metric].quantile(quantiles).unstack().reindex(columns=quantiles)
        quartiles.columns = [f"{label}_{pct}_cad_per_placed" for pct in ("p25", "median", "p75")]
        totals = totals.join(quartiles)
    return totals
