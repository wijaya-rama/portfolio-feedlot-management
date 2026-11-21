"""Read-only Phase 1 source reconciliation. Prints aggregate JSON to stdout."""

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

CSV = "data/Feedlot_Management_Flat_15000.csv"
BOOK = "data/Feedlot_Management_StarSchema.xlsx"
HTML = "index.html"


def mismatch(actual, expected, tolerance=0):
    """Count mismatches, with two missing values treated as equal."""
    if pd.api.types.is_numeric_dtype(actual) and pd.api.types.is_numeric_dtype(expected):
        return int((~np.isclose(actual, expected, atol=tolerance, rtol=0, equal_nan=True)).sum())
    equal = actual.eq(expected).fillna(False) | (actual.isna() & expected.isna())
    return int((~equal).sum())


def residual(actual, expected, tolerance):
    delta = actual - expected
    return {
        "tolerance": tolerance,
        "over_tolerance": mismatch(actual, expected, tolerance),
        "max_abs": round(float(delta.abs().max()), 8),
        "signed_total": round(float(delta.sum()), 8),
    }


def date_profile(frame):
    result = {}
    for col in frame.columns:
        if col.endswith("_date"):
            parsed = pd.to_datetime(frame[col], format="%Y-%m-%d", errors="coerce")
            result[col] = {
                "invalid_nonblank": int((parsed.isna() & frame[col].notna()).sum()),
                "first": str(parsed.min().date()),
                "last": str(parsed.max().date()),
            }
    return result


def profile(frame):
    return {
        "rows": len(frame),
        "columns": {col: {"type": str(frame[col].dtype), "missing": int(frame[col].isna().sum())}
                    for col in frame.columns},
        "duplicate_rows": int(frame.duplicated().sum()),
        "distinct_ids": {col: int(frame[col].nunique()) for col in ("animal_id", "lot_id", "pen_id")
                         if col in frame},
        "dates": date_profile(frame),
    }


def key_check(frame, cols):
    return {
        "missing": int(frame[cols].isna().any(axis=1).sum()),
        "duplicate_excess": int(frame.duplicated(cols).sum()),
    }


def mapping_errors(frame, source, key, fields):
    return {
        field: mismatch(frame[field], frame[key].map(source[reference]), 1e-8)
        for field, reference in fields.items()
    }


def group_sums(frame, group, fields):
    return frame.groupby(group, observed=True)[fields].sum()


def date(values):
    return pd.to_datetime(values, format="%Y-%m-%d")


def inventory_checks(flat, tables):
    sources = {"CSV": flat, **tables}
    keys = {
        "CSV": ["animal_id"], "Feedlot_Flat_15000": ["animal_id"],
        "Dim_Pen": ["pen_id"], "Dim_Lot": ["lot_id"], "Dim_Cattle": ["animal_id"],
        "Fact_Closeout_Sales": ["animal_id"], "Fact_Feed_Daily": ["lot_id", "pen_id", "feed_date"],
        "Fact_Health_Treatments": ["treatment_id"], "Fact_Scale_Weights": ["weigh_id"],
    }
    pen = tables["Dim_Pen"].set_index("pen_id")
    lot = tables["Dim_Lot"].set_index("lot_id")
    cattle = tables["Dim_Cattle"].set_index("animal_id")
    parents = {"animal_id": cattle, "pen_id": pen, "lot_id": lot}
    fk = {
        name: {col: int((~frame[col].isin(parent.index)).sum())
               for col, parent in parents.items() if col in frame and name != {"animal_id": "Dim_Cattle", "lot_id": "Dim_Lot", "pen_id": "Dim_Pen"}[col]}
        for name, frame in sources.items() if name in keys
    }
    paths = {
        name: {
            **mapping_errors(frame, lot, "lot_id", {"pen_id": "pen_id"}),
            **{f"cattle_{col}": err for col, err in
               mapping_errors(frame, cattle, "animal_id", {"lot_id": "lot_id", "pen_id": "pen_id"}).items()}
        }
        for name, frame in sources.items() if name in keys if {"lot_id", "animal_id"} <= set(frame)
    }
    paths["Fact_Feed_Daily"] = mapping_errors(tables["Fact_Feed_Daily"], lot, "lot_id", {"pen_id": "pen_id"})
    master = tables["Feedlot_Flat_15000"].set_index("animal_id").reindex(flat.animal_id)
    close = tables["Fact_Closeout_Sales"].set_index("animal_id")
    flat_by_id = flat.set_index("animal_id")
    shared = flat.columns.intersection(master.columns)
    dict_rows = tables["Data_Dictionary"]
    return {
        "profiles": {name: profile(frame) for name, frame in sources.items()},
        "primary_keys": {name: key_check(sources[name], cols) for name, cols in keys.items()},
        "scale_animal_stage_key": key_check(tables["Fact_Scale_Weights"], ["animal_id", "weigh_stage"]),
        "rfid_key": key_check(tables["Dim_Cattle"], ["rfid_tag"]),
        "rfid_non_15_digit": int((~tables["Dim_Cattle"].rfid_tag.str.fullmatch(r"\d{15}", na=False)).sum()),
        "foreign_key_orphans": fk,
        "relationship_mismatches": paths,
        "csv_excel_flat": {
            "same_columns_and_order": list(flat) == list(tables["Feedlot_Flat_15000"]),
            "same_animal_id_order": flat.animal_id.equals(tables["Feedlot_Flat_15000"].animal_id),
            "mismatch_by_column": {col: mismatch(flat_by_id[col], master[col], 1e-8) for col in shared},
        },
        "csv_closeout_shared_columns": {
            col: mismatch(flat_by_id[col], close[col].reindex(flat_by_id.index), 1e-8)
            for col in flat_by_id.columns.intersection(close.columns)
        },
        "csv_dimension_attributes": {
            name: mapping_errors(flat, parent, key, {col: col for col in flat.columns.intersection(parent.columns)})
            for name, parent, key in (("cattle", cattle, "animal_id"), ("lot", lot, "lot_id"), ("pen", pen, "pen_id"))
        },
        "dictionary_coverage": {
            name: len(set(frame.columns) & set(dict_rows.loc[dict_rows.Table.eq(name), "Column Name"]))
            for name, frame in tables.items() if name.startswith(("Dim_", "Fact_"))
        },
    }


