"""Build the validated Phase 2A analytical tables and their audit reports."""

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .contracts import FINISHED, MORTALITY, SCHEMA_VERSION
from .loaders import load_sources, schema
from .metrics import aggregate_closeout, aggregate_pen_feed, kpi_catalog
from .relations import require_key
from .transformations import (
    animal_closeout, animal_health_summary, animal_scale_stage, lot_closeout,
    lot_feed_reconciliation, pen_day_feed,
)
from .validation import Controls, validate_sources
from .weather import empty_weather, exposure_windows, load_snapshot, reference_metadata


@dataclass(frozen=True)
class TableContract:
    key: tuple[str, ...]
    grain: str
    lineage: str
    eligibility: str
    controls: str
    limitations: str


TABLES = {
    "animal_closeout": TableContract(
        ("animal_id",), "One closed placement per animal",
        "Fact_Closeout_Sales + Dim_Cattle (individual breed, sex, frame, RFID) + Dim_Lot + Dim_Pen",
        "Ledger includes all outcomes. Sold growth and carcass metrics exclude mortality placeholders.",
        "Animal key, dimension path, exact-cent ledger, source parity and snapshot counts.",
        "Modeled costs only. Date roles are separate. Lot predominant breed is contextual metadata.",
    ),
    "animal_health_summary": TableContract(
        ("animal_id",), "One lifetime health summary per placed animal",
        "Fact_Health_Treatments rolled up and joined to animal_closeout",
        "Treated requires one or more events. First pull uses treatment date then treatment ID.",
        "Animal coverage, event counts and direct cost plus CAD 18 base to closeout veterinary cost.",
        "Untreated has zero recorded visits and null first-event details. Lifetime fields are retrospective.",
    ),
    "animal_scale_stage": TableContract(
        ("animal_id", "weigh_stage"), "One recorded weigh stage per animal",
        "Fact_Scale_Weights + animal_closeout entry attributes",
        "Period ADG uses a previous positive elapsed interval. Arrival intervals are missing.",
        "Stage and weigh keys, event dates and weights, source period and inclusive cumulative ADG.",
        "Later stages favor surviving cattle. Recorded inclusive cumulative ADG and elapsed ADG differ.",
    ),
    "lot_closeout": TableContract(
        ("lot_id",), "One completed procurement lot",
        "Dim_Lot + Dim_Pen + animal_closeout and health rollups",
        "All matched animal records, with sold and metric-specific eligible counts separately.",
        "Placed = sold + mortality by lot, financial bridge and date-role checks.",
        "Use additive components for rollups. Lot attributes describe procurement cohorts.",
    ),
    "lot_feed_reconciliation": TableContract(
        ("lot_id",), "One matched feed-delivery and allocation bridge per lot",
        "Fact_Feed_Daily and Fact_Closeout_Sales independently rolled up before the join",
        "All recorded delivery days and all animal allocations in each closed lot.",
        "DM and CAD residuals within 0.005 per placed head and equal head-days.",
        "Observed rounding bounds describe reconciliation. Allocation algorithm is unavailable.",
    ),
    "pen_day_feed": TableContract(
        ("pen_id", "feed_date"), "One observed pen delivery day",
        "Fact_Feed_Daily rolled up by pen/date + Dim_Pen",
        "Recorded delivery rows supply delivered DM, cost and head-days.",
        "Capacity, delivery grain, feed components, occupancy and delivery-to-ledger head-days.",
        "Days without deliveries are absent. Capacity repeats across dates. Delivered amounts are not individual intake.",
    ),
    "weather_daily": TableContract(
        ("date",), "One calendar date for the representative reference point",
        "Versioned Open-Meteo Historical Weather API response with explicit ERA5 model",
        "Requested local date range. Source-variable coverage tracked separately.",
        "Source URL, raw and clean checksums, units, ordered unique dates and physical bounds.",
        "Representative reanalysis, fixed provider UTC offset. Empty when the source is unavailable.",
    ),
    "kpi_catalog": TableContract(
        ("metric_id", "version"), "One implemented definition per metric and version",
        "Shared metric definitions used by Pandas aggregation functions",
        "Metric-level populations, additive components and denominator rules.",
        "Unique metric/version and calculation tests against independent controls.",
        "Fractions are stored unscaled. Individual-ratio means use recorded precision.",
    ),
    "audit_exceptions": TableContract(
        ("rule", "source_table", "source_key"), "One known limitation or qualified variance per rule and key",
        "Source contracts, lot_feed_reconciliation and weather provenance",
        "Validated builds record known qualifications. Failed hard controls stop the build.",
        "Unique source-scoped rule key and recorded observed/expected context.",
        "One issue can affect several outputs. A qualification is separate from a failed control.",
    ),
    "animal_weather_exposure": TableContract(
        ("animal_id",), "One inclusive entry-to-exit exposure window per animal",
        "animal_closeout date/pen attributes + weather_daily",
        "All closed animals. Each weather measure requires complete coverage of its variable.",
        "One row per animal, inclusive days equal financial DOF, coverage checked.",
        "Retrospective descriptive exposure for a town reference. No financial or biological fields.",
    ),
    "lot_weather_exposure": TableContract(
        ("lot_id",), "One inclusive first-to-last feed-day exposure window per lot",
        "lot_feed_reconciliation feed dates + Dim_Pen + weather_daily",
        "All recorded lot feeding windows. Each weather variable needs full-window coverage.",
        "One row per lot, inclusive days equal validated lot feed days and end at final exit.",
        "Calendar days, with no weighting by dynamic lot size. Shelter labels are proxies.",
    ),
}


