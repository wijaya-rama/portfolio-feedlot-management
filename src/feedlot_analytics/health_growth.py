"""Link dated treatment history to scale intervals and fixed observation windows."""

import pandas as pd

from .contracts import FINISHED, MORTALITY, STAGE_DAYS
from .feed_growth import STAGES, growth_events
from .health_statistics import with_entry_band
from .relations import add_columns, require_key

FOLLOWUP_STAGES = ("Day 35", "Day 70", "Day 105")


def _event_count_as_of(rows, dates, *, include_date):
    """Return the count known through a date, or strictly before it."""
    left = dates[["animal_id", "date"]].assign(position=range(len(dates)))
    right = (rows[["animal_id", "treatment_date", "event_number"]]
             .drop_duplicates(["animal_id", "treatment_date"], keep="last"))
    match = pd.merge_asof(
        left.sort_values("date"), right.sort_values("treatment_date"),
        left_on="date", right_on="treatment_date", by="animal_id",
        allow_exact_matches=include_date,
    )
    return match.sort_values("position").event_number.fillna(0).astype(int).set_axis(dates.index)


def intervals_with_treatments(scale, animals, events):
    """Keep observed intervals at scale grain and distinguish interior from boundary events."""
    weighings = growth_events(scale, animals)
    intervals = weighings.loc[weighings.elapsed_interval_days.gt(0)].copy()
    intervals["previous_stage"] = weighings.groupby("animal_id", observed=True).weigh_stage.shift()
    start = intervals[["animal_id", "previous_weigh_date"]].rename(columns={"previous_weigh_date": "date"})
    end = intervals[["animal_id", "weigh_date"]].rename(columns={"weigh_date": "date"})
    before = _event_count_as_of(events, start, include_date=False)
    through_start = _event_count_as_of(events, start, include_date=True)
    before_end = _event_count_as_of(events, end, include_date=False)
    through_end = _event_count_as_of(events, end, include_date=True)
    return intervals.assign(
        prior_events=before, events_on_start=through_start - before,
        events_inside=before_end - through_start, events_on_end=through_end - before_end,
    )


def first_pull_vs_stage(history, scale):
    """Include every first-treated animal for each stage and retain unobserved weigh dates."""
    key = ("animal_id",)
    treated = history.loc[history.first_treatment_date.notna(), [
        "animal_id", "first_treatment_date", "first_treatment_dof", "entry_date", "exit_date", "exit_type",
    ]]
    dates = scale.pivot(index="animal_id", columns="weigh_stage", values="weigh_date").reindex(columns=STAGES)
    rows = add_columns(treated, dates.reset_index(), key=key, cardinality="one_to_one", require_match=False)
    long = rows.melt(id_vars=list(treated), var_name="stage", value_name="stage_date")
    pull = long.first_treatment_date
    stage = long.stage_date
    long["timing"] = "No weigh record"
    long.loc[pull.lt(stage), "timing"] = "First pull before weigh"
    long.loc[pull.eq(stage), "timing"] = "Same date, order unknown"
    long.loc[pull.gt(stage), "timing"] = "First pull after weigh"
    return long


def treatment_growth_pairs(history, intervals, *, event="first"):
    """Select the nearest fully pre/post intervals, with strict date ordering."""
    if event not in {"first", "second"}:
        raise ValueError("Expected the first or second treatment")
    key = ("animal_id",)
    index_date = f"{event}_treatment_date"
    cohort = history.loc[history[index_date].notna(), [
        "animal_id", "lot_id", "pen_id", "exit_type", "exit_date", index_date,
    ]].rename(columns={index_date: "index_date"})
    rows = add_columns(intervals, cohort[["animal_id", "index_date"]], key=key,
                       cardinality="many_to_one", require_match=False)
    before = rows.weigh_date.lt(rows.index_date)
    after = rows.previous_weigh_date.gt(rows.index_date)
    pairs = cohort.copy()
    for label, mask, order, keep in (
        ("pre", before, "weigh_date", "last"), ("post", after, "previous_weigh_date", "first"),
    ):
        columns = [
            "animal_id", "previous_stage", "weigh_stage", "previous_weigh_date", "weigh_date",
            "elapsed_interval_days", "interval_adg_kg", "events_inside", "events_on_start", "events_on_end",
        ]
        picked = rows.loc[mask, columns].sort_values(order).drop_duplicates("animal_id", keep=keep)
        pairs = add_columns(pairs, picked.add_prefix(f"{label}_").rename(
            columns={f"{label}_animal_id": "animal_id"}
        ), key=key, cardinality="one_to_one", require_match=False)
    pairs["pre_gap_days"] = (pairs.index_date - pairs.pre_weigh_date).dt.days
    pairs["post_gap_days"] = (pairs.post_previous_weigh_date - pairs.index_date).dt.days
    pairs["adg_change"] = pairs.post_interval_adg_kg - pairs.pre_interval_adg_kg
    pairs["mortality"] = pairs.exit_type.eq(MORTALITY)
    return pairs


