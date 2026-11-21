"""Monthly ownership, cost accumulation and release for the audited closed cohort."""

from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import BOOK, COSTS, FINISHED, MORTALITY
from .feed_growth import SOURCE_HASHES, load_analysis
from .inventory_market import MARKET_AMOUNTS, attach_market, market_quotes
from .loaders import NA_OPTIONS, TEXT_DTYPES, schema, sha256, typed_dates
from .pipeline import BuildResult
from .relations import cents, require_key
from .validation import Controls

IDENTITY = ("animal_id", "lot_id", "pen_id", "breed", "sex")
LOT_PEN_MONTH = ("month_end", "lot_id", "pen_id")
ANIMAL_MONTH = ("animal_id", "month_end")
YARDAGE_CENTS_PER_DAY = 60
UNDATED_VET_BASE_CENTS = 1800
STOCK_FLOWS = ("placed_head", "sold_head", "mortality_head")
SOURCE_COSTS = ("purchase_cents", "direct_vet_cents")
PRODUCTION_COSTS = ("direct_vet_cents", "estimated_feed_cents", "estimated_yardage_cents")
MOVEMENTS = (*STOCK_FLOWS, "production_head_days", "purchase_cents", *PRODUCTION_COSTS,
             "adjustments_applied_cents", "source_sold_release_cents", "source_mortality_release_cents",
             "estimated_sold_cogs_cents", "estimated_mortality_loss_cents")
OPENING = ("opening_head", "source_opening_wip_cents", "estimated_opening_wip_cents")
CLOSING = ("closing_head", "source_closing_wip_cents", "estimated_closing_wip_cents",
           "closing_purchase_basis_cents")
ACTUAL_AMOUNTS = {
    "actual_closing_wip_cents": "closing_head",
    "actual_sold_cogs_cents": "sold_head",
    "actual_mortality_loss_cents": "mortality_head",
}
MARKET_COUNTS = ("weight_eligible_head", "market_valued_head", "market_less_selling_costs_valued_head")
FEED_VALUES = ("delivered_as_fed_kg", "delivered_dm_kg", "recorded_head_days", "delivery_cost_cents")


def _month_end(dates):
    return dates + pd.offsets.MonthEnd(0)


def _animal_feed_by_month(animals, delivery):
    """Allocate each dated lot–pen delivery across inclusive feeding head-days in cents."""
    require_key(delivery, ("lot_id", "pen_id", "feed_date"), "dated feed")
    if (delivery[["recorded_head_days", "delivered_feed_cost_cad"]].isna().any(axis=None)
            or delivery.delivered_feed_cost_cad.lt(0).any()):
        raise ValueError("Dated feed requires head counts and nonnegative delivered costs")
    cohorts = animals.groupby(["lot_id", "pen_id"], sort=True)
    deliveries = delivery.groupby(["lot_id", "pen_id"], sort=True)
    if cohorts.groups.keys() != deliveries.groups.keys():
        raise ValueError("Dated feed is required for every recorded lot and pen")
    parts = []
    for key, group in cohorts:
        group = group.sort_values("animal_id")
        feed = deliveries.get_group(key).sort_values("feed_date")
        dates = pd.date_range(group.entry_date.min(), group.exit_date.max())
        if not dates.equals(pd.DatetimeIndex(feed.feed_date)):
            raise ValueError(f"Incomplete dated feed for lot and pen {key}")
        day = dates.to_numpy()[None, :]
        eligible = ((group.entry_date.to_numpy()[:, None] <= day) &
                    (group.exit_date.to_numpy()[:, None] >= day))
        counts = eligible.sum(axis=0)
        if (counts == 0).any() or not np.array_equal(counts, feed.recorded_head_days.to_numpy()):
            raise ValueError(f"Feed head-days disagree with cattle dates for lot and pen {key}")
        base, remainder = np.divmod(cents(feed.delivered_feed_cost_cad).to_numpy(), counts)
        # Residual cents go to the first eligible IDs in sorted order on each day.
        daily = np.where(eligible, base + (eligible.cumsum(axis=0) <= remainder), 0)
        month_ends = dates + pd.offsets.MonthEnd(0)
        for month_end in month_ends.unique():
            month = month_ends == month_end
            present = eligible[:, month].any(axis=1)
            parts.append(pd.DataFrame({
                "animal_id": group.animal_id[present],
                "month_end": month_end,
                "estimated_feed_cents": daily[present][:, month].sum(axis=1),
            }))
    return pd.concat(parts, ignore_index=True)


