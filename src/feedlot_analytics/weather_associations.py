"""Calendar exposure and exploratory associations for simulated feedlot outcomes."""

import numpy as np
import pandas as pd

from .contracts import PEN_TYPES
from .feed_growth import feed_rollup, lot_composition_controls
from .metrics import aggregate_pen_feed
from .relations import add_columns, require_key, safe_ratio
from .weather import COLD_THRESHOLD_C, exposure_windows, map_weather_date

TEMPERATURE = "temperature_2m_mean"
EXTREME_MIN_C = -20.0
DM = "delivered_dm_per_head_day"
COST = "delivered_cost_per_head_day"
SEASONS = {
    12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON",
}
PEN_CONTRAST = ("Confinement Barn", "Standard Open Dirt")


def weather_calendar(weather):
    """Identify cold runs and mark incomplete months using observed calendar dates."""
    require_key(weather, ("date",), "weather")
    daily = weather.sort_values("date").copy()
    daily["month"] = daily.date.dt.to_period("M")
    daily["season"] = daily.date.dt.month.map(SEASONS)
    daily["full_month"] = daily.groupby("month").date.transform("size").eq(daily.date.dt.days_in_month)
    daily["cold"] = daily[TEMPERATURE].lt(COLD_THRESHOLD_C)
    daily["extreme_cold"] = daily.temperature_2m_min.le(EXTREME_MIN_C)
    return daily


def weather_spells(daily, flag):
    """Runs of consecutive qualifying dates, with archive-edge censoring flagged."""
    require_key(daily, ("date",), "weather")
    dates = daily.loc[daily[flag], "date"].sort_values()
    runs = dates.diff().dt.days.ne(1).cumsum()
    spells = dates.groupby(runs).agg(first_date="min", last_date="max", days="size").reset_index(drop=True)
    spells["touches_archive_edge"] = (
        spells.first_date.eq(daily.date.min()) | spells.last_date.eq(daily.date.max())
    )
    return spells


def weather_rollup(daily, *, by):
    """Describe all nine weather variables without filling uncovered dates."""
    return daily.groupby(list(by), observed=True).agg(
        weather_days=("date", "size"), cold_days=("cold", "sum"), extreme_days=("extreme_cold", "sum"),
        mean_air_c=(TEMPERATURE, "mean"), lowest_min_c=("temperature_2m_min", "min"),
        highest_max_c=("temperature_2m_max", "max"), mean_apparent_c=("apparent_temperature_mean", "mean"),
        mean_daily_max_wind_kmh=("wind_speed_10m_max", "mean"), peak_wind_kmh=("wind_speed_10m_max", "max"),
        peak_gust_kmh=("wind_gusts_10m_max", "max"), snowfall_cm=("snowfall_sum", "sum"),
        precipitation_mm=("precipitation_sum", "sum"), mean_humidity_pct=("relative_humidity_2m_mean", "mean"),
    )


def feed_calendar(pen_days, daily):
    """One matched row per operational date, and a separate observed-pen-type calendar."""
    key = ("feed_date",)
    overall = aggregate_pen_feed(pen_days, by=key)
    by_type = aggregate_pen_feed(pen_days, by=(*key, "pen_type"))
    mapped = tuple(map_weather_date(frame, daily, date_role="feed_date") for frame in (overall, by_type))
    if not all(frame.weather_date_available.all() for frame in mapped):
        raise ValueError("Each delivery date requires observed weather")
    return mapped


def feed_mix_by_date(delivery, animals):
    """Summarize the lot placement mix and recorded feed stage on each feed date."""
    context = lot_composition_controls(animals).drop(columns="mean_financial_dof")
    data = add_columns(delivery, context, key=("lot_id",), cardinality="many_to_one")
    classes = pd.get_dummies(data[["ration_phase", "pen_type"]], dtype=float)
    numeric = [*context.columns.drop("lot_id"), "dof_current"]
    values = pd.concat([data[numeric], classes], axis=1)
    weighted = values.mul(data.recorded_head_days, axis=0).groupby(data.feed_date).sum()
    head_days = data.groupby("feed_date").recorded_head_days.sum()
    return weighted.div(head_days, axis=0).reset_index()


