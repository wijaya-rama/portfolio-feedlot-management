"""Optional live-cattle quote assumptions for the month-end inventory."""

import numpy as np
import pandas as pd

from .contracts import SEXES
from .loaders import calendar_dates
from .relations import require_key

CAD_PER_CWT_LIVE = "CAD/cwt live"
CAD_PER_KG_LIVE = "CAD/kg live"
KG_PER_CWT = 45.359237
QUOTE_DATES = ("month_end", "observed_on", "published_on")
QUOTE_NUMBERS = ("min_live_kg", "max_live_kg", "price", "costs_to_sell_cad_per_head")
QUOTE_TEXT = ("quote_id", "sex", "animal_class", "geography", "unit", "reference", "usage_rights")
QUOTE_COLUMNS = ("quote_id", *QUOTE_DATES, "sex", "animal_class", "geography",
                 "min_live_kg", "max_live_kg", "price", "unit", "reference", "usage_rights",
                 "costs_to_sell_cad_per_head")
MARKET_AMOUNTS = ("estimated_market_value_cents", "indicative_market_less_costs_to_sell_cents")


def market_quotes(rows):
    """Validate supplied assumptions. An empty iterable supplies no price observations."""
    quotes = pd.DataFrame.from_records(rows)
    if len(quotes) and set(quotes) - set(QUOTE_COLUMNS):
        raise ValueError("Unrecognized market quote columns")
    quotes = quotes.reindex(columns=QUOTE_COLUMNS)
    for name in QUOTE_TEXT:
        quotes[name] = quotes[name].astype("string").str.strip()
        if not quotes[name].str.len().gt(0).fillna(False).all():
            raise ValueError(f"Market quote requires {name}")
    for name in QUOTE_DATES:
        quotes[name] = calendar_dates(quotes[name].astype("string"))
    for name in QUOTE_NUMBERS:
        quotes[name] = pd.to_numeric(quotes[name], errors="raise").astype("float64")
        valid = np.isfinite(quotes[name]) & quotes[name].ge(0)
        if name == "costs_to_sell_cad_per_head":
            valid |= quotes[name].isna()
        if not valid.all():
            raise ValueError(f"Invalid market quote {name}")
    require_key(quotes, ("quote_id",), "market quotes")
    valid_dates = (quotes.month_end.dt.is_month_end & quotes.observed_on.le(quotes.published_on)
                   & quotes.published_on.le(quotes.month_end))
    valid_price = quotes.unit.isin((CAD_PER_CWT_LIVE, CAD_PER_KG_LIVE)) & quotes.price.gt(0)
    if not valid_dates.all():
        raise ValueError("Market quote must be observed and published by its reporting month-end")
    if not valid_price.all() or not quotes.max_live_kg.gt(quotes.min_live_kg).all():
        raise ValueError("Market quote requires a positive price in CAD per liveweight unit and a valid weight band")
    if not quotes.sex.isin(SEXES).all():
        raise ValueError("Market quote sex must match the recorded cattle categories")
    quotes = quotes.sort_values(["month_end", "sex", "min_live_kg"], ignore_index=True)
    previous_upper = quotes.groupby(["month_end", "sex"]).max_live_kg.shift()
    if quotes.min_live_kg.lt(previous_upper).any():
        raise ValueError("Market quote weight bands overlap for a month and sex")
    quotes["cad_per_live_kg"] = quotes.price.where(
        quotes.unit.eq(CAD_PER_KG_LIVE), quotes.price / KG_PER_CWT,
    )
    return quotes


def attach_market(ledger, scales, quotes, *, max_weight_age_days):
    """Carry the latest available scale weight without using future weights or exits."""
    if (isinstance(max_weight_age_days, bool) or not isinstance(max_weight_age_days, int)
            or max_weight_age_days < 0):
        raise ValueError("max_weight_age_days must be a nonnegative integer")
    stock = ledger.loc[ledger.closing_head.eq(1), ["animal_id", "month_end", "sex"]]
    weighings = scales[["animal_id", "weigh_date", "weight_kg"]]
    require_key(weighings, ("animal_id", "weigh_date"), "dated individual weighings")
    stock = pd.merge_asof(
        stock.sort_values("month_end"), weighings.sort_values("weigh_date"),
        by="animal_id", left_on="month_end", right_on="weigh_date", direction="backward",
    )
    stock["weight_age_days"] = (stock.month_end - stock.weigh_date).dt.days.astype("Int64")
    usable = stock.weight_age_days.le(max_weight_age_days).fillna(False)
    stock["liveweight_proxy_kg"] = stock.weight_kg.where(usable)
    stock["weight_basis"] = pd.Series("carried_forward", index=stock.index, dtype="string")
    stock.loc[stock.weight_age_days.eq(0).fillna(False), "weight_basis"] = "same_day_scale"
    stock.loc[~usable, "weight_basis"] = "stale_scale"
    stock.loc[stock.weigh_date.isna(), "weight_basis"] = "missing_scale"
    stock["quote_id"] = pd.Series(pd.NA, index=stock.index, dtype="string")
    for col in MARKET_AMOUNTS:
        stock[col] = pd.Series(pd.NA, index=stock.index, dtype="Int64")
    for quote in quotes.itertuples(index=False):
        mask = (stock.month_end.eq(quote.month_end) & stock.sex.eq(quote.sex)
                & stock.liveweight_proxy_kg.ge(quote.min_live_kg)
                & stock.liveweight_proxy_kg.lt(quote.max_live_kg))
        gross_cad = stock.loc[mask, "liveweight_proxy_kg"] * quote.cad_per_live_kg
        stock.loc[mask, "quote_id"] = quote.quote_id
        stock.loc[mask, MARKET_AMOUNTS[0]] = (100 * gross_cad).round().astype("Int64")
        if pd.notna(quote.costs_to_sell_cad_per_head):
            net_cad = gross_cad - quote.costs_to_sell_cad_per_head
            stock.loc[mask, MARKET_AMOUNTS[1]] = (100 * net_cad).round().astype("Int64")
    stock["market_status"] = pd.Series("no_price_assumption", index=stock.index, dtype="string")
    stock.loc[~usable, "market_status"] = "weight_unavailable"
    stock.loc[stock.quote_id.notna(), "market_status"] = "estimated"
    result = ledger.merge(
        stock.drop(columns=["sex", "weight_kg"]).rename(columns={"weigh_date": "last_scale_date"}),
        on=["animal_id", "month_end"], how="left", validate="one_to_one",
    )
    result["market_status"] = result.market_status.fillna("no_closing_stock")
    return result