def _animal_months(animals, treatments, delivery, months):
    cohort = animals[[*IDENTITY, "entry_date", "exit_date", "exit_type", "purchase_cost_cad"]]
    entries = cohort.merge(pd.DataFrame({"month_end": months}), how="cross")
    start = entries.month_end.dt.to_period("M").dt.start_time
    entries = entries.loc[entries.entry_date.le(entries.month_end) & entries.exit_date.ge(start)].copy()
    start = start.loc[entries.index]
    exits = entries.exit_date.le(entries.month_end)
    entries["opening_head"] = entries.entry_date.lt(start).astype("int64")
    entries["placed_head"] = entries.entry_date.ge(start).astype("int64")
    entries["sold_head"] = (exits & entries.exit_type.eq(FINISHED)).astype("int64")
    entries["mortality_head"] = (exits & entries.exit_type.eq(MORTALITY)).astype("int64")
    entries["closing_head"] = (~exits).astype("int64")
    first_day = entries.entry_date.where(entries.entry_date.ge(start), start)
    last_day = entries.exit_date.where(exits, entries.month_end)
    entries["production_head_days"] = (last_day - first_day).dt.days + 1
    entries["purchase_cents"] = cents(entries.purchase_cost_cad).where(entries.placed_head.eq(1), 0)
    entries["closing_purchase_basis_cents"] = cents(entries.purchase_cost_cad).where(~exits, 0)
    entries["exit_date"] = entries.exit_date.where(exits)
    entries["exit_type"] = entries.exit_type.where(exits)
    require_key(treatments, ("treatment_id",), "dated treatments")
    treatment_costs = treatments.assign(
        month_end=_month_end(treatments.treatment_date), direct_vet_cents=cents(treatments.vet_cost_cad),
    ).groupby(list(ANIMAL_MONTH), as_index=False).direct_vet_cents.sum()
    entries = entries.drop(columns="purchase_cost_cad").merge(
        treatment_costs, on=list(ANIMAL_MONTH), how="left", validate="one_to_one",
    )
    entries["direct_vet_cents"] = entries.direct_vet_cents.fillna(0).astype("int64")
    feed = _animal_feed_by_month(animals, delivery)
    entries = entries.merge(feed, on=list(ANIMAL_MONTH), how="left", validate="one_to_one")
    if entries.estimated_feed_cents.isna().any() or len(entries) != len(feed):
        raise ValueError("Dated feed allocations must cover all animal-months")
    entries["estimated_yardage_cents"] = entries.production_head_days * YARDAGE_CENTS_PER_DAY
    entries["adjustments_applied_cents"] = 0
    entries = entries.sort_values(list(ANIMAL_MONTH), ignore_index=True)
    for basis, costs, sold, mortality in (
        ("source", SOURCE_COSTS, "source_sold_release_cents", "source_mortality_release_cents"),
        ("estimated", ("purchase_cents", *PRODUCTION_COSTS, "adjustments_applied_cents"),
         "estimated_sold_cogs_cents", "estimated_mortality_loss_cents"),
    ):
        additions = entries[list(costs)].sum(axis=1)
        accumulated = additions.groupby(entries.animal_id).cumsum()
        entries[f"{basis}_opening_wip_cents"] = accumulated - additions
        entries[f"{basis}_closing_wip_cents"] = accumulated.where(entries.closing_head.eq(1), 0)
        entries[sold] = accumulated.where(entries.sold_head.eq(1), 0)
        entries[mortality] = accumulated.where(entries.mortality_head.eq(1), 0)
    return entries


def _availability(frame):
    for value, head in ACTUAL_AMOUNTS.items():
        frame[value] = pd.Series(0, index=frame.index, dtype="Int64").mask(frame[head].gt(0))
    return frame


def _monthly_totals(ledger, months, dimensions):
    amount_fields = [*OPENING, *MOVEMENTS, *CLOSING, *MARKET_COUNTS]
    keys = ["month_end", *dimensions]
    calendar = pd.DataFrame({"month_end": months})
    if dimensions:
        calendar = calendar.merge(ledger[list(dimensions)].drop_duplicates(), how="cross")
    grouped = ledger.groupby(keys, as_index=False)
    totals = calendar.merge(grouped[amount_fields].sum(), on=keys, how="left", validate="one_to_one")
    totals[amount_fields] = totals[amount_fields].fillna(0).astype("int64")
    market = grouped[list(MARKET_AMOUNTS)].sum(min_count=1)
    totals = totals.merge(market, on=keys, how="left", validate="one_to_one")
    for value, count in zip(MARKET_AMOUNTS, MARKET_COUNTS[1:], strict=True):
        totals[value] = (totals[value].where(totals[count].eq(totals.closing_head))
                         .mask(totals.closing_head.eq(0), 0))
    return _availability(totals.sort_values(keys, ignore_index=True))