def exposure_summary(windows, *, by):
    """Describe exposure windows and explicitly count shared calendar schedules."""
    dates = [column for column in windows if column in (
        "entry_date", "exit_date", "first_feed_date", "last_feed_date",
    )]
    context = windows.assign(
        cold_day_equivalents=windows.cold_days,
        temperature_day_sum=windows.mean_temperature_c * windows.expected_exposure_days,
    )
    groups = context.groupby(list(by), observed=True)
    result = groups.agg(
        windows=("expected_exposure_days", "size"), exposure_days=("expected_exposure_days", "sum"),
        cold_days=("cold_day_equivalents", "sum"), mean_cold_days=("cold_days", "mean"),
        mean_window_cold_share=("cold_day_proportion", "mean"), mean_window_snow_cm=("snowfall_exposure_cm", "mean"),
        mean_window_peak_wind_kmh=("maximum_wind_kmh", "mean"), temperature_day_sum=("temperature_day_sum", "sum"),
    )
    result["distinct_windows"] = context[[*by, *[date for date in dates if date not in by]]].drop_duplicates().groupby(
        list(by), observed=True
    ).size()
    result["exposure_day_cold_share"] = safe_ratio(result.cold_days, result.exposure_days)
    result["exposure_day_mean_c"] = safe_ratio(result.temperature_day_sum, result.exposure_days)
    return result


def interval_exposure(events, weather, lots):
    """Attach endpoint weather and weather over (previous weighing, current weighing]."""
    require_key(events, ("animal_id", "weigh_stage"), "weighings")
    timed = add_columns(
        events, weather[["date", TEMPERATURE]].rename(
            columns={"date": "weigh_date", TEMPERATURE: "weigh_day_temperature_c"}
        ), key=("weigh_date",), cardinality="many_to_one",
    )
    timed = timed.loc[timed.elapsed_interval_days.gt(0)].copy()
    timed = add_columns(timed, lots[["lot_id", "pen_type"]], key=("lot_id",), cardinality="many_to_one")
    timed["first_interval_day"] = timed.previous_weigh_date + pd.Timedelta(days=1)
    key = ("first_interval_day", "weigh_date", "pen_type")
    distinct = timed[list(key)].drop_duplicates(ignore_index=True).reset_index(names="window_id")
    windows = exposure_windows(distinct, weather, id_col="window_id",
                               start_col="first_interval_day", end_col="weigh_date")
    attach = [*key, "expected_exposure_days", "weather_date_count", "temperature_days",
              "mean_temperature_c", "cold_day_proportion"]
    aligned = add_columns(timed, windows[attach], key=key, cardinality="many_to_one")
    if (not aligned.expected_exposure_days.eq(aligned.elapsed_interval_days).all()
            or not aligned.temperature_days.eq(aligned.elapsed_interval_days).all()
            or not aligned.weather_date_count.eq(aligned.elapsed_interval_days).all()):
        raise ValueError("Weigh intervals require an exact, complete elapsed-day weather match")
    return aligned


def growth_weather_inputs(intervals, lots):
    """Reduce aligned intervals to one observation per lot and stage."""
    weighted = intervals.assign(
        temperature_days_sum=intervals.mean_temperature_c * intervals.elapsed_interval_days,
        cold_days_sum=intervals.cold_day_proportion * intervals.elapsed_interval_days,
    )
    totals = weighted.groupby(["lot_id", "weigh_stage"], observed=True, as_index=False).agg(
        head=("animal_id", "size"), interval_gain_kg=("interval_gain_kg", "sum"),
        interval_days=("elapsed_interval_days", "sum"), first_day=("first_interval_day", "min"),
        last_day=("weigh_date", "max"), temperature_days_sum=("temperature_days_sum", "sum"),
        cold_days_sum=("cold_days_sum", "sum"),
    )
    totals["mean_interval_days"] = safe_ratio(totals.interval_days, totals["head"])
    totals["interval_adg"] = safe_ratio(totals.interval_gain_kg, totals.interval_days)
    totals["mean_temperature_c"] = safe_ratio(totals.temperature_days_sum, totals.interval_days)
    totals["cold_day_proportion"] = safe_ratio(totals.cold_days_sum, totals.interval_days)
    composition = [
        lot_composition_controls(frame).assign(weigh_stage=stage)
        for stage, frame in intervals.groupby("weigh_stage", observed=True)
    ]
    totals = add_columns(totals, pd.concat(composition, ignore_index=True),
                         key=("lot_id", "weigh_stage"), cardinality="one_to_one")
    return add_columns(totals, lots[["lot_id", "pen_id", "pen_type", "arrival_date"]],
                       key=("lot_id",), cardinality="many_to_one")


