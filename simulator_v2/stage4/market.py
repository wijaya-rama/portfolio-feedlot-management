"""Non-posting liveweight estimate using only information available at close."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from ..stage1.fixture import local
from ..stage2.estimation import Model


@dataclass(frozen=True)
class Quote:
    quote_id: str
    region: str
    category: str
    unit: str
    observed_at: datetime
    available_at: datetime
    cents_per_kg: int
    source: str = "synthetic_management_scenario"


@dataclass(frozen=True)
class MarketValue:
    month: str
    estimate_snapshot_id: str
    animal_id: str
    lot_id: str
    location_id: str
    effective_before: datetime
    knowledge_cutoff: datetime
    estimate_id: str
    estimated_liveweight_g: int | None
    weight_observation_id: str | None
    weight_available_at: datetime | None
    quote_id: str | None
    quote_available_at: datetime | None
    category: str
    region: str
    estimated_value_cents: int | None
    coverage_status: str


def quote_for(quotes, *, cutoff, category, region, maximum_age_days):
    return max((row for row in quotes
                if 0 < row.cents_per_kg and row.category == category and row.region == region
                and row.unit == "CAD_cents_per_kg_live"
                and cutoff - timedelta(days=maximum_age_days) <= row.observed_at < cutoff
                and row.observed_at <= row.available_at <= cutoff),
               key=lambda row: (row.observed_at, row.available_at, row.quote_id), default=None)


def valuation(fixture):
    config = fixture.config["market"]
    region = config["region"]
    quotes = tuple(Quote(key, region, category, config["unit"], local(observed), local(available), cents)
                   for key, observed, available, category, cents in config["quotes"])
    profiles = {row.animal_id: row for row in fixture.operations.profiles}
    values = []
    for period in fixture.calendar:
        cutoff = period.effective_before
        snapshot, estimates = fixture.operations.final_estimator.estimates(cutoff, models=(Model.B,))
        for estimate in estimates:
            category = profiles[estimate.animal_id].sex
            quote = quote_for(quotes, cutoff=cutoff, category=category, region=region,
                              maximum_age_days=config["maximum_age_days"])
            kg = estimate.estimated_liveweight_kg
            valid = (kg is not None and kg > 0 and estimate.last_measured_at is not None
                     and estimate.last_available_at is not None
                     and estimate.last_measured_at < cutoff
                     and estimate.last_available_at <= cutoff
                     and estimate.confidence_status != "low_stale")
            weight = int((Decimal(str(kg)) * 1000).to_integral_value(rounding=ROUND_HALF_UP)) if valid else None
            cents = (weight * quote.cents_per_kg + 500) // 1000 if valid and quote else None
            coverage = "covered" if cents is not None else "weight_gap" if not valid else "live_quote_gap"
            values.append(MarketValue(
                period.month, snapshot.snapshot_id, estimate.animal_id, estimate.lot_id, estimate.location_id,
                cutoff, snapshot.knowledge_cutoff, estimate.estimate_id, weight,
                estimate.last_observation_id, estimate.last_available_at,
                quote.quote_id if quote else None, quote.available_at if quote else None, category, region,
                cents, coverage))
    return quotes, tuple(values)


@dataclass(frozen=True)
class MarketCoverage:
    month: str
    active_head: int
    covered_head: int
    missing_quote_head: int
    missing_weight_head: int
    covered_value_cents: int | None
    full_yard_value_cents: int | None


def coverage(market, calendar):
    groups = defaultdict(list)
    for row in market:
        groups[row.month].append(row)
    for period in calendar:
        rows = groups[period.month]
        covered = [row.estimated_value_cents for row in rows if row.estimated_value_cents is not None]
        partial = sum(covered) if covered else None
        total = partial if len(covered) == len(rows) else None
        yield MarketCoverage(period.month, len(rows), len(covered),
                             sum(row.coverage_status == "live_quote_gap" for row in rows),
                             sum(row.coverage_status == "weight_gap" for row in rows), partial, total)
