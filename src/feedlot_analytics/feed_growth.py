"""Phase 2B-2 feed, recorded occupancy and scale analyses."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import BOOK, CSV, FINISHED, STAGE_DAYS
from .loaders import NA_OPTIONS, TEXT_DTYPES, sha256, typed_dates
from .metrics import FEED_COMPONENTS, FEED_METRICS, animal_components, apply_metrics
from .pipeline import build
from .relations import add_columns, require_key, safe_ratio
from .weather import DAILY_UNITS, EXPECTED_DATES

SNAPSHOT = Path("phase2a/weather/era5-20261121T143547299379Z-fd9571517552")
SOURCE_HASHES = {
    CSV: "80e5534d1342343f600b125bd7406864d5ff9636aaaf2a83133c304dbabdc618",
    BOOK: "d2e15c6bda9bdab65612d2ed0a7c808ebb840dd3e8db6f7f134d86d2b92d81c5",
}
WEATHER_HASHES = {
    "raw_sha256": "fd95715175528e25d5a3ff6fe9e57bb0b6bf916dbf4003e63b1c6f78cad6fb99",
    "clean_sha256": "6f2c10fd5b56edcb7d60e95d9e5a88f148930b3d34873402f8ae0c8d0c30d313",
}
STAGES = (*STAGE_DAYS, "Closeout")
DELIVERY_NAMES = {
    "total_as_fed_kg": "delivered_as_fed_kg",
    "total_dmi_kg": "delivered_dm_kg",
    "total_feed_cost_cad": "delivered_feed_cost_cad",
    "head_count_active": "recorded_head_days",
}


def verify_build(result, baseline):
    """Check the fixed snapshot and previously published non-weather results."""
    summary = result.reconciliation["summary"]
    controls = result.reconciliation["controls"]
    if len(controls) != 661 or not all(row["passed"] for row in controls):
        raise ValueError("Phase 2B-2 requires all 661 baseline controls")
    for name in ("schema_version", "checks_passed", "checks_failed", "population",
                 "modeled_ledger_cad", "mortality_loss_cad", "kpis", "feed_bridge"):
        if summary[name] != baseline[name]:
            raise ValueError(f"Baseline reconciliation changed: {name}")
    for name, count in baseline["table_rows"].items():
        if name not in ("weather_daily", "audit_exceptions") and summary["table_rows"][name] != count:
            raise ValueError(f"Baseline row count changed: {name}")
    manifest = result.source_manifest
    if any(manifest["files"][name]["sha256"] != digest for name, digest in SOURCE_HASHES.items()):
        raise ValueError("Original cattle source hash changed")
    weather = manifest["weather"]
    if (weather["status"] != "verified"
            or any(weather[name] != digest for name, digest in WEATHER_HASHES.items())
            or (weather["grid_latitude"], weather["grid_longitude"]) != (50.0, -112.75)):
        raise ValueError("Expected the verified Picture Butte weather snapshot")
    daily = result.tables["weather_daily"]
    require_key(daily, ("date",), "daily weather")
    dates = EXPECTED_DATES
    if not pd.DatetimeIndex(daily.date).equals(dates) or daily[list(DAILY_UNITS)].isna().any(axis=None):
        raise ValueError("Weather requires all nine variables across 704 dates")
    coverage = ["weather_date_count", "temperature_days", "wind_days", "snow_days"]
    for grain, count in (("animal", 15000), ("lot", 90)):
        windows = result.tables[f"{grain}_weather_exposure"]
        require_key(windows, (f"{grain}_id",), f"{grain} exposure")
        if len(windows) != count or not windows[coverage].eq(windows.expected_exposure_days, axis=0).all(axis=None):
            raise ValueError(f"Incomplete {grain} weather windows")


def load_analysis(root: Path):
    """Build Phase 2A first, then recover phase labels at their native delivery grain."""
    result = build(root, weather_snapshot=root / SNAPSHOT)
    baseline = json.loads((root / "phase2a/reconciliation.json").read_text(encoding="utf-8"))
    verify_build(result, baseline)
    native = pd.read_excel(root / BOOK, sheet_name="Fact_Feed_Daily", engine="openpyxl",
                           dtype=TEXT_DTYPES, **NA_OPTIONS)
    if sha256(root / BOOK) != SOURCE_HASHES[BOOK]:
        raise ValueError("Workbook changed while reading ration phase")
    return result, delivery_rows(typed_dates(native), result.tables["pen_day_feed"])


def delivery_rows(native, pen_days):
    """Retain all lot–pen–days and reconcile additive quantities to the canonical fact."""
    require_key(native, ("lot_id", "pen_id", "feed_date"), "native deliveries")
    key = ("pen_id", "feed_date")
    require_key(pen_days, key, "pen-days")
    data = native.rename(columns=DELIVERY_NAMES).assign(delivery_rows=1)
    native_totals = data.groupby(list(key))[list(FEED_COMPONENTS)].sum().sort_index()
    canonical = pen_days.set_index(list(key))[list(FEED_COMPONENTS)].sort_index()
    if (not native_totals.index.equals(canonical.index)
            or not np.allclose(native_totals, canonical, atol=1e-8, rtol=0)):
        raise ValueError("Native feed quantities disagree with the canonical pen-day ledger")
    return add_columns(data, pen_days[[*key, "pen_type", "site_zone"]],
                       key=key, cardinality="many_to_one")


def feed_rollup(frame, *, by):
    """Aggregate matched feed and head-days; express ration shares by DM and cost."""
    totals = frame.groupby(list(by), observed=True, dropna=False)[list(FEED_COMPONENTS)].sum()
    result = apply_metrics(totals, FEED_METRICS)
    result["cad_per_kg_dm"] = safe_ratio(result.delivered_feed_cost_cad, result.delivered_dm_kg)
    for component in ("forage", "concentrate", "supplement"):
        result[f"{component}_dm_share"] = safe_ratio(result[f"{component}_dmi_kg"], result.delivered_dm_kg)
        result[f"{component}_cost_share"] = safe_ratio(
            result[f"{component}_cost_cad"], result.delivered_feed_cost_cad
        )
    return result


def recorded_occupancy(pen_days, *, by):
    """Occupancy on delivery-observed pen-days, with repeated capacity used as capacity-days."""
    require_key(pen_days, ("pen_id", "feed_date"), "pen-days")
    if pen_days.groupby("pen_id").capacity_head.nunique().ne(1).any():
        raise ValueError("Each pen requires one nominal capacity")
    groups = pen_days.assign(
        near_capacity=pen_days.recorded_occupancy_fraction.ge(.90),
        at_capacity=pen_days.recorded_occupancy_fraction.ge(1),
        exceeds_capacity=pen_days.recorded_occupancy_fraction.gt(1),
        overlapping_lots=pen_days.recorded_lots.gt(1),
    ).groupby(list(by), observed=True, dropna=False)
    totals = groups.agg(
        pens=("pen_id", "nunique"), dates=("feed_date", "nunique"),
        observed_pen_days=("pen_id", "size"), observed_capacity_days=("capacity_head", "sum"),
        recorded_head_days=("recorded_head_days", "sum"), peak_fraction=("recorded_occupancy_fraction", "max"),
        near_capacity_days=("near_capacity", "sum"), at_capacity_days=("at_capacity", "sum"),
        above_capacity_days=("exceeds_capacity", "sum"), overlapping_lot_days=("overlapping_lots", "sum"),
    )
    capacities = (pen_days[[*dict.fromkeys((*by, "pen_id", "capacity_head"))]]
                  .drop_duplicates().groupby(list(by), observed=True, dropna=False).capacity_head.sum())
    totals["nominal_capacity_observed_pens"] = capacities
    totals["recorded_occupancy"] = safe_ratio(totals.recorded_head_days, totals.observed_capacity_days)
    return totals


def sold_efficiency(animals, health):
    """Keep accepted sold eligibility and recorded precision for individual ratios."""
    components = animal_components(animals, health)
    sold = animals.loc[components[["head_adg_eligible", "head_fcr_eligible", "head_feed_cog_eligible"]]
                       .eq(1).all(axis=1)].copy()
    sold["fcr_percentile"] = sold.fcr.rank(method="max", pct=True)
    return sold


def lot_efficiency_review(lots, delivery):
    """Compare sold lot FCR to other lots in its placement quarter."""
    key = ("lot_id",)
    feed = feed_rollup(delivery, by=key).reset_index()
    fields = [*key, "pen_id", "arrival_date", "head_placed", "head_fcr_eligible",
              "fcr_gain_kg", "sold_fcr", "sold_feed_cog", "sold_adg_kg_per_day",
              "all_outcome_margin_per_head_placed"]
    review = add_columns(lots[fields], feed, key=key, cardinality="one_to_one")
    review["placement_quarter"] = review.arrival_date.dt.to_period("Q")
    groups = review.groupby("placement_quarter", observed=True).sold_fcr
    review["peer_lots"] = groups.transform("size") - 1
    review["peer_median_fcr"] = groups.transform(
        lambda values: pd.Series([values.drop(index).median() for index in values.index], index=values.index)
    )
    review["fcr_above_peer_median"] = review.sold_fcr - review.peer_median_fcr
    return review


def growth_events(scale, animals):
    """Add individual context without changing scale-event grain."""
    require_key(scale, ("animal_id", "weigh_stage"), "scale")
    dimensions = ["animal_id", "breed", "sex", "frame_score", "financial_dof", "net_margin_cad"]
    events = add_columns(scale, animals[dimensions], key=("animal_id",), cardinality="many_to_one")
    events["weigh_stage"] = pd.Categorical(events.weigh_stage, categories=STAGES, ordered=True)
    if events.weigh_stage.isna().any():
        raise ValueError("Unexpected scale stage")
    events["entry_weight_group"] = pd.cut(
        events.entry_weight_kg, [-np.inf, 310, 340, 370, np.inf],
        labels=["<310 kg", "310–<340 kg", "340–<370 kg", "≥370 kg"], right=False,
    )
    return events


def stage_coverage(events, animals):
    """At-risk through each scheduled elapsed day; Closeout eligibility is sale."""
    days = (animals.exit_date - animals.entry_date).dt.days
    eligible = {stage: int(days.ge(offset).sum()) for stage, offset in STAGE_DAYS.items()}
    eligible["Closeout"] = int(animals.exit_type.eq(FINISHED).sum())
    counts = events.groupby("weigh_stage", observed=True).agg(
        recorded=("animal_id", "size"), lots=("lot_id", "nunique"),
        mortality=("exit_type", lambda values: values.ne(FINISHED).sum()),
    ).reindex(STAGES, fill_value=0)
    counts["eligible"] = pd.Series(eligible)
    counts["coverage_eligible"] = safe_ratio(counts.recorded, counts.eligible)
    counts["share_placements"] = counts.recorded / len(animals)
    return counts


def stage_summary(events, *, by=("weigh_stage",)):
    """Summarize observed animals with elapsed interval and elapsed cumulative ADG."""
    groups = events.groupby(list(by), observed=True)
    stats = groups.agg(
        recorded=("animal_id", "size"), lots=("lot_id", "nunique"), pens=("pen_id", "nunique"),
        median_weight_kg=("weight_kg", "median"), weight_p25=("weight_kg", lambda values: values.quantile(.25)),
        weight_p75=("weight_kg", lambda values: values.quantile(.75)),
        interval_head=("interval_adg_kg", "count"), interval_days=("elapsed_interval_days", "sum"),
        mean_interval_days=("elapsed_interval_days", "mean"), interval_gain_kg=("interval_gain_kg", "sum"),
        mean_interval_adg=("interval_adg_kg", "mean"), sd_interval_adg=("interval_adg_kg", "std"),
        mean_elapsed_cumulative_adg=("elapsed_cumulative_adg_kg", "mean"),
    )
    stats["elapsed_weighted_interval_adg"] = safe_ratio(stats.interval_gain_kg, stats.interval_days)
    return stats


def _cluster_mean(values, *, draws, rng):
    sums = values.groupby("pen_id", observed=True).delta.agg(["sum", "count"]).to_numpy()
    if len(sums) < 2:
        return np.nan, np.nan
    sample = rng.integers(len(sums), size=(draws, len(sums)))
    totals, counts = sums[sample].sum(axis=1).T
    return np.quantile(totals / counts, [.025, .975])


def matched_growth(events, *, draws=2000, seed=20261121):
    """Pair successive interval ADGs and resample complete pens for sensitivity."""
    if draws < 1:
        raise ValueError("At least one resample is required")
    wide = events.pivot(index=["animal_id", "lot_id", "pen_id"], columns="weigh_stage", values="interval_adg_kg")
    rng = np.random.default_rng(seed)
    comparisons = []
    for before, after in zip(STAGES[1:-1], STAGES[2:], strict=True):
        pair = wide[[before, after]].dropna()
        if pair.empty:
            continue
        delta = pair[after] - pair[before]
        low, high = _cluster_mean(delta.rename("delta").reset_index(), draws=draws, rng=rng)
        comparisons.append({
            "from_stage": before, "to_stage": after, "matched_head": len(pair),
            "lots": pair.index.get_level_values("lot_id").nunique(),
            "pens": pair.index.get_level_values("pen_id").nunique(),
            "before_adg": pair[before].mean(), "after_adg": pair[after].mean(),
            "paired_change": delta.mean(), "sd_change": delta.std(),
            "pen_bootstrap_low": low, "pen_bootstrap_high": high,
            "rank_correlation": pair.rank().corr().iloc[0, 1],
        })
    return wide, pd.DataFrame(comparisons)


def growth_variability(wide):
    """Compare realized within- and between-lot sums of squares and repeated low ranks."""
    early = ["Day 35", "Day 70", "Day 105"]
    matched = wide.dropna(subset=early)[early]
    lot_means = matched.groupby(level="lot_id").transform("mean")
    between = (lot_means - matched.mean()).pow(2).sum()
    within = (matched - lot_means).pow(2).sum()
    summary = pd.DataFrame({
        "matched_head": len(matched), "pooled_sd": matched.std(),
        "within_lot_sd": np.sqrt(within / (len(matched) - matched.index.get_level_values("lot_id").nunique())),
        "between_lot_share_of_ss": safe_ratio(between, within + between),
    })
    # Use the bottom decile within each lot and interval; ties can increase the flag count.
    cutoffs = matched.groupby(level="lot_id").transform("quantile", q=.10)
    low = matched.le(cutoffs)
    flags = pd.Series({
        "matched_head": len(matched), "low_day35": int(low["Day 35"].sum()),
        "low_day35_and_day70": int((low["Day 35"] & low["Day 70"]).sum()),
        "low_all_three": int(low.all(axis=1).sum()),
        "median_individual_adg_range": (matched.max(axis=1) - matched.min(axis=1)).median(),
    })
    return summary, flags


def lot_composition_controls(animals):
    """One lot context row based on the supplied eligible animals and their actual traits."""
    require_key(animals, ("animal_id",), "animal composition population")
    base = animals.groupby("lot_id", observed=True).agg(
        mean_entry_weight_kg=("entry_weight_kg", "mean"), mean_financial_dof=("financial_dof", "mean"),
    )
    traits = pd.get_dummies(animals[["breed", "sex", "frame_score"]], dtype=float)
    shares = traits.groupby(animals.lot_id, observed=True).mean()
    return base.join(shares).reset_index()
