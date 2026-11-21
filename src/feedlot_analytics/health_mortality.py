"""Dated health events, recorded outcomes and mortality at animal grain."""

import json

import numpy as np
import pandas as pd

from .contracts import BOOK, FINISHED, MORTALITY
from .feed_growth import SNAPSHOT, SOURCE_HASHES, verify_build
from .health_statistics import supported_difference
from .loaders import NA_OPTIONS, TEXT_DTYPES, sha256, typed_dates
from .metrics import aggregate_closeout
from .pipeline import build
from .relations import add_columns, cents, require_key, safe_ratio

DOF_BINS = [0, 14, 30, 60, 105, np.inf]
DOF_LABELS = ["1–14", "15–30", "31–60", "61–105", "106+"]


def load_health_analysis(root):
    """Replay the verified foundation, then read the native treatment fact."""
    result = build(root, weather_snapshot=root / SNAPSHOT)
    baseline = json.loads((root / "phase2a/reconciliation.json").read_text(encoding="utf-8"))
    verify_build(result, baseline)
    raw = pd.read_excel(root / BOOK, sheet_name="Fact_Health_Treatments", engine="openpyxl",
                        dtype=TEXT_DTYPES, **NA_OPTIONS)
    if sha256(root / BOOK) != SOURCE_HASHES[BOOK]:
        raise ValueError("Workbook changed while reading native treatments")
    return result, treatment_events(typed_dates(raw), result.tables["animal_closeout"])


def treatment_events(treatments, animals):
    """Retain one row per treatment ID and order within animal by date and ID."""
    require_key(treatments, ("treatment_id",), "treatments")
    rows = add_columns(treatments, animals[["animal_id", "lot_id", "pen_id", "entry_date", "exit_date", "exit_type"]],
                       key=("animal_id", "lot_id", "pen_id"), cardinality="many_to_one")
    valid = (rows.treatment_date.between(rows.entry_date, rows.exit_date)
             & rows.dof_at_treatment.eq((rows.treatment_date - rows.entry_date).dt.days + 1))
    if not valid.fillna(False).all():
        raise ValueError("Treatment must have valid inclusive DOF from entry through exit")
    rows = rows.sort_values(["animal_id", "treatment_date", "treatment_id"], ignore_index=True)
    rows["event_number"] = rows.groupby("animal_id", sort=False).cumcount() + 1
    rows["direct_cost_cents"] = cents(rows.vet_cost_cad)
    return rows


def animal_history(animals, health, events):
    """Create a one-row animal history and reconcile independently totaled event costs."""
    key = ("animal_id",)
    columns = ["animal_id", "treatment_events", "first_treatment_id", "first_treatment_date",
               "first_treatment_dof", "first_diagnosis", "first_drug_protocol",
               "direct_treatment_cost_cents", "base_vet_cost_cad"]
    history = add_columns(animals, health[columns], key=key, cardinality="one_to_one")
    indexed = events.set_index("treatment_id")
    second = events.loc[events.event_number.eq(2), ["animal_id", "treatment_date"]].rename(
        columns={"treatment_date": "second_treatment_date"}
    )
    history = add_columns(history, second, key=key, cardinality="one_to_one", require_match=False)
    counts = events.groupby("animal_id").size()
    direct = events.groupby("animal_id").direct_cost_cents.sum()
    first = events.loc[events.event_number.eq(1)].set_index("animal_id").treatment_id
    expected_first = history.animal_id.map(first)
    if not (
        history.treatment_events.eq(history.animal_id.map(counts).fillna(0)).all()
        and history.direct_treatment_cost_cents.eq(history.animal_id.map(direct).fillna(0)).all()
        and history.first_treatment_id.fillna("").eq(expected_first.fillna("")).all()
        and cents(history.vet_cost_cad).eq(cents(history.base_vet_cost_cad) + history.direct_treatment_cost_cents).all()
    ):
        raise ValueError("Animal health history disagrees with the event or veterinary ledger")
    history["first_recorded_outcome"] = history.first_treatment_id.map(indexed.outcome)
    history["history"] = np.select(
        [history.treatment_events.eq(0), history.treatment_events.eq(1)],
        ["No recorded treatment", "One event"], default="Two or more events",
    )
    return history


def treatment_followup(history, *, index="first", days=30):
    """Track the days after an index event through a fixed horizon or competing exit."""
    if index not in {"first", "second"} or days < 1:
        raise ValueError("Expected a first or second event and a positive horizon")
    index_date = f"{index}_treatment_date"
    rows = history.loc[history[index_date].notna()].copy()
    rows["days_from_index_to_exit"] = (rows.exit_date - rows[index_date]).dt.days
    death = rows.exit_type.eq(MORTALITY)
    rows["index_day_death"] = death & rows.days_from_index_to_exit.eq(0)
    rows["later_death_in_window"] = death & rows.days_from_index_to_exit.between(1, days)
    rows["later_death_through_exit"] = death & rows.days_from_index_to_exit.gt(0)
    rows["sale_in_window"] = rows.exit_type.eq(FINISHED) & rows.days_from_index_to_exit.between(0, days)
    rows["observed_through_window"] = rows.days_from_index_to_exit.ge(days)
    rows["at_risk_next_day"] = rows.days_from_index_to_exit.gt(0)
    rows["followup_status"] = np.select(
        [rows.index_day_death, rows.later_death_in_window, rows.sale_in_window],
        ["Index-day death", "Death in follow-up", "Competing sale"], default="Event-free through horizon",
    )
    if index == "first":
        gap = (rows.second_treatment_date - rows.first_treatment_date).dt.days
        rows["same_day_repeat"] = gap.eq(0)
        rows["repeat_in_window"] = gap.between(1, days)
    return rows


