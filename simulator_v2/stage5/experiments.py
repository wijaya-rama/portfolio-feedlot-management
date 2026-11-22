"""Paired fixtures and fixed-input physiological sensitivity."""

from dataclasses import replace

from ..stage1.fixture import FINAL_CUTOFF, START
from ..stage1.model import midnight
from ..stage1.provenance import canonical, sha256
from ..stage1.validation import reject_failures
from ..stage2.backtest import evaluate, latent_targets, report
from ..stage3.allocation import Method
from ..stage3_5.fixture import integrated_fixture
from .diagnostics import cross_stage, decision_digest, financials, metrics, outcomes, physiology_checks
from .fixture import build_operations, changed_scenario, replay_growth, weather_scenario
from .weather import Weather, coverage, load_archive

def run(seed, calibration):
    fallback = weather_scenario(calibration)
    archive, provenance = load_archive()
    retrospective = Weather("retrospective", fallback.fallback, archive=archive)
    operations, scale = build_operations(seed, fallback, calibration)
    physics = replay_growth(operations, retrospective, calibration)
    checks = {"baseline_operational_and_retrospective": cross_stage(operations, scale, physics)}
    financial, financial_evidence, journals = financials(operations)

    sensitivity = calibration["sensitivity"]
    normal_weather = weather_scenario(calibration, sensitivity["normal_c"])
    cold_weather = weather_scenario(calibration, sensitivity["cold_c"])
    rows = {}
    bounds = operations.biology_config["biology"]["gain_bounds_kg_per_day"]

    def record(name, ops, model, accounts, comparison, *, parameters=calibration):
        terminal = outcomes(ops, model, parameters)
        results = metrics(model, terminal)
        checks[name] = (*checks.get(name, ()), physiology_checks(model, bounds))
        reject_failures(checks[name])
        rows[name] = {
            "comparison": comparison, "scenario_config_sha256": sha256(canonical(ops.scenario)),
            "calibration_sha256": sha256(canonical(parameters)), "decision_sha256": decision_digest(ops),
            "biology": results, "finance": accounts, "animal_outcomes": terminal,
        }

    record("operational_as_of", operations, operations.biology, financial, None)
    record("retrospective_archive_and_fallback", operations, physics, financial, "operational_as_of")
    normal = replay_growth(operations, normal_weather, calibration)
    record("normal_fixed_feed", operations, normal, financial, None)
    cold = replay_growth(operations, cold_weather, calibration)
    record("cold_fixed_feed", operations, cold, financial, "normal_fixed_feed")
    healthy = tuple(replace(row, burden=0.0) for row in operations.health)
    no_burden = replay_growth(operations, normal_weather, calibration, health=healthy)
    record("clinical_burden_removed_fixed_feed", operations, no_burden, financial, "normal_fixed_feed")

    for method in (Method.EQUAL, Method.BODYWEIGHT):
        model = replay_growth(operations, normal_weather, calibration, method=method)
        accounts, _, _ = financials(operations, method=method)
        record(method.value, operations, model, accounts, "normal_fixed_feed")

    for parameter in ("maintenance_me_efficiency", "gain_me_efficiency", "cold_maintenance_per_c"):
        group = "stress" if parameter == "cold_maintenance_per_c" else "maintenance"
        forcing = cold_weather if group == "stress" else normal_weather
        for label, value in zip(("low", "high"), sensitivity[f"{parameter}_bounds"], strict=True):
            parameters = {**calibration, group: {**calibration[group], parameter: value}}
            model = replay_growth(operations, forcing, parameters)
            record(f"{parameter}_{label}", operations, model, financial,
                   "cold_fixed_feed" if group == "stress" else "normal_fixed_feed", parameters=parameters)

    scenario_reference = replay_growth(operations, fallback, calibration)
    record("seasonal_fixed_physical", operations, scenario_reference, financial, None)
    for name in ("lower_me", "reduced_offer", "elevated_mix_loss", "elevated_distribution_loss"):
        changed, scale_rows = build_operations(seed, fallback, calibration,
                                               scenario=changed_scenario(calibration, name))
        model = replay_growth(changed, fallback, calibration)
        checks[name] = cross_stage(changed, scale_rows, model)
        accounts, _, _ = financials(changed)
        record(name, changed, model, accounts, "seasonal_fixed_physical")

    for policy in ("tighter", "consumption_only"):
        accounts, _, _ = financials(operations, loss_policy=policy)
        record(f"loss_classification_{policy}", operations, normal, accounts, "normal_fixed_feed")
    packer = calibration["financial_scenarios"]["packer_settlement_multiplier"]
    for label, value in {"low": packer[0], "high": packer[-1]}.items():
        accounts, _, _ = financials(operations, packer_multiplier=value)
        record(f"packer_{label}", operations, normal, accounts, "normal_fixed_feed")

    baseline = integrated_fixture(seed)
    baseline_steps = baseline.biology.steps
    old_elapsed = sum((row.end_at - row.start_at).total_seconds() / 86400 for row in baseline_steps)
    old = {
        "scenario": baseline.scenario["version"],
        "elapsed_animal_days": old_elapsed,
        "adg_kg": sum(row.end_weight_kg - row.start_weight_kg for row in baseline_steps) / old_elapsed,
        "estimated_dmi_total_kg": sum(row.consumed_g_dm for row in baseline_steps) / 1000,
        "mean_ending_weight_kg": sum(values[-1].end_weight_kg for values in baseline.biology.steps_by_animal.values())
        / len(baseline.profiles),
        "decision_sha256": decision_digest(baseline),
    }

    backtest = evaluate(operations.final_estimator, operations.profiles, start_at=midnight(START),
                        evaluation_cutoff=FINAL_CUTOFF, config=operations.biology_config)
    latent = latent_targets(backtest[0], operations.biology, operations.biology.timeline.snapshot_id)
    backtest_summary = report(backtest[0], operations.biology_config, latent=latent)
    return {
        "operations": operations, "physical": physics, "scale_settlements": scale, "journal": journals,
        "experiments": rows, "cross_stage_checks": checks, "financial_evidence": financial_evidence,
        "archive_metadata": provenance, "weather_coverage": coverage(retrospective),
        "prior_baseline": old, "backtest": backtest_summary,
    }