def closeout_checks(flat, lot, cattle):
    sold = flat.loc[flat.exit_type.eq("Finished Sale")]
    dead = flat.loc[flat.exit_type.eq("Mortality")]
    dof = (date(flat.exit_date) - date(flat.entry_date)).dt.days + 1
    costs = ["purchase_cost_cad", "allocated_feed_cost_cad", "yardage_cost_cad", "vet_cost_cad"]
    cost = flat[costs].sum(axis=1)
    totals = [*costs, "gross_revenue_cad", "net_margin_cad", "total_production_cost_cad"]
    fields = ["financial_dof", "entry_weight_kg", "exit_weight_kg", "total_gain_kg",
              "lifetime_adg_kg", "allocated_dmi_kg", "fcr", "total_cost_of_gain_per_kg",
              "feed_cost_of_gain_per_kg", "hot_carcass_weight_kg", "dressing_pct"]
    lot_index = lot.set_index("lot_id")
    end = flat.groupby("lot_id").exit_date.max()
    workbook_cattle = cattle.set_index("animal_id")
    return {
        "exit_counts": flat.exit_type.value_counts().to_dict(),
        "status_vs_exit": mismatch(flat.status, flat.exit_type.replace({"Finished Sale": "Sold"})),
        "no_closeout_in_cattle": int((~cattle.animal_id.isin(flat.animal_id)).sum()),
        "counts_vs_lot_head_in": mismatch(flat.groupby("lot_id").size().reindex(lot_index.index), lot_index.head_count_in),
        "animal_entries_vs_lot_arrival": mismatch(flat.entry_date, flat.arrival_date),
        "lot_exit_date_count_distribution": flat.groupby("lot_id").exit_date.nunique().value_counts().to_dict(),
        "lots_with_split_sold_dates": int(sold.groupby("lot_id").exit_date.nunique().gt(1).sum()),
        "recorded_breed_vs_lot_breed": int(flat.breed.ne(flat.predominant_breed).sum()),
        "recorded_sex_vs_lot_sex": int(flat.sex.ne(flat.lot_sex).sum()),
        "nonpositive_dof_or_entry_weight": int((dof.le(0) | flat.entry_weight_kg.le(0)).sum()),
        "lot_calendar_days": (date(end) - date(lot_index.arrival_date)).dt.days.add(1).agg(["min", "max"]).to_dict(),
        "dof": mismatch(flat.financial_dof, dof),
        "sold_nonpositive": {f: int(sold[f].le(0).sum()) for f in fields},
        "dead_nonzero_closeout_placeholders": {
            f: int(dead[f].ne(0).sum())
            for f in ("exit_weight_kg", "total_gain_kg", "lifetime_adg_kg", "fcr",
                      "total_cost_of_gain_per_kg", "feed_cost_of_gain_per_kg",
                      "hot_carcass_weight_kg", "dressing_pct", "grid_price_per_kg_carcass",
                      "gross_revenue_cad")
        },
        "purchase": residual(flat.purchase_cost_cad, flat.entry_weight_kg * flat.feeder_purchase_price_per_kg, .005001),
        "yardage": residual(flat.yardage_cost_cad, flat.financial_dof * .60, .005001),
        "production_cost": residual(flat.total_production_cost_cad, cost, .005001),
        "margin": residual(flat.net_margin_cad, flat.gross_revenue_cad - cost, .005001),
        "negative_cost_rows": {f: int(flat[f].lt(0).sum()) for f in costs},
        "gain": residual(sold.total_gain_kg, sold.exit_weight_kg - sold.entry_weight_kg, 1e-6),
        "adg": residual(sold.lifetime_adg_kg, sold.total_gain_kg / sold.financial_dof, .000501),
        "fcr": residual(sold.fcr, sold.allocated_dmi_kg / sold.total_gain_kg, .000501),
        "feed_cog": residual(sold.feed_cost_of_gain_per_kg, sold.allocated_feed_cost_cad / sold.total_gain_kg, .005001),
        "nonpurchase_cog": residual(sold.total_cost_of_gain_per_kg,
                                    sold[costs[1:]].sum(axis=1) / sold.total_gain_kg, .005001),
        "hcw": residual(sold.hot_carcass_weight_kg, sold.exit_weight_kg * sold.dressing_pct, .050001),
        "revenue": residual(sold.gross_revenue_cad,
                            sold.hot_carcass_weight_kg * sold.grid_price_per_kg_carcass, .005001),
        "invalid_sold_dressing_fraction": int((sold.dressing_pct.le(0) | sold.dressing_pct.gt(1)).sum()),
        "sold_entry_weight_not_below_exit": int(sold.entry_weight_kg.ge(sold.exit_weight_kg).sum()),
        "nonpositive_sold_grid_price_or_revenue": int((sold.grid_price_per_kg_carcass.le(0) | sold.gross_revenue_cad.le(0)).sum()),
        "sold_missing_grade": int(sold.quality_grade.isna().sum()),
        "dead_nonmissing_grade": int(dead.quality_grade.notna().sum()),
        "grade_counts": sold.quality_grade.value_counts().to_dict(),
        "sold_metric_ranges": sold[fields].agg(["min", "mean", "max"]).round(6).to_dict(),
        "sold_margin": sold[totals].sum().round(2).to_dict(),
        "dead_margin": dead[totals].sum().round(2).to_dict(),
        "all_margin": flat[totals].sum().round(2).to_dict(),
        "margin_per_placed": round(flat.net_margin_cad.sum() / len(flat), 6),
        "margin_per_sold_all_costs": round(flat.net_margin_cad.sum() / len(sold), 6),
        "margin_per_sold_sold_costs": round(sold.net_margin_cad.mean(), 6),
        "breeds": sold.groupby("breed").agg(head=("animal_id", "size"), margin=("net_margin_cad", "mean"),
            carcass=("hot_carcass_weight_kg", "mean"), dress=("dressing_pct", "mean"),
            high_grade=("quality_grade", lambda g: g.isin(["Canada Prime", "Canada AAA"]).mean())).round(5).to_dict("index"),
        "frames": sold.groupby("frame_score").agg(head=("animal_id", "size"), margin=("net_margin_cad", "mean"),
            carcass=("hot_carcass_weight_kg", "mean"), adg=("lifetime_adg_kg", "mean")).round(5).to_dict("index"),
        "sold_ratio_of_totals": {
            "adg": sold.total_gain_kg.sum() / sold.financial_dof.sum(),
            "fcr": sold.allocated_dmi_kg.sum() / sold.total_gain_kg.sum(),
            "feed_cog": sold.allocated_feed_cost_cad.sum() / sold.total_gain_kg.sum(),
            "nonpurchase_cog": sold[costs[1:]].sum().sum() / sold.total_gain_kg.sum(),
            "dressing": sold.hot_carcass_weight_kg.sum() / sold.exit_weight_kg.sum(),
        },
        "all_feed_per_sold_gain": flat.allocated_dmi_kg.sum() / sold.total_gain_kg.sum(),
        "cattle_status_vs_closeout": mismatch(flat.exit_type.replace({"Finished Sale": "Sold"}), flat.animal_id.map(workbook_cattle.status)),
    }