def growth_landmark(history, intervals, *, start="Day 35", end="Day 70"):
    """Start follow-up at a recorded weigh date, with status determined before that date."""
    if not STAGE_DAYS[start] < STAGE_DAYS[end]:
        raise ValueError("Landmark follow-up stage must follow the time-zero stage")
    key = ("animal_id",)
    initial = intervals.loc[intervals.weigh_stage.eq(start), [
        "animal_id", "weigh_date", "interval_adg_kg",
    ]].rename(columns={"weigh_date": "landmark_date", "interval_adg_kg": "landmark_adg"})
    rows = add_columns(history, initial, key=key, cardinality="one_to_one", require_match=False)
    rows = rows.loc[rows.exit_date.gt(rows.landmark_date)].copy()
    days = STAGE_DAYS[end] - STAGE_DAYS[start]
    rows["horizon"] = rows.landmark_date + pd.to_timedelta(days, unit="D")
    rows["same_day_first"] = rows.first_treatment_date.eq(rows.landmark_date)
    rows["prior_treatment"] = rows.first_treatment_date.lt(rows.landmark_date)
    rows["new_first_in_window"] = (
        rows.first_treatment_date.gt(rows.landmark_date) & rows.first_treatment_date.le(rows.horizon)
    )
    rows["death_through_end"] = rows.exit_type.eq(MORTALITY) & rows.exit_date.le(rows.horizon)
    rows["sale_through_end"] = rows.exit_type.eq(FINISHED) & rows.exit_date.le(rows.horizon)
    following = intervals.loc[intervals.weigh_stage.eq(end) & intervals.previous_stage.eq(start), [
        "animal_id", "weigh_date", "previous_weigh_date", "interval_adg_kg",
    ]].rename(columns={"weigh_date": "next_weigh_date", "interval_adg_kg": "next_adg"})
    rows = add_columns(rows, following, key=key, cardinality="one_to_one", require_match=False)
    valid = rows.previous_weigh_date.eq(rows.landmark_date) & rows.next_weigh_date.eq(rows.horizon)
    rows["next_adg"] = rows.next_adg.where(valid)
    rows["adg_change"] = rows.next_adg - rows.landmark_adg
    return with_entry_band(rows)


def persistent_growth(history, intervals, *, landmark_ranks=True, followup_days=30, quantile=.10):
    """Flag three consecutive low within-lot ranks and retain timing of first treatment.

    The main cutoffs use cattle measured on each stage date. The complete-case
    option reproduces the Phase 2B-2 retrospective ranking population.
    """
    if not 0 < quantile < 1 or followup_days < 1:
        raise ValueError("Expected a quantile fraction and positive follow-up days")
    rows = intervals.loc[intervals.weigh_stage.isin(FOLLOWUP_STAGES) & intervals.interval_adg_kg.notna()].copy()
    ids = rows.groupby("animal_id", observed=True).weigh_stage.nunique()
    complete = ids.index[ids.eq(len(FOLLOWUP_STAGES))]
    if not landmark_ranks:
        rows = rows.loc[rows.animal_id.isin(complete)].copy()
    groups = ["lot_id", "weigh_stage", "weigh_date"] if landmark_ranks else ["lot_id", "weigh_stage"]
    rows["low"] = rows.interval_adg_kg.le(rows.groupby(groups, observed=True).interval_adg_kg
                                        .transform("quantile", q=quantile))
    low = rows.loc[rows.animal_id.isin(complete)].groupby("animal_id").low.all()
    last = rows.loc[rows.weigh_stage.eq("Day 105"), ["animal_id", "weigh_date"]].assign(
        persistent_low=lambda frame: frame.animal_id.map(low)
    ).dropna(subset=["persistent_low"]).rename(columns={"weigh_date": "landmark_date"})
    require_key(last, ("animal_id",), "persistent growth landmark")
    cohort = add_columns(history.loc[history.animal_id.isin(last.animal_id)], last,
                         key=("animal_id",), cardinality="one_to_one")
    cohort["persistent_low"] = cohort.persistent_low.astype(bool)
    cohort["prior_treatment"] = cohort.first_treatment_date.lt(cohort.landmark_date)
    cohort["same_day_first"] = cohort.first_treatment_date.eq(cohort.landmark_date)
    cohort["ever_treated"] = cohort.first_treatment_date.notna()
    horizon = cohort.landmark_date + pd.to_timedelta(followup_days, unit="D")
    cohort["at_risk_next_day"] = cohort.exit_date.gt(cohort.landmark_date)
    cohort["new_first_in_window"] = (
        cohort.first_treatment_date.gt(cohort.landmark_date) & cohort.first_treatment_date.le(horizon)
    )
    cohort["death_in_window"] = (
        cohort.at_risk_next_day & cohort.exit_type.eq(MORTALITY) & cohort.exit_date.le(horizon)
    )
    cohort["sale_in_window"] = (
        cohort.at_risk_next_day & cohort.exit_type.eq(FINISHED) & cohort.exit_date.le(horizon)
    )
    return with_entry_band(cohort)