def sold_weather_inputs(sold, windows, lots):
    """Use the case-matched sold animal windows for sold ADG and allocated FCR."""
    key = ("animal_id",)
    require_key(sold, key, "eligible sold animals")
    selected = add_columns(sold, windows[[*key, "mean_temperature_c", "cold_day_proportion"]],
                           key=key, cardinality="one_to_one")
    grouped = selected.groupby("lot_id", as_index=False)
    exposures = grouped.agg(
        mean_temperature_c=("mean_temperature_c", "mean"), cold_day_proportion=("cold_day_proportion", "mean"),
        first_day=("entry_date", "min"), last_day=("exit_date", "max"),
        head=("animal_id", "size"), entry_schedules=("entry_date", "nunique"),
        exit_schedules=("exit_date", "nunique"),
    )
    lot_metrics = lots[["lot_id", "pen_id", "pen_type", "arrival_date", "sold_adg_kg_per_day", "sold_fcr",
                       "head_adg_eligible", "head_fcr_eligible"]]
    selected_lots = add_columns(exposures, lot_metrics, key=("lot_id",), cardinality="one_to_one")
    if (not selected_lots.head_adg_eligible.eq(selected_lots["head"]).all()
            or not selected_lots.head_fcr_eligible.eq(selected_lots["head"]).all()):
        raise ValueError("Sold exposure and performance denominators must be identical")
    return add_columns(selected_lots, lot_composition_controls(selected), key=("lot_id",), cardinality="one_to_one")


def _residual_fit(frame, *, predictor, outcome, controls, fixed):
    """Residualize both variables against the nuisance design before fitting the slope."""
    nuisance = frame[list(controls)].to_numpy(dtype=float)
    if fixed:
        indicators = pd.get_dummies(frame[list(fixed)].astype("category"), drop_first=True, dtype=float)
        nuisance = np.column_stack((nuisance, indicators))
    design = np.column_stack((np.ones(len(frame)), nuisance))
    if frame.empty:
        return np.nan, np.empty(0), np.empty(0), 0.0, 0
    observed = frame[[predictor, outcome]].to_numpy(dtype=float)
    coefficients, _, rank, _ = np.linalg.lstsq(design, observed, rcond=None)
    x, y = (observed - design @ coefficients).T
    xx = x @ x
    if len(frame) <= rank + 1 or xx <= 1e-12 * max(1, observed[:, 0].var() * len(frame)):
        return np.nan, x, y, xx, rank
    slope = (x @ y) / xx
    return slope, x, y - slope * x, xx, rank


def association(frame, *, predictor, outcome, increment=1.0, controls=(), fixed=(),
                exclude_by=(), daily_date=None, hac_lags=()):
    """Fit a slope at declared grain, with optional contiguous daily HAC and deletion ranges."""
    columns = list(dict.fromkeys((predictor, outcome, *controls, *fixed, *exclude_by)))
    if daily_date:
        columns.append(daily_date)
    data = frame[columns].dropna().copy()
    if daily_date:
        require_key(data, (daily_date,), "daily regression")
        data = data.sort_values(daily_date)
        if not data[daily_date].diff().dropna().eq(pd.Timedelta(days=1)).all():
            raise ValueError("Daily HAC requires consecutive calendar dates")
    if hac_lags and not daily_date:
        raise ValueError("HAC lags require an explicit daily date column")
    kwargs = {"predictor": predictor, "outcome": outcome, "controls": controls, "fixed": fixed}
    slope, x, residual, xx, rank = _residual_fit(data, **kwargs)
    result = {
        "observations": len(data), "residual_df": len(data) - rank - 1,
        "predictor_residual_sd": np.sqrt(xx / len(data)) if len(data) else np.nan,
        "effect": slope * increment,
    }
    for lag in hac_lags:
        if not 0 <= lag < len(data):
            raise ValueError("HAC bandwidth must be smaller than the daily sample")
        # Bartlett kernel applied to the slope's Frisch–Waugh–Lovell score.
        score = x * residual / xx if np.isfinite(slope) else np.full(len(data), np.nan)
        variance = score @ score
        for offset in range(1, lag + 1):
            variance += 2 * (1 - offset / (lag + 1)) * (score[offset:] @ score[:-offset])
        half_width = 1.96 * np.sqrt(max(variance, 0)) * abs(increment) if np.isfinite(variance) else np.nan
        result[f"hac{lag}_low"] = result["effect"] - half_width
        result[f"hac{lag}_high"] = result["effect"] + half_width
    for column in exclude_by:
        estimates = []
        for label in data[column].unique():
            trimmed = data.loc[data[column].ne(label)]
            if not trimmed.empty:
                estimate, *_ = _residual_fit(trimmed, **kwargs)
                if np.isfinite(estimate):
                    estimates.append(estimate * increment)
        result[f"{column}_groups"] = data[column].nunique()
        result[f"{column}_identified"] = len(estimates)
        result[f"{column}_low"] = min(estimates, default=np.nan)
        result[f"{column}_high"] = max(estimates, default=np.nan)
    return result


