"""Deterministic synthetic overlay on the accepted Stage 1 movement fixture."""

from dataclasses import dataclass
from datetime import date, timedelta

from ..stage1.fixture import END, FINAL_CUTOFF, START, animal_id, fixture as stage1_fixture, local
from ..stage1.model import EventKind
from .biology import Biology, WeatherDay, make_profile
from .config import load_config
from .estimation import Estimator, Model, assess_draft, operational_health
from .health import Action, ClinicalInput, build_health
from .observations import Kind, Observations, WeighPlan, correct, simulate_observations
from .timeline import PhysicalTimeline

# Age and liveweight at opening/receipt. These are independent of terminal outcomes.
PROFILE_INPUTS = (
    ("Angus-cross", "steer", "large", 462.0, 385),
    ("Hereford-cross", "heifer", "medium", 437.0, 398),
    ("Charolais-cross", "steer", "large", 382.0, 332),
    ("Angus-cross", "steer", "large", 572.0, 459),
    ("Angus-cross", "steer", "medium", 448.0, 367),
    ("Hereford-cross", "heifer", "medium", 427.0, 357),
    ("Charolais-cross", "steer", "large", 442.0, 361),
    ("Angus-cross", "steer", "medium", 365.0, 320),
    ("Hereford-cross", "heifer", "medium", 391.0, 336),
    ("Charolais-cross", "steer", "large", 402.0, 349),
    ("Angus-cross", "steer", "medium", 417.0, 350),
    ("Angus-cross", "heifer", "medium", 548.0, 439),
)

# Independent scripted scenarios. Hospital admission/return and death come from Stage 1.
CLINICAL_PLAN = {
    1: (
        ("2024-01-28 07:00", Action.ONSET, "severe", None),
        ("2024-01-28 12:00", Action.PULL, None, None),
        ("2024-01-28 12:30", Action.TREAT, None, "low"),
        ("2024-01-30 08:00", Action.REASSESS, None, None),
    ),
    2: (
        ("2023-12-31 07:00", Action.ONSET, "mild", None),
        ("2023-12-31 09:30", Action.PULL, None, None),
        ("2023-12-31 10:30", Action.TREAT, None, "moderate"),
        ("2023-12-31 19:00", Action.REASSESS, None, None),
        ("2024-01-01 06:30", Action.RECOVER, None, None),
    ),
    5: (
        ("2024-01-20 22:00", Action.ONSET, "moderate", None),
        ("2024-01-21 07:00", Action.PULL, None, None),
        ("2024-01-21 09:00", Action.TREAT, None, "moderate"),
        ("2024-01-23 07:00", Action.REASSESS, None, None),
        ("2024-01-24 07:30", Action.RECOVER, None, None),
    ),
    8: (("2024-01-01 12:00", Action.ONSET, "severe", None),),
    9: (
        ("2024-03-03 07:00", Action.ONSET, "mild", None),
        ("2024-03-04 07:00", Action.PULL, None, None),
        ("2024-03-06 09:00", Action.REASSESS, None, None),
        ("2024-03-08 09:00", Action.CHRONIC, None, None),
    ),
    10: (
        ("2024-03-09 16:00", Action.ONSET, "moderate", None),
        ("2024-03-10 01:30", Action.PULL, None, None),
        ("2024-03-10 04:00", Action.TREAT, None, "low"),
        ("2024-03-10 09:00", Action.REASSESS, None, None),
        ("2024-03-10 10:30", Action.REPEAT, None, "moderate"),
        ("2024-03-10 16:00", Action.REASSESS, None, None),
        ("2024-03-10 19:30", Action.RECOVER, None, None),
    ),
}


def clinical_inputs():
    return tuple(ClinicalInput(
        f"SYN-CLINICAL-{n:02d}-{index:02d}", animal_id(n), action, local(when),
        severity=severity, treatment_response=response,
    ) for n, events in CLINICAL_PLAN.items()
        for index, (when, action, severity, response) in enumerate(events, 1))


def weather_inputs():
    return tuple(WeatherDay(
        f"SYN-WEATHER-{day}", date.fromisoformat(day), local(f"{day} 12:00"),
        local(available), scenario,
    ) for day, available, scenario in (
        ("2024-01-12", "2024-01-13 09:00", "cold_snap"),
        ("2024-01-13", "2024-01-14 09:00", "cold_snap"),
        ("2024-03-10", "2024-03-12 09:00", "neutral"),
    ))