@dataclass
class BuildResult:
    tables: dict[str, pd.DataFrame]
    source_manifest: dict
    transformation_manifest: dict
    reconciliation: dict


def exceptions_table(animals, feed_bridge, weather_manifest):
    records = []

    def record(rule, source_table, source_key, severity, status, observed, interpretation):
        records.append({
            "rule": rule, "source_table": source_table, "source_key": source_key,
            "severity": severity, "status": status, "observed": observed, "interpretation": interpretation,
        })

    for row in feed_bridge.itertuples(index=False):
        for rule, gap, unit in (
            ("feed_dm_rounding", row.dm_delivered_less_allocated_kg, "kg DM"),
            ("feed_cost_rounding", row.cost_delivered_less_allocated_cad, "CAD"),
        ):
            if gap:
                record(rule, "lot_feed_reconciliation", row.lot_id, "low", "qualified",
                       f"{gap:+.2f} {unit}", f"Delivered minus allocated; bound ±{row.rounding_bound_per_metric:.3f}.")
    record("flat_untreated_encoding", "CSV / Feedlot_Flat_15000", "all", "low", "verified",
           "CSV literal None versus blank Excel cells in primary diagnosis and protocol.",
           "Equivalent for untreated animals in the parity check; native values retained.")
    mixed = int(animals.breed.ne(animals.predominant_breed).sum())
    record("individual_breed_scope", "Dim_Cattle / Dim_Lot", "all", "high", "verified",
           f"{mixed} animal breeds differ from their lot label.", "Group individual results by Dim_Cattle.breed.")
    record("simulator_provenance", "source bundle", "all", "high", "open",
           "Simulator code, seed, and independent farm records are absent.",
           "Seasonal rules, allocation method, independent occupancy and intervention effects are unverified.")
    if weather_manifest["status"] != "verified":
        record("weather_source_unavailable", "weather_daily", "reference", "medium", weather_manifest["status"],
               weather_manifest["detail"], "Exposure values are unavailable; dates and expected days are retained.")
    for name, missing in weather_manifest.get("missing_by_variable", {}).items():
        if missing:
            record("weather_null_values", "weather_daily", name, "medium", "qualified",
                   f"{missing} dates with null observations", "Unfilled; dependent windows require complete coverage.")
    return pd.DataFrame(records).astype("string")


