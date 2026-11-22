"""Distributional diagnostics from the published diagnostic dataset."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import floor, ceil
from statistics import mean

import pyarrow as pa
import pyarrow.compute as pc

from ..stage1.model import UTC, business_date, midnight
from .reporting import stock_reporting
from .validation import Audit

DAY = timedelta(days=1)


def describe(values):
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}

    def quantile(fraction):
        position = fraction * (len(ordered) - 1)
        low, high = floor(position), ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {key: round(value, 4) for key, value in {
        "n": len(ordered), "min": ordered[0], "p05": quantile(.05), "p25": quantile(.25),
        "median": quantile(.50), "p75": quantile(.75), "p95": quantile(.95),
        "max": ordered[-1], "mean": mean(ordered)}.items()}


def extremes(values, count=3):
    ranked = sorted(values.items(), key=lambda item: (item[1], item[0]))
    tails = {"low": ranked[:count], "high": reversed(ranked[-count:])}
    return {side: [{"animal_id": key, "value": round(value, 4)} for key, value in rows]
            for side, rows in tails.items()}


def summarize(root, tables, runner, daily, monthly, closes):
    data = Audit(root, tables)
    outcomes = {row["animal_id"]: row for row in data.rows("animal_outcomes")}
    status = Counter(row["status"] for row in outcomes.values())
    movements = list(data.rows("movement_events"))
    by_date = Counter(business_date(row["effective_at"]).isoformat()
                      for row in movements if row["kind"] == "receipt")
    receiving = [(row["end_at"] - row["start_at"]) / DAY for row in data.rows("physical_intervals")
                 if runner.yard.kinds[row["location_id"]] == "receiving" and row["end_at"] is not None]
    positions = defaultdict(list)
    peaks, roster = Counter(), Counter()
    reporting_months = {row.period_end.strftime("%Y-%m") for row in monthly}
    peak_yard = 0
    for event in sorted(movements, key=lambda row: (row["effective_at"], row["sequence"])):
        month = business_date(event["effective_at"]).strftime("%Y-%m")
        if event["from_location_id"]:
            roster[event["from_location_id"]] -= 1
        if event["to_location_id"]:
            pen = event["to_location_id"]
            roster[pen] += 1
            peak_yard = max(peak_yard, sum(roster.values()))
            if month in reporting_months:
                peaks[month, pen] = max(peaks[month, pen], roster[pen])
    for row in daily:
        if row.scope_type == "location":
            key = row.period_end.strftime("%Y-%m"), row.scope_id
            positions[key].append(row.closing_head)
            peaks[key] = max(peaks[key], row.opening_head, row.closing_head)
    occupancy = [{"month": month, "pen": pen, "capacity": runner.yard.capacity[pen],
                  "closing_head_daily": describe(values), "peak_any_event_head": peaks[month, pen]}
                 for (month, pen), values in sorted(positions.items())]
    adg, dmi, pct, conversion = {}, {}, {}, {}
    grams, by_phase, stage_days = Counter(), Counter(), Counter()
    day_dm, day_exposure, day_weight_hours = Counter(), Counter(), Counter()
    us_day_cache = {}
    epoch = midnight(runner.first) - (midnight(runner.first) - datetime(1970, 1, 1, tzinfo=UTC))
    for batch in data.batches("growth_operational", columns=[
        "animal_id", "start_at", "elapsed_days", "start_weight_kg", "end_weight_kg",
        "production_stage", "consumed_g_dm",
    ]):
        for key, st_us, elapsed, sw, ew, stage, dm in zip(
            batch.column(0).to_pylist(),
            pc.cast(batch.column(1), pa.int64()).to_pylist(),
            batch.column(2).to_pylist(),
            batch.column(3).to_pylist(),
            batch.column(4).to_pylist(),
            batch.column(5).to_pylist(),
            batch.column(6).to_pylist(),
        ):
            day = us_day_cache.get(st_us)
            if day is None:
                day = business_date(epoch + timedelta(microseconds=st_us))
                us_day_cache[st_us] = day
            grams[key] += dm
            day_dm[key, day] += dm
            day_exposure[key, day] += elapsed
            day_weight_hours[key, day] += elapsed * (sw + ew) / 2
            by_phase[stage] += dm
            stage_days[stage] += elapsed
    for key, row in outcomes.items():
        time = row["simulated_days"]
        gain = row["latent_weight_kg"] - row["entry_weight_kg"]
        if time > 0:
            adg[key] = gain / time
            dmi[key] = grams[key] / 1000 / time
        if gain > 0 and time >= 7:
            conversion[key] = (grams[key] / 1000) / gain
    full_day_pct = [100 * day_dm[key] / 1000 * day_exposure[key] / day_weight_hours[key] for key in day_dm
                    if day_exposure[key] >= 0.95 and day_weight_hours[key] > 0]
    health = list(data.rows("health_events"))
    episodes = {row["episode_id"]: row["animal_id"] for row in health if row["action"] == "onset"}
    episode_by_animal = Counter(episodes.values())
    t = Counter(row["episode_id"] for row in health if row["action"] in {"treatment", "repeat_treatment"})
    death_episode_ids = {row["episode_id"] for row in health if row["action"] == "death"}
    deaths_with_treatment = sum(t[episode] > 0 for episode in death_episode_ids)
    carcass = list(data.rows("carcasses"))
    scale = list(data.rows("weigh_attempts"))
    observations = {row["observation_id"]: row for row in data.rows("weight_observations")}
    samples = list(data.rows("scale_samples_diagnostic"))
    by_kind = defaultdict(Counter)
    for row in scale:
        by_kind[row["kind"]][row["status"]] += 1
    correction_ids = {key for key, row in observations.items() if row["corrects_observation_id"]}
    revised_uses = sum(
        val in correction_ids
        for batch in data.batches("weight_estimates", columns=["last_observation_id"])
        for val in batch.column(0).to_pylist()
    )
    error = defaultdict(list)
    for row in samples:
        ticket = observations[row["observation_id"]]
        error[ticket["kind"]].append(ticket["measured_weight_kg"] - row["latent_kg"])
    feed = Counter()
    for row in data.rows("feed_cost_bridge"):
        feed.update({key: value for key, value in row.items() if key.endswith(("_cents", "_g_af", "_g_dm"))})
    mix_loss, distribution, refusals = [], [], []
    for row in data.rows("mixes"):
        mix_loss.append(100 * row["loss"]["g_af"] / row["input"]["g_af"])
    delivered = {}
    for row in data.rows("feed_deliveries", columns=["delivery_id", "loaded", "delivered", "delivery_loss"]):
        distribution.append(100 * row["delivery_loss"]["g_af"] / row["loaded"]["g_af"])
        delivered[row["delivery_id"]] = row["delivered"]["g_af"]
    for row in data.rows("bunk_settlements", columns=["delivery_id", "refusal"]):
        if grams_af := delivered[row["delivery_id"]]:
            refusals.append(100 * row["refusal"]["g_af"] / grams_af)
    lots_sold = defaultdict(set)
    for row in data.rows("shipment_lines"):
        lots_sold[row["lot_id"]].add(row["shipment_id"])
    wh_bridges = list(data.rows("warehouse_af_bridge"))
    last = midnight(runner.last + DAY)
    wh_month = {name: sum(row[name] for row in wh_bridges if row["period_end"] == last)
                for name in ("closing_g_af", "closing_cents")}
    wh_in = {"opening_g_af": sum(row["opening_g_af"] for row in wh_bridges
                                if row["period_start"] == runner.start),
             **{name: sum(row[name] for row in wh_bridges)
                for name in ("receipt_g_af", "issue_g_af", "spoilage_g_af", "receipt_cents", "issue_cents")}}
    utilization = [{"bin_id": row["bin_id"], "peak_g_af": runner.supply.max_bin[row["bin_id"]],
                    "capacity_g_af": row["capacity_g_af"]} for row in data.rows("warehouse_bins")]
    exceptions = Counter(row["reason"] for row in data.rows("exceptions"))
    sources = {key: sum(part["rows"] for part in tables.values() if part["table"] == key) for key in (
        "movement_events", "health_events", "warehouse_transactions", "weight_observations", "packer_settlements",
        "financial_sources", "feed_allocations", "accounting_feed_allocations", "journal_lines")}
    revenue = [close[6] for view, close in closes if view == "as_known"]
    totals = {field: sum(getattr(row, field) for row in revenue) for field in (
        "net_sales_cents", "sales_cogs_cents", "sales_gross_margin_cents", "mortality_burden_cents",
        "modeled_yard_contribution_cents", "feed_operating_variance_cents")}
    settled = list(data.rows("packer_settlements"))
    totals["final_packer_value_cents"] = sum(row["final_cents"] for row in settled)
    totals["closing_wip_cents"] = revenue[-1].closing_wip_cents
    return {
        "placements_by_date": by_date,
        "stock_reporting": stock_reporting(monthly, (row["status"] for row in outcomes.values())),
        "peak_concurrent_inventory": peak_yard,
        "head": {"placements": sum(by_date.values()), "opening": len(runner.yard.opening),
                 "carry_out": status["active"], "sale": status["sold"], "death": status["dead"]},
        "yard_soh": [row for row in monthly if row.scope_type == "yard"], "occupancy": occupancy,
        "receiving_elapsed_days": describe(receiving),
        "animal_days": sum(row.animal_days for row in monthly if row.scope_type == "yard"),
        "adg_kg_per_elapsed_day": describe(adg.values()), "dmi_kg_per_elapsed_day": describe(dmi.values()),
        "dmi_pct_bw_full_days": describe(full_day_pct),
        "feed_conversion_kg_dm_per_kg_gain": describe(conversion.values()),
        "feed_conversion_excluded": len(outcomes) - len(conversion),
        "dmi_kg_per_elapsed_day_by_phase": {stage: round(by_phase[stage] / 1000 / days, 4)
                                            for stage, days in sorted(stage_days.items())},
        "outliers": {"adg": extremes(adg), "dmi": extremes(dmi), "feed_conversion": extremes(conversion)},
        "health": {"episodes": len(episodes), "affected_animals": len(episode_by_animal),
                   "repeat_episode_animals": sum(value > 1 for value in episode_by_animal.values()),
                   "repeat_treatment_services": sum(row["action"] == "repeat_treatment" for row in health),
                   "episodes_with_repeat_treatment": sum(value > 1 for value in t.values()),
                   "deaths_with_treatment_in_episode": deaths_with_treatment,
                   "deaths_without_treatment_in_episode": status["dead"] - deaths_with_treatment,
                   "actions": Counter(row["action"] for row in health)},
        "scale": {"by_kind": dict(by_kind), "ticket_error_kg": {key: describe(values) for key, values in error.items()},
                  "late_corrections": len(correction_ids), "decision_estimates_using_correction": revised_uses},
        "carcass": {"shipment_groups": len({value for rows in lots_sold.values() for value in rows}),
                    "sale_lots_with_multiple_shipments": sum(len(rows) > 1 for rows in lots_sold.values()),
                    "sale_dof": describe(row["days_on_feed"] for row in outcomes.values() if row["status"] == "sold"),
                    "measured_liveweight_kg": describe(row["measured_liveweight_kg"] for row in carcass
                                                      if row["measured_liveweight_kg"] is not None),
                    "latent_exit_liveweight_kg": describe(row["latent_exit_liveweight_kg"] for row in carcass),
                    "hcw_kg": describe(row["hcw_kg"] for row in carcass),
                    "dressing_pct": describe(100 * row["dressing_fraction"] for row in carcass),
                    "quality_grade": Counter(row["quality_grade"] or "missing" for row in carcass),
                    "yield_class": Counter(row["yield_class"] or "missing" for row in carcass),
                    "final_cents_per_kg_hcw": describe(row["final_cents_per_kg_hcw"] for row in settled)},
        "feed_bunk_and_cost_totals": feed,
        "loss_pct_as_fed": {"mix": describe(mix_loss), "distribution": describe(distribution),
                             "refusal": describe(refusals)},
        "warehouse": {**wh_month, **wh_in, "bins": utilization},
        "finance_horizon": totals, "exceptions": exceptions, "source_and_fact_counts": sources,
    }
