"""Summaries at explicit exposure and accounting grains for the Stage 5 fixture."""

from collections import defaultdict
from dataclasses import asdict, replace
from math import isclose

from ..stage1.fixture import FINAL_CUTOFF
from ..stage1.model import EventKind, business_date
from ..stage1.provenance import canonical, sha256
from ..stage1.validation import Check, reject_failures
from ..stage2.config import uniform
from ..stage2.health import Action
from ..stage2.observations import Kind
from ..stage3.reconciliation import feed_bridges, wip_candidates
from ..stage3_5.reconciliation import dm_bridges
from ..stage3_5.validation import _decisions, _dry_matter, _releases, _scale
from ..stage3.validation import _biology_checks, validate as validate_feed
from ..stage4.fixture import Fixture, settings as finance_settings
from ..stage4.ledger import Account, balance
from ..stage4.market import valuation
from ..stage4.report import close_series, dry_matter, feed_bridge, invoice_routes, journal_sets, recoverable, validation


def decision_digest(operations, before=None):
    plans = [row for row in operations.schedule.plans if before is None or row.decision_at < before]
    windows = {row.decision_snapshot_id for row in plans}
    return sha256(canonical([
        plans, [row for row in operations.schedule.estimates if row.snapshot_id in windows],
        [row for row in operations.decision_sources if row.snapshot_id in windows],
    ]))


def outcomes(operations, model, calibration):
    dress_low, dress_high = calibration["carcass"]["dressing_fraction"]
    measured = {row.animal_id: row for row in operations.observations if row.kind == Kind.FINAL_SALE}
    results = []
    for profile in operations.profiles:
        animal = profile.animal_id
        exit_event = operations.timeline.exits.get(animal)
        entry = operations.timeline.entries[animal]
        end = exit_event.effective_at if exit_event else FINAL_CUTOFF
        steps = model.steps_by_animal[animal]
        kg = model.weight_at(animal, end)
        sold = exit_event is not None and exit_event.kind == EventKind.SALE
        fraction = dress_low + (dress_high - dress_low) * uniform(
            operations.timeline.seed, "stage5-dressing", animal) if sold else None
        hcw = round(fraction * kg, 1) if sold else None
        episodes = [event for event in operations.health if event.animal_id == animal]
        results.append({
            "animal_id": animal, "lot_id": profile.lot_id, "sex": profile.sex, "breed": profile.breed,
            "outcome": exit_event.kind if exit_event else "carry_out", "entry_live_kg": profile.entry_weight_kg,
            "end_live_kg": kg, "elapsed_days_from_known_entry": sum(row.elapsed_days for row in steps),
            "operational_sale_ticket_kg": measured[animal].measured_weight_kg if animal in measured else None,
            "calendar_days_from_known_entry": (business_date(end) - business_date(entry.effective_at)).days + 1,
            "opening_history_incomplete": entry.kind == EventKind.OPENING,
            "estimated_dmi_kg": sum(row.consumed_g_dm for row in steps) / 1000,
            "first_treatments": sum(row.action == Action.TREAT for row in episodes),
            "repeat_treatments": sum(row.action == Action.REPEAT for row in episodes),
            "hospital_admissions": sum(row.action == Action.ADMIT for row in episodes),
            "dressing_fraction_scenario": fraction, "hcw_kg_scenario": hcw,
            "quality_grade": None, "grade_status": "grade_evidence_missing" if sold else "not_eligible",
            "illustrative_grid_only_cents": [round(hcw * price) for price in
                                             calibration["carcass"]["synthetic_base_cents_per_kg_hcw"]]
            if sold else None,
        })
    return results


