"""Canonical facts with dimension-only joins and independent event rollups."""

import pandas as pd

from .contracts import COSTS, FINISHED
from .metrics import FEED_METRICS, aggregate_closeout, apply_metrics
from .relations import add_columns, cents, safe_ratio


def animal_closeout(cattle, closeout, lots, pens):
    attributes = cattle[["animal_id", "rfid_tag", "breed", "sex", "frame_score", "status"]]
    animal = add_columns(closeout, attributes, key=("animal_id",), cardinality="one_to_one")
    # Nominal capacity and the lot's placed count stay on their own dimension grains.
    context = lots.drop(columns=["pen_id", "head_count_in"])
    animal = add_columns(animal, context, key=("lot_id",), cardinality="many_to_one")
    animal = add_columns(animal, pens.drop(columns=["capacity_head", "bunk_space_m"]),
                         key=("pen_id",), cardinality="many_to_one")
    animal["production_cost_cents"] = animal[list(COSTS)].apply(cents).sum(axis=1)
    animal["production_cost_cad"] = animal.production_cost_cents / 100
    animal["elapsed_exit_days"] = (animal.exit_date - animal.entry_date).dt.days
    animal["placement_quarter"] = animal.entry_date.dt.to_period("Q").astype("string")
    animal["exit_month"] = animal.exit_date.dt.to_period("M").astype("string")
    animal["lot_closeout_date"] = animal.groupby("lot_id").exit_date.transform("max")
    return animal.sort_values("animal_id", ignore_index=True)


def animal_health_summary(animals, treatments):
    ordered = treatments.sort_values(["animal_id", "treatment_date", "treatment_id"])
    first = ordered.drop_duplicates("animal_id")[[
        "animal_id", "treatment_id", "treatment_date", "dof_at_treatment",
        "diagnosis", "drug_protocol", "outcome",
    ]].rename(columns={
        "treatment_id": "first_treatment_id", "treatment_date": "first_treatment_date",
        "dof_at_treatment": "first_treatment_dof", "diagnosis": "first_diagnosis",
        "drug_protocol": "first_drug_protocol", "outcome": "first_treatment_outcome",
    })
    rows = ordered.assign(
        cost_cents=cents(ordered.vet_cost_cad),
        chronic=ordered.outcome.eq("Chronic / Repeat"),
        recovered=ordered.outcome.eq("Recovered"),
        mortality=ordered.outcome.eq("Mortality"),
        brd=ordered.diagnosis.eq("BRD - Bovine Respiratory"),
    )
    counts = rows.groupby("animal_id", as_index=False).agg(
        treatment_events=("treatment_id", "size"),
        direct_treatment_cost_cents=("cost_cents", "sum"),
        chronic_events=("chronic", "sum"),
        recovery_events=("recovered", "sum"),
        mortality_treatment_events=("mortality", "sum"),
        brd_events=("brd", "sum"),
    )
    # Nullable integers preserve exact types across a left join to untreated cattle.
    counts = counts.astype({col: "Int64" for col in counts if col != "animal_id"})
    key = ("animal_id",)
    stats = add_columns(animals[["animal_id", "lot_id", "pen_id", "vet_cost_cad"]], counts,
                        key=key, cardinality="one_to_one", require_match=False)
    stats = add_columns(stats, first.astype({"first_treatment_dof": "Int64"}),
                        key=key, cardinality="one_to_one", require_match=False)
    for col in counts.columns.drop("animal_id"):
        stats[col] = stats[col].fillna(0).astype("int64")
    stats["treated"] = stats.treatment_events.gt(0)
    stats["repeat_treated"] = stats.treatment_events.gt(1)
    stats["first_pull_by_day30"] = stats.first_treatment_dof.between(1, 30).fillna(False).astype(bool)
    stats["direct_treatment_cost_cad"] = stats.direct_treatment_cost_cents / 100
    stats["base_vet_cost_cad"] = (cents(stats.vet_cost_cad) - stats.direct_treatment_cost_cents) / 100
    return stats