def daily_feed_associations(daily, mix):
    """Compare pooled with within-month, mix-adjusted relationships at one row per date."""
    key = ("feed_date",)
    data = add_columns(daily, mix, key=key, cardinality="one_to_one").loc[lambda rows: rows.full_month]
    controls = tuple(mix.columns.drop("feed_date"))
    results = []
    for outcome in (DM, COST):
        for predictor, increment in ((TEMPERATURE, 10.0), ("cold", 1.0), ("extreme_cold", 1.0)):
            designs = (("pooled", (), ()), ("within month", (), ("month",)),
                       ("within month + mix", controls, ("month",)))
            for model, numeric, fixed in designs:
                estimates = association(
                    data, predictor=predictor, outcome=outcome, increment=increment, controls=numeric,
                    fixed=fixed, daily_date="feed_date", hac_lags=(14, 28),
                )
                results.append({
                    "outcome": outcome, "predictor": predictor, "increment": increment, "model": model,
                    "cold_dates": int(data.cold.sum()), "extreme_dates": int(data.extreme_cold.sum()),
                    "months": data.month.nunique(), **estimates,
                })
    return pd.DataFrame(results)


def paired_pen_weather(daily_by_type):
    """Use dates with deliveries in both the barn and standard open classifications."""
    common = daily_by_type.loc[daily_by_type.full_month & daily_by_type.pen_type.isin(PEN_CONTRAST)]
    wide = common.pivot(index="feed_date", columns="pen_type", values=[DM, COST]).dropna()
    dates = common[["feed_date", "month", TEMPERATURE, "cold"]].drop_duplicates()
    require_key(dates, ("feed_date",), "matched pen-type weather")
    joined = dates.set_index("feed_date").loc[wide.index].copy()
    barn, open_dirt = PEN_CONTRAST
    records = []
    for outcome in (DM, COST):
        joined["difference"] = wide[outcome][barn] - wide[outcome][open_dirt]
        estimates = association(joined, predictor=TEMPERATURE, outcome="difference", increment=10,
                                fixed=("month",), exclude_by=("month",))
        records.append({
            "outcome": outcome, "common_dates": len(joined), "cold_dates": int(joined.cold.sum()),
            "mean_barn_less_open": joined.difference.mean(), **estimates,
        })
    return pd.DataFrame(records)


def lot_associations(frame, *, predictor, outcomes, increment, controls, calendar="placement_month"):
    """Use equally weighted lots and drop whole pens or scan overlapping weather blocks."""
    require_key(frame, ("lot_id",), "lot regression")
    data = frame.assign(
        placement_month=frame.arrival_date.dt.to_period("M"),
        placement_quarter=frame.arrival_date.dt.to_period("Q"),
    )
    first = data.first_day.min()
    start = pd.Timestamp(first.year, 1 if first.month <= 6 else 7, 1)
    block_starts = pd.date_range(start, data.last_day.max(), freq="2QS-JAN")
    results = []
    for outcome in outcomes:
        model = dict(predictor=predictor, outcome=outcome, increment=increment,
                     controls=controls, fixed=(calendar, "pen_type"))
        estimates = association(data, **model, exclude_by=("pen_id",))
        block_estimates = []
        for left in block_starts:
            right = left + pd.DateOffset(months=6)
            kept = data.last_day.lt(left) | data.first_day.ge(right)
            effect = association(data.loc[kept], **model)["effect"]
            if np.isfinite(effect):
                block_estimates.append(effect)
        results.append({
            "outcome": outcome, "predictor": predictor, "increment": increment, "calendar": calendar,
            "eligible_head": int(data["head"].sum()), "unique_schedules": len(data[["first_day", "last_day"]].drop_duplicates()),
            "within_calendar_groups": data[calendar].nunique(),
            "calendar_block_groups": len(block_starts), "calendar_block_identified": len(block_estimates),
            "calendar_block_low": min(block_estimates, default=np.nan),
            "calendar_block_high": max(block_estimates, default=np.nan), **estimates,
        })
    return pd.DataFrame(results)


def within_lot_performance(sold):
    """Describe FCR, ADG and margin with matched within-lot traits and pen deletion."""
    fields = ("fcr", "lifetime_adg_kg", "net_margin_cad", "entry_weight_kg")
    traits = pd.get_dummies(sold[["breed", "sex", "frame_score"]], drop_first=True, dtype=float)
    values = pd.concat([sold[list(fields)], traits], axis=1)
    deviations = values - values.groupby(sold.lot_id, observed=True).transform("mean")
    deviations["pen_id"] = sold.pen_id
    controls = ("entry_weight_kg", *traits.columns)
    results = []
    for predictor, outcome, increment in (
        ("lifetime_adg_kg", "fcr", .10), ("lifetime_adg_kg", "net_margin_cad", .10),
        ("fcr", "net_margin_cad", 1.0),
    ):
        fit = association(deviations, predictor=predictor, outcome=outcome, increment=increment,
                          controls=controls, exclude_by=("pen_id",))
        fit["residual_df"] -= sold.lot_id.nunique() - 1
        results.append({"predictor": predictor, "outcome": outcome, "increment": increment, **fit})
    return pd.DataFrame(results)