def _check_bridge(controls, table, name, *, dimensions=()):
    controls.rows(f"{name}.stock", table.opening_head.add(table.placed_head)
                  .sub(table.sold_head).sub(table.mortality_head).eq(table.closing_head))
    for basis, costs, sold, mortality in (
        ("source", SOURCE_COSTS, "source_sold_release_cents", "source_mortality_release_cents"),
        ("estimated", ("purchase_cents", *PRODUCTION_COSTS, "adjustments_applied_cents"),
         "estimated_sold_cogs_cents", "estimated_mortality_loss_cents"),
    ):
        closing = (table[f"{basis}_opening_wip_cents"] + table[list(costs)].sum(axis=1)
                   - table[sold] - table[mortality])
        controls.rows(f"{name}.{basis}_wip", closing.eq(table[f"{basis}_closing_wip_cents"]))
    ending = table[list(CLOSING[:3])]
    previous = (ending.groupby([table[column] for column in dimensions]).shift(fill_value=0)
                if dimensions else ending.shift(fill_value=0))
    previous.columns = list(OPENING)
    controls.rows(f"{name}.continuity", previous.eq(table[list(OPENING)]).all(axis=1))


def _annual_totals(monthly):
    years = monthly.groupby(monthly.month_end.dt.year.rename("year"), as_index=True)
    annual = years[list(OPENING)].first().join(years[list(MOVEMENTS)].sum())
    closing = years.tail(1).assign(year=lambda rows: rows.month_end.dt.year).set_index("year")
    annual = annual.join(closing[[*CLOSING, *MARKET_COUNTS, *MARKET_AMOUNTS]])
    annual["closing_month_end"] = closing.month_end
    return _availability(annual.reset_index())


def _closeout_audit(animals, ledger):
    """Keep lifetime source amounts in a retrospective comparison at the actual exit."""
    exits = ledger.loc[ledger.sold_head.add(ledger.mortality_head).eq(1)]
    releases = exits[[*ANIMAL_MONTH, "lot_id", "pen_id", "exit_date", "exit_type",
                      "estimated_sold_cogs_cents", "estimated_mortality_loss_cents"]].rename(
                          columns={"month_end": "exit_month_end"},
                      )
    booked = animals.set_index("animal_id")
    for name in COSTS:
        releases[f"booked_lifetime_{name.removesuffix('_cad')}_cents"] = releases.animal_id.map(cents(booked[name]))
    releases["booked_lifetime_total_cents"] = releases.animal_id.map(booked.production_cost_cents)
    incurred = ledger.groupby("animal_id")[["direct_vet_cents", "estimated_feed_cents",
                                             "estimated_yardage_cents"]].sum()
    for booked_name, modeled_name, delta in (
        ("vet_cost", "direct_vet_cents", "undated_vet_base_cents"),
        ("allocated_feed_cost", "estimated_feed_cents", "booked_less_allocated_delivery_cents"),
        ("yardage_cost", "estimated_yardage_cents", "booked_less_modeled_yardage_cents"),
    ):
        releases[delta] = (releases[f"booked_lifetime_{booked_name}_cents"]
                           - releases.animal_id.map(incurred[modeled_name]))
    return releases.reset_index(drop=True)


