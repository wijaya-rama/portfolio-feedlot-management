"""Run configuration, synthetic master records and animal event contracts."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = timezone.utc
_ZERO = timedelta(0)
CALENDAR = "America/Edmonton"
EDMONTON = ZoneInfo(CALENDAR)
SCHEMA_VERSION = "stage1.1"
POLICY_VERSION = "livestock.1"


def is_utc(value):
    if type(value) is datetime:
        if value.tzinfo is UTC:
            return True
        return value.utcoffset() == _ZERO
    return isinstance(value, datetime) and value.utcoffset() == _ZERO


@lru_cache(maxsize=16384)
def _business_date_utc(instant):
    return instant.astimezone(EDMONTON).date()


def business_date(instant):
    if type(instant) is datetime and instant.tzinfo is UTC:
        return _business_date_utc(instant)
    if not is_utc(instant):
        raise ValueError("business_date requires a UTC timestamp")
    return instant.astimezone(EDMONTON).date()


@lru_cache(maxsize=4096)
def midnight(day):
    return datetime.combine(day, time.min, EDMONTON).astimezone(UTC)


class LocationKind(StrEnum):
    PRODUCTION = "production"
    RECEIVING = "receiving"
    HOSPITAL = "hospital"


class EventKind(StrEnum):
    OPENING = "opening"
    RECEIPT = "receipt"
    TRANSFER = "transfer"
    SALE = "sale"
    DEATH = "death"
    REVERSAL = "reversal"


class AnimalStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SOLD = "sold"
    DEAD = "dead"


@dataclass(frozen=True)
class RunConfig:
    scenario: str
    seed: int
    start_date: date
    end_date: date
    synthetic: bool = True
    calendar: str = CALENDAR
    schema_version: str = SCHEMA_VERSION
    policy_version: str = POLICY_VERSION

    def __post_init__(self):
        if (not self.scenario.strip() or type(self.seed) is not int
                or type(self.start_date) is not date or type(self.end_date) is not date
                or not self.start_date <= self.end_date < date.max
                or self.synthetic is not True or self.calendar != CALENDAR
                or self.schema_version != SCHEMA_VERSION or self.policy_version != POLICY_VERSION):
            raise ValueError("invalid Stage 1 configuration")


@dataclass(frozen=True)
class Lot:
    lot_id: str
    supplier_id: str
    compatibility_group: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    synthetic: bool = True


@dataclass(frozen=True)
class Animal:
    animal_id: str
    lot_id: str
    rfid: str
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    synthetic: bool = True


@dataclass(frozen=True)
class LocationVersion:
    location_version_id: str
    location_id: str
    kind: LocationKind
    capacity_head: int
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    synthetic: bool = True


@dataclass(frozen=True)
class Source:
    system: str
    document_id: str
    line_id: str
    revision: int = 1
    synthetic: bool = True


@dataclass(frozen=True)
class AnimalEvent:
    event_id: str
    animal_id: str
    kind: EventKind
    effective_at: datetime
    posted_at: datetime
    available_at: datetime
    sequence: int
    source: Source
    from_location_id: str | None = None
    to_location_id: str | None = None
    supersedes_event_id: str | None = None
    reason: str | None = None
    synthetic: bool = True

    @property
    def order(self):
        return self.effective_at, self.sequence, self.event_id
