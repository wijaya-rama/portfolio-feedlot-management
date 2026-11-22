"""Independent hard gates over the published partition grain and source crosswalks.

Supports two clearly identified validation modes:
- ``full`` (via ``reconcile`` / ``reconcile_with_mode(..., mode="full")``):
  Complete independent disk-based audit across all partitions, ledgers,
  fingerprints, and cross-domain invariants. Required for all published candidates.
- ``incremental`` (via ``reconcile_incremental`` / ``reconcile_with_mode(..., mode="incremental")``):
  Targeted validation of changed monthly partitions and their dependent
  cross-period balances/closes. Explicitly reports ``complete_independent_audit: False``
  and must never be treated as a substitute for full independent validation.
"""

from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from math import isclose

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..stage1.model import UTC, business_date, midnight
from ..stage1.soh import StockRow
from ..stage3.units import BPS, half_up
from ..stage4.ledger import Account
from .close_index import OrderedFingerprints, canonical_journal_from_columns
from .config import SCHEMA
from .export import digest as file_digest_sha256
from .reporting import stock_reporting

AMOUNTS = ("g_af", "g_dm", "kj", "cp_g", "cents")
NUTRIENTS = ("g_dm", "energy_kj", "cp_g")
_EPOCH_DT = datetime(1970, 1, 1, tzinfo=UTC)
_NORMAL_FEED_COMPONENTS = frozenset({"feed_consumption", "mix_normal", "distribution_normal", "refusal_normal"})

_JOURNAL_COLUMNS = [
    "accounting_month", "amount_cents", "animal_id", "approval_id", "available_at",
    "component", "credit_account", "debit_account", "document_id", "effective_at",
    "journal_id", "ledger_version", "line_id", "location_id", "lot_id",
    "outcome_event_id", "period_routing_at", "policy_version", "pool_id", "posted_at",
    "principal_release", "restatement_approval_id", "reverses_journal_id",
    "service_date", "source_id", "source_posted_at", "source_snapshot_id",
    "source_system", "yard_id",
]


def _dt_to_us(value):
    if value is None:
        return None
    if value.tzinfo is not UTC:
        value = value.astimezone(UTC)
    delta = value - _EPOCH_DT
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _ts_us_list(column):
    return pc.cast(column, pa.int64()).to_pylist()


def _ts_us_np(column):
    return pc.cast(column, pa.int64()).to_numpy(zero_copy_only=False)


def _date_days_list(column):
    return pc.cast(column, pa.int32()).to_pylist()


class Audit:
    def __init__(self, root, tables):
        self.root = root
        self.parts = defaultdict(list)
        for name, row in sorted(tables.items()):
            self.parts[row["table"]].append((row["month"], name))
        self.checks = {}

    def batches(self, table, month=None, columns=None):
        for period, path in self.parts[table]:
            if month is None or period == month:
                yield from pq.ParquetFile(self.root / path).iter_batches(batch_size=8192, columns=columns)

    def rows(self, table, month=None, columns=None):
        for batch in self.batches(table, month=month, columns=columns):
            yield from batch.to_pylist()

    def check(self, key, valid, detail=""):
        result = self.checks.setdefault(key, {"passed": True, "assertions": 0})
        result["assertions"] += 1
        if not valid:
            raise ValueError(f"Stage 6A gate {key} failed: {detail}")

    def check_many(self, key, count, valid, detail=""):
        if count <= 0:
            return
        result = self.checks.setdefault(key, {"passed": True, "assertions": 0})
        result["assertions"] += count
        if not valid:
            raise ValueError(f"Stage 6A gate {key} failed: {detail}")

    def index(self, rows, key, table):
        result = {}
        entry = self.checks.setdefault("primary_keys", {"passed": True, "assertions": 0})
        if callable(key):
            for row in rows:
                identifier = key(row)
                entry["assertions"] += 1
                if identifier is None or identifier in result:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {(table, identifier)}")
                result[identifier] = row
        else:
            for row in rows:
                identifier = row[key]
                entry["assertions"] += 1
                if identifier is None or identifier in result:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {(table, identifier)}")
                result[identifier] = row
        return result


def vector(row, fields):
    return tuple(row[key] for key in fields)


def bridge(row, source, *targets):
    return all(row[source][field] == sum(row[key][field] for key in targets) for field in AMOUNTS)


def audit_movements(audit, runner, replay, daily, monthly):
    outcomes = audit.index(audit.rows("animal_outcomes"), "animal_id", "outcomes")
    animals = audit.index(audit.rows("animals"), "animal_id", "animals")
    lots = audit.index(audit.rows("lots"), "lot_id", "lots")
    locations = audit.index(audit.rows("locations"), "location_id", "locations")
    events = audit.index(audit.rows("movement_events"), "event_id", "movements")
    audit.check("foreign_keys", all(row["lot_id"] in lots for row in animals.values()), "animal-to-lot")
    audit.check("movement_replay", len(events) == len(replay.events), "movement transcript")
    profiles = audit.index(audit.rows("animal_profiles"), "animal_id", "profiles")
    states = {row.animal_id: row for row in replay.states if row.animal_id in profiles}
    placements = list(audit.rows("placement_requests"))
    opening = audit.index(audit.rows("opening_cattle"), "animal_id", "opening cattle")
    receipt_count = sum(row["kind"] == "receipt" for row in events.values())
    audit.check("placement_disposition", receipt_count + len(runner.yard.pending) == len(placements),
                "each scheduled placement received or explicitly open")
    audit.check("outcomes", set(outcomes) == set(profiles) == set(states), "one terminal record per entry")
    audit.check("outcomes", all((row.status, row.location_id) == (outcomes[key]["status"], outcomes[key]["location_id"])
                                for key, row in states.items()), "closing state")
    enter, exit_at = {}, {}
    pen = Counter()
    for event in sorted(events.values(), key=lambda row: (row["effective_at"], row["sequence"])):
        key, kind = event["animal_id"], event["kind"]
        audit.check("foreign_keys", key in animals, key)
        origin, destination = event["from_location_id"], event["to_location_id"]
        if origin:
            audit.check("yard_capacity", pen[origin] > 0, event["event_id"])
            pen[origin] -= 1
        if destination:
            pen[destination] += 1
            audit.check("yard_capacity", destination in locations and
                        pen[destination] <= locations[destination]["capacity_head"], event["event_id"])
        if kind in {"receipt", "opening"}:
            enter[key] = event["effective_at"]
        if kind in {"sale", "death"}:
            exit_at[key] = event["effective_at"]
    by_date = Counter()
    for batch in audit.batches("yardage", columns=["date"]):
        by_date.update(batch.column(0).to_pylist())
    for row in daily:
        if row.scope_type == "yard":
            audit.check("animal_days", row.animal_days == by_date[row.period_start] == runner.daily_active[row.period_start],
                        row.period_start)
            audit.check("stock_equation", row.transfers_in == row.transfers_out == 0 and
                        row.opening_head + row.receipts - row.sales - row.deaths == row.closing_head, row.period_start)
    published = [StockRow(**{key: value for key, value in row.items() if key != "run_id"})
                 for row in audit.rows("monthly_soh") if row["scope_type"] == "yard"]
    period_rows = [row for row in monthly if row.scope_type == "yard"]
    audit.check("period_end_stock_reporting", published == period_rows)
    reported = stock_reporting(published, (row["status"] for row in outcomes.values()))
    audit.check("final_simulation_stock_reporting", reported["final_simulation_soh"] == sum(pen.values()))
    audit.check("opening_wip_sources", len(opening) == sum(row["kind"] == "opening" for row in events.values())
                and all(row["wip_cents"] > 0 and row["status"] == "active" for row in opening.values()))
    return animals, events, enter, exit_at, outcomes


