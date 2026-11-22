"""Independent hard gates over the published partition grain and source crosswalks."""

from collections import Counter, defaultdict
from hashlib import sha256 as hasher
from math import isclose

import pyarrow.parquet as pq

from ..stage1.provenance import canonical
from ..stage3.units import BPS, half_up
from ..stage4.ledger import Account
from .config import SCHEMA

AMOUNTS = ("g_af", "g_dm", "kj", "cp_g", "cents")
NUTRIENTS = ("g_dm", "energy_kj", "cp_g")


class Audit:
    def __init__(self, root, tables):
        self.root = root
        self.parts = defaultdict(list)
        for name, row in sorted(tables.items()):
            self.parts[row["table"]].append((row["month"], name))
        self.checks = {}

    def rows(self, table, month=None, columns=None):
        for period, path in self.parts[table]:
            if month is None or period == month:
                for batch in pq.ParquetFile(self.root / path).iter_batches(columns=columns):
                    yield from batch.to_pylist()

    def check(self, key, valid, detail=""):
        result = self.checks.setdefault(key, {"passed": True, "assertions": 0})
        result["assertions"] += 1
        if not valid:
            raise ValueError(f"Stage 6A gate {key} failed: {detail}")

    def index(self, rows, key, table):
        result = {}
        for row in rows:
            identifier = key(row) if callable(key) else row[key]
            self.check("primary_keys", identifier is not None and identifier not in result, (table, identifier))
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
    by_date = Counter(row["date"] for row in audit.rows("yardage", columns=["date"]))
    for row in daily:
        if row.scope_type == "yard":
            audit.check("animal_days", row.animal_days == by_date[row.period_start] == runner.daily_active[row.period_start],
                        row.period_start)
            audit.check("stock_equation", row.transfers_in == row.transfers_out == 0 and
                        row.opening_head + row.receipts - row.sales - row.deaths == row.closing_head, row.period_start)
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
    actual_intervals = defaultdict(list)
    for row in audit.rows("physical_intervals"):
        actual_intervals[row["start_event_id"]].append(row)
    recipes = audit.index(audit.rows("ration_versions"), "record_id", "rations")
    equipment = audit.index(audit.rows("warehouse_equipment"), "record_id", "equipment")
    planning = runner.feeding.planning
    for month in months:
        plans = audit.index(audit.rows("feed_plans", month), "plan_id", "feed plan")
        estimates = audit.index(audit.rows("weight_estimates", month), "estimate_id", "estimate")
        snapshots = audit.index(audit.rows("decision_snapshots", month), "snapshot_id", "decision snapshot")
        weights = audit.index(audit.rows("feeding_weight_inputs", month), "weight_input_id", "feed weight")
        exposures = audit.index(audit.rows("feed_exposures", month), "exposure_id", "feed exposure")
        delivery = audit.index(audit.rows("feed_deliveries", month), "delivery_id", "delivery")
        mixes = audit.index(audit.rows("mixes", month), "mix_id", "mix")
        settled = audit.index(audit.rows("bunk_settlements", month), "settlement_id", "settlement")
        access = audit.index(audit.rows("feed_access_snapshots", month), "access_snapshot_id", "access snapshot")
        warehouse_issues = audit.index((row for row in audit.rows("warehouse_entries", month)
                                        if row["kind"] == "issue"), "entry_id", "issue entries")
        for row in estimates.values():
            cutoff, key = row["knowledge_cutoff"], row["animal_id"]
            old = max((obs for obs in anchors[key] if obs["measured_at"] < cutoff and obs["available_at"] <= cutoff),
                      key=lambda obs: (obs["measured_at"], obs["available_at"], obs["observation_id"]), default=None)
            snapshot = snapshots[row["snapshot_id"]]
            incoming = events[row["location_event_id"]]
            audit.check("no_future_estimates", row["last_observation_id"] == (old["observation_id"] if old else None)
                        and snapshot["knowledge_cutoff"] == cutoff == row["effective_before"] == row["estimate_for"]
                        and incoming["available_at"] <= cutoff and incoming["to_location_id"] == row["location_id"],
                        row["estimate_id"])
            if row["health_event_id"]:
                current = health[row["health_event_id"]]
                audit.check("no_future_health", current["available_at"] <= cutoff and current["operational_visible"],
                            row["estimate_id"])
        weights_by_pen = defaultdict(list)
        for row in weights.values():
            weights_by_pen[row["estimate_snapshot_id"], row["roster_pen_id"]].append(row)
        for row in plans.values():
            members = weights_by_pen[row["decision_snapshot_id"], row["pen_id"]]
            stages = set(recipes[row["ration_version_id"]]["eligible_stages"].split(","))
            target = sum(min(planning["stage_dm_g_per_window"][item["production_stage"]],
                             item["score_weight_g"] * planning["intake_limit_bps_per_window"] // BPS)
                         * planning["clinical_intake_bps"].get(estimates[item["estimate_id"]]["clinical_status"], BPS)
                         // BPS for item in members)
            audit.check("ration_and_plan", row["known_head"] == len(members)
                        and target == row["planned_g_dm"] and all(item["production_stage"] in stages for item in members),
                        row["plan_id"])
        inputs = defaultdict(Counter)
        issue_links = set()
        for row in audit.rows("mix_inputs", month):
            key = row["layer_entry_id"]
            source = warehouse_issues[key]
            audit.check("fifo_issue_to_mix", key not in issue_links and row["amount"]["g_af"] == -source["g_af"]
                        and row["amount"]["g_dm"] == -source["g_dm"]
                        and row["amount"]["cents"] == -source["cents"], key)
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
        posting = audit.index(audit.rows("accounting_feed_allocations", month), "allocation_id", "posting allocation")
        links = audit.index(audit.rows("posting_allocation_links", month), "release_allocation_id", "release crosswalk")
        posting_amounts = defaultdict(Counter)
        unique = set()
        by_settlement = defaultdict(Counter)
        flows = defaultdict(Counter)
        for row in audit.rows("feed_allocations", month):
            identifier = row["allocation_id"]
            audit.check("primary_keys", identifier not in unique, ("feed allocation", identifier))
            unique.add(identifier)
            key, pen = row["animal_id"], row["pen_id"]
            first, last = row["access_start"], row["access_end"]
            weight = weights[row["weight_input_id"]]
            estimate = estimates[weight["estimate_id"]]
            exposure = exposures[row["exposure_id"]]
            plan = plans[delivery[row["delivery_id"]]["plan_id"]]
            interval = actual_intervals[exposure["movement_in_id"]][0]
            audit.check("feed_eligibility", first < last and enter[key] <= first
                        and last <= exit_at.get(key, last) and interval["location_id"] == pen
                        and interval["animal_id"] == key and interval["start_at"] <= first
                        and last <= (interval["end_at"] or last) and exposure["animal_id"] == key
                        and exposure["first_at"] <= first < last <= exposure["end_at"]
                        and plan["window_start"] <= first < last <= plan["window_end"], identifier)
            audit.check("frozen_feed_input", row["estimate_id"] == estimate["estimate_id"]
                        and row["decision_cutoff"] == weight["cutoff"] == plan["decision_at"]
                        and row["decision_cutoff"] <= first and weight["roster_pen_id"] == pen, identifier)
            aggregate = posting[links[identifier]["posting_allocation_id"]]
            audit.check("timed_to_posting_allocation", aggregate["animal_id"] == key
                        and aggregate["settlement_id"] == row["settlement_id"]
                        and aggregate["access_start"] <= first < last <= aggregate["access_end"], identifier)
            posting_amounts[aggregate["allocation_id"]].update({field: row[field]
                                                               for field in (*NUTRIENTS, "cents", "duration_seconds")})
            by_settlement[row["settlement_id"]].update({field: row[field] for field in (*NUTRIENTS, "cents")})
            flows[key, pen, row["window_start"]].update({field: row[field] for field in NUTRIENTS})
        audit.check("timed_to_posting_allocation", unique == set(links))
        for key, row in posting.items():
            audit.check("timed_to_posting_allocation", vector(posting_amounts[key], (*NUTRIENTS, "cents", "duration_seconds"))
                        == vector(row, (*NUTRIENTS, "cents", "duration_seconds")), key)
        for key, row in settled.items():
            pool = row["modeled_consumption"]
            audit.check("allocation_conservation", vector(by_settlement[key], (*NUTRIENTS, "cents"))
                        == (pool["g_dm"], pool["kj"], pool["cp_g"], pool["cents"]), key)
        for path in ("operational", "retrospective") if runner.retro else ("operational",):
            growth = defaultdict(Counter)
            for row in audit.rows(f"growth_{path}", month):
                k = row["animal_id"], row["location_id"], row["window_start_at"]
                if row["window_start_at"] is not None:
                    growth[k].update(g_dm=row["consumed_g_dm"], energy_kj=round(row["energy_mj"] * 1000),
                                     cp_g=round(row["protein_kg"] * 1000))
                audit.check("biological_reserve_balance", isclose(
                    row["starting_me_mj"] + row["energy_mj"], row["maintenance_used_me_mj"] +
                    row["gain_used_me_mj"] + row["ending_me_mj"] + row["excess_me_mj"], abs_tol=1e-8)
                    and isclose(row["starting_cp_kg"] + row["protein_kg"], row["cp_maintenance_used_kg"] +
                                row["cp_gain_used_kg"] + row["ending_cp_kg"] + row["excess_cp_kg"], abs_tol=1e-9),
                    (path, k))
                audit.check("growth_time", enter[k[0]] <= row["start_at"] < row["end_at"] <= exit_at.get(k[0], row["end_at"])
                            and (path == "retrospective" or row["weather_kind"] != "archive_reanalysis"), (path, k))
            audit.check("feed_to_biology", all(growth[k] == flows[k] for k in growth.keys() | flows.keys()), (month, path))


def audit_finance(audit, closes, outcomes):
    sources = {}
    for row in audit.rows("financial_sources", columns=["source_id", "available_at"]):
        key = row["source_id"]
        audit.check("primary_keys", key not in sources, ("financial source", key))
        sources[key] = row["available_at"]
    for row in audit.rows("financial_source_links"):
        child, parent = sources[row["source_id"]], sources[row["parent_id"]]
        audit.check("finance_source_timing", parent <= child, row["source_id"])
    sums = Counter()
    releases = {}
    for view in ("as_known", "restated"):
        snapshots = [close[0] for close_view, close in closes if close_view == view]
        period_results = [close for close_view, close in closes if close_view == view]
        for first, next_close in zip(period_results, period_results[1:]):
            audit.check("monthly_close_continuity", next_close[0].prior_month_close_id == first[0].close_id
                        and first[6].closing_wip_cents == next_close[6].opening_wip_cents,
                        (view, first[0].month))
            ending = {row.account: row.closing_signed_cents for row in first[4]}
            audit.check("monthly_trial_continuity", all(row.opening_signed_cents == ending[row.account]
                                                         for row in next_close[4]), (view, first[0].month))
        count = Counter()
        digests = {snap.month: hasher(b"[") for snap in snapshots} if view == "as_known" else {}
        for month, _ in audit.parts[f"journals_{view}"]:
            journal_links = {}
            for row in audit.rows(f"journals_{view}", month):
                key = row["journal_id"]
                audit.check("primary_keys", key not in journal_links, ("journal", key))
                audit.check("journal_source_foreign_key", row["source_id"] in sources, key)
                audit.check("balanced_paired_entries", row["debit_account"] != row["credit_account"]
                            and row["amount_cents"] >= 0, key)
                eligibility = [snap for snap in snapshots if row["accounting_month"] <= snap.month
                               and row["available_at"] <= snap.knowledge_cutoff]
                if view == "as_known":
                    journal_links[key] = (row["debit_account"], row["credit_account"], row["amount_cents"])
                    if row["principal_release"]:
                        animal = row["animal_id"]
                        audit.check("outcome_release", animal not in releases, key)
                        releases[animal] = row
                    if row["component"] in {"feed_consumption", "mix_normal", "distribution_normal", "refusal_normal"}:
                        sums[row["pool_id"]] += row["amount_cents"]
                    if eligibility:
                        encoded = canonical({key: value for key, value in row.items() if key != "run_id"})[:-1]
                        for snap in eligibility:
                            digest = digests[snap.month]
                            if count[snap.month]:
                                digest.update(b",")
                            digest.update(encoded)
                count.update(snap.month for snap in eligibility)
            if view == "as_known":
                seen = defaultdict(set)
                for row in audit.rows("journal_lines", month):
                    key, line = row["journal_id"], row["line_number"]
                    debit, credit, cents = journal_links[key]
                    audit.check("balanced_two_line_journal", line in (1, 2) and line not in seen[key]
                                and (row["account"], row["signed_cents"]) == (
                                    (debit, cents) if line == 1 else (credit, -cents)), key)
                    seen[key].add(line)
                audit.check("balanced_two_line_journal", len(seen) == len(journal_links)
                            and all(lines == {1, 2} for lines in seen.values()), month)
        for snap in snapshots:
            audit.check("books_close_counts", count[snap.month] == snap.source_journal_count, (view, snap.month))
            if snap.month in digests:
                digests[snap.month].update(b"]\n")
                audit.check("stable_original_snapshot", digests[snap.month].hexdigest() == snap.journal_sha256, snap.month)
    audit.check("outcome_release", set(releases) == {key for key, row in outcomes.items() if row["status"] != "active"})
    for key, row in releases.items():
        expected = Account.COGS if outcomes[key]["status"] == "sold" else Account.MORTALITY
        audit.check("outcome_release", row["debit_account"] == expected and row["credit_account"] == Account.WIP, key)
    feeds = audit.index(audit.rows("feed_cost_bridge"), "settlement_id", "feed cost")
    for key, row in feeds.items():
        cap = sum(row[field] for field in ("consumption_cents", "normal_mix_cents",
                                          "normal_distribution_cents", "normal_refusal_cents"))
        outbound = sum(row[field] for field in ("mix_loss_cents", "distribution_loss_cents", "refusal_cents",
                                               "bunk_loss_cents", "consumption_cents"))
        audit.check("no_double_charged_feed", cap == sums[row["delivery_id"]] and
                    outbound == cap + row["abnormal_cents"] + row["recoverable_cents"] + row["pending_cents"], key)
    for row in audit.rows("warehouse_af_bridge"):
        for unit in ("g_af", "cents"):
            total = sum(row[f"{name}_{unit}"] for name in ("opening", "receipt", "transfer_in", "issue",
                        "transfer_out", "adjustment", "spoilage", "return"))
            if unit == "cents":
                total += row["invoice_cents"]
            audit.check("warehouse_af_value", total == row[f"closing_{unit}"] >= 0, row["snapshot_id"])
    for row in audit.rows("warehouse_dm_bridge"):
        total = sum(row[f"{name}_g_dm"] for name in ("opening", "receipts", "transfers", "issues", "adjustments",
                   "spoilage", "returns", "assay_revaluation", "rounding"))
        audit.check("warehouse_dm", total == row["closing_g_dm"] >= 0, row["snapshot_id"])


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


def reconcile(root, tables, runner, replay, daily, monthly, closes):
    audit = Audit(root, tables)
    for filename in tables:
        parquet = pq.ParquetFile(root / filename)
        schema = parquet.schema_arrow
        audit.check("schema_version", schema.metadata == {
            b"schema_version": SCHEMA.encode(), b"synthetic": b"true"
        } and schema.field("run_id").nullable is False, filename)
    _, events, enter, exit_at, outcomes = audit_movements(audit, runner, replay, daily, monthly)
    observations, anchors, health = audit_observations(audit, events, enter, exit_at)
    audit_feeding(audit, [row.month for row in runner.calendar], events, enter, exit_at, anchors, health, runner)
    audit_finance(audit, closes, outcomes)
    audit_sales(audit, observations, events)
    return audit.checks