def protocol_review(events, history, health, *, by=("diagnosis", "drug_protocol")):
    """Return event totals and exclusive first-event cohorts with subsequent outcomes."""
    keys = list(by)
    rows = events.assign(
        first_event=events.event_number.eq(1), repeat_event=events.event_number.gt(1),
        recovered=events.outcome.eq("Recovered").fillna(False),
        chronic=events.outcome.eq("Chronic / Repeat").fillna(False),
        mortality_label=events.outcome.eq(MORTALITY).fillna(False), missing_outcome=events.outcome.isna(),
    )
    event_review = rows.groupby(keys, dropna=False, observed=True).agg(
        unique_animals=("animal_id", "nunique"), events=("treatment_id", "size"),
        first_events=("first_event", "sum"), repeat_events=("repeat_event", "sum"),
        recovered_labels=("recovered", "sum"), chronic_labels=("chronic", "sum"),
        mortality_labels=("mortality_label", "sum"), missing_outcome=("missing_outcome", "sum"),
        direct_cost_cents=("direct_cost_cents", "sum"),
    )
    event_review["direct_cad_per_event"] = event_review.direct_cost_cents / (100 * event_review.events)
    ledger_keys = {"diagnosis": "first_diagnosis", "drug_protocol": "first_drug_protocol"}
    first = treatment_followup(history)
    first_followup = first.rename(columns={value: key for key, value in ledger_keys.items()})
    outcomes = first_followup.groupby(keys, dropna=False, observed=True).agg(
        start_head=("animal_id", "size"), next_day_head=("at_risk_next_day", "sum"),
        day0_deaths=("index_day_death", "sum"), deaths_days_1_30=("later_death_in_window", "sum"),
        competing_sales_0_30=("sale_in_window", "sum"), deaths_after_first=("later_death_through_exit", "sum"),
        repeat_days_1_30=("repeat_in_window", "sum"), observed_through_30=("observed_through_window", "sum"),
    )
    outcomes["death_risk_days_1_30"] = safe_ratio(outcomes.deaths_days_1_30, outcomes.next_day_head)
    # Reduce the event fact to an exclusive first-event lookup before attaching the ledger.
    return event_review, outcomes.join(
        aggregate_closeout(first, health,
                           by=tuple(ledger_keys[key] for key in keys))
        .rename(columns={value: key for key, value in ledger_keys.items()}).set_index(keys)
    )


def risk_segments(history, *, include_event_day=False):
    """Partition each animal's inclusive days into zero, one and two-plus prior events."""
    require_key(history, ("animal_id",), "risk history")
    keys = ["animal_id", "lot_id", "pen_id"]
    lag = int(not include_event_day)
    first = (history.first_treatment_date - history.entry_date).dt.days + 1 + lag
    second = (history.second_treatment_date - history.entry_date).dt.days + 1 + lag
    last = (history.exit_date - history.entry_date).dt.days + 1
    stop = last + 1
    first = first.fillna(stop).clip(upper=stop).astype(int)
    second = second.fillna(stop).clip(upper=stop).astype(int)
    if first.lt(1).any() or second.lt(first).any() or last.lt(1).any():
        raise ValueError("Invalid risk window or treatment state order")
    segments = []
    for state, start, end in ((0, 1, first), (1, first, second), (2, second, stop)):
        rows = history[keys].assign(state=state, start_dof=start, stop_dof=end)
        rows["death"] = end.eq(stop) & history.exit_type.eq(MORTALITY)
        segments.append(rows.loc[rows.start_dof.lt(rows.stop_dof)])
    return pd.concat(segments, ignore_index=True)


def daily_risk(segments):
    """Aggregate risk head-days and deaths at lot, pen, inclusive DOF and prior-event state."""
    keys = ["pen_id", "lot_id", "dof", "state"]
    if segments.empty:
        return pd.DataFrame(columns=[*keys, "head_days", "deaths"])
    starts = segments.rename(columns={"start_dof": "dof"})[keys].assign(change=1)
    stops = segments.rename(columns={"stop_dof": "dof"})[keys].assign(change=-1)
    changes = pd.concat([starts, stops]).groupby(keys, observed=True).change.sum()
    grid = (changes.unstack("dof", fill_value=0)
            .reindex(columns=range(1, int(segments.stop_dof.max()) + 1), fill_value=0).cumsum(axis=1))
    risk = grid.stack(future_stack=True).rename("head_days")
    deaths = (segments.loc[segments.death].assign(dof=lambda frame: frame.stop_dof - 1)
              .groupby(keys, observed=True).size().rename("deaths"))
    daily = risk.loc[risk.gt(0)].to_frame().join(deaths)
    daily["deaths"] = daily.deaths.fillna(0).astype(int)
    return daily.reset_index()


def risk_contrasts(daily, *, max_dof=None):
    """Compare mortality intensity within same lot and DOF where both states exist."""
    rows = daily if max_dof is None else daily.loc[daily.dof.le(max_dof)]
    results = []
    for exposure, reference in (([1, 2], [0]), ([2], [1])):
        keys = ["pen_id", "lot_id", "dof"]
        exposed = rows.loc[rows.state.isin(exposure)].groupby(keys)[["head_days", "deaths"]].sum()
        control = rows.loc[rows.state.isin(reference)].groupby(keys)[["head_days", "deaths"]].sum()
        cells = exposed.rename(columns={"head_days": "exposed_n", "deaths": "exposed_total"}).join(
            control.rename(columns={"head_days": "reference_n", "deaths": "reference_total"}), how="outer"
        ).fillna(0)
        results.append({"prior_event_state": "1+ vs 0" if reference == [0] else "2+ vs 1",
                        **supported_difference(cells.reset_index(), scale=1000)})
    return pd.DataFrame(results)