def audit_observations(audit, events, enter, exit_at):
    obs = audit.index(audit.rows("weight_observations"), "observation_id", "observations")
    contexts = audit.index(audit.rows("physical_contexts"), "snapshot_id", "physical context")
    anchors = defaultdict(list)
    for row in obs.values():
        key = row["animal_id"]
        instant = row["measured_at"]
        audit.check("weighing_chronology", enter[key] <= instant <= exit_at.get(key, instant)
                    and instant <= row["posted_at"] <= row["available_at"]
                    and row["physical_snapshot_id"] in contexts, row["observation_id"])
        if row["kind"] == "final_sale":
            linked = events[row["movement_event_id"]]
            audit.check("terminal_scale", linked["kind"] == "sale" and instant == linked["effective_at"], key)
        else:
            anchors[key].append(row)
        if previous := row["corrects_observation_id"]:
            old = obs[previous]
            audit.check("immutable_scale_revision", old["animal_id"] == key and old["measured_at"] == instant
                        and old["available_at"] < row["available_at"] and row["source_event_id"] != old["source_event_id"],
                        row["observation_id"])
    attempts = audit.index(audit.rows("weigh_attempts"), "source_event_id", "attempts")
    for row in attempts.values():
        audit.check("scale_attempt_link", ((row["status"] == "measured") == (row["observation_id"] in obs))
                    and row["physical_snapshot_id"] in contexts, row["source_event_id"])
    health = audit.index(audit.rows("health_events"), "health_event_id", "health")
    for row in health.values():
        key = row["animal_id"]
        audit.check("health_event_time", enter[key] <= row["effective_at"] <= exit_at.get(key, row["effective_at"])
                    and row["effective_at"] <= row["posted_at"] <= row["available_at"]
                    and (row["action"] == "onset") != row["operational_visible"], row["health_event_id"])
        if prior := row["previous_health_event_id"]:
            old = health[prior]
            audit.check("health_episode_link", old["episode_id"] == row["episode_id"]
                        and old["effective_at"] <= row["effective_at"])
        if link := row["movement_event_id"]:
            audit.check("health_movement_link", events[link]["animal_id"] == key
                        and events[link]["effective_at"] == row["effective_at"])
    for sample in audit.rows("scale_samples_diagnostic"):
        ticket = obs[sample["observation_id"]]
        precision = sample["precision_kg"]
        simulated = round(round((sample["latent_kg"] + sample["scale_bias_kg"] +
                                 sample["measurement_error_kg"]) / precision) * precision, 6)
        audit.check("measured_vs_latent", simulated == ticket["measured_weight_kg"]
                    and sample["physical_snapshot_id"] == ticket["physical_snapshot_id"])
    return obs, anchors, health


