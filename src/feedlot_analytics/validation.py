"""Fail fast on broken grains, and report reconciliation at source precision."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .contracts import (
    COSTS, DATE_BOUNDS, DOMAINS, EXPECTED_COUNTS, EXPECTED_MARGIN_CENTS,
    FINANCE, FINISHED, FLAT, FLAT_NULLABLE, INT_FIELDS, MORTALITY, SHEETS,
    STAGE_DAYS, TEXT_FIELDS,
)
from .loaders import Sources, typed_dates
from .relations import add_columns, cents, within


class ValidationError(ValueError):
    """A source contract or reconciliation failed."""

    def __init__(self, rules):
        self.rules = tuple(rules)
        super().__init__("Failed validation: " + ", ".join(self.rules))


@dataclass
class Controls:
    results: list[dict] = field(default_factory=list)

    def equal(self, rule, actual, expected):
        self.results.append({
            "rule": rule, "actual": actual, "expected": expected, "passed": actual == expected,
        })

    def rows(self, rule, valid):
        self.equal(rule, int((~np.asarray(pd.Series(valid).fillna(False), dtype=bool)).sum()), 0)

    def require_pass(self):
        failed = [check["rule"] for check in self.results if not check["passed"]]
        if failed:
            raise ValidationError(failed)


def check_source_schema(frames, controls):
    for name, spec in {"CSV": FLAT, **SHEETS}.items():
        frame = frames[name]
        controls.equal(f"{name}.columns", list(frame), list(spec.columns))
        controls.equal(f"{name}.rows", len(frame), spec.rows)
    controls.require_pass()
    for name, spec in {"CSV": FLAT, **SHEETS}.items():
        if not spec.key:
            continue
        frame = frames[name]
        nullable = FLAT_NULLABLE if spec is FLAT else ("quality_grade",)
        required = [col for col in frame if col not in nullable]
        controls.rows(f"{name}.required", ~frame[required].isna().any(axis=1))
        controls.rows(f"{name}.primary_key", ~frame.duplicated(list(spec.key)))
        for col in frame:
            if col in TEXT_FIELDS or col in DATE_BOUNDS:
                controls.equal(f"{name}.{col}.type", str(frame[col].dtype), "string")
                controls.rows(f"{name}.{col}.nonblank", frame[col].isna() | frame[col].str.strip().ne(""))
            elif col in INT_FIELDS:
                controls.equal(f"{name}.{col}.integer_type", pd.api.types.is_integer_dtype(frame[col]), True)
            else:
                controls.equal(f"{name}.{col}.numeric_type", pd.api.types.is_numeric_dtype(frame[col]), True)
                if pd.api.types.is_numeric_dtype(frame[col]):
                    controls.rows(f"{name}.{col}.finite_or_missing", frame[col].isna() | np.isfinite(frame[col]))
        for col, domain in DOMAINS.get(name, {}).items():
            controls.rows(f"{name}.{col}.domain", frame[col].isin(domain) | frame[col].isna())
    controls.require_pass()


def check_parity(left, right, key, name, controls):
    reference = right.set_index(key)
    controls.rows(f"{name}.{key}.exists", left[key].isin(reference.index))
    for col in left.columns.intersection(reference.columns):
        actual, expected = left[col], left[key].map(reference[col])
        if pd.api.types.is_numeric_dtype(actual):
            match = np.isclose(actual, expected, atol=1e-8, rtol=0, equal_nan=True)
        else:
            match = actual.eq(expected).fillna(False) | (actual.isna() & expected.isna())
        controls.rows(f"{name}.{col}.parity", match)


def check_relationships(frames, controls):
    pen, lot, cattle = (frames[f"Dim_{table}"] for table in ("Pen", "Lot", "Cattle"))
    animal = cattle.set_index("animal_id")
    lots = lot.set_index("lot_id")
    for name, frame in frames.items():
        if "pen_id" in frame and name != "Dim_Pen":
            controls.rows(f"{name}.pen_fk", frame.pen_id.isin(pen.pen_id))
        if "lot_id" in frame and name != "Dim_Lot":
            controls.rows(f"{name}.lot_fk", frame.lot_id.isin(lot.lot_id))
            controls.rows(f"{name}.lot_pen_path", frame.pen_id.eq(frame.lot_id.map(lots.pen_id)))
        if "animal_id" in frame and name != "Dim_Cattle":
            controls.rows(f"{name}.animal_fk", frame.animal_id.isin(cattle.animal_id))
            controls.rows(f"{name}.animal_lot_path", frame.lot_id.eq(frame.animal_id.map(animal.lot_id)))
            controls.rows(f"{name}.animal_pen_path", frame.pen_id.eq(frame.animal_id.map(animal.pen_id)))
    controls.rows("cattle.rfid", cattle.rfid_tag.str.fullmatch(r"\d{15}") & ~cattle.rfid_tag.duplicated())
    scale = frames["Fact_Scale_Weights"]
    controls.rows("scale.animal_stage_key", ~scale.duplicated(["animal_id", "weigh_stage"]))
    flat = frames["CSV"]
    for name, key in (
        ("Feedlot_Flat_15000", "animal_id"), ("Fact_Closeout_Sales", "animal_id"),
        ("Dim_Cattle", "animal_id"), ("Dim_Lot", "lot_id"), ("Dim_Pen", "pen_id"),
    ):
        check_parity(flat, frames[name], key, f"flat_vs_{name}", controls)
    controls.require_pass()


def check_closeout(frames, controls):
    close = frames["Fact_Closeout_Sales"]
    cattle, lots = frames["Dim_Cattle"], frames["Dim_Lot"].set_index("lot_id")
    sold = close.loc[close.exit_type.eq(FINISHED)]
    dead = close.loc[close.exit_type.eq(MORTALITY)]
    dof = (close.exit_date - close.entry_date).dt.days + 1
    controls.rows("closeout.dof", dof.eq(close.financial_dof) & dof.gt(0))
    controls.rows("closeout.entries", close.entry_date.eq(close.lot_id.map(lots.arrival_date)))
    controls.rows("closeout.cattle_coverage", cattle.animal_id.isin(close.animal_id))
    status = cattle.set_index("animal_id").status
    controls.rows("closeout.exit_vs_cattle_status",
                  close.exit_type.replace({FINISHED: "Sold"}).eq(close.animal_id.map(status)))
    controls.rows("lots.placed_vs_recorded", lots.head_count_in.eq(close.groupby("lot_id").size()))
    controls.rows("lots.single_sold_date", sold.groupby("lot_id").exit_date.nunique().le(1))

    money = close[list(FINANCE)].apply(cents)
    controls.rows("closeout.cent_precision", within(close[list(FINANCE)], money / 100, 1e-8).all(axis=1))
    costs = money[list(COSTS)].sum(axis=1)
    controls.rows("closeout.positive_inputs", close.entry_weight_kg.gt(0)
                  & close.allocated_dmi_kg.ge(0) & money[list(COSTS)].ge(0).all(axis=1))
    controls.rows("closeout.purchase", within(
        close.purchase_cost_cad, close.entry_weight_kg * close.lot_id.map(lots.feeder_purchase_price_per_kg),
        .005001,
    ))
    controls.rows("closeout.yardage", money.yardage_cost_cad.eq(dof * 60))
    controls.rows("closeout.ledger", money.net_margin_cad.eq(money.gross_revenue_cad - costs))
    flat_cost = frames["CSV"].set_index("animal_id").total_production_cost_cad
    controls.rows("closeout.flat_cost", costs.eq(cents(close.animal_id.map(flat_cost))))
    for key, value in {
        "sold_only_margin_cents": int(money.loc[sold.index, "net_margin_cad"].sum()),
        "mortality_loss_cents": -int(money.loc[dead.index, "net_margin_cad"].sum()),
        "all_outcome_margin_cents": int(money.net_margin_cad.sum()),
    }.items():
        controls.equal(f"snapshot.{key}", value, EXPECTED_MARGIN_CENTS[key])

    placeholders = [
        "exit_weight_kg", "total_gain_kg", "lifetime_adg_kg", "fcr", "total_cost_of_gain_per_kg",
        "feed_cost_of_gain_per_kg", "hot_carcass_weight_kg", "dressing_pct",
        "grid_price_per_kg_carcass", "gross_revenue_cad",
    ]
    controls.rows("closeout.death_placeholders", dead[placeholders].eq(0).all(axis=1) & dead.quality_grade.isna())
    controls.rows("closeout.sold_outputs", sold[placeholders].gt(0).all(axis=1) & sold.quality_grade.notna()
                  & sold.dressing_pct.le(1) & sold.allocated_dmi_kg.gt(0)
                  & sold.hot_carcass_weight_kg.le(sold.exit_weight_kg))
    for rule, actual, expected, tolerance in (
        ("gain", sold.total_gain_kg, sold.exit_weight_kg - sold.entry_weight_kg, 1e-6),
        ("adg", sold.lifetime_adg_kg, sold.total_gain_kg / sold.financial_dof, .000501),
        ("fcr", sold.fcr, sold.allocated_dmi_kg / sold.total_gain_kg, .000501),
        ("feed_cog", sold.feed_cost_of_gain_per_kg, sold.allocated_feed_cost_cad / sold.total_gain_kg, .005001),
        ("nonpurchase_cog", sold.total_cost_of_gain_per_kg,
         sold[list(COSTS[1:])].sum(axis=1) / sold.total_gain_kg, .005001),
        ("hcw", sold.hot_carcass_weight_kg, sold.exit_weight_kg * sold.dressing_pct, .050001),
        ("revenue", sold.gross_revenue_cad, sold.hot_carcass_weight_kg * sold.grid_price_per_kg_carcass, .005001),
    ):
        controls.rows(f"closeout.{rule}", within(actual, expected, tolerance))


def check_feed(frames, controls):
    feed = frames["Fact_Feed_Daily"]
    close = frames["Fact_Closeout_Sales"]
    lots = frames["Dim_Lot"].set_index("lot_id")
    pens = frames["Dim_Pen"].set_index("pen_id")
    capacity = pens.capacity_head
    controls.rows("pens.positive_geometry", capacity.gt(0) & pens.bunk_space_m.gt(0))
    controls.rows("lots.positive_inputs", lots.head_count_in.gt(0) & lots.target_finish_weight_kg.gt(0)
                  & lots.feeder_purchase_price_per_kg.gt(0))
    controls.rows("lots.placement_capacity", lots.head_count_in.le(lots.pen_id.map(capacity)))
    controls.rows("feed.positive_and_physical", feed.head_count_active.gt(0)
                  & feed.dm_pct.gt(0) & feed.dm_pct.le(1)
                  & feed.filter(regex=r"_kg$|_cad$").ge(0).all(axis=1))
    days = (feed.feed_date - feed.lot_id.map(lots.arrival_date)).dt.days + 1
    phase = np.select([days.le(14), days.le(28), days.le(70)],
                      ["Starter", "Transition", "Grower"], default="Finisher")
    controls.rows("feed.dof_phase", days.gt(0) & feed.dof_current.eq(days) & feed.ration_phase.eq(phase))
    span = feed.groupby("lot_id").feed_date.agg(["min", "max", "size"]).reindex(lots.index)
    last_exit = close.groupby("lot_id").exit_date.max().reindex(lots.index)
    controls.rows("feed.complete_lot_span", span["min"].eq(lots.arrival_date) & span["max"].eq(last_exit)
                  & span["size"].eq((span["max"] - span["min"]).dt.days + 1))
    pen_day = feed.groupby(["pen_id", "feed_date"], as_index=False).head_count_active.agg(["size", "sum"])
    controls.rows("feed.pen_day_capacity", pen_day["sum"].le(pen_day.pen_id.map(capacity)))
    controls.rows("feed.nonoverlapping_lots", pen_day["size"].eq(1))

    implied = pd.Series(index=feed.index, dtype="int64")
    timelines = close.groupby("lot_id")
    for lot_id, deliveries in feed.groupby("lot_id"):
        animals = timelines.get_group(lot_id)
        dates = deliveries.feed_date.to_numpy()
        entered = np.searchsorted(np.sort(animals.entry_date.to_numpy()), dates, side="right")
        exited = np.searchsorted(np.sort(animals.exit_date.to_numpy()), dates, side="left")
        implied.loc[deliveries.index] = entered - exited
    controls.rows("feed.inclusive_roster", feed.head_count_active.eq(implied))

    for rule, total, expected, tolerance in (
        ("dm_from_asfed", "total_dmi_kg", feed.total_as_fed_kg * feed.dm_pct, .005001),
        ("dm_components", "total_dmi_kg",
         feed[["forage_dmi_kg", "concentrate_dmi_kg", "supplement_dmi_kg"]].sum(axis=1), .010001),
        ("cost_components", "total_feed_cost_cad",
         feed[["forage_cost_cad", "concentrate_cost_cad", "supplement_cost_cad"]].sum(axis=1), .010001),
    ):
        controls.rows(f"feed.{rule}", within(feed[total], expected, tolerance))
    for name, field, allocated in (
        ("dm", "total_dmi_kg", "allocated_dmi_kg"),
        ("cost", "total_feed_cost_cad", "allocated_feed_cost_cad"),
    ):
        shown = feed.groupby("lot_id")[field].sum()
        assigned = close.groupby("lot_id")[allocated].sum()
        bound = lots.head_count_in * .005 + 1e-6
        controls.rows(f"feed.{name}_allocation_tolerance", assigned.sub(shown).abs().le(bound))


def check_events(frames, controls):
    close = frames["Fact_Closeout_Sales"]
    lifetimes = close[["animal_id", "entry_date", "exit_date", "exit_type"]]
    health, scale = (
        add_columns(frames[name], lifetimes, key=("animal_id",), cardinality="many_to_one")
        for name in ("Fact_Health_Treatments", "Fact_Scale_Weights")
    )
    for name, frame, column in (("health", health, "treatment_date"), ("scale", scale, "weigh_date")):
        controls.rows(f"{name}.within_lifetime",
                      frame[column].ge(frame.entry_date) & frame[column].le(frame.exit_date))
    controls.rows("health.dof", health.dof_at_treatment.eq((health.treatment_date - health.entry_date).dt.days + 1))
    controls.rows("health.positive_cent_cost", health.vet_cost_cad.gt(0)
                  & within(health.vet_cost_cad, cents(health.vet_cost_cad) / 100, 1e-8))
    controls.rows("health.mortality_outcome", health.outcome.ne(MORTALITY) | health.exit_type.eq(MORTALITY))
    by_animal = health.groupby("animal_id")
    flat = frames["CSV"]
    first = health.sort_values(["treatment_date", "treatment_id"]).drop_duplicates("animal_id").set_index("animal_id")
    count = flat.animal_id.map(by_animal.size()).fillna(0)
    direct = health.assign(cost_cents=cents(health.vet_cost_cad)).groupby("animal_id").cost_cents.sum()
    chronic = health.outcome.eq("Chronic / Repeat").groupby(health.animal_id).any()
    controls.rows("health.flat_count", flat.treatment_count.eq(count) & flat.morbidity_flag.eq("Treated").eq(count.gt(0)))
    chronic_recorded = flat.animal_id.map(chronic).astype("boolean").fillna(False)
    controls.rows("health.flat_chronic", flat.has_chronic_outcome.eq("Yes").eq(chronic_recorded))
    for col, event in (("primary_diagnosis", "diagnosis"), ("primary_drug_protocol", "drug_protocol")):
        actual, expected = flat[col], flat.animal_id.map(first[event])
        controls.rows(f"health.flat_{event}", actual.eq(expected).fillna(False) | (actual.isna() & expected.isna()))
    controls.rows("health.flat_direct_cost", flat.total_vet_cost_cad.isna().eq(count.eq(0))
                  & cents(flat.total_vet_cost_cad.fillna(0)).eq(flat.animal_id.map(direct).fillna(0)))
    controls.rows("health.base_vet_cost",
                  cents(close.vet_cost_cad).sub(close.animal_id.map(direct).fillna(0)).eq(1800))

    ordered = scale.sort_values(["animal_id", "weigh_date", "weigh_id"])
    intervals = ordered.groupby("animal_id").weigh_date.diff().dt.days
    changes = ordered.groupby("animal_id").weight_kg.diff()
    arrival = ordered.loc[ordered.weigh_stage.eq("Arrival")]
    finish = ordered.loc[ordered.weigh_stage.eq("Closeout")]
    elapsed = (ordered.weigh_date - ordered.entry_date).dt.days
    scheduled = ordered.loc[ordered.weigh_stage.isin(STAGE_DAYS)]
    controls.rows("scale.scheduled_days", elapsed.loc[scheduled.index].eq(scheduled.weigh_stage.map(STAGE_DAYS)))
    controls.rows("scale.positive_weights", ordered.weight_kg.gt(0))
    controls.rows("scale.valid_intervals", intervals.fillna(0).eq(ordered.days_since_last_weigh)
                  & (ordered.weigh_stage.eq("Arrival") | (intervals.gt(0) & changes.ge(0))))
    controls.rows("scale.period_adg", within(ordered.period_adg_kg, (changes / intervals).fillna(0), .000501))
    lookup = close.set_index("animal_id")
    entry = ordered.animal_id.map(lookup.entry_weight_kg)
    controls.rows("scale.cumulative_adg_inclusive",
                  within(ordered.cumulative_adg_kg, (ordered.weight_kg - entry) / (elapsed + 1), .000501))
    controls.rows("scale.arrival_coverage", close.animal_id.isin(arrival.animal_id))
    controls.rows("scale.arrival_value", arrival.weigh_date.eq(arrival.entry_date)
                  & arrival.weight_kg.eq(arrival.animal_id.map(lookup.entry_weight_kg)))
    controls.rows("scale.closeout_coverage",
                  close.animal_id.isin(finish.animal_id).eq(close.exit_type.eq(FINISHED)))
    controls.rows("scale.closeout_value", finish.weigh_date.eq(finish.exit_date)
                  & finish.weight_kg.eq(finish.animal_id.map(lookup.exit_weight_kg)))


def validate_sources(sources: Sources, controls: Controls) -> dict[str, pd.DataFrame]:
    controls.equal("workbook.sheets", sorted(sources.sheets), sorted(SHEETS))
    controls.require_pass()
    raw = {"CSV": sources.flat, **sources.sheets}
    check_source_schema(raw, controls)
    frames = {name: typed_dates(frame) for name, frame in raw.items()}
    for column in ("primary_diagnosis", "primary_drug_protocol"):
        csv = sources.flat
        workbook = sources.sheets["Feedlot_Flat_15000"]
        controls.rows(f"CSV.{column}.untreated_placeholder",
                      csv[column].eq("None").fillna(False).eq(csv.treatment_count.eq(0))
                      & csv[column].notna())
        controls.rows(f"Feedlot_Flat_15000.{column}.untreated_blank",
                      workbook[column].isna().eq(workbook.treatment_count.eq(0)))
        frames["CSV"][column] = csv[column].mask(csv[column].eq("None"))
    for name, frame in frames.items():
        for col, (start, end) in DATE_BOUNDS.items():
            if col in frame:
                actual = frame[col].agg(["min", "max"]).dt.strftime("%Y-%m-%d").tolist()
                controls.equal(f"{name}.{col}.bounds", actual, [start, end])
    check_relationships(frames, controls)
    check_closeout(frames, controls)
    check_feed(frames, controls)
    check_events(frames, controls)
    close = frames["Fact_Closeout_Sales"]
    feed = frames["Fact_Feed_Daily"]
    health = frames["Fact_Health_Treatments"]
    counts = {
        "head_placed": frames["Dim_Cattle"].animal_id.nunique(),
        "head_sold": close.exit_type.eq(FINISHED).sum(),
        "head_mortality": close.exit_type.eq(MORTALITY).sum(),
        "lots": frames["Dim_Lot"].lot_id.nunique(),
        "pens": frames["Dim_Pen"].pen_id.nunique(),
        "head_treated": health.animal_id.nunique(),
        "treatment_events": health.treatment_id.nunique(),
        "financial_head_days": close.financial_dof.sum(),
        "recorded_head_days": feed.head_count_active.sum(),
    }
    for key, value in counts.items():
        controls.equal(f"snapshot.{key}", int(value), EXPECTED_COUNTS[key])
    controls.require_pass()
    return frames