def _weather_input(root, snapshot):
    if snapshot is not None:
        return load_snapshot(snapshot)
    attempt_file = root / "phase2a/weather_attempt.json"
    if not attempt_file.is_file():
        attempt = {"status": "not_loaded", "detail": "No verified snapshot supplied to the build."}
    else:
        attempt = json.loads(attempt_file.read_text(encoding="utf-8"))
        if attempt.get("request_url") != reference_metadata()["request_url"] or attempt.get("status") != "blocked":
            raise ValueError("Archived weather attempt must describe the blocked reference request")
    return empty_weather(), {
        **reference_metadata(), **attempt, "date_count": 0, "extracted_at_utc": None,
        "grid_latitude": None, "grid_longitude": None, "elevation_m": None, "missing_by_variable": {},
    }


def _check_tables(tables, controls):
    for name, table in tables.items():
        require_key(table, TABLES[name].key, name)
        controls.equal(f"canonical.{name}.key_violations", 0, 0)
    animals = tables["animal_closeout"]
    health = tables["animal_health_summary"]
    lots = tables["lot_closeout"]
    bridge = tables["lot_feed_reconciliation"]
    controls.equal("canonical.health_rows", len(health), len(animals))
    controls.rows("canonical.lot_headcount", lots.head_placed.eq(lots.head_sold + lots.head_mortality)
                  & lots.head_placed.eq(lots.head_count_in))
    controls.rows("canonical.lot_margin", lots.all_outcome_margin_cents.eq(
        lots.sold_only_margin_cents - lots.mortality_loss_cents
    ))
    controls.rows("canonical.feed_bridge", bridge.within_rounding_bound
                  & bridge.recorded_head_days.eq(bridge.financial_head_days))
    animal_days = animals.set_index("animal_id").financial_dof
    exposure = tables["animal_weather_exposure"]
    controls.rows("canonical.animal_exposure_days",
                  exposure.expected_exposure_days.eq(exposure.animal_id.map(animal_days)))
    feeding_days = bridge.set_index("lot_id").feed_days
    exposure = tables["lot_weather_exposure"]
    controls.rows("canonical.lot_exposure_days",
                  exposure.expected_exposure_days.eq(exposure.lot_id.map(feeding_days)))
    for name in ("animal_weather_exposure", "lot_weather_exposure"):
        exposure = tables[name]
        controls.rows(f"canonical.{name}.date_coverage",
                      exposure.weather_date_count.eq(exposure.expected_exposure_days)
                      if len(tables["weather_daily"]) else exposure.weather_date_count.eq(0))
    controls.require_pass()