def audit_feeding(audit, months, events, enter, exit_at, anchors, health, runner):
    actual_intervals = {}
    for row in audit.rows("physical_intervals"):
        actual_intervals.setdefault(row["start_event_id"], (
            row["animal_id"], row["location_id"], _dt_to_us(row["start_at"]), _dt_to_us(row["end_at"]),
        ))
    recipes = audit.index(audit.rows("ration_versions"), "record_id", "rations")
    equipment = audit.index(audit.rows("warehouse_equipment"), "record_id", "equipment")
    planning = runner.feeding.planning
    enter_us = {key: _dt_to_us(val) for key, val in enter.items()}
    exit_us = {key: _dt_to_us(val) for key, val in exit_at.items()}
    events_avail_us = {key: (_dt_to_us(row["available_at"]), row["to_location_id"]) for key, row in events.items()}
    health_avail_us = {key: (_dt_to_us(row["available_at"]), row["operational_visible"]) for key, row in health.items()}
    anchors_us = {
        key: [(_dt_to_us(obs["measured_at"]), _dt_to_us(obs["available_at"]), obs["observation_id"]) for obs in rows]
        for key, rows in anchors.items()
    }
    pk_entry = audit.checks.setdefault("primary_keys", {"passed": True, "assertions": 0})
    elig_entry = audit.checks.setdefault("feed_eligibility", {"passed": True, "assertions": 0})
    frozen_entry = audit.checks.setdefault("frozen_feed_input", {"passed": True, "assertions": 0})
    ttp_entry = audit.checks.setdefault("timed_to_posting_allocation", {"passed": True, "assertions": 0})

    for month in months:
        plans = audit.index(audit.rows("feed_plans", month), "plan_id", "feed plan")
        snapshots = audit.index(audit.rows("decision_snapshots", month), "snapshot_id", "decision snapshot")
        delivery = audit.index(audit.rows("feed_deliveries", month), "delivery_id", "delivery")
        mixes = audit.index(audit.rows("mixes", month), "mix_id", "mix")
        settled = audit.index(audit.rows("bunk_settlements", month), "settlement_id", "settlement")
        access = audit.index(audit.rows("feed_access_snapshots", month), "access_snapshot_id", "access snapshot")

        warehouse_issues = {}
        for batch in audit.batches("warehouse_entries", month, ["entry_id", "kind", "g_af", "g_dm", "cents"]):
            for eid, kind, gaf, gdm, cents in zip(
                batch.column(0).to_pylist(), batch.column(1).to_pylist(),
                batch.column(2).to_pylist(), batch.column(3).to_pylist(), batch.column(4).to_pylist(),
            ):
                if kind == "issue":
                    pk_entry["assertions"] += 1
                    if eid is None or eid in warehouse_issues:
                        raise ValueError(f"Stage 6A gate primary_keys failed: {('issue entries', eid)}")
                    warehouse_issues[eid] = (gaf, gdm, cents)

        snap_cutoff_us = {k: _dt_to_us(v["knowledge_cutoff"]) for k, v in snapshots.items()}
        estimates_clinical = {}
        nfe_entry = audit.checks.setdefault("no_future_estimates", {"passed": True, "assertions": 0})
        nfh_entry = audit.checks.setdefault("no_future_health", {"passed": True, "assertions": 0})
        for batch in audit.batches("weight_estimates", month, [
            "estimate_id", "animal_id", "snapshot_id", "location_event_id", "location_id",
            "last_observation_id", "health_event_id", "clinical_status",
            "knowledge_cutoff", "effective_before", "estimate_for",
        ]):
            for est_id, key, snap_id, loc_ev, loc_id, last_obs, h_ev, clin, cut_us, eff_us, for_us in zip(
                batch.column(0).to_pylist(), batch.column(1).to_pylist(), batch.column(2).to_pylist(),
                batch.column(3).to_pylist(), batch.column(4).to_pylist(), batch.column(5).to_pylist(),
                batch.column(6).to_pylist(), batch.column(7).to_pylist(),
                _ts_us_list(batch.column(8)), _ts_us_list(batch.column(9)), _ts_us_list(batch.column(10)),
            ):
                pk_entry["assertions"] += 1
                if est_id is None or est_id in estimates_clinical:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {('estimate', est_id)}")
                estimates_clinical[est_id] = clin
                old = None
                for cand in anchors_us.get(key, ()):
                    if cand[0] < cut_us and cand[1] <= cut_us:
                        if old is None or cand > old:
                            old = cand
                inc_avail, inc_loc = events_avail_us[loc_ev]
                nfe_entry["assertions"] += 1
                if not (last_obs == (old[2] if old else None)
                        and snap_cutoff_us[snap_id] == cut_us == eff_us == for_us
                        and inc_avail <= cut_us and inc_loc == loc_id):
                    raise ValueError(f"Stage 6A gate no_future_estimates failed: {est_id}")
                if h_ev:
                    h_avail, h_vis = health_avail_us[h_ev]
                    nfh_entry["assertions"] += 1
                    if not (h_avail <= cut_us and h_vis):
                        raise ValueError(f"Stage 6A gate no_future_health failed: {est_id}")

        weight_meta = {}
        weights_by_pen = defaultdict(list)
        for batch in audit.batches("feeding_weight_inputs", month, [
            "weight_input_id", "estimate_id", "estimate_snapshot_id", "roster_pen_id",
            "production_stage", "score_weight_g", "cutoff",
        ]):
            for wid, est_id, snap_id, pen_id, stage, score_g, cut_us in zip(
                batch.column(0).to_pylist(), batch.column(1).to_pylist(), batch.column(2).to_pylist(),
                batch.column(3).to_pylist(), batch.column(4).to_pylist(), batch.column(5).to_pylist(),
                _ts_us_list(batch.column(6)),
            ):
                pk_entry["assertions"] += 1
                if wid is None or wid in weight_meta:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {('feed weight', wid)}")
                weight_meta[wid] = (est_id, cut_us, pen_id)
                weights_by_pen[snap_id, pen_id].append((stage, score_g, est_id))

        exposure_meta = {}
        for batch in audit.batches("feed_exposures", month, [
            "exposure_id", "animal_id", "movement_in_id", "first_at", "end_at",
        ]):
            for eid, key, mov_in, first_us, end_us in zip(
                batch.column(0).to_pylist(), batch.column(1).to_pylist(), batch.column(2).to_pylist(),
                _ts_us_list(batch.column(3)), _ts_us_list(batch.column(4)),
            ):
                pk_entry["assertions"] += 1
                if eid is None or eid in exposure_meta:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {('feed exposure', eid)}")
                exposure_meta[eid] = (key, first_us, end_us, actual_intervals[mov_in])

        for row in plans.values():
            members = weights_by_pen[row["decision_snapshot_id"], row["pen_id"]]
            stages = set(recipes[row["ration_version_id"]]["eligible_stages"].split(","))
            target = sum(min(planning["stage_dm_g_per_window"][stage],
                             score_g * planning["intake_limit_bps_per_window"] // BPS)
                         * planning["clinical_intake_bps"].get(estimates_clinical[est_id], BPS)
                         // BPS for stage, score_g, est_id in members)
            audit.check("ration_and_plan", row["known_head"] == len(members)
                        and target == row["planned_g_dm"] and all(stage in stages for stage, _, _ in members),
                        row["plan_id"])
        inputs = defaultdict(Counter)
        issue_links = set()
        for row in audit.rows("mix_inputs", month):
            key = row["layer_entry_id"]
            src_af, src_dm, src_cents = warehouse_issues[key]
            audit.check("fifo_issue_to_mix", key not in issue_links and row["amount"]["g_af"] == -src_af
                        and row["amount"]["g_dm"] == -src_dm
                        and row["amount"]["cents"] == -src_cents, key)
            issue_links.add(key)
            inputs[row["mix_id"]].update(row["amount"])
        audit.check("fifo_issue_to_mix", issue_links == set(warehouse_issues))
        for row in mixes.values():
            audit.check("mix_conservation", bridge(row, "input", "produced", "loss")
                        and inputs[row["mix_id"]] == row["input"] and
                        row["input"]["g_af"] <= equipment[row["mixer_version_id"]]["capacity_g_af"], row["mix_id"])
        for row in delivery.values():
            plan, mix = plans[row["plan_id"]], mixes[row["mix_id"]]
            audit.check("delivery_conservation", bridge(row, "loaded", "delivered", "delivery_loss")
                        and row["loaded"] == mix["produced"]
                        and row["loaded"]["g_af"] <= equipment[row["truck_version_id"]]["capacity_g_af"], row["delivery_id"])
            audit.check("dispatch_time", row["window_start"] == plan["decision_at"]
                        and row["window_end"] == plan["window_end"] and row["pen_id"] == plan["pen_id"])
        for row in settled.values():
            proof = access[row["access_snapshot_id"]]
            audit.check("settlement_trace", proof["knowledge_cutoff"] == row["available_at"]
                        and row["decision_snapshot_id"] in snapshots, row["settlement_id"])
            enclosing = {**row, "delivered": delivery[row["delivery_id"]]["delivered"]}
            audit.check("bunk_conservation", bridge(enclosing, "delivered", "modeled_consumption", "refusal", "bunk_loss"),
                        row["settlement_id"])

        posting_meta = {}
        for batch in audit.batches("accounting_feed_allocations", month, [
            "allocation_id", "animal_id", "settlement_id", "access_start", "access_end",
            "g_dm", "energy_kj", "cp_g", "cents", "duration_seconds",
        ]):
            for pid, key, sid, st_us, en_us, dm, ej, cp, cents, dur in zip(
                batch.column(0).to_pylist(), batch.column(1).to_pylist(), batch.column(2).to_pylist(),
                _ts_us_list(batch.column(3)), _ts_us_list(batch.column(4)),
                batch.column(5).to_pylist(), batch.column(6).to_pylist(), batch.column(7).to_pylist(),
                batch.column(8).to_pylist(), batch.column(9).to_pylist(),
            ):
                pk_entry["assertions"] += 1
                if pid is None or pid in posting_meta:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {('posting allocation', pid)}")
                posting_meta[pid] = (key, sid, st_us, en_us, (dm, ej, cp, cents, dur))

        links = {}
        for batch in audit.batches("posting_allocation_links", month, ["release_allocation_id", "posting_allocation_id"]):
            rids = batch.column(0).to_pylist()
            pids = batch.column(1).to_pylist()
            for rid, pid in zip(rids, pids):
                pk_entry["assertions"] += 1
                if rid is None or rid in links:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {('release crosswalk', rid)}")
                links[rid] = pid

        plan_by_delivery = {}
        for did, drow in delivery.items():
            prow = plans[drow["plan_id"]]
            plan_by_delivery[did] = (
                _dt_to_us(prow["window_start"]), _dt_to_us(prow["window_end"]), _dt_to_us(prow["decision_at"]),
            )

        estimates = estimates_clinical

        posting_amounts = {}
        unique = set()
        by_settlement = {}
        flows = {}
        for batch in audit.batches("feed_allocations", month, [
            "allocation_id", "animal_id", "pen_id", "access_start", "access_end", "weight_input_id",
            "exposure_id", "delivery_id", "estimate_id", "decision_cutoff", "settlement_id",
            "duration_seconds", "window_start", "cents", "g_dm", "energy_kj", "cp_g",
        ]):
            a_ids = batch.column(0).to_pylist()
            animals_c = batch.column(1).to_pylist()
            pens_c = batch.column(2).to_pylist()
            starts_us = _ts_us_list(batch.column(3))
            ends_us = _ts_us_list(batch.column(4))
            w_ids = batch.column(5).to_pylist()
            e_ids = batch.column(6).to_pylist()
            d_ids = batch.column(7).to_pylist()
            est_ids = batch.column(8).to_pylist()
            cutoffs_us = _ts_us_list(batch.column(9))
            s_ids = batch.column(10).to_pylist()
            durs = batch.column(11).to_pylist()
            ws_us = _ts_us_list(batch.column(12))
            cents_c = batch.column(13).to_pylist()
            dms = batch.column(14).to_pylist()
            ejs = batch.column(15).to_pylist()
            cps = batch.column(16).to_pylist()
            for (identifier, key, pen, first, last, wid, eid, did, est_id, dec_cutoff,
                 sid, dur, wstart, cents, dm, ej, cp) in zip(
                a_ids, animals_c, pens_c, starts_us, ends_us, w_ids, e_ids, d_ids, est_ids,
                cutoffs_us, s_ids, durs, ws_us, cents_c, dms, ejs, cps,
            ):
                pk_entry["assertions"] += 1
                if identifier in unique:
                    raise ValueError(f"Stage 6A gate primary_keys failed: {('feed allocation', identifier)}")
                unique.add(identifier)
                w_est_id, w_cutoff, w_pen = weight_meta[wid]
                exp_animal, exp_first, exp_end, (int_animal, int_loc, int_start, int_end) = exposure_meta[eid]
                p_wstart, p_wend, p_decision = plan_by_delivery[did]
                ex_us = exit_us.get(key)
                elig_entry["assertions"] += 1
                if not (first < last and enter_us[key] <= first
                        and (ex_us is None or last <= ex_us) and int_loc == pen
                        and int_animal == key and int_start <= first
                        and (int_end is None or last <= int_end) and exp_animal == key
                        and exp_first <= first < last <= exp_end
                        and p_wstart <= first < last <= p_wend):
                    raise ValueError(f"Stage 6A gate feed_eligibility failed: {identifier}")
                frozen_entry["assertions"] += 1
                if not (est_id == w_est_id and w_est_id in estimates
                        and dec_cutoff == w_cutoff == p_decision
                        and dec_cutoff <= first and w_pen == pen):
                    raise ValueError(f"Stage 6A gate frozen_feed_input failed: {identifier}")
                pid = links[identifier]
                p_animal, p_sid, p_start, p_end, _ = posting_meta[pid]
                ttp_entry["assertions"] += 1
                if not (p_animal == key and p_sid == sid and p_start <= first < last <= p_end):
                    raise ValueError(f"Stage 6A gate timed_to_posting_allocation failed: {identifier}")
                acc = posting_amounts.get(pid)
                if acc is None:
                    posting_amounts[pid] = [dm, ej, cp, cents, dur]
                else:
                    acc[0] += dm
                    acc[1] += ej
                    acc[2] += cp
                    acc[3] += cents
                    acc[4] += dur
                s_acc = by_settlement.get(sid)
                if s_acc is None:
                    by_settlement[sid] = [dm, ej, cp, cents]
                else:
                    s_acc[0] += dm
                    s_acc[1] += ej
                    s_acc[2] += cp
                    s_acc[3] += cents
                fk = (key, pen, wstart)
                f_acc = flows.get(fk)
                if f_acc is None:
                    flows[fk] = [dm, ej, cp]
                else:
                    f_acc[0] += dm
                    f_acc[1] += ej
                    f_acc[2] += cp

        audit.check("timed_to_posting_allocation", unique == set(links))
        for pid, (_, _, _, _, expected_vec) in posting_meta.items():
            actual = posting_amounts.get(pid)
            audit.check("timed_to_posting_allocation", (tuple(actual) if actual else (0, 0, 0, 0, 0)) == expected_vec, pid)
        for key, row in settled.items():
            pool = row["modeled_consumption"]
            actual = by_settlement.get(key)
            audit.check("allocation_conservation", (tuple(actual) if actual else (0, 0, 0, 0))
                        == (pool["g_dm"], pool["kj"], pool["cp_g"], pool["cents"]), key)

        res_entry = audit.checks.setdefault("biological_reserve_balance", {"passed": True, "assertions": 0})
        gt_entry = audit.checks.setdefault("growth_time", {"passed": True, "assertions": 0})
        for path in ("operational", "retrospective") if runner.retro else ("operational",):
            growth = {}
            is_op = (path == "operational")
            for batch in audit.batches(f"growth_{path}", month, [
                "animal_id", "location_id", "window_start_at", "consumed_g_dm", "energy_mj",
                "protein_kg", "starting_me_mj", "maintenance_used_me_mj", "gain_used_me_mj",
                "ending_me_mj", "excess_me_mj", "starting_cp_kg", "cp_maintenance_used_kg",
                "cp_gain_used_kg", "ending_cp_kg", "excess_cp_kg", "start_at", "end_at", "weather_kind",
            ]):
                n = batch.num_rows
                if not n:
                    continue
                e_mj = batch.column(4).to_numpy(zero_copy_only=False)
                p_kg = batch.column(5).to_numpy(zero_copy_only=False)
                s_me = batch.column(6).to_numpy(zero_copy_only=False)
                m_me = batch.column(7).to_numpy(zero_copy_only=False)
                g_me = batch.column(8).to_numpy(zero_copy_only=False)
                end_me = batch.column(9).to_numpy(zero_copy_only=False)
                exc_me = batch.column(10).to_numpy(zero_copy_only=False)
                s_cp = batch.column(11).to_numpy(zero_copy_only=False)
                m_cp = batch.column(12).to_numpy(zero_copy_only=False)
                g_cp = batch.column(13).to_numpy(zero_copy_only=False)
                end_cp = batch.column(14).to_numpy(zero_copy_only=False)
                exc_cp = batch.column(15).to_numpy(zero_copy_only=False)

                me_lhs = s_me + e_mj
                me_rhs = m_me + g_me + end_me + exc_me
                cp_lhs = s_cp + p_kg
                cp_rhs = m_cp + g_cp + end_cp + exc_cp
                # Exact math.isclose semantics: |a - b| <= max(1e-9 * max(|a|, |b|), abs_tol)
                me_ok = np.abs(me_lhs - me_rhs) <= np.maximum(1e-9 * np.maximum(np.abs(me_lhs), np.abs(me_rhs)), 1e-8)
                cp_ok = np.abs(cp_lhs - cp_rhs) <= np.maximum(1e-9 * np.maximum(np.abs(cp_lhs), np.abs(cp_rhs)), 1e-9)
                res_entry["assertions"] += n
                if not (bool(np.all(me_ok)) and bool(np.all(cp_ok))):
                    bad = int(np.flatnonzero(~(me_ok & cp_ok))[0])
                    raise ValueError(f"Stage 6A gate biological_reserve_balance failed: {(path, batch.column(0)[bad].as_py())}")

                start_us_np = _ts_us_np(batch.column(16))
                end_us_np = _ts_us_np(batch.column(17))
                order_ok = bool(np.all(start_us_np < end_us_np))
                weather_ok = True
                if is_op:
                    weather_ok = pc.all(pc.not_equal(batch.column(18), "archive_reanalysis")).as_py() is not False
                animals_c = batch.column(0).to_pylist()
                start_us_l = start_us_np.tolist()
                end_us_l = end_us_np.tolist()
                gt_entry["assertions"] += n
                if not (order_ok and weather_ok):
                    raise ValueError(f"Stage 6A gate growth_time failed: {(path, month)}")
                for key, st, en in zip(animals_c, start_us_l, end_us_l):
                    ex = exit_us.get(key)
                    if not (enter_us[key] <= st and (ex is None or en <= ex)):
                        raise ValueError(f"Stage 6A gate growth_time failed: {(path, key)}")

                ws_col = batch.column(2)
                if ws_col.null_count < n:
                    valid_mask = pc.is_valid(ws_col)
                    if ws_col.null_count > 0:
                        f_animals = pc.filter(batch.column(0), valid_mask).to_pylist()
                        f_locs = pc.filter(batch.column(1), valid_mask).to_pylist()
                        f_ws = _ts_us_list(pc.filter(ws_col, valid_mask))
                        f_dm = pc.filter(batch.column(3), valid_mask).to_pylist()
                        f_emj = pc.filter(batch.column(4), valid_mask).to_pylist()
                        f_pkg = pc.filter(batch.column(5), valid_mask).to_pylist()
                    else:
                        f_animals = animals_c
                        f_locs = batch.column(1).to_pylist()
                        f_ws = _ts_us_list(ws_col)
                        f_dm = batch.column(3).to_pylist()
                        f_emj = e_mj.tolist()
                        f_pkg = p_kg.tolist()
                    for key, loc, ws, dm, em, pk in zip(f_animals, f_locs, f_ws, f_dm, f_emj, f_pkg):
                        gk = (key, loc, ws)
                        g_acc = growth.get(gk)
                        ej = round(em * 1000)
                        cp = round(pk * 1000)
                        if g_acc is None:
                            growth[gk] = [dm, ej, cp]
                        else:
                            g_acc[0] += dm
                            g_acc[1] += ej
                            g_acc[2] += cp
            audit.check("feed_to_biology", all(growth.get(k, [0, 0, 0]) == flows.get(k, [0, 0, 0])
                                               for k in growth.keys() | flows.keys()), (month, path))


def audit_finance(audit, closes, outcomes, *, check_months=None):
    sources = {}
    pk_entry = audit.checks.setdefault("primary_keys", {"passed": True, "assertions": 0})
    for batch in audit.batches("financial_sources", columns=["source_id", "available_at"]):
        sids = batch.column(0).to_pylist()
        avails = _ts_us_list(batch.column(1))
        for key, avail in zip(sids, avails):
            pk_entry["assertions"] += 1
            if key in sources:
                raise ValueError(f"Stage 6A gate primary_keys failed: {('financial source', key)}")
            sources[key] = avail

    timing_entry = audit.checks.setdefault("finance_source_timing", {"passed": True, "assertions": 0})
    for batch in audit.batches("financial_source_links", columns=["source_id", "parent_id"]):
        children = batch.column(0).to_pylist()
        parents = batch.column(1).to_pylist()
        timing_entry["assertions"] += len(children)
        for child_id, parent_id in zip(children, parents):
            if sources[parent_id] > sources[child_id]:
                raise ValueError(f"Stage 6A gate finance_source_timing failed: {child_id}")

    published = audit.index(audit.rows("finance_snapshots"), "close_id", "financial snapshot")
    audit.check("snapshot_publication", len(published) == len(closes))
    by_view = {}
    for _, result in closes:
        snap = result[0]
        row = published[snap.close_id]
        audit.check("snapshot_publication", all(row[key] == value for key, value in vars(snap).items()), snap.close_id)
        if snap.view == "as_known":
            audit.check("original_close_lock", snap.knowledge_cutoff == snap.locked_at
                        and snap.replaces_close_id is None and snap.approval_id is None, snap.month)
            by_view[snap.month] = snap
        else:
            original = by_view[snap.month]
            audit.check("restatement_close_lock", snap.replaces_close_id == original.close_id
                        and snap.effective_before == original.effective_before
                        and snap.knowledge_cutoff > original.knowledge_cutoff and snap.approval_id,
                        snap.month)

    sums = Counter()
    releases = {}
    fk_entry = audit.checks.setdefault("journal_source_foreign_key", {"passed": True, "assertions": 0})
    bal_entry = audit.checks.setdefault("balanced_paired_entries", {"passed": True, "assertions": 0})
    ord_entry = audit.checks.setdefault("journal_partition_order", {"passed": True, "assertions": 0})
    line_entry = audit.checks.setdefault("balanced_two_line_journal", {"passed": True, "assertions": 0})
    out_entry = audit.checks.setdefault("outcome_release", {"passed": True, "assertions": 0})

    for view in ("as_known", "restated"):
        is_known = (view == "as_known")
        snapshots = [close[0] for close_view, close in closes if close_view == view]
        period_results = [close for close_view, close in closes if close_view == view]
        for first, next_close in zip(period_results, period_results[1:]):
            audit.check("monthly_close_continuity", next_close[0].prior_month_close_id == first[0].close_id
                        and first[6].closing_wip_cents == next_close[6].opening_wip_cents,
                        (view, first[0].month))
            ending = {row.account: row.closing_signed_cents for row in first[4]}
            audit.check("monthly_trial_continuity", all(row.opening_signed_cents == ending[row.account]
                                                         for row in next_close[4]), (view, first[0].month))
        snap_months = tuple(snap.month for snap in snapshots)
        snap_cutoffs_us = tuple(_dt_to_us(snap.knowledge_cutoff) for snap in snapshots)
        n_snaps = len(snapshots)
        fingerprints = OrderedFingerprints(n_snaps)
        partitions = audit.parts[f"journals_{view}"]
        audit.check("journal_partition_order", partitions == sorted(partitions), view)
        preceding = None
        for month, _ in partitions:
            if check_months is not None and month not in check_months:
                # Incremental mode still needs cumulative journal fingerprints for dependent closes.
                for batch in audit.batches(f"journals_{view}", month, _JOURNAL_COLUMNS):
                    c_month = batch.column(0).to_pylist()
                    c_amount = batch.column(1).to_pylist()
                    c_animal = batch.column(2).to_pylist()
                    c_approval = batch.column(3).to_pylist()
                    c_avail = _ts_us_list(batch.column(4))
                    c_comp = batch.column(5).to_pylist()
                    c_credit = batch.column(6).to_pylist()
                    c_debit = batch.column(7).to_pylist()
                    c_doc = batch.column(8).to_pylist()
                    c_eff = _ts_us_list(batch.column(9))
                    c_jid = batch.column(10).to_pylist()
                    c_lver = batch.column(11).to_pylist()
                    c_line = batch.column(12).to_pylist()
                    c_loc = batch.column(13).to_pylist()
                    c_lot = batch.column(14).to_pylist()
                    c_out = batch.column(15).to_pylist()
                    c_rout = _ts_us_list(batch.column(16))
                    c_pver = batch.column(17).to_pylist()
                    c_pool = batch.column(18).to_pylist()
                    c_post = _ts_us_list(batch.column(19))
                    c_rel = batch.column(20).to_pylist()
                    c_rapp = batch.column(21).to_pylist()
                    c_rev = batch.column(22).to_pylist()
                    c_sdate = _date_days_list(batch.column(23))
                    c_sid = batch.column(24).to_pylist()
                    c_spost = _ts_us_list(batch.column(25))
                    c_ssnap = batch.column(26).to_pylist()
                    c_ssys = batch.column(27).to_pylist()
                    c_yard = batch.column(28).to_pylist()
                    for (acc_m, amt, an, app, av, comp, cr, dr, doc, eff, jid, lver, ln, loc, lot,
                         oev, rout, pver, pool, post, prel, rapp, rev, sday, sid, spost, ssnap, ssys, yard) in zip(
                        c_month, c_amount, c_animal, c_approval, c_avail, c_comp, c_credit, c_debit,
                        c_doc, c_eff, c_jid, c_lver, c_line, c_loc, c_lot, c_out, c_rout, c_pver,
                        c_pool, c_post, c_rel, c_rapp, c_rev, c_sdate, c_sid, c_spost, c_ssnap, c_ssys, c_yard,
                    ):
                        first_idx = max(bisect_left(snap_months, acc_m), bisect_left(snap_cutoffs_us, av))
                        if first_idx < n_snaps:
                            fingerprints.add(first_idx, canonical_journal_from_columns(
                                acc_m, amt, an, app, av, comp, cr, dr, doc, eff, jid, lver, ln, loc, lot,
                                oev, rout, pver, pool, post, prel, rapp, rev, sday, sid, spost, ssnap, ssys, yard,
                            ))
                        if is_known:
                            if prel:
                                releases[an] = (dr, cr)
                            if comp in _NORMAL_FEED_COMPONENTS:
                                sums[pool] += amt
                continue

            journal_links = {}
            for batch in audit.batches(f"journals_{view}", month, _JOURNAL_COLUMNS):
                c_month = batch.column(0).to_pylist()
                c_amount = batch.column(1).to_pylist()
                c_animal = batch.column(2).to_pylist()
                c_approval = batch.column(3).to_pylist()
                c_avail = _ts_us_list(batch.column(4))
                c_comp = batch.column(5).to_pylist()
                c_credit = batch.column(6).to_pylist()
                c_debit = batch.column(7).to_pylist()
                c_doc = batch.column(8).to_pylist()
                c_eff = _ts_us_list(batch.column(9))
                c_jid = batch.column(10).to_pylist()
                c_lver = batch.column(11).to_pylist()
                c_line = batch.column(12).to_pylist()
                c_loc = batch.column(13).to_pylist()
                c_lot = batch.column(14).to_pylist()
                c_out = batch.column(15).to_pylist()
                c_rout = _ts_us_list(batch.column(16))
                c_pver = batch.column(17).to_pylist()
                c_pool = batch.column(18).to_pylist()
                c_post = _ts_us_list(batch.column(19))
                c_rel = batch.column(20).to_pylist()
                c_rapp = batch.column(21).to_pylist()
                c_rev = batch.column(22).to_pylist()
                c_sdate = _date_days_list(batch.column(23))
                c_sid = batch.column(24).to_pylist()
                c_spost = _ts_us_list(batch.column(25))
                c_ssnap = batch.column(26).to_pylist()
                c_ssys = batch.column(27).to_pylist()
                c_yard = batch.column(28).to_pylist()
                for (acc_m, amt, an, app, av, comp, cr, dr, doc, eff, jid, lver, ln, loc, lot,
                     oev, rout, pver, pool, post, prel, rapp, rev, sday, sid, spost, ssnap, ssys, yard) in zip(
                    c_month, c_amount, c_animal, c_approval, c_avail, c_comp, c_credit, c_debit,
                    c_doc, c_eff, c_jid, c_lver, c_line, c_loc, c_lot, c_out, c_rout, c_pver,
                    c_pool, c_post, c_rel, c_rapp, c_rev, c_sdate, c_sid, c_spost, c_ssnap, c_ssys, c_yard,
                ):
                    pk_entry["assertions"] += 1
                    if jid in journal_links:
                        raise ValueError(f"Stage 6A gate primary_keys failed: {('journal', jid)}")
                    fk_entry["assertions"] += 1
                    if sid not in sources:
                        raise ValueError(f"Stage 6A gate journal_source_foreign_key failed: {jid}")
                    bal_entry["assertions"] += 1
                    if dr == cr or amt < 0:
                        raise ValueError(f"Stage 6A gate balanced_paired_entries failed: {jid}")
                    clock = post if is_known else rout
                    ord_entry["assertions"] += 1
                    if preceding is not None and clock < preceding:
                        raise ValueError(f"Stage 6A gate journal_partition_order failed: {jid}")
                    preceding = clock
                    first_idx = max(bisect_left(snap_months, acc_m), bisect_left(snap_cutoffs_us, av))
                    if first_idx < n_snaps:
                        fingerprints.add(first_idx, canonical_journal_from_columns(
                            acc_m, amt, an, app, av, comp, cr, dr, doc, eff, jid, lver, ln, loc, lot,
                            oev, rout, pver, pool, post, prel, rapp, rev, sday, sid, spost, ssnap, ssys, yard,
                        ))
                    if is_known:
                        journal_links[jid] = (dr, cr, amt)
                        if prel:
                            out_entry["assertions"] += 1
                            if an in releases:
                                raise ValueError(f"Stage 6A gate outcome_release failed: {jid}")
                            releases[an] = (dr, cr)
                        if comp in _NORMAL_FEED_COMPONENTS:
                            sums[pool] += amt
                    else:
                        journal_links[jid] = None
            if is_known:
                seen_mask = {}
                for batch in audit.batches("journal_lines", month, ["journal_id", "line_number", "account", "signed_cents"]):
                    jids = batch.column(0).to_pylist()
                    lnums = batch.column(1).to_pylist()
                    accts = batch.column(2).to_pylist()
                    scents = batch.column(3).to_pylist()
                    for key, line, acct, sc in zip(jids, lnums, accts, scents):
                        debit, credit, cents = journal_links[key]
                        prev = seen_mask.get(key, 0)
                        bit = 1 if line == 1 else (2 if line == 2 else 0)
                        line_entry["assertions"] += 1
                        if not (bit and not (prev & bit) and (
                            (acct == debit and sc == cents) if line == 1 else (acct == credit and sc == -cents)
                        )):
                            raise ValueError(f"Stage 6A gate balanced_two_line_journal failed: {key}")
                        seen_mask[key] = prev | bit
                audit.check("balanced_two_line_journal", len(seen_mask) == len(journal_links)
                            and all(mask == 3 for mask in seen_mask.values()), month)
        for snap, (digest, count) in zip(snapshots, fingerprints.results(), strict=True):
            audit.check("books_close_counts", count == snap.source_journal_count, (view, snap.month))
            gate = "stable_original_snapshot" if is_known else "stable_restated_snapshot"
            audit.check(gate, digest == snap.journal_sha256, snap.month)

    audit.check("outcome_release", set(releases) == {key for key, row in outcomes.items() if row["status"] != "active"})
    for key, (debit_acct, credit_acct) in releases.items():
        expected = Account.COGS if outcomes[key]["status"] == "sold" else Account.MORTALITY
        audit.check("outcome_release", debit_acct == expected and credit_acct == Account.WIP, key)
    feeds_seen = set()
    ndcf_entry = audit.checks.setdefault("no_double_charged_feed", {"passed": True, "assertions": 0})
    for batch in audit.batches("feed_cost_bridge", columns=[
        "settlement_id", "delivery_id", "consumption_cents", "normal_mix_cents",
        "normal_distribution_cents", "normal_refusal_cents", "mix_loss_cents",
        "distribution_loss_cents", "refusal_cents", "bunk_loss_cents",
        "abnormal_cents", "recoverable_cents", "pending_cents",
    ]):
        for (sid, did, cons, nmix, ndist, nref, mloss, dloss, refc, bloss, abn, rec, pend) in zip(
            batch.column(0).to_pylist(), batch.column(1).to_pylist(), batch.column(2).to_pylist(),
            batch.column(3).to_pylist(), batch.column(4).to_pylist(), batch.column(5).to_pylist(),
            batch.column(6).to_pylist(), batch.column(7).to_pylist(), batch.column(8).to_pylist(),
            batch.column(9).to_pylist(), batch.column(10).to_pylist(), batch.column(11).to_pylist(),
            batch.column(12).to_pylist(),
        ):
            pk_entry["assertions"] += 1
            if sid is None or sid in feeds_seen:
                raise ValueError(f"Stage 6A gate primary_keys failed: {('feed cost', sid)}")
            feeds_seen.add(sid)
            cap = cons + nmix + ndist + nref
            outbound = mloss + dloss + refc + bloss + cons
            ndcf_entry["assertions"] += 1
            if not (cap == sums[did] and outbound == cap + abn + rec + pend):
                raise ValueError(f"Stage 6A gate no_double_charged_feed failed: {sid}")

    wh_af_entry = audit.checks.setdefault("warehouse_af_value", {"passed": True, "assertions": 0})
    for batch in audit.batches("warehouse_af_bridge", columns=[
        "snapshot_id",
        "opening_g_af", "receipt_g_af", "transfer_in_g_af", "issue_g_af",
        "transfer_out_g_af", "adjustment_g_af", "spoilage_g_af", "return_g_af", "closing_g_af",
        "opening_cents", "receipt_cents", "transfer_in_cents", "issue_cents",
        "transfer_out_cents", "adjustment_cents", "spoilage_cents", "return_cents",
        "invoice_cents", "closing_cents",
    ]):
        n = batch.num_rows
        if not n:
            continue
        af_tot = sum(batch.column(i).to_numpy(zero_copy_only=False) for i in range(1, 9))
        af_cls = batch.column(9).to_numpy(zero_copy_only=False)
        c_tot = sum(batch.column(i).to_numpy(zero_copy_only=False) for i in range(10, 19))
        c_cls = batch.column(19).to_numpy(zero_copy_only=False)
        wh_af_entry["assertions"] += 2 * n
        if not (bool(np.all((af_tot == af_cls) & (af_cls >= 0))) and bool(np.all((c_tot == c_cls) & (c_cls >= 0)))):
            raise ValueError("Stage 6A gate warehouse_af_value failed")

    wh_dm_entry = audit.checks.setdefault("warehouse_dm", {"passed": True, "assertions": 0})
    for batch in audit.batches("warehouse_dm_bridge", columns=[
        "snapshot_id", "opening_g_dm", "receipts_g_dm", "transfers_g_dm", "issues_g_dm",
        "adjustments_g_dm", "spoilage_g_dm", "returns_g_dm", "assay_revaluation_g_dm",
        "rounding_g_dm", "closing_g_dm",
    ]):
        n = batch.num_rows
        if not n:
            continue
        dm_tot = sum(batch.column(i).to_numpy(zero_copy_only=False) for i in range(1, 10))
        dm_cls = batch.column(10).to_numpy(zero_copy_only=False)
        wh_dm_entry["assertions"] += n
        if not bool(np.all((dm_tot == dm_cls) & (dm_cls >= 0))):
            raise ValueError("Stage 6A gate warehouse_dm failed")


def audit_sales(audit, observations, events):
    carcasses = audit.index(audit.rows("carcasses"), "sale_event_id", "carcass")
    sales = {key for key, row in events.items() if row["kind"] == "sale"}
    draft = audit.index(audit.rows("draft_decisions"), "draft_id", "draft")
    audit.check("sale_disposition", len(sales) == len(carcasses) == sum(1 for _ in audit.rows("shipment_lines")))
    for line in audit.rows("shipment_lines"):
        key = line["sale_event_id"]
        row = carcasses[key]
        audit.check("sale_disposition", key in sales and draft[line["draft_id"]]["status"] == "selected"
                    and draft[line["draft_id"]]["decided_at"] < line["effective_at"]
                    and row["animal_id"] == line["animal_id"] == draft[line["draft_id"]]["animal_id"], key)
        audit.check("carcass_consistency", 0 < row["dressing_fraction"] < 1
                    and abs(row["hcw_kg"] - row["latent_exit_liveweight_kg"] * row["dressing_fraction"]) <= 0.05001
                    and (row["quality_grade"] is None) == (row["yield_class"] is None), key)
        if row["liveweight_observation_id"]:
            audit.check("carcass_scale_link", observations[row["liveweight_observation_id"]]["measured_weight_kg"]
                        == row["measured_liveweight_kg"], key)
    for row in audit.rows("packer_settlements"):
        key = row["sale_event_id"]
        hcw = round(row["hcw_kg"] * 10)
        audit.check("synthetic_grid_settlement", key in carcasses and
                    row["effective_at"] < row["available_at"] and row["hcw_kg"] == carcasses[key]["hcw_kg"] and
                    row["final_cents"] == half_up(hcw * row["base_cents_per_kg_hcw"], 10) + row["premium_cents"]
                    - row["discount_cents"] - row["freight_cents"] ==
                    row["provisional_cents"] + row["adjustment_cents"], key)


def audit_weather(audit, runner):
    eligible = {}
    for vintage in runner.config["weather"]["forecasts"]:
        issued = vintage["issued_at"]
        available = vintage["available_at"]
        day = vintage["day"]
        due = midnight(date.fromisoformat(day))
        candidate = datetime.fromisoformat(issued), datetime.fromisoformat(available), vintage["source_id"]
        if candidate[1] <= due and (day not in eligible or candidate > eligible[day]):
            eligible[day] = candidate
    published = audit.index(audit.rows("weather_forecasts"), "source_id", "forecast vintages")
    audit.check("weather_forecast_publication", set(published) == {row[2] for row in eligible.values()})
    nfw_entry = audit.checks.setdefault("no_future_weather", {"passed": True, "assertions": 0})
    us_expected_cache = {}
    for batch in audit.batches("weather_exposure", columns=["path", "start_at", "kind", "source_id"]):
        for path, st_us, kind, sid in zip(
            batch.column(0).to_pylist(), _ts_us_list(batch.column(1)),
            batch.column(2).to_pylist(), batch.column(3).to_pylist(),
        ):
            if path == "operational":
                expected = us_expected_cache.get(st_us)
                if expected is None:
                    day = business_date(_EPOCH_DT + timedelta(microseconds=st_us))
                    point = eligible.get(day.isoformat())
                    expected = ("issued_forecast", point[2]) if point else ("seasonal_fallback", f"SYN-SEASONAL-{day:%m}")
                    us_expected_cache[st_us] = expected
                nfw_entry["assertions"] += 1
                if (kind, sid) != expected:
                    raise ValueError(f"Stage 6A gate no_future_weather failed: {st_us}")


def _check_schema(audit, root, filenames):
    for filename in filenames:
        parquet = pq.ParquetFile(root / filename)
        schema = parquet.schema_arrow
        audit.check("schema_version", schema.metadata == {
            b"schema_version": SCHEMA.encode(), b"synthetic": b"true"
        } and schema.field("run_id").nullable is False, filename)


def reconcile(root, tables, runner, replay, daily, monthly, closes):
    """Mode A: Full independent validation over every published partition and close."""
    audit = Audit(root, tables)
    _check_schema(audit, root, tables)
    _, events, enter, exit_at, outcomes = audit_movements(audit, runner, replay, daily, monthly)
    observations, anchors, health = audit_observations(audit, events, enter, exit_at)
    audit_feeding(audit, [row.month for row in runner.calendar], events, enter, exit_at, anchors, health, runner)
    audit_finance(audit, closes, outcomes)
    audit_sales(audit, observations, events)
    audit_weather(audit, runner)
    return audit.checks


def reconcile_incremental(root, tables, runner, replay, daily, monthly, closes, *,
                          changed_months, prior_partition_digests=None):
    """Mode B: Incremental validation of changed monthly partitions and dependent balances.

    Explicitly marks ``complete_independent_audit: False``; published candidates must
    still pass full independent validation via ``reconcile(...)``.
    """
    all_months = [row.month for row in runner.calendar]
    changed = sorted(set(changed_months))
    if not changed or not set(changed) <= set(all_months):
        raise ValueError(f"changed_months must be a nonempty subset of calendar months: {changed}")
    earliest_changed = changed[0]
    dependent_months = [m for m in all_months if m >= earliest_changed]
    dependent_set = set(dependent_months)

    audit = Audit(root, tables)
    changed_files = [name for name, info in tables.items() if info["month"] is None or info["month"] in dependent_set]
    _check_schema(audit, root, changed_files)

    verified_unchanged = 0
    if prior_partition_digests is not None:
        for name, info in sorted(tables.items()):
            if info["month"] is not None and info["month"] not in dependent_set:
                expected_sha = prior_partition_digests.get(name)
                actual_sha = file_digest_sha256(root / name)
                audit.check("immutable_partition_digest", expected_sha is not None and actual_sha == expected_sha, name)
                verified_unchanged += 1

    _, events, enter, exit_at, outcomes = audit_movements(audit, runner, replay, daily, monthly)
    observations, anchors, health = audit_observations(audit, events, enter, exit_at)
    audit_feeding(audit, changed, events, enter, exit_at, anchors, health, runner)
    audit_finance(audit, closes, outcomes, check_months=dependent_set)
    audit_sales(audit, observations, events)
    audit_weather(audit, runner)
    return {
        "mode": "incremental",
        "complete_independent_audit": False,
        "changed_months": changed,
        "dependent_months": dependent_months,
        "verified_unchanged_partitions": verified_unchanged,
        "hard_gates": audit.checks,
    }


def reconcile_with_mode(root, tables, runner, replay, daily, monthly, closes, *,
                        mode="full", changed_months=None, prior_partition_digests=None):
    if mode == "full":
        checks = reconcile(root, tables, runner, replay, daily, monthly, closes)
        return {
            "mode": "full",
            "complete_independent_audit": True,
            "changed_months": [row.month for row in runner.calendar],
            "dependent_months": [row.month for row in runner.calendar],
            "verified_unchanged_partitions": 0,
            "hard_gates": checks,
        }
    if mode == "incremental":
        return reconcile_incremental(
            root, tables, runner, replay, daily, monthly, closes,
            changed_months=changed_months or (),
            prior_partition_digests=prior_partition_digests,
        )
    raise ValueError(f"unknown validation mode: {mode}")