def feed_checks(flat, feed, lot, pens):
    by_lot = flat.groupby("lot_id")
    lot_index = lot.set_index("lot_id")
    arrivals = feed.lot_id.map(lot_index.arrival_date)
    days = (date(feed.feed_date) - date(arrivals)).dt.days + 1
    thresholds = [days.le(14), days.le(28), days.le(70)]
    phases = pd.Series(np.select(thresholds, ["Starter", "Transition", "Grower"], default="Finisher"),
                       index=feed.index)
    feed_range = feed.groupby("lot_id").feed_date.agg(["min", "max", "size"])
    span = (date(feed_range["max"]) - date(feed_range["min"])).dt.days + 1
    feed_actual = group_sums(feed, "lot_id", ["total_dmi_kg", "total_feed_cost_cad"])
    feed_alloc = by_lot[["allocated_dmi_kg", "allocated_feed_cost_cad"]].sum().reindex(feed_actual.index)
    capacity = pens.set_index("pen_id").capacity_head
    pen_day = feed.groupby(["pen_id", "feed_date"]).head_count_active.agg(["size", "sum"]).reset_index()
    position = flat.assign(exit_day=date(flat.exit_date))
    exit_order = {key: np.sort(g.exit_day.to_numpy()) for key, g in position.groupby("lot_id")}
    active = pd.Series(index=feed.index, dtype="int64")
    for key, group in feed.groupby("lot_id"):
        active.loc[group.index] = len(exit_order[key]) - np.searchsorted(
            exit_order[key], date(group.feed_date).to_numpy(), side="left")
    months = feed.assign(month=feed.feed_date.str[:7]).groupby("month")[
        ["total_dmi_kg", "total_feed_cost_cad", "head_count_active"]].sum()
    months["dmi_per_head_day"] = months.total_dmi_kg / months.head_count_active
    months["cost_per_head_day"] = months.total_feed_cost_cad / months.head_count_active
    feed_only = feed.lot_id.map(by_lot.exit_date.max())
    return {
        "feed_days": mismatch(feed.dof_current, days),
        "feed_phase": mismatch(feed.ration_phase, phases),
        "feed_gaps_within_lot": int((span - feed_range["size"]).sum()),
        "feed_start_vs_arrival": mismatch(feed_range["min"], lot_index.arrival_date.reindex(feed_range.index)),
        "feed_end_vs_lot_max_exit": mismatch(feed_range["max"], by_lot.exit_date.max().reindex(feed_range.index)),
        "feed_rows_after_last_lot_exit": int(feed.feed_date.gt(feed_only).sum()),
        "exits_after_last_feed_day": int(flat.exit_date.gt(flat.lot_id.map(feed_range["max"])).sum()),
        "feed_active_head_vs_entry_exit_ledger": residual(feed.head_count_active, active, 0),
        "lots_with_headcount_mismatch": int(feed.loc[feed.head_count_active.ne(active), "lot_id"].nunique()),
        "feed_rows_with_zero_implied_active": int(active.eq(0).sum()),
        "lots_placed_above_capacity": int(lot.head_count_in.gt(lot.pen_id.map(capacity)).sum()),
        "pen_days_with_multiple_lots": int(pen_day["size"].gt(1).sum()),
        "pen_days_above_capacity": int(pen_day["sum"].gt(pen_day.pen_id.map(capacity)).sum()),
        "feed_days_nonpositive_head": int(feed.head_count_active.le(0).sum()),
        "lots_without_feed_rows": int((~lot.lot_id.isin(feed.lot_id)).sum()),
        "feed_head_days": int(feed.head_count_active.sum()),
        "inclusive_financial_head_days": int(flat.financial_dof.sum()),
        "dm_outside_unit_interval": int((feed.dm_pct.le(0) | feed.dm_pct.gt(1)).sum()),
        "negative_feed_quantity_or_cost": int(feed.filter(regex=r"_kg$|_cad$").lt(0).any(axis=1).sum()),
        "dmi_from_asfed": residual(feed.total_dmi_kg, feed.total_as_fed_kg * feed.dm_pct, .005001),
        "dmi_components": residual(feed.total_dmi_kg, feed[["forage_dmi_kg", "concentrate_dmi_kg",
                                   "supplement_dmi_kg"]].sum(axis=1), .010001),
        "feed_cost_components": residual(feed.total_feed_cost_cad, feed[["forage_cost_cad", "concentrate_cost_cad",
                                   "supplement_cost_cad"]].sum(axis=1), .010001),
        "daily_totals": feed_actual.sum().round(2).to_dict(),
        "allocated_totals": feed_alloc.sum().round(2).to_dict(),
        "lot_dmi_allocation": residual(feed_alloc.allocated_dmi_kg, feed_actual.total_dmi_kg, .010001),
        "lot_cost_allocation": residual(feed_alloc.allocated_feed_cost_cad, feed_actual.total_feed_cost_cad, .010001),
        "lots_beyond_per_head_cent_rounding_bound": {
            "dmi": int((feed_alloc.allocated_dmi_kg.sub(feed_actual.total_dmi_kg).abs() > (by_lot.size() * .005 + 1e-6)).sum()),
            "cost": int((feed_alloc.allocated_feed_cost_cad.sub(feed_actual.total_feed_cost_cad).abs() > (by_lot.size() * .005 + 1e-6)).sum()),
        },
        "months": months.round(6).to_dict("index"),
    }