def animal_scale_stage(animals, weighings):
    stages = add_columns(weighings, animals[["animal_id", "entry_date", "entry_weight_kg", "exit_type"]],
                         key=("animal_id",), cardinality="many_to_one")
    stages = stages.sort_values(["animal_id", "weigh_date", "weigh_id"], ignore_index=True)
    previous = stages.groupby("animal_id", sort=False)
    stages["previous_weigh_date"] = previous.weigh_date.shift()
    stages["elapsed_interval_days"] = (stages.weigh_date - stages.previous_weigh_date).dt.days.astype("Int64")
    stages["interval_gain_kg"] = previous.weight_kg.diff()
    stages["interval_adg_kg"] = safe_ratio(
        stages.interval_gain_kg, stages.elapsed_interval_days.astype("float64")
    )
    stages["elapsed_days_since_entry"] = (stages.weigh_date - stages.entry_date).dt.days
    stages["inclusive_stage_days"] = stages.elapsed_days_since_entry + 1
    stages["gain_since_entry_kg"] = stages.weight_kg - stages.entry_weight_kg
    stages["elapsed_cumulative_adg_kg"] = safe_ratio(stages.gain_since_entry_kg, stages.elapsed_days_since_entry)
    return stages


def lot_closeout(animals, health, lots, pens):
    key = ("lot_id",)
    totals = aggregate_closeout(animals, health, by=key)
    windows = animals.groupby("lot_id", as_index=False).agg(
        lot_closeout_date=("exit_date", "max"), breed_count=("breed", "nunique"),
    )
    sold_dates = (animals.loc[animals.exit_type.eq(FINISHED)].groupby("lot_id", as_index=False)
                  .exit_date.max().rename(columns={"exit_date": "sold_closeout_date"}))
    totals = add_columns(lots, totals, key=key, cardinality="one_to_one")
    totals = add_columns(totals, windows, key=key, cardinality="one_to_one")
    totals = add_columns(totals, sold_dates, key=key, cardinality="one_to_one", require_match=False)
    return add_columns(totals, pens[["pen_id", "site_zone", "pen_type"]],
                       key=("pen_id",), cardinality="many_to_one")


def lot_feed_reconciliation(animals, feed):
    # Each independent ledger is reduced to one row per lot before bridging the two.
    delivered = feed.groupby("lot_id", as_index=False).agg(
        pen_id=("pen_id", "first"), first_feed_date=("feed_date", "min"),
        last_feed_date=("feed_date", "max"), feed_days=("feed_date", "size"),
        recorded_head_days=("head_count_active", "sum"),
        delivered_dm_kg=("total_dmi_kg", "sum"), delivered_feed_cost_cad=("total_feed_cost_cad", "sum"),
    )
    allocated = animals.groupby("lot_id", as_index=False).agg(
        head_placed=("animal_id", "size"), financial_head_days=("financial_dof", "sum"),
        allocated_dm_kg=("allocated_dmi_kg", "sum"), allocated_feed_cost_cad=("allocated_feed_cost_cad", "sum"),
    )
    bridge = add_columns(delivered, allocated, key=("lot_id",), cardinality="one_to_one")
    dm_delta = bridge.delivered_dm_kg - bridge.allocated_dm_kg
    cost_delta = bridge.delivered_feed_cost_cad - bridge.allocated_feed_cost_cad
    bridge["dm_delivered_less_allocated_kg"] = dm_delta.round(2)
    bridge["cost_delivered_less_allocated_cad"] = cost_delta.round(2)
    bridge["rounding_bound_per_metric"] = bridge.head_placed * .005
    bridge["within_rounding_bound"] = (
        dm_delta.abs().le(bridge.rounding_bound_per_metric + 1e-6)
        & cost_delta.abs().le(bridge.rounding_bound_per_metric + 1e-6)
    )
    return bridge


def pen_day_feed(feed, pens):
    daily = feed.groupby(["pen_id", "feed_date"], as_index=False).agg(
        delivery_rows=("lot_id", "size"), recorded_lots=("lot_id", "nunique"),
        recorded_head_days=("head_count_active", "sum"), delivered_as_fed_kg=("total_as_fed_kg", "sum"),
        delivered_dm_kg=("total_dmi_kg", "sum"), delivered_feed_cost_cad=("total_feed_cost_cad", "sum"),
        forage_dmi_kg=("forage_dmi_kg", "sum"), concentrate_dmi_kg=("concentrate_dmi_kg", "sum"),
        supplement_dmi_kg=("supplement_dmi_kg", "sum"), forage_cost_cad=("forage_cost_cad", "sum"),
        concentrate_cost_cad=("concentrate_cost_cad", "sum"), supplement_cost_cad=("supplement_cost_cad", "sum"),
    )
    daily = add_columns(daily, pens, key=("pen_id",), cardinality="many_to_one")
    daily["feed_month"] = daily.feed_date.dt.to_period("M").astype("string")
    daily["recorded_occupancy_fraction"] = safe_ratio(daily.recorded_head_days, daily.capacity_head)
    return apply_metrics(daily, FEED_METRICS)
