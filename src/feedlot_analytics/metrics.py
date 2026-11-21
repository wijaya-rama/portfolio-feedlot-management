"""Additive components and final ratios at explicit reporting grains."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .contracts import COSTS, FINANCE, FINISHED, GRADES, MORTALITY, SCHEMA_VERSION
from .relations import add_columns, cents, require_key, safe_ratio


@dataclass(frozen=True)
class Metric:
    metric_id: str
    label: str
    numerator: str
    denominator: str | None
    unit: str
    eligibility: str
    eligible_count: str
    scale: float = 1.0


CLOSEOUT_METRICS = (
    Metric("head_placed", "Head placed", "head_placed", None, "head",
           "Unique animal IDs in the selected placement cohort.", "head_placed"),
    Metric("head_sold", "Head sold", "head_sold", None, "head",
           "Unique selected Finished Sale animals. Use exit date for sales activity.", "head_sold"),
    Metric("head_mortality", "Deaths", "head_mortality", None, "head",
           "Unique selected mortality animals. Use exit date for death activity.", "head_mortality"),
    Metric("head_treated", "Head treated", "head_treated", None, "head",
           "Unique animals with one or more treatments during the recorded lifetime.", "head_treated"),
    Metric("treatment_events", "Treatment events", "treatment_events", None, "event",
           "Recorded lifetime treatment events among selected animals, including repeat treatments.", "treatment_events"),
    Metric("financial_head_days", "Inclusive financial head-days", "financial_head_days", None, "head-day",
           "All selected outcomes, entry and exit dates included.", "head_placed"),
    Metric("all_outcome_margin_cad", "All-outcome modeled margin", "all_outcome_margin_cents", None, "CAD",
           "All selected animals, including deaths. Revenue less four recorded cost components.", "head_placed", .01),
    Metric("sold_only_margin_cad", "Sold-only modeled margin", "sold_only_margin_cents", None, "CAD",
           "Selected Finished Sale animals only.", "head_sold", .01),
    Metric("mortality_loss_cad", "Recorded mortality loss", "mortality_loss_cents", None, "CAD",
           "Positive ledger burden on mortality rows. Already included in all-outcome margin.", "head_mortality", .01),
    Metric("all_outcome_margin_per_head_placed", "All-outcome margin / head placed",
           "all_outcome_margin_cents", "head_placed", "CAD/head placed",
           "All outcomes across the selected placement cohort.", "head_placed", .01),
    Metric("all_outcome_margin_per_head_sold", "All-outcome margin / head sold",
           "all_outcome_margin_cents", "head_sold", "CAD/head sold",
           "All outcomes in numerator, Finished Sale animals in denominator, within the same cohort.", "head_sold", .01),
    Metric("sold_only_margin_per_head_sold", "Sold-only margin / head sold",
           "sold_only_margin_cents", "head_sold", "CAD/head sold",
           "Finished Sale animals in both numerator and denominator.", "head_sold", .01),
    Metric("mortality_rate", "Deaths / head placed", "head_mortality", "head_placed", "fraction",
           "Closed placement population, including all outcomes.", "head_placed"),
    Metric("recorded_morbidity_rate", "Treated animals / head placed", "head_treated", "head_placed", "fraction",
           "Lifetime recorded treatment; at least one event per animal. Surveillance coverage is unavailable.", "head_placed"),
    Metric("repeat_treatment_rate", "Repeat-treated animals / treated animals", "head_repeat_treated", "head_treated",
           "fraction", "Treated animals with at least two events over their recorded lifetime.", "head_treated"),
    Metric("first_pull_by_day30_share", "First pull by inclusive day 30 / treated animals",
           "head_first_pull_by_day30", "head_treated", "fraction",
           "First recorded treatment ordered by treatment date, then treatment ID.", "head_treated"),
    Metric("direct_vet_cad_per_event", "Direct veterinary cost / treatment event", "direct_treatment_cost_cents",
           "treatment_events", "CAD/event", "Identified treatment records; part of closeout veterinary spend.",
           "treatment_events", .01),
    Metric("sold_adg_kg_per_day", "Sold ADG, ratio of totals", "adg_gain_kg", "adg_financial_days", "kg/day",
           "Finished Sale animals with positive gain and inclusive financial DOF.", "head_adg_eligible"),
    Metric("mean_individual_sold_adg", "Mean recorded individual sold ADG", "individual_adg_sum", "head_adg_eligible",
           "kg/day", "Recorded rounded individual ratios for ADG-eligible sold animals.", "head_adg_eligible"),
    Metric("sold_fcr", "Sold FCR, ratio of totals", "fcr_dm_kg", "fcr_gain_kg", "kg DM/kg gain",
           "Finished Sale animals with positive gain and known nonnegative allocated DM.", "head_fcr_eligible"),
    Metric("mean_individual_sold_fcr", "Mean recorded individual sold FCR", "individual_fcr_sum", "head_fcr_eligible",
           "kg DM/kg gain", "Recorded rounded individual ratios for FCR-eligible sold animals.", "head_fcr_eligible"),
    Metric("sold_feed_cog", "Sold feed cost of gain, ratio of totals", "feed_cog_cost_cents", "feed_cog_gain_kg",
           "CAD/kg gain", "Finished Sale animals with positive gain and known allocated feed cost.",
           "head_feed_cog_eligible", .01),
    Metric("mean_individual_sold_feed_cog", "Mean recorded individual sold feed cost of gain",
           "individual_feed_cog_sum", "head_feed_cog_eligible", "CAD/kg gain",
           "Recorded rounded individual ratios for feed COG-eligible animals.", "head_feed_cog_eligible"),
    Metric("sold_nonpurchase_cog", "Sold non-purchase cost of gain, ratio of totals", "nonpurchase_cog_cents",
           "nonpurchase_cog_gain_kg", "CAD/kg gain", "Finished Sale animals with positive gain and known feed, "
           "yardage and veterinary costs.", "head_nonpurchase_eligible", .01),
    Metric("dressing_yield", "Sold dressing yield, ratio of totals", "dressing_hcw_kg", "dressing_live_kg",
           "fraction", "Finished Sale animals with positive HCW and exit live weight.", "head_dressing_eligible"),
    Metric("mean_individual_dressing", "Mean recorded individual dressing fraction", "individual_dressing_sum",
           "head_dressing_eligible", "fraction", "Recorded individual dressing fractions for dressing-eligible "
           "sold animals.", "head_dressing_eligible"),
    Metric("mean_hcw_kg", "Mean hot carcass weight", "hcw_kg", "head_hcw_eligible", "kg/head sold",
           "Finished Sale animals with positive HCW.", "head_hcw_eligible"),
    Metric("prime_aaa_share", "Prime and AAA share of graded sales", "head_prime_aaa", "head_graded", "fraction",
           "Graded Finished Sale animals. Report ungraded sold head separately.", "head_graded"),
    Metric("purchase_basis_cad_per_kg", "Purchase cost / placed live weight", "purchase_cost_cents",
           "placement_weight_kg", "CAD/kg live", "Selected placements with validated positive entry weight.",
           "head_placed", .01),
    Metric("realized_carcass_price_cad_per_kg", "Sold realized price / kg carcass", "hcw_eligible_revenue_cents",
           "hcw_kg", "CAD/kg HCW", "Finished Sale animals with positive HCW.", "head_hcw_eligible", .01),
)

FEED_METRICS = (
    Metric("recorded_head_days", "Recorded feed head-days", "recorded_head_days", None, "head-day",
           "Sum of active-head counts across recorded delivery days.", "recorded_head_days"),
    Metric("delivered_dm_per_head_day", "Delivered DM / recorded head-day", "delivered_dm_kg",
           "recorded_head_days", "kg DM/head-day", "Matched delivery rows and recorded head-days.",
           "recorded_head_days"),
    Metric("delivered_cost_per_head_day", "Delivered feed cost / recorded head-day", "delivered_feed_cost_cad",
           "recorded_head_days", "CAD/head-day", "Matched delivery rows and recorded head-days.",
           "recorded_head_days"),
)


def kpi_catalog() -> pd.DataFrame:
    """Build the catalog from the same metric definitions used in aggregation."""
    families = (
        (CLOSEOUT_METRICS, "animal_closeout + animal_health_summary",
         "entry_date for placement cohorts, exit_date for activity, lot_closeout_date for completed lots"),
        (FEED_METRICS, "Fact_Feed_Daily -> pen_day_feed", "feed_date"),
    )
    records = []
    for metrics, lineage, date_role in families:
        for metric in metrics:
            records.append({
                **asdict(metric), "version": SCHEMA_VERSION, "lineage": lineage, "date_role": date_role,
                "aggregation": "ratio of additive totals" if metric.denominator else "sum",
                "unavailable": "NaN for zero or missing denominator" if metric.denominator else "not applicable",
            })
    return pd.DataFrame(records).astype({
        column: "string" for column in records[0] if column != "scale"
    })


def select_period(frame, *, date_role, start, end):
    """Select an inclusive interval on an explicitly typed calendar role."""
    dates = frame[date_role]
    if not date_role.endswith("_date") or not pd.api.types.is_datetime64_any_dtype(dates):
        raise ValueError(f"{date_role} must name a typed calendar date column")
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    for bound in (start, end):
        if pd.isna(bound) or bound.tzinfo is not None or bound != bound.normalize():
            raise ValueError("Date boundaries must be timezone-naive calendar dates")
    if start > end:
        raise ValueError("Period start must precede or equal period end")
    return frame.loc[dates.between(start, end)].copy()


def apply_metrics(totals, metrics):
    result = totals.copy()
    for metric in metrics:
        numerator = totals[metric.numerator]
        if metric.scale != 1:
            numerator = numerator * metric.scale
        result[metric.metric_id] = (numerator if metric.denominator is None else
                                    safe_ratio(numerator, totals[metric.denominator]))
    return result


def animal_components(animals, health_summary):
    """One row of additive data per animal. Eligibility applies to both sides of each ratio."""
    key = ("animal_id",)
    require_key(animals, key, "animal_closeout")
    sold = animals.exit_type.eq(FINISHED)
    dead = animals.exit_type.eq(MORTALITY)
    money = animals[list(FINANCE)].apply(cents)
    money.columns = [col.removesuffix("_cad") + "_cents" for col in money]
    money["production_cost_cents"] = money[[col.removesuffix("_cad") + "_cents" for col in COSTS]].sum(axis=1)
    money = money.rename(columns={"net_margin_cents": "all_outcome_margin_cents"})
    money["sold_only_margin_cents"] = money.all_outcome_margin_cents.where(sold, 0)
    money["mortality_loss_cents"] = -money.all_outcome_margin_cents.where(dead, 0)

    health = health_summary[["animal_id", "treatment_events", "treated", "repeat_treated",
                             "first_pull_by_day30", "direct_treatment_cost_cents"]]
    matched = add_columns(animals[["animal_id"]], health, key=key, cardinality="one_to_one")
    matched.index = animals.index
    gain = sold & animals.total_gain_kg.gt(0)
    adg = gain & animals.financial_dof.gt(0)
    fcr = gain & animals.allocated_dmi_kg.ge(0)
    feed_cog = gain & animals.allocated_feed_cost_cad.ge(0)
    nonpurchase = feed_cog & animals.yardage_cost_cad.ge(0) & animals.vet_cost_cad.ge(0)
    hcw = sold & animals.hot_carcass_weight_kg.gt(0)
    dressing = hcw & animals.exit_weight_kg.gt(0)
    graded = sold & animals.quality_grade.isin(GRADES)
    counts = {
        "head_placed": np.ones(len(animals), dtype="int64"),
        "head_sold": sold, "head_mortality": dead,
        "head_treated": matched.treated, "head_repeat_treated": matched.repeat_treated,
        "head_first_pull_by_day30": matched.first_pull_by_day30,
        "head_adg_eligible": adg, "head_fcr_eligible": fcr, "head_feed_cog_eligible": feed_cog,
        "head_nonpurchase_eligible": nonpurchase, "head_hcw_eligible": hcw,
        "head_dressing_eligible": dressing, "head_graded": graded, "head_ungraded_sold": sold & ~graded,
        "head_prime_aaa": graded & animals.quality_grade.isin(GRADES[:2]),
    }
    for label, grade in zip(("prime", "aaa", "aa", "b_discount"), GRADES, strict=True):
        counts[f"head_grade_{label}"] = graded & animals.quality_grade.eq(grade).fillna(False)
    quantities = {
        "financial_head_days": animals.financial_dof,
        "treatment_events": matched.treatment_events,
        "direct_treatment_cost_cents": matched.direct_treatment_cost_cents,
        "placement_weight_kg": animals.entry_weight_kg,
        "allocated_dm_kg": animals.allocated_dmi_kg,
        "adg_gain_kg": animals.total_gain_kg.where(adg, 0),
        "adg_financial_days": animals.financial_dof.where(adg, 0),
        "individual_adg_sum": animals.lifetime_adg_kg.where(adg, 0),
        "fcr_dm_kg": animals.allocated_dmi_kg.where(fcr, 0),
        "fcr_gain_kg": animals.total_gain_kg.where(fcr, 0),
        "individual_fcr_sum": animals.fcr.where(fcr, 0),
        "feed_cog_cost_cents": money.allocated_feed_cost_cents.where(feed_cog, 0),
        "feed_cog_gain_kg": animals.total_gain_kg.where(feed_cog, 0),
        "individual_feed_cog_sum": animals.feed_cost_of_gain_per_kg.where(feed_cog, 0),
        "nonpurchase_cog_cents": (money.allocated_feed_cost_cents + money.yardage_cost_cents
                                  + money.vet_cost_cents).where(nonpurchase, 0),
        "nonpurchase_cog_gain_kg": animals.total_gain_kg.where(nonpurchase, 0),
        "hcw_kg": animals.hot_carcass_weight_kg.where(hcw, 0),
        "hcw_eligible_revenue_cents": money.gross_revenue_cents.where(hcw, 0),
        "dressing_hcw_kg": animals.hot_carcass_weight_kg.where(dressing, 0),
        "dressing_live_kg": animals.exit_weight_kg.where(dressing, 0),
        "individual_dressing_sum": animals.dressing_pct.where(dressing, 0),
    }
    indicators = pd.DataFrame(counts, index=animals.index).astype("int64")
    return pd.concat([money, indicators, pd.DataFrame(quantities, index=animals.index)], axis=1)


def _sum_components(dimensions, components, by):
    if not by:
        return pd.DataFrame([{name: values.sum() for name, values in components.items()}]).astype(components.dtypes)
    frame = pd.concat([dimensions[list(by)], components], axis=1)
    return frame.groupby(list(by), dropna=False, observed=True, as_index=False)[list(components)].sum()


ANIMAL_GROUPS = frozenset({
    "animal_id", "breed", "sex", "frame_score", "lot_id", "pen_id", "origin_region", "pen_type", "site_zone",
    "entry_date", "exit_date", "lot_closeout_date", "placement_quarter", "exit_month", "exit_type",
    "entry_weight_kg", "quality_grade", "treated", "repeat_treated", "first_diagnosis",
})


def aggregate_closeout(animals, health_summary, *, by=()):
    """Compute metrics for a unique animal subset, carrying eligible counts and raw denominators."""
    by = tuple(by)
    if set(by) - ANIMAL_GROUPS:
        raise ValueError(f"Unsupported animal grouping: {sorted(set(by) - ANIMAL_GROUPS)}")
    health_groups = [col for col in by if col in {"treated", "repeat_treated", "first_diagnosis"}]
    dimensions = animals[list(set(by) - set(health_groups))]
    if health_groups:
        dimension_columns = ["animal_id", *[col for col in dimensions if col != "animal_id"]]
        dimensions = add_columns(animals[dimension_columns],
                                 health_summary[["animal_id", *health_groups]], key=("animal_id",),
                                 cardinality="one_to_one")
        dimensions.index = animals.index
    totals = _sum_components(dimensions, animal_components(animals, health_summary), by)
    return apply_metrics(totals, CLOSEOUT_METRICS)


FEED_COMPONENTS = (
    "delivered_as_fed_kg", "delivered_dm_kg", "delivered_feed_cost_cad", "recorded_head_days",
    "delivery_rows", "forage_dmi_kg", "concentrate_dmi_kg", "supplement_dmi_kg",
    "forage_cost_cad", "concentrate_cost_cad", "supplement_cost_cad",
)


def aggregate_pen_feed(pen_days, *, by=()):
    """Roll up deliveries and matched head-days without summing repeated capacity."""
    require_key(pen_days, ("pen_id", "feed_date"), "pen_day_feed")
    by = tuple(by)
    allowed = {"pen_id", "feed_date", "feed_month", "pen_type", "site_zone"}
    if set(by) - allowed:
        raise ValueError(f"Unsupported pen-day grouping: {sorted(set(by) - allowed)}")
    totals = _sum_components(pen_days, pen_days[list(FEED_COMPONENTS)], by)
    return apply_metrics(totals, FEED_METRICS)