def event_checks(flat, health, scale):
    animal = flat.set_index("animal_id")
    h = health.join(animal[["entry_date", "exit_date", "exit_type"]], on="animal_id", validate="many_to_one")
    s = scale.join(animal[["entry_date", "exit_date", "exit_type", "entry_weight_kg", "exit_weight_kg",
                           "financial_dof", "lifetime_adg_kg"]], on="animal_id", validate="many_to_one")
    dof = (date(h.treatment_date) - date(h.entry_date)).dt.days + 1
    ordered_scale = s.sort_values(["animal_id", "weigh_date", "weigh_id"])
    prior_days = date(ordered_scale.weigh_date).groupby(ordered_scale.animal_id).diff().dt.days.fillna(0)
    prior_gain = ordered_scale.groupby("animal_id").weight_kg.diff()
    rate = (prior_gain / prior_days.where(prior_days.gt(0))).fillna(0)
    elapsed = (date(s.weigh_date) - date(s.entry_date)).dt.days
    gain = s.weight_kg - s.entry_weight_kg
    elapsed_adg = (gain / elapsed.where(elapsed.gt(0))).fillna(0)
    inclusive_adg = gain / (elapsed + 1)
    first = h.sort_values(["treatment_date", "treatment_id"]).drop_duplicates("animal_id").set_index("animal_id")
    event_count = h.groupby("animal_id").size().reindex(animal.index, fill_value=0)
    direct = h.groupby("animal_id").vet_cost_cad.sum().reindex(animal.index, fill_value=0)
    chronic = h.outcome.str.contains("Chronic", na=False).groupby(h.animal_id).any().reindex(animal.index, fill_value=False)
    arrival = s.loc[s.weigh_stage.eq("Arrival")]
    close = s.loc[s.weigh_stage.eq("Closeout")]
    sold = animal.loc[animal.exit_type.eq("Finished Sale")]
    treated = sold.index.isin(first.index)
    base = animal.vet_cost_cad - direct
    return {
        "health": {
            "events": len(h), "treated_animals": len(first), "repeat_animals": int(event_count.gt(1).sum()),
            "event_count_distribution": event_count.value_counts().to_dict(),
            "event_diagnosis": h.diagnosis.value_counts().to_dict(),
            "first_diagnosis": first.diagnosis.value_counts().to_dict(),
            "outcomes": h.outcome.value_counts().to_dict(),
            "first_outcomes": first.outcome.value_counts().to_dict(),
            "diagnosis_outcomes": h.groupby(["diagnosis", "outcome"]).size().unstack(fill_value=0).to_dict("index"),
            "protocol_outcomes": h.groupby(["drug_protocol", "outcome"]).size().unstack(fill_value=0).to_dict("index"),
            "event_cost": float(h.vet_cost_cad.sum().round(2)),
            "events_through_day_30": int(dof.between(1, 30).sum()),
            "first_events_through_day_30": int(first.dof_at_treatment.between(1, 30).sum()),
            "brd_events_through_day_30": int((dof.between(1, 30) & h.diagnosis.str.startswith("BRD")).sum()),
            "outside_animal_dates": int((h.treatment_date.lt(h.entry_date) | h.treatment_date.gt(h.exit_date)).sum()),
            "dof_mismatch": mismatch(h.dof_at_treatment, dof),
            "nonpositive_treatment_cost": int(h.vet_cost_cad.le(0).sum()),
            "death_with_treatment": int((animal.exit_type.eq("Mortality") & event_count.gt(0)).sum()),
            "death_with_repeat_treatment": int((animal.exit_type.eq("Mortality") & event_count.gt(1)).sum()),
            "mortality_events_vs_closeout": int((h.outcome.eq("Mortality") & h.exit_type.ne("Mortality")).sum()),
            "flat_count_mismatch": mismatch(animal.treatment_count, event_count),
            "flat_morbidity_mismatch": mismatch(animal.morbidity_flag.eq("Treated"), event_count.gt(0)),
            "flat_diagnosis_vs_first": mismatch(animal.primary_diagnosis, first.diagnosis.reindex(animal.index)),
            "flat_protocol_vs_first": mismatch(animal.primary_drug_protocol, first.drug_protocol.reindex(animal.index)),
            "flat_direct_cost": residual(animal.total_vet_cost_cad.fillna(0), direct, .005001),
            "flat_chronic": mismatch(animal.has_chronic_outcome.eq("Yes"), chronic),
            "base_vet_cost": residual(base, pd.Series(18, index=base.index), .005001),
            "sold_cohorts": sold.assign(treated=treated).groupby("treated").agg(
                head=("exit_type", "size"), margin=("net_margin_cad", "mean"),
                entry=("entry_weight_kg", "mean"), exit=("exit_weight_kg", "mean")).round(6).to_dict("index"),
        },
        "scale": {
            "stage_counts": s.weigh_stage.value_counts().to_dict(),
            "elapsed_days_by_stage": elapsed.groupby(s.weigh_stage).agg(["min", "max"]).to_dict("index"),
            "outside_animal_dates": int((s.weigh_date.lt(s.entry_date) | s.weigh_date.gt(s.exit_date)).sum()),
            "nonpositive_weight": int(s.weight_kg.le(0).sum()),
            "negative_interval_gain": int(prior_gain.lt(0).sum()),
            "nonarrival_nonpositive_interval": int((prior_days.le(0) & ordered_scale.weigh_stage.ne("Arrival")).sum()),
            "arrival_entry_weight": mismatch(arrival.weight_kg, arrival.entry_weight_kg),
            "arrival_entry_date": mismatch(arrival.weigh_date, arrival.entry_date),
            "closeout_exit_weight": mismatch(close.weight_kg, close.exit_weight_kg),
            "closeout_exit_date": mismatch(close.weigh_date, close.exit_date),
            "closeout_mortality_rows": int(close.exit_type.eq("Mortality").sum()),
            "sold_missing_closeout_weigh": int((~sold.index.isin(close.animal_id)).sum()),
            "days_since_last": mismatch(ordered_scale.days_since_last_weigh, prior_days),
            "period_adg": residual(ordered_scale.period_adg_kg, rate, .003001),
            "cumulative_adg_elapsed": residual(s.cumulative_adg_kg, elapsed_adg, .003001),
            "cumulative_adg_inclusive": residual(s.cumulative_adg_kg, inclusive_adg, .003001),
            "cumulative_adg_close_vs_financial_adg": residual(close.cumulative_adg_kg, close.lifetime_adg_kg, .003001),
        },
        "join_fanout": {
            "closeout_join_scale_and_health_rows": int(
                (s.groupby("animal_id").size().reindex(animal.index, fill_value=1) * event_count.clip(lower=1)).sum()),
        },
    }