def _reconcile(animals, treatments, ledger, feed_monthly, tables):
    controls = Controls()
    reference = animals.set_index("animal_id").sort_index()
    by_animal = ledger.groupby("animal_id").sum(numeric_only=True).sort_index()
    require_key(ledger, ANIMAL_MONTH, "animal-month")
    controls.equal("animal.coverage", by_animal.index.equals(reference.index), True)
    expected_days = (reference.exit_date - reference.entry_date).dt.days + 1
    for name, expected in (
        ("placed_head", 1), ("sold_head", reference.exit_type.eq(FINISHED)),
        ("mortality_head", reference.exit_type.eq(MORTALITY)), ("production_head_days", expected_days),
        ("purchase_cents", cents(reference.purchase_cost_cad)),
        ("direct_vet_cents", treatments.assign(cost=cents(treatments.vet_cost_cad))
         .groupby("animal_id").cost.sum().reindex(reference.index, fill_value=0)),
        ("estimated_yardage_cents", expected_days * YARDAGE_CENTS_PER_DAY),
    ):
        controls.rows(f"animal.{name}", by_animal[name].eq(expected))
    _check_bridge(controls, ledger, "animal_month", dimensions=("animal_id",))
    feed = feed_monthly.set_index(list(LOT_PEN_MONTH)).sort_index()
    allocated = ledger.groupby(list(LOT_PEN_MONTH))[["estimated_feed_cents", "production_head_days"]].sum()
    controls.equal("feed.monthly_coverage", allocated.index.equals(feed.index), True)
    controls.rows("feed.monthly_cost", allocated.estimated_feed_cents.eq(feed.delivery_cost_cents))
    controls.rows("feed.monthly_head_days", allocated.production_head_days.eq(feed.recorded_head_days))
    for name, dimensions in (
        ("monthly_yard", ()), ("monthly_lot", ("lot_id", "pen_id")), ("monthly_recorded_pen", ("pen_id",)),
    ):
        totals = tables[name]
        _check_bridge(controls, totals, name, dimensions=dimensions)
        keys = [*dimensions, "month_end"]
        # Count dated entries/exits directly at each reporting grain.
        for head, dated in (
            ("placed_head", animals.assign(month_end=_month_end(animals.entry_date))),
            ("sold_head", animals.loc[animals.exit_type.eq(FINISHED)].assign(month_end=_month_end(animals.exit_date))),
            ("mortality_head", animals.loc[animals.exit_type.eq(MORTALITY)].assign(month_end=_month_end(animals.exit_date))),
        ):
            by_event = dated.groupby(keys).size()
            reported = totals.set_index(keys)[head]
            controls.rows(f"{name}.{head}", reported.eq(by_event.reindex(reported.index, fill_value=0)))
    annual = tables["annual_yard"]
    _check_bridge(controls, annual, "annual_yard")
    audit = tables["lifetime_closeout_audit"].set_index("animal_id").sort_index()
    require_key(audit.reset_index(), ("animal_id",), "exit release audit")
    controls.equal("exit.coverage", audit.index.equals(reference.index), True)
    controls.rows("exit.recorded_date_and_outcome",
                  audit.exit_date.eq(reference.exit_date) & audit.exit_type.eq(reference.exit_type))
    gap = audit.undated_vet_base_cents + audit.booked_less_allocated_delivery_cents + audit.booked_less_modeled_yardage_cents
    modeled = audit.estimated_sold_cogs_cents + audit.estimated_mortality_loss_cents
    controls.rows("exit.lifetime_cost_comparison", modeled.add(gap).eq(reference.production_cost_cents))
    controls.rows("exit.undated_vet_base", audit.undated_vet_base_cents.eq(UNDATED_VET_BASE_CENTS))
    controls.rows("exit.yardage_proxy_comparison", audit.booked_less_modeled_yardage_cents.eq(0))
    for outcome, column in ((FINISHED, "estimated_sold_cogs_cents"),
                            (MORTALITY, "estimated_mortality_loss_cents")):
        releases = audit.loc[audit.exit_type.eq(outcome)]
        for name, dates in (
            ("monthly_yard", releases.exit_month_end), ("annual_yard", releases.exit_date.dt.year),
        ):
            period = "month_end" if name == "monthly_yard" else "year"
            reported = tables[name].set_index(period)[column]
            controls.rows(f"{name}.{column}", reported.eq(releases.groupby(dates)[column].sum()
                                                         .reindex(reported.index, fill_value=0)))
    controls.require_pass()
    return controls.results


