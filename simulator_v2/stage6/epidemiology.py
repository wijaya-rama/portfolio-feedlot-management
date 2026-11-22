"""Epidemiological event bridge, exposure-adjusted mortality rates, and Markov verification."""

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import json
from math import inf, isfinite
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq

from ..stage2.health import Action

DAY = timedelta(days=1)
SEVERITIES = ("mild", "moderate", "severe")
HEALTH_RNG_STREAMS = (
    "health/background-death",
    "health/onset",
    "health/severity",
    "health/episode-death",
    "health/detection",
    "health/treatment",
    "health/recovery",
    "health/chronic",
    "health/repeat",
)


def _read_table(root, name, columns=None):
    rows = []
    for path in sorted(Path(root).glob(f"{name}/**/*.parquet")):
        rows.extend(pq.ParquetFile(path).read(columns=columns).to_pylist())
    return rows


def _review_cycle(death, days):
    survival = 1.0 - death
    exposure = sum(survival ** k for k in range(days))
    return death * exposure, survival ** days, exposure


def _detected_outcomes(health, severity, recovery):
    days = health["reassess_days"]
    chronic_after = health["chronic_after_days"]
    chronic_prob = health["chronic_probability"]
    acute_death = health["detected_death_daily"][severity]
    chronic_death = health.get("chronic_death_daily", acute_death)
    die, survive, exposure = _review_cycle(acute_death, days)
    die_chronic, survive_chronic, exposure_chronic = _review_cycle(chronic_death, days)

    chronic_exit = die_chronic + survive_chronic * recovery
    acute_continue = survive * (1.0 - recovery)
    to_chronic = acute_continue * chronic_prob
    acute_exit = die + survive * recovery + to_chronic
    if acute_exit:
        die_after, days_after = die, exposure
        if to_chronic:
            die_after += to_chronic * (die_chronic / chronic_exit if chronic_exit else 0.0)
            days_after += to_chronic * (exposure_chronic / chronic_exit if chronic_exit else inf)
        die_after /= acute_exit
        days_after /= acute_exit
    else:
        die_after, days_after = 0.0, inf

    # Index by the number of reassessments before the episode can become chronic.
    outcomes = [(die_after, days_after)]
    for _ in range((chronic_after - 1) // days):
        prior_die, prior_days = outcomes[-1]
        if acute_continue:
            outcomes.append((die + acute_continue * prior_die, exposure + acute_continue * prior_days))
        else:
            outcomes.append((die, exposure))
    return outcomes


def markov_expected_rates(health_policy):
    """Exact episode CFR without competing sale exits, and approximate annualized rates."""
    days = health_policy["reassess_days"]
    compounded = health_policy.get("recovery_basis", "per_reassessment") == "daily_compounded"
    first_stationary_detection_day = health_policy["chronic_after_days"] - days

    by_severity = {}
    weighted_cfr = 0.0
    for idx, sev in enumerate(SEVERITIES):
        h_u = health_policy["untreated_death_daily"][idx]
        detect = (1.0 - h_u) * health_policy["detection_daily"][idx]
        leave_undetected = h_u + detect
        rec_raw = health_policy["recovery_daily"][idx]
        rec = 1.0 - (1.0 - rec_raw) ** days if compounded else rec_raw
        outcomes = _detected_outcomes(health_policy, idx, rec)

        post_detection_cfr, post_detection_days = None, None
        overall_cfr = h_u / leave_undetected if leave_undetected else 0.0
        if detect:
            # Conditional on detection before death, detection lag is geometric.
            survive_undetected = 1.0 - leave_undetected
            post_detection_cfr, post_detection_days = 0.0, 0.0
            for lag in range(first_stationary_detection_day):
                weight = survive_undetected ** lag * leave_undetected
                if weight:
                    reviews_before = (health_policy["chronic_after_days"] - 1 - lag) // days
                    cfr, duration = outcomes[reviews_before]
                    post_detection_cfr += weight * cfr
                    post_detection_days += weight * duration
            tail = survive_undetected ** first_stationary_detection_day
            if tail:
                post_detection_cfr += tail * outcomes[0][0]
                post_detection_days += tail * outcomes[0][1]
            overall_cfr += detect / leave_undetected * post_detection_cfr

        weighted_cfr += health_policy["severity_weights"][idx] * overall_cfr
        by_severity[sev] = {
            "effective_review_recovery_prob": round(rec, 6),
            "overall_cfr_pct": round(100.0 * overall_cfr, 3),
            "post_detection_cfr_pct": (
                round(100.0 * post_detection_cfr, 3) if post_detection_cfr is not None else None
            ),
            "expected_post_detection_days": (
                round(post_detection_days, 2)
                if post_detection_days is not None and isfinite(post_detection_days) else None
            ),
        }

    # Approximate average daily onset risk across a ~150-day stay (receiving + post-recovery multipliers)
    base_onset = health_policy["onset_daily"]
    avg_mult = (
        1.0
        + (3.0 / 150.0) * (health_policy["receiving_multiplier"] - 1.0)
        + min(0.5, base_onset * 25.0) * (health_policy["post_recovery_multiplier"] - 1.0)
    )
    episodes_100ay = base_onset * avg_mult * 365.25 * 100.0
    disease_deaths_100ay = episodes_100ay * weighted_cfr
    bg_deaths_100ay = health_policy["background_death_daily"] * 365.25 * 100.0
    return {
        "recovery_basis": health_policy.get("recovery_basis", "per_reassessment"),
        "chronic_death_daily": health_policy.get("chronic_death_daily"),
        "by_severity": by_severity,
        "weighted_episode_cfr_pct": round(100.0 * weighted_cfr, 3),
        "approx_episodes_per_100_animal_years": round(episodes_100ay, 2),
        "approx_disease_deaths_per_100_animal_years": round(disease_deaths_100ay, 2),
        "background_deaths_per_100_animal_years": round(bg_deaths_100ay, 2),
        "approx_total_deaths_per_100_animal_years": round(disease_deaths_100ay + bg_deaths_100ay, 2),
    }


def epidemiological_bridge(dataset_root):
    """Build the complete animal-time-at-risk -> onset -> detection -> treatment -> outcome bridge."""
    root = Path(dataset_root)
    config = json.loads((root / "config.json").read_bytes())
    outcomes = {r["animal_id"]: r for r in _read_table(root, "animal_outcomes")}
    locations = {r["location_id"]: r["kind"] for r in _read_table(root, "locations")}
    opening = _read_table(root, "opening_cattle", columns=["animal_id"])
    daily_yard = [r for r in _read_table(root, "daily_soh") if r["scope_type"] == "yard"]
    events = sorted(_read_table(root, "health_events"), key=lambda r: (r["effective_at"], r["health_event_id"]))
    movements = _read_table(root, "movement_events", columns=["animal_id", "kind"])

    status_counts = Counter(r["status"] for r in outcomes.values())
    total_animals = len(outcomes)
    opening_count = len(opening)
    placement_count = sum(1 for r in movements if r["kind"] == "receipt")
    deaths = status_counts["dead"]
    sold = status_counts["sold"]
    carry_out = status_counts["active"]

    cal_animal_days = sum(r["animal_days"] for r in daily_yard)
    elapsed_animal_days = sum(r["simulated_days"] for r in outcomes.values())
    animal_years_cal = cal_animal_days / 365.25
    animal_years_elapsed = elapsed_animal_days / 365.25

    episodes = defaultdict(list)
    for ev in events:
        episodes[ev["episode_id"]].append(ev)

    onset_episodes = 0
    background_deaths = 0
    affected_animals = set()
    animals_severe = set()
    animals_detected = set()
    animals_treated = set()
    animals_chronic = set()
    animals_admitted = set()
    ep_per_animal = Counter()

    onset_by_loc = Counter()
    ep_counts = {sev: Counter() for sev in SEVERITIES}
    days_to_detect = defaultdict(list)
    days_to_recover = defaultdict(list)
    days_to_death = defaultdict(list)
    death_breakdown = Counter()
    censored_unrecovered = Counter()

    for ep_id, evs in episodes.items():
        first = evs[0]
        animal_id = first["animal_id"]
        actions = [e["action"] for e in evs]
        if first["action"] == Action.DEATH and len(evs) == 1 and first["severity"] is None:
            background_deaths += 1
            death_breakdown["background_death"] += 1
            continue

        onset_episodes += 1
        sev = first["severity"]
        affected_animals.add(animal_id)
        ep_per_animal[animal_id] += 1
        if sev == "severe":
            animals_severe.add(animal_id)
        onset_by_loc[locations.get(first["location_id"], "unknown")] += 1

        c = ep_counts[sev]
        c["onsets"] += 1
        was_detected = Action.PULL in actions
        was_treated = Action.TREAT in actions
        was_repeat = Action.REPEAT in actions
        was_admitted = Action.ADMIT in actions
        was_chronic = Action.CHRONIC in actions
        was_recovered = Action.RECOVER in actions
        was_dead = Action.DEATH in actions

        if was_detected:
            c["detected"] += 1
            animals_detected.add(animal_id)
            pull = next(e for e in evs if e["action"] == Action.PULL)
            days_to_detect[sev].append((pull["effective_at"] - first["effective_at"]) / DAY)
        if was_treated:
            c["treated"] += 1
            animals_treated.add(animal_id)
        if was_repeat:
            c["repeat_treated_episodes"] += 1
        c["repeat_treatment_services"] += sum(1 for a in actions if a == Action.REPEAT)
        if was_admitted:
            c["hospital_admitted"] += 1
            animals_admitted.add(animal_id)
        if was_chronic:
            c["chronic"] += 1
            animals_chronic.add(animal_id)
        if was_recovered:
            c["recovered"] += 1
            rec = next(e for e in evs if e["action"] == Action.RECOVER)
            days_to_recover[sev].append((rec["effective_at"] - first["effective_at"]) / DAY)
        if was_dead:
            c["died"] += 1
            d_ev = next(e for e in evs if e["action"] == Action.DEATH)
            d_days = (d_ev["effective_at"] - first["effective_at"]) / DAY
            days_to_death[sev].append(d_days)
            if not was_detected:
                stage = "onset_day_undetected" if d_days == 0 else "post_onset_undetected"
            elif was_chronic:
                stage = "chronic"
            else:
                stage = f"detected_acute_{'treated' if was_treated else 'untreated'}"
            death_breakdown[f"{sev}_{stage}"] += 1
        elif not was_recovered:
            censored_unrecovered[f"{sev}_{outcomes[animal_id]['status']}"] += 1

    by_severity = {}
    for sev in SEVERITIES:
        c = ep_counts[sev]
        onsets = c["onsets"]
        by_severity[sev] = {
            "onsets": onsets,
            "detected": c["detected"],
            "treated": c["treated"],
            "repeat_treated_episodes": c["repeat_treated_episodes"],
            "repeat_treatment_services": c["repeat_treatment_services"],
            "hospital_admitted": c["hospital_admitted"],
            "chronic": c["chronic"],
            "recovered": c["recovered"],
            "died": c["died"],
            "cfr_pct": round(100.0 * c["died"] / onsets, 2) if onsets else 0.0,
            "median_days_to_detect": round(median(days_to_detect[sev]), 2) if days_to_detect[sev] else None,
            "median_days_to_recover": round(median(days_to_recover[sev]), 2) if days_to_recover[sev] else None,
            "median_days_to_death": round(median(days_to_death[sev]), 2) if days_to_death[sev] else None,
        }

    return {
        "config_version": config["version"],
        "health_scenario_version": config["health"].get("scenario_version", "stage6b-adverse-health.1-legacy"),
        "seed": config["seed"],
        "denominators_and_competing_exits": {
            "carry_in_opening": opening_count,
            "placements": placement_count,
            "total_animals_at_risk": total_animals,
            "sold_exits": sold,
            "death_exits": deaths,
            "carry_out_censored": carry_out,
            "competing_exit_proportions_pct": {
                "sold_pct": round(100.0 * sold / total_animals, 2),
                "died_pct": round(100.0 * deaths / total_animals, 2),
                "carry_out_censored_pct": round(100.0 * carry_out / total_animals, 2),
            },
            "calendar_animal_days": cal_animal_days,
            "elapsed_animal_days": round(elapsed_animal_days, 2),
            "mean_elapsed_days_per_animal": round(elapsed_animal_days / total_animals, 2),
            "animal_years_calendar": round(animal_years_cal, 3),
            "animal_years_elapsed": round(animal_years_elapsed, 3),
        },
        "mortality_metrics": {
            "crude_mortality_proportion_pct": round(100.0 * deaths / total_animals, 2),
            "deaths_per_1000_calendar_animal_days": round(1000.0 * deaths / cal_animal_days, 4),
            "deaths_per_1000_elapsed_animal_days": round(1000.0 * deaths / elapsed_animal_days, 4),
            "annualized_deaths_per_100_animal_years_calendar": round(100.0 * deaths / animal_years_cal, 2),
            "annualized_deaths_per_100_animal_years_elapsed": round(100.0 * deaths / animal_years_elapsed, 2),
            "background_deaths": background_deaths,
            "disease_attributed_deaths": deaths - background_deaths,
            "death_breakdown_by_severity_and_stage": dict(sorted(death_breakdown.items())),
        },
        "animal_level_incidence": {
            "animals_with_any_onset": len(affected_animals),
            "animal_attack_proportion_pct": round(100.0 * len(affected_animals) / total_animals, 2),
            "animals_with_repeat_episodes": sum(v > 1 for v in ep_per_animal.values()),
            "animals_detected": len(animals_detected),
            "animals_treated": len(animals_treated),
            "animals_hospital_admitted": len(animals_admitted),
            "animals_severe": len(animals_severe),
            "animals_chronic": len(animals_chronic),
        },
        "episode_level_bridge": {
            "total_onset_episodes": onset_episodes,
            "episodes_per_100_animal_years_elapsed": round(100.0 * onset_episodes / animal_years_elapsed, 2),
            "onset_by_location_kind": dict(sorted(onset_by_loc.items())),
            "by_severity": by_severity,
            "censored_while_unrecovered": dict(sorted(censored_unrecovered.items())),
            "action_totals": dict(sorted(Counter(e["action"] for e in events).items())),
        },
        "rng_stream_independence": {
            "distinct_streams": list(HEALTH_RNG_STREAMS),
            "all_streams_distinct": len(set(HEALTH_RNG_STREAMS)) == len(HEALTH_RNG_STREAMS),
            "note": "Each health draw uses SHA-256 over (seed, 'stage6a/<stream>', animal_id, day_or_episode), independent of feed/weight/carcass/finance streams.",
        },
        "theoretical_markov_expectation": markov_expected_rates(config["health"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = epidemiological_bridge(args.dataset)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