def dashboard_checks(flat, feed, health, embedded):
    legacy = pd.DataFrame(embedded["LOTS"]).set_index("id")
    sold = flat.loc[flat.exit_type.eq("Finished Sale")]
    dead = flat.loc[flat.exit_type.eq("Mortality")]
    all_lots = flat.groupby("lot_id")
    sold_lots = sold.groupby("lot_id")
    dead_lots = dead.groupby("lot_id")
    placed = all_lots.size()
    sold_counts = sold_lots.size()
    dead_counts = dead_lots.size().reindex(placed.index, fill_value=0)
    sold_margin = sold_lots.net_margin_cad.sum()
    all_margin = all_lots.net_margin_cad.sum()
    dead_margin = dead_lots.net_margin_cad.sum().reindex(placed.index, fill_value=0)
    implied = legacy.sold * legacy.margin
    fields = {
        "dof": "financial_dof", "adg": "lifetime_adg_kg", "fcr": "fcr", "entryW": "entry_weight_kg",
        "exitW": "exit_weight_kg", "gain": "total_gain_kg", "dmi": "allocated_dmi_kg",
        "cog": "total_cost_of_gain_per_kg", "fcog": "feed_cost_of_gain_per_kg", "pCost": "purchase_cost_cad",
        "fCost": "allocated_feed_cost_cad", "yCost": "yardage_cost_cad", "vCost": "vet_cost_cad",
        "gRev": "gross_revenue_cad", "dressing": "dressing_pct", "hotW": "hot_carcass_weight_kg",
    }
    precision = dict.fromkeys(fields, .005001)
    precision.update(dict.fromkeys(("dof", "entryW", "exitW", "gain", "dmi", "hotW"), .050001))
    precision.update(dict.fromkeys(("adg", "dressing"), .000501))
    quarter = date(all_lots.arrival_date.first()).dt.to_period("Q").astype(str)
    grades = pd.crosstab(sold.lot_id, sold.quality_grade)
    h = health.groupby("lot_id").animal_id.nunique()
    feed_months = feed.assign(month=feed.feed_date.str[:7]).groupby("month")[
        ["total_dmi_kg", "total_feed_cost_cad", "head_count_active"]].sum().reindex(embedded["MONTHS"])
    breed_idx = legacy.b.map(dict(enumerate(embedded["BREEDS"])))
    sold_per_breed = legacy.groupby(breed_idx).sold.sum()
    first_pull = health.sort_values(["treatment_date", "treatment_id"]).drop_duplicates("animal_id")
    diagnosis_fields = {"brd": "BRD - Bovine Respiratory", "footRot": "Foot Rot",
                        "bloat": "Bloat / Acidosis", "buller": "Buller / Injury"}
    diagnoses = {}
    for scope, rows in (("first", first_pull), ("all_events", health)):
        counts = pd.crosstab(rows.lot_id, rows.diagnosis).reindex(legacy.index, fill_value=0)
        diagnoses[scope] = {field: mismatch(legacy[field], counts[label]) for field, label in diagnosis_fields.items()}
    health_groups = health.groupby(["lot_id", "drug_protocol"])
    drug_coverage = {}
    drug_cost = {}
    for index, drug in enumerate(embedded["DRUGS"]):
        actual = pd.DataFrame(legacy.drugs.map(lambda values: values[index]).to_list(),
                              columns=["cases", "recovered", "deaths", "cost"], index=legacy.index)
        expected = health_groups.agg(cases=("animal_id", "size"),
                                     recovered=("outcome", lambda outcomes: outcomes.eq("Recovered").sum()),
                                     deaths=("outcome", lambda outcomes: outcomes.eq("Mortality").sum()),
                                     cost=("vet_cost_cad", "sum")).xs(drug, level="drug_protocol")
        expected = expected.reindex(legacy.index, fill_value=0)
        drug_coverage[drug] = {field: mismatch(actual[field], expected[field]) for field in ("cases", "recovered", "deaths")}
        drug_cost[drug] = residual(actual.cost, expected.cost, .050001)
    legacy_breed = legacy.assign(breed=breed_idx, margin_total=implied, hcw_total=legacy.hotW * legacy.sold)
    breed_stats = legacy_breed.groupby("breed")[["sold", "margin_total", "hcw_total", "prime", "aaa"]].sum()
    breed_stats["sold_margin"] = breed_stats.margin_total / breed_stats.sold
    breed_stats["mean_hcw"] = breed_stats.hcw_total / breed_stats.sold
    breed_stats["prime_aaa_share"] = (breed_stats.prime + breed_stats.aaa) / breed_stats.sold
    actual_shelter = sold.groupby("pen_type").agg(head=("animal_id", "size"),
                      margin=("net_margin_cad", "mean"), fcr=("fcr", "mean"))
    export = {
        "lots": len(legacy),
        "lot_ids_missing_extra": [sorted(set(placed.index) - set(legacy.index)), sorted(set(legacy.index) - set(placed.index))],
        "dimensions": {
            field: mismatch(legacy[field].map(dict(enumerate(embedded[labels]))), all_lots[col].first().reindex(legacy.index))
            for field, labels, col in (("b", "BREEDS", "predominant_breed"), ("z", "ZONES", "site_zone"),
                                       ("s", "SEXES", "lot_sex"), ("pt", "PEN_TYPES", "pen_type"),
                                       ("reg", "REGIONS", "origin_region"))
        },
        "placement_quarter_mismatch": mismatch(legacy.q.map(dict(enumerate(embedded["QUARTERS"]))), quarter.reindex(legacy.index)),
        "pen_mismatch": mismatch(legacy.pen, all_lots.pen_id.first().reindex(legacy.index)),
        "arrival_mismatch": mismatch(legacy.arr, all_lots.arrival_date.first().reindex(legacy.index)),
        "head_counts_mismatch": {col: mismatch(legacy[col], val.reindex(legacy.index))
                                  for col, val in (("headIn", placed), ("sold", sold_counts), ("mort", dead_counts),
                                                   ("sickCount", h.reindex(placed.index, fill_value=0)),
                                                   ("healthyCount", placed - h.reindex(placed.index, fill_value=0)))},
        "grade_mismatch": {col: mismatch(legacy[col], grades[grade].reindex(legacy.index, fill_value=0))
                           for col, grade in (("prime", "Canada Prime"), ("aaa", "Canada AAA"),
                                               ("aa", "Canada AA"), ("bGr", "B-Grade/Discount"))},
        "sold_mean_mismatch_by_lot": {
            f: mismatch(legacy[f], sold_lots[col].mean().reindex(legacy.index), precision[f])
            for f, col in fields.items()
        },
        "entry_weight_mismatch_vs_all_lot_mean": mismatch(legacy.entryW, all_lots.entry_weight_kg.mean().reindex(legacy.index), .050001),
        "purchase_matches_all_lots": mismatch(legacy.pCost, all_lots.purchase_cost_cad.mean().reindex(legacy.index), .005001),
        "placement_quarters": quarter.value_counts().sort_index().to_dict(),
        "embedded_rounded_sold_margin": round(float(implied.sum()), 2),
        "embedded_all_margin": round(float(legacy.totMargin.sum()), 2),
        "embedded_gap": round(float(implied.sum() - legacy.totMargin.sum()), 2),
        "source_sold_margin": round(float(sold_margin.sum()), 2),
        "source_all_margin": round(float(all_margin.sum()), 2),
        "source_death_margin": round(float(dead_margin.sum()), 2),
        "embedded_totmargin_vs_all": residual(legacy.totMargin, all_margin.reindex(legacy.index), .005001),
        "embedded_sold_margin_vs_sold_mean": residual(legacy.margin, (sold_margin / sold_counts).reindex(legacy.index), .005001),
        "implied_sold_vs_exact": residual(implied, sold_margin.reindex(legacy.index), 1),
        "example_first_lot": {
            "id": legacy.index[0], "placed": int(placed.loc[legacy.index[0]]),
            "sold": int(sold_counts.loc[legacy.index[0]]),
            "deaths": int(dead_counts.loc[legacy.index[0]]),
            "sold_margin": round(float(sold_margin.loc[legacy.index[0]]), 2),
            "death_margin": round(float(dead_margin.loc[legacy.index[0]]), 2),
            "all_margin": round(float(all_margin.loc[legacy.index[0]]), 2),
            "rounded_implied_sold": round(float(implied.iloc[0]), 2),
        },
        "monthly_dmi_vs_daily": residual(pd.Series(embedded["DMI_HEAD_DAY"]),
                         (feed_months.total_dmi_kg / feed_months.head_count_active).reset_index(drop=True), .005001),
        "monthly_cost_vs_daily": residual(pd.Series(embedded["COST_HEAD_DAY"]),
                         (feed_months.total_feed_cost_cad / feed_months.head_count_active).reset_index(drop=True), .005001),
        "breed_sold_legacy_scope": sold_per_breed.to_dict(),
        "breed_legacy_metrics": breed_stats[["sold_margin", "mean_hcw", "prime_aaa_share"]].round(5).to_dict("index"),
        "source_sold_shelter_metrics": actual_shelter.round(5).to_dict("index"),
        "legacy_diagnosis_totals": {field: int(legacy[field].sum()) for field in diagnosis_fields},
        "legacy_diagnosis_mismatches": diagnoses,
        "legacy_drug_outcomes_vs_all_events": drug_coverage,
        "legacy_drug_cost_vs_all_events": drug_cost,
        "health_weights": {
            "legacy_assumed_treated_sold": int((legacy.sickCount - legacy.mort).clip(lower=0).sum()),
            "observed_treated_sold": int(sold.morbidity_flag.eq("Treated").sum()),
            "legacy_scale_exit_gap": float(np.average(
                legacy.scaleH.map(lambda stage: stage[-1]) - legacy.scaleS.map(lambda stage: stage[-1]), weights=legacy.sold)),
        },
        "legacy_waterfall": {
            "purchase": float(np.average(legacy.pCost, weights=legacy.headIn)),
            **{f: float(np.average(legacy[f], weights=legacy.sold)) for f in ("fCost", "yCost", "vCost", "gRev", "margin")},
        },
    }
    return export