def _inventory_tables(animals, treatments, delivery, scales, quotes, *, max_weight_age_days):
    require_key(animals, ("animal_id",), "cattle ownership")
    if not (animals.entry_date.le(animals.exit_date) & animals.exit_type.isin((FINISHED, MORTALITY))).all():
        raise ValueError("Cattle require dated entry and a dated sale or mortality outcome")
    months = pd.date_range(animals.entry_date.min(), _month_end(animals.exit_date.max()), freq="ME")
    ledger = _animal_months(animals, treatments, delivery, months)
    ledger = _availability(attach_market(ledger, scales, quotes, max_weight_age_days=max_weight_age_days))
    ledger["weight_eligible_head"] = ledger.liveweight_proxy_kg.notna().astype("int64")
    for value, count in zip(MARKET_AMOUNTS, MARKET_COUNTS[1:], strict=True):
        ledger[count] = ledger[value].notna().astype("int64")
    feed = delivery.assign(
        month_end=_month_end(delivery.feed_date), delivery_cost_cents=cents(delivery.delivered_feed_cost_cad),
    ).groupby(list(LOT_PEN_MONTH), as_index=False)[list(FEED_VALUES)].sum()
    tables = {
        "animal_month": ledger,
        "monthly_yard": _monthly_totals(ledger, months, ()),
        "monthly_lot": _monthly_totals(ledger, months, ("lot_id", "pen_id")),
        "monthly_recorded_pen": _monthly_totals(ledger, months, ("pen_id",)),
        "monthly_feed_delivery": feed,
        "lifetime_closeout_audit": _closeout_audit(animals, ledger),
        "market_quote_assumptions": quotes,
    }
    tables["annual_yard"] = _annual_totals(tables["monthly_yard"])
    return tables, _reconcile(animals, treatments, ledger, feed, tables)


def build_monthly_inventory(root: Path, *, quote_rows=(), max_weight_age_days=45) -> BuildResult:
    """Build the validated inventory export without changing the canonical Phase 2A tables."""
    quotes = market_quotes(quote_rows)
    baseline, delivery = load_analysis(root)
    treatments = pd.read_excel(root / BOOK, sheet_name="Fact_Health_Treatments",
                               dtype=TEXT_DTYPES, engine="openpyxl", **NA_OPTIONS)
    if sha256(root / BOOK) != SOURCE_HASHES[BOOK]:
        raise ValueError("Workbook changed while reading dated treatments")
    tables, checks = _inventory_tables(
        baseline.tables["animal_closeout"], typed_dates(treatments), delivery,
        baseline.tables["animal_scale_stage"], quotes, max_weight_age_days=max_weight_age_days,
    )
    contracts = {
        "animal_month": (ANIMAL_MONTH, "Each animal with at least one inclusive production day in the month"),
        "monthly_yard": (("month_end",), "One row per dataset calendar month"),
        "monthly_lot": (("month_end", "lot_id"), "Calendar month by lot with its recorded pen"),
        "monthly_recorded_pen": (("month_end", "pen_id"), "Calendar month by pen represented in the cohort"),
        "annual_yard": (("year",), "First opening, summed flows and final modeled month-end by calendar year"),
        "monthly_feed_delivery": (LOT_PEN_MONTH, "Lot–pen–month with observed deliveries"),
        "lifetime_closeout_audit": (("animal_id",), "Retrospective booked costs and modeled release by exit animal"),
        "market_quote_assumptions": (("quote_id",), "User-supplied as-of live price assumption and provenance"),
    }
    for name, (key, _) in contracts.items():
        require_key(tables[name], key, name)
    manifest = {
        "schema_version": "2b.4.5",
        "tables": {name: {"key": key, "grain": grain, **schema(tables[name])}
                   for name, (key, grain) in contracts.items()},
        "money_unit": "nominal CAD cents",
        "cutoff": "Calendar month-end EOD. Entry inclusive, exit exclusive for stock; both inclusive for production.",
        "assumptions": {
            "feed": "Equal share per active head on each recorded lot–pen delivery date with stable cent rounding",
            "yardage_cents_per_inclusive_head_day": YARDAGE_CENTS_PER_DAY,
            "undated_vet_base_cents_per_placement_excluded": UNDATED_VET_BASE_CENTS,
            "max_weight_age_days": max_weight_age_days,
            "market": "No default quotes. User assumptions require observation and publication by month-end.",
        },
        "limitations": [
            "Simulated records. No physical pen transfers, warehouse ledger, or independently posted actual WIP or COGS.",
            "The source basis includes purchase and dated direct treatments. The estimate adds delivery shares and yardage.",
            "Actual values are null when eligible head exist. Market totals require prices for all closing head.",
        ],
    }
    summary = {
        "baseline_checks_passed": baseline.reconciliation["summary"]["checks_passed"],
        "weather_dates_verified": baseline.reconciliation["summary"]["weather"]["date_count"],
        "checks_passed": len(checks),
        "checks_failed": 0,
        "table_rows": {name: len(frame) for name, frame in tables.items()},
    }
    return BuildResult(tables, baseline.source_manifest, manifest, {"summary": summary, "controls": checks})