def metrics(model, terminal):
    buckets = defaultdict(list)
    for row in model.steps:
        buckets[row.weather_kind].append(row)
    by_source = {}
    for key, rows in sorted(buckets.items()):
        elapsed = sum(row.elapsed_days for row in rows)
        gain = sum(row.gain_kg - row.loss_kg for row in rows)
        dm = sum(row.consumed_g_dm for row in rows) / 1000
        by_source[key] = {
            "animal_days_elapsed": elapsed, "net_gain_kg": gain, "adg_kg": gain / elapsed,
            "estimated_dmi_kg": dm, "dmi_kg_per_animal_day": dm / elapsed,
            "gain_to_feed_kg_per_kg_dm": gain / dm if dm else None,
            "maintenance_me_mj": sum(row.maintenance_required_me_mj for row in rows),
        }
    rows = model.steps
    elapsed = sum(row.elapsed_days for row in rows)
    dm = sum(row.consumed_g_dm for row in rows) / 1000
    gain = sum(row.gain_kg - row.loss_kg for row in rows)
    hcw = [row["hcw_kg_scenario"] for row in terminal if row["hcw_kg_scenario"] is not None]
    day_feed = defaultdict(int)
    day_weight = {}
    for row in rows:
        key = row.animal_id, business_date(row.start_at)
        day_feed[key] += row.consumed_g_dm
        day_weight.setdefault(key, row.start_weight_kg)
    dmi_bw = sorted(100 * gm / 1000 / day_weight[key] for key, gm in day_feed.items())
    return {
        "by_weather_source": by_source, "elapsed_animal_days": elapsed, "adg_kg": gain / elapsed,
        "estimated_dmi_total_kg": dm, "dmi_kg_per_animal_day": dm / elapsed,
        "gain_to_feed": gain / dm if dm else None, "dm_feed_per_kg_gain": dm / gain if gain > 0 else None,
        "min_ending_weight_kg": min(row["end_live_kg"] for row in terminal),
        "mean_ending_weight_kg": sum(row["end_live_kg"] for row in terminal) / len(terminal),
        "max_ending_weight_kg": max(row["end_live_kg"] for row in terminal),
        "mean_sold_hcw_kg_scenario": sum(hcw) / len(hcw) if hcw else None,
        "mean_burden_time_weighted": sum(row.health_burden * row.elapsed_days for row in rows) / elapsed,
        "insufficient_me_elapsed_animal_days": sum(row.elapsed_days for row in rows
                                                    if row.maintenance_used_me_mj < row.maintenance_required_me_mj),
        "dmi_bw_pct_animal_business_day": {
            "denominator": "first step liveweight, includes partial days", "n": len(dmi_bw),
            "min": dmi_bw[0], "median": dmi_bw[len(dmi_bw) // 2], "max": dmi_bw[-1],
            "over_3_pct": sum(value > 3 for value in dmi_bw),
        },
    }


def physiology_checks(model, growth_bounds):
    low, high = growth_bounds
    issues = []
    for row in model.steps:
        me_out = row.maintenance_used_me_mj + row.gain_used_me_mj + row.ending_me_mj + row.excess_me_mj
        cp_out = row.cp_maintenance_used_kg + row.cp_gain_used_kg + row.ending_cp_kg + row.excess_cp_kg
        tolerance = 1e-9
        if (not isclose(row.starting_me_mj + row.energy_mj, me_out, abs_tol=tolerance)
                or not isclose(row.starting_cp_kg + row.protein_kg, cp_out, abs_tol=tolerance)
                or row.maintenance_used_me_mj > row.maintenance_required_me_mj
                or row.maintenance_used_me_mj + row.gain_used_me_mj > row.starting_me_mj + tolerance
                or row.cp_maintenance_used_kg + row.cp_gain_used_kg > row.starting_cp_kg + tolerance
                or not model.bounds[0] - tolerance <= row.end_weight_kg <= model.bounds[1] + tolerance
                or row.gain_kg > high * row.elapsed_days + tolerance
                or row.loss_kg > -low * row.elapsed_days + tolerance):
            issues.append(f"{row.animal_id}/{row.start_at}")
    return Check("STAGE5_NUTRIENT_TIME_BALANCE", model.forcing.mode, "conserved and bounded", "checked",
                 len(issues), tuple(issues[:10]))


def cross_stage(operations, scale_settlements, physical):
    phy_ops = replace(operations, biology=physical, growth_inputs=physical.adapter.growth_inputs(physical))
    scale_ops = replace(operations, active_settlements=scale_settlements, timeline=operations.biology.timeline)
    bridges = feed_bridges(phy_ops, wip_candidates(phy_ops))
    bounds = operations.biology_config["biology"]["gain_bounds_kg_per_day"]
    checks = (*validate_feed(phy_ops, bridges, timed=True), *_biology_checks(scale_ops),
              _scale(operations), _decisions(operations), _releases(operations),
              _dry_matter(phy_ops, tuple(dm_bridges(phy_ops)), bridges),
              physiology_checks(physical, bounds), physiology_checks(operations.biology, bounds))
    bad = []
    for animal, exit_event in operations.timeline.exits.items():
        for model in (operations.biology, physical):
            if model.steps_by_animal[animal][-1].end_at != exit_event.effective_at:
                bad.append(animal)
    checks += (Check("STAGE5_EXIT_TERMINAL", "fixture", "no biology after an exit", "checked", len(bad), tuple(bad)),)
    reject_failures(checks)
    return checks


def financials(operations, *, method=None, loss_policy="selected", packer_multiplier=1.0):
    config = finance_settings()
    config["source_scenario"] = operations.scenario["version"]
    config["version"] = f"stage5-financial-comparison.1+{config['version']}"
    if method is not None:
        config["method"] = method
        operations = replace(operations, scenario={**operations.scenario, "method": method})
    if packer_multiplier != 1.0:
        for key, cents in config["sale_provisional_cents"].items():
            config["sale_provisional_cents"][key] = round(cents * packer_multiplier)
        config["packer_final"]["final_cents"] = round(config["packer_final"]["final_cents"] * packer_multiplier)
    book = Fixture(operations, config, loss_policy)
    journals = journal_sets(book)
    original = close_series(book, journals)
    alternate = journal_sets(book, corrected=True)
    revised = close_series(book, alternate, originals=original)
    bridges = tuple(feed_bridge(book))
    invoices = tuple(invoice_routes(book, journals))
    recovery = tuple(recoverable(book, invoices))
    checks = validation(book, journals, original, revised, bridges, invoices, recovery, expect_baseline=False)
    dm_count = len(tuple(dry_matter(book, (*original, *revised))))
    _, market = valuation(book)
    selected = [item for row in operations.active_settlements for item in row.allocations
                if item.method == config["method"]]
    horizon = next(row for row in bridges if row.period == "horizon")
    alloc_g_dm = sum(item.g_dm for item in selected)
    alloc_cents = sum(item.cents for item in selected)
    checks += (Check("STAGE5_ALLOCATED_DM_AND_BASE_COST", "fixture",
                     (horizon.original_consumed_g_dm, horizon.consumption_base_cents), (alloc_g_dm, alloc_cents),
                     int((alloc_g_dm, alloc_cents) != (horizon.original_consumed_g_dm, horizon.consumption_base_cents))),)
    reject_failures(checks)
    monthly = [row[6] for row in original]
    summary = {
        "loss_policy": loss_policy, "allocation_method": config["method"], "journal_count": len(journals),
        "revised_journal_count": len(alternate), "checks": len(checks), "monthly_dm_bridges": dm_count,
        "journal_net_cents": sum(balance(journals, account) for account in Account),
        "ending_wip_cents": monthly[-1].closing_wip_cents, "ending_inventory_cents": monthly[-1].inventory_cents,
        "ending_inventory_g_af": monthly[-1].inventory_g_af,
        "cogs_cents": sum(row.sales_cogs_cents for row in monthly),
        "revenue_cents": sum(row.net_sales_cents for row in monthly),
        "margin_cents": sum(row.sales_gross_margin_cents for row in monthly),
        "mortality_cents": sum(row.mortality_burden_cents for row in monthly),
        "feed_variance_cents": sum(row.feed_operating_variance_cents for row in monthly),
        "contribution_cents": sum(row.modeled_yard_contribution_cents for row in monthly),
        "offered_g_af": sum(row.delivered.g_af for row in operations.deliveries),
        "offered_g_dm": sum(row.delivered.g_dm for row in operations.deliveries),
        "modeled_consumed_g_af": sum(row.row.modeled_consumption.g_af for row in operations.active_settlements),
        "modeled_consumed_g_dm": alloc_g_dm,
        "physical_mix_loss_g_af": sum(row.loss.g_af for row in operations.mixes),
        "physical_distribution_loss_g_af": sum(row.delivery_loss.g_af for row in operations.deliveries),
        "physical_refusal_g_af": sum(row.row.refusal.g_af for row in operations.active_settlements),
        "physical_bunk_loss_g_af": sum(row.row.bunk_loss.g_af for row in operations.active_settlements),
        "physical_mix_loss_g_dm": sum(row.loss.g_dm for row in operations.mixes),
        "physical_distribution_loss_g_dm": sum(row.delivery_loss.g_dm for row in operations.deliveries),
        "physical_refusal_g_dm": sum(row.row.refusal.g_dm for row in operations.active_settlements),
        "physical_bunk_loss_g_dm": sum(row.row.bunk_loss.g_dm for row in operations.active_settlements),
        "feed_cost_bridge": asdict(horizon),
    }
    evidence = {
        "checks": checks, "monthly_original": monthly, "monthly_restated": [row[6] for row in revised],
        "invoice_routes": invoices, "recoverable": recovery, "market_rows": tuple(market),
        "book_canonical_sha256": sha256(canonical(journals)),
        "restated_book_canonical_sha256": sha256(canonical(alternate)),
    }
    return summary, evidence, journals