def collect(root):
    paths = [root / path for path in (CSV, BOOK, HTML)]
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    flat = pd.read_csv(paths[0], dtype={"rfid_tag": "string"})
    with pd.ExcelFile(paths[1], engine="openpyxl") as workbook:
        tables = {name: workbook.parse(name, dtype={"rfid_tag": "string"}) for name in workbook.sheet_names}
    embedded = json.loads(re.search(r"^const D = (\{.*\});$", paths[2].read_text(encoding="utf-8"), re.M)[1])
    lot, pen, cattle = (tables[f"Dim_{name}"] for name in ("Lot", "Pen", "Cattle"))
    feed, health, scale = (tables[f"Fact_{name}"] for name in ("Feed_Daily", "Health_Treatments", "Scale_Weights"))
    results = {
        "sha256": hashes,
        "inventory": inventory_checks(flat, tables),
        "closeout": closeout_checks(flat, lot, cattle),
        "feed": feed_checks(flat, feed, lot, pen),
        **event_checks(flat, health, scale),
        "dashboard": dashboard_checks(flat, feed, health, embedded),
    }
    rollup = flat.assign(entry_quarter=flat.entry_date.str[:4] + "Q" + date(flat.entry_date).dt.quarter.astype(str),
                         exit_month=flat.exit_date.str[:7])
    results["closeout_rollups"] = {
        dim: {"groups": int(rollup[dim].nunique()),
              "margin_cad": round(float(rollup.groupby(dim).net_margin_cad.sum().sum()), 2)}
        for dim in ("lot_id", "pen_id", "entry_quarter", "exit_month")
    }
    summary = tables["Executive_Summary"].dropna().set_index("Metric / Dimension")["Value / Description"]
    results["workbook_summary"] = {label: float(value) for label, value in summary.items()
                                   if isinstance(value, (int, float))}
    feed_rows = feed.groupby("lot_id").size()
    results["join_fanout"]["closeout_join_feed_on_lot_rows"] = int(flat.lot_id.map(feed_rows).sum())
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Repository root containing data/ and index.html")
    args = parser.parse_args()
    print(json.dumps(collect(args.root), indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