def weighing_plans(timeline):
    rows = []
    for animal, event in sorted(timeline.entries.items()):
        kind = Kind.OPENING if event.kind == EventKind.OPENING else Kind.RECEIVING
        rows.append(WeighPlan(
            f"SYN-SCALE-{animal}-{kind}", animal, kind, event.effective_at,
            missing_probability=1.0 if animal == animal_id(11) else None,
            movement_event_id=event.event_id,
        ))
    for animal, event in sorted(timeline.exits.items()):
        if event.kind == EventKind.SALE:
            rows.append(WeighPlan(
                f"SYN-SCALE-{animal}-sale", animal, Kind.FINAL_SALE,
                event.effective_at - timedelta(minutes=5),
                timedelta(minutes=45), timedelta(hours=2),
                missing_probability=1.0 if animal == animal_id(4) else None,
                movement_event_id=event.event_id,
            ))

    for n, when, kind, days, missing in (
        (1, "2024-01-08 12:00", Kind.FOLLOW_UP, 0, None),
        (2, "2023-12-31 13:00", Kind.HOSPITAL, 0, 0.0),
        (2, "2024-01-30 12:00", Kind.FOLLOW_UP, 0, 1.0),
        (2, "2024-03-04 12:00", Kind.FOLLOW_UP, 0, 0.0),
        (3, "2024-01-07 12:00", Kind.FOLLOW_UP, 0, 0.0),
        (3, "2024-01-30 12:00", Kind.FOLLOW_UP, 0, None),
        (3, "2024-03-06 12:00", Kind.FOLLOW_UP, 0, 0.0),
        (5, "2024-01-14 12:00", Kind.FOLLOW_UP, 3, 0.0),
        (5, "2024-01-29 12:00", Kind.DRAFTING, 0, 0.0),
        (6, "2024-01-09 12:00", Kind.FOLLOW_UP, 0, None),
        (7, "2024-01-31 12:00", Kind.FOLLOW_UP, 0, 0.0),
        (7, "2024-02-27 12:00", Kind.DRAFTING, 0, 0.0),
        (9, "2024-03-08 11:00", Kind.FOLLOW_UP, 0, None),
        (10, "2024-03-10 11:00", Kind.HOSPITAL, 0, 0.0),
        (11, "2024-03-11 12:00", Kind.FOLLOW_UP, 0, 0.0),
        (12, "2024-03-10 20:30", Kind.DRAFTING, 0, 0.0),
    ):
        rows.append(WeighPlan(f"SYN-SCALE-{n:02d}-{when[:10]}-{kind}", animal_id(n), kind,
                              local(when), timedelta(days=days, minutes=10),
                              missing_probability=missing))
    return tuple(rows)


@dataclass(frozen=True)
class Fixture:
    ledger: object
    timeline: PhysicalTimeline
    config: dict
    profiles: tuple
    weather: tuple
    clinical_inputs: tuple
    health: tuple
    biology: Biology
    weighing_plans: tuple
    attempts: tuple
    observations: Observations
    estimator: Estimator


def build_fixture(seed=42, *, ledger=None, clinical=None, weather=None, config=None):
    if ledger is None:
        ledger = stage1_fixture(seed)
    if config is None:
        config = load_config()
    timeline = PhysicalTimeline(ledger, FINAL_CUTOFF, FINAL_CUTOFF)
    inputs = clinical_inputs() if clinical is None else tuple(clinical)
    weather = weather_inputs() if weather is None else tuple(weather)
    profiles = []
    for n, (breed, sex, frame, kg, age) in enumerate(PROFILE_INPUTS, 1):
        profiles.append(make_profile(timeline, config, animal_id(n), breed=breed, sex=sex,
                                     frame=frame, entry_weight_kg=kg, entry_age_days=age))
    health = build_health(timeline, inputs, config)
    biology = Biology(timeline, profiles, health, weather, config)
    plans = weighing_plans(timeline)
    attempts, records = simulate_observations(timeline, biology, plans, config)
    parent = next(row for row in records if row.source_event_id == "SYN-SCALE-05-2024-01-14-follow_up")
    correction = correct(
        parent, source_id="SYN-SCALE-CORR-05-JAN14", posted_at=local("2024-01-19 08:00"),
        available_at=local("2024-01-19 10:00"), measured_weight_kg=round(parent.measured_weight_kg - 1.6, 1),
    )
    observations = Observations(timeline, (*records, correction), config)
    estimator = Estimator(ledger, observations, operational_health(health), config)
    return Fixture(ledger, timeline, config, tuple(profiles), weather, inputs, health, biology,
                   plans, attempts, observations, estimator)


def draft_example(estimator):
    snapshot, estimates = estimator.estimates(local("2024-01-29 12:30"),
                                               models=(Model.B,), animal_id=animal_id(5))
    return snapshot, estimates, assess_draft(estimates[0], threshold_kg=470.0)