def _reconcile(tables, controls, weather_manifest):
    animals = tables["animal_closeout"]
    health = tables["animal_health_summary"]
    lots = tables["lot_closeout"]
    summary = aggregate_closeout(animals, health).iloc[0]
    ledger_columns = (
        "purchase_cost_cents", "allocated_feed_cost_cents", "yardage_cost_cents", "vet_cost_cents",
        "production_cost_cents", "gross_revenue_cents", "all_outcome_margin_cents",
    )
    ledger = aggregate_closeout(animals, health, by=("exit_type",)).set_index("exit_type")
    bridges = {
        outcome: {name.removesuffix("_cents") + "_cad": int(values[name]) / 100
                  for name in ledger_columns}
        for outcome, values in (("all_outcomes", summary), ("sold", ledger.loc[FINISHED]),
                                ("mortality", ledger.loc[MORTALITY]))
    }
    pen_feed = aggregate_pen_feed(tables["pen_day_feed"]).iloc[0]
    bridge = tables["lot_feed_reconciliation"]
    control_counts = (
        "head_placed", "head_sold", "head_mortality", "head_treated", "treatment_events", "financial_head_days",
    )
    metric_ids = (
        "all_outcome_margin_per_head_placed", "all_outcome_margin_per_head_sold", "sold_only_margin_per_head_sold",
        "sold_adg_kg_per_day", "mean_individual_sold_adg", "sold_fcr", "mean_individual_sold_fcr",
        "sold_feed_cog", "mean_individual_sold_feed_cog", "dressing_yield", "mean_individual_dressing",
        "recorded_morbidity_rate", "first_pull_by_day30_share", "prime_aaa_share",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "checks_passed": sum(check["passed"] for check in controls.results),
        "checks_failed": sum(not check["passed"] for check in controls.results),
        "table_rows": {name: len(frame) for name, frame in tables.items()},
        "population": {
            **{key: int(summary[key]) for key in control_counts},
            "lots": len(lots), "pens": int(animals.pen_id.nunique()),
            "lots_with_multiple_breeds": int(lots.breed_count.gt(1).sum()),
            "animals_different_from_lot_breed": int(animals.breed.ne(animals.predominant_breed).sum()),
            "head_graded": int(summary.head_graded), "head_ungraded_sold": int(summary.head_ungraded_sold),
        },
        "modeled_ledger_cad": bridges,
        "mortality_loss_cad": round(float(summary.mortality_loss_cad), 2),
        "kpis": {key: round(float(summary[key]), 8) for key in metric_ids},
        "feed_bridge": {
            "delivered_dm_kg": round(float(pen_feed.delivered_dm_kg), 2),
            "allocated_dm_kg": round(float(summary.allocated_dm_kg), 2),
            "dm_delivered_less_allocated_kg": round(float(bridge.dm_delivered_less_allocated_kg.sum()), 2),
            "delivered_feed_cost_cad": round(float(pen_feed.delivered_feed_cost_cad), 2),
            "allocated_feed_cost_cad": int(summary.allocated_feed_cost_cents) / 100,
            "cost_delivered_less_allocated_cad": round(float(bridge.cost_delivered_less_allocated_cad.sum()), 2),
            "recorded_head_days": int(pen_feed.recorded_head_days),
            "lots_within_rounding_bound": int(bridge.within_rounding_bound.sum()),
        },
        "weather": {name: weather_manifest[name] for name in ("status", "requested_date_count", "date_count")},
    }


def build(root: Path, *, weather_snapshot: Path | None = None) -> BuildResult:
    sources = load_sources(root)
    controls = Controls()
    frames = validate_sources(sources, controls)
    weather, provenance = _weather_input(root, weather_snapshot)
    cattle, lots, pens = (frames[f"Dim_{dimension}"] for dimension in ("Cattle", "Lot", "Pen"))
    feed = frames["Fact_Feed_Daily"]
    animals = animal_closeout(cattle, frames["Fact_Closeout_Sales"], lots, pens)
    health = animal_health_summary(animals, frames["Fact_Health_Treatments"])
    bridge = lot_feed_reconciliation(animals, feed)
    closeouts = lot_closeout(animals, health, lots, pens)
    tables = {
        "animal_closeout": animals,
        "animal_health_summary": health,
        "animal_scale_stage": animal_scale_stage(animals, frames["Fact_Scale_Weights"]),
        "lot_closeout": closeouts,
        "lot_feed_reconciliation": bridge,
        "pen_day_feed": pen_day_feed(feed, pens),
        "weather_daily": weather,
        "kpi_catalog": kpi_catalog(),
        "audit_exceptions": exceptions_table(animals, bridge, provenance),
        "animal_weather_exposure": exposure_windows(
            animals, weather, id_col="animal_id", start_col="entry_date", end_col="exit_date",
        ),
        "lot_weather_exposure": exposure_windows(
            bridge.merge(pens[["pen_id", "pen_type"]], on="pen_id", validate="many_to_one"), weather,
            id_col="lot_id", start_col="first_feed_date", end_col="last_feed_date",
        ),
    }
    _check_tables(tables, controls)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "tables": {
            name: {**vars(TABLES[name]), **schema(frame)} for name, frame in tables.items()
        },
        "weather": provenance,
    }
    source_manifest = {**sources.manifest, "weather": provenance}
    return BuildResult(
        tables, source_manifest, manifest,
        {"summary": _reconcile(tables, controls, provenance), "controls": controls.results},
    )
