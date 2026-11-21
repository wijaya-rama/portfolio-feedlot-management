"""Sold carcass outcomes and integrated lot review for Phase 2B-3."""

import numpy as np
import pandas as pd

from .contracts import FINISHED, GRADES
from .feed_growth import lot_composition_controls
from .metrics import CLOSEOUT_METRICS, aggregate_closeout, animal_components, apply_metrics
from .relations import add_columns, safe_ratio


def sold_carcasses(history):
    """Add sold-only comparison variables and retain missing invalid measurements."""
    sold = history.loc[history.exit_type.eq(FINISHED)].copy()
    hcw = sold.hot_carcass_weight_kg.where(sold.hot_carcass_weight_kg.gt(0))
    live = sold.exit_weight_kg.where(sold.exit_weight_kg.gt(0))
    gain = sold.total_gain_kg.where(sold.total_gain_kg.gt(0))
    sold["eligible_hcw_kg"] = hcw
    sold["individual_yield_pct"] = 100 * safe_ratio(hcw, live)
    sold["individual_realized_price"] = safe_ratio(sold.gross_revenue_cad, hcw)
    sold["eligible_prime_aaa"] = sold.quality_grade.isin(GRADES[:2]).astype(float).where(
        sold.quality_grade.isin(GRADES)
    )
    sold["individual_financial_adg"] = safe_ratio(gain, sold.financial_dof)
    sold["individual_allocated_fcr"] = safe_ratio(sold.allocated_dmi_kg.where(sold.allocated_dmi_kg.ge(0)), gain)
    return sold


def carcass_bands(sold, health):
    """Use absolute live-weight bands and pooled ratio components for sold markets."""
    boundaries = {
        "entry_weight_kg": [-np.inf, 300, 330, 360, 390, np.inf],
        "exit_weight_kg": [-np.inf, 550, 600, 650, 700, np.inf],
    }
    components = animal_components(sold, health)
    sections = []
    for field, bounds in boundaries.items():
        band = pd.cut(sold[field], bounds, right=False)
        grouped = components.groupby(band, observed=True, dropna=False).sum()
        table = apply_metrics(grouped, CLOSEOUT_METRICS)
        sections.append(table.assign(weight=field, band=table.index.astype(str)))
    return pd.concat(sections, ignore_index=True)


def lot_health_review(lots, animals):
    """Join observed breed shares and contrast lots to their own placement-quarter peers."""
    lots = lots.assign(placement_quarter=lots.arrival_date.dt.to_period("Q").astype("string"))
    quarter = lots.groupby("placement_quarter", observed=True)
    denominator = quarter.head_placed.transform("sum") - lots.head_placed
    peer_deaths = quarter.head_mortality.transform("sum") - lots.head_mortality
    margin_on_sales = lots.sold_only_margin_cents / (100 * lots.head_placed)
    death_burden = lots.mortality_loss_cents / (100 * lots.head_placed)
    result = lots.assign(
        quarter_lots=quarter.lot_id.transform("size"),
        peer_mortality=safe_ratio(peer_deaths, denominator),
        high_morbidity=lots.recorded_morbidity_rate.gt(quarter.recorded_morbidity_rate.transform("quantile", q=.75)),
        below_median_sold_adg=lots.sold_adg_kg_per_day.lt(quarter.sold_adg_kg_per_day.transform("median")),
        below_median_margin=lots.all_outcome_margin_per_head_placed.lt(
            quarter.all_outcome_margin_per_head_placed.transform("median")
        ),
        sold_margin_contribution_per_placed=margin_on_sales,
        death_burden_per_placed=death_burden,
    )
    result["mortality_gap_pp"] = 100 * (result.mortality_rate - result.peer_mortality)
    result["joint_review"] = result.high_morbidity & result.below_median_sold_adg & result.below_median_margin
    shares = lot_composition_controls(animals).drop(columns=["mean_financial_dof"])
    return add_columns(result, shares, key=("lot_id",), cardinality="one_to_one")
