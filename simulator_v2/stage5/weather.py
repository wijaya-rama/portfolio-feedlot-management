"""Preserve archive UTC intervals and isolate retrospective and as-of weather."""

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path

from ..stage1.model import CALENDAR, UTC, business_date, is_utc, midnight
from ..stage1.provenance import sha256

ARCHIVE = (Path(__file__).resolve().parents[2] / "phase2a" / "weather"
           / "era5-20261121T143547299379Z-fd9571517552")
HORIZON = date(2024, 1, 1), date(2025, 12, 31)
DAY = timedelta(days=1)
UNITS = {
    "temperature_2m_mean": "°C", "temperature_2m_min": "°C", "temperature_2m_max": "°C",
    "apparent_temperature_mean": "°C", "wind_speed_10m_max": "km/h",
    "wind_gusts_10m_max": "km/h", "precipitation_sum": "mm", "snowfall_sum": "cm",
    "relative_humidity_2m_mean": "%",
}


@dataclass(frozen=True)
class ArchiveDay:
    source_id: str
    day: date
    start_at: datetime
    end_at: datetime
    values: dict


@dataclass(frozen=True)
class Forecast:
    source_id: str
    day: date
    issued_at: datetime
    available_at: datetime
    mean_c: float


@dataclass(frozen=True)
class Exposure:
    source_id: str
    kind: str
    mean_c: float


def load_archive(path=ARCHIVE):
    manifest = json.loads((path / "weather_manifest.json").read_bytes())
    raw = (path / "open_meteo_raw.json").read_bytes()
    clean = (path / "weather_daily.csv").read_bytes()
    if (sha256(raw) != manifest["raw_sha256"] or sha256(clean) != manifest["clean_sha256"]):
        raise ValueError("weather archive digest mismatch")
    payload = json.loads(raw)
    metadata = {"latitude": "grid_latitude", "longitude": "grid_longitude", "elevation": "elevation_m",
                "timezone": "timezone", "utc_offset_seconds": "utc_offset_seconds"}
    if (any(payload[key] != manifest[value] for key, value in metadata.items())
            or payload["timezone"] != CALENDAR or payload["utc_offset_seconds"] != -21600
            or payload["daily_units"] != {"time": "iso8601", **UNITS}
            or manifest["expected_daily_units"] != UNITS or manifest["daily_units"] != UNITS):
        raise ValueError("unexpected weather grid, time or units")
    daily = payload["daily"]
    dates = tuple(date.fromisoformat(value) for value in daily["time"])
    first, last = (date.fromisoformat(manifest[key]) for key in ("first_date", "last_date"))
    expected = tuple(first + i * DAY for i in range((last - first).days + 1))
    if (dates != expected or len(dates) != manifest["date_count"] or set(daily) != {"time", *UNITS}
            or any(len(daily[key]) != len(dates) for key in UNITS)):
        raise ValueError("weather dates or variable coverage do not match the manifest")
    utc_offset = timezone(timedelta(seconds=payload["utc_offset_seconds"]))
    rows = []
    for index, day in enumerate(dates):
        values = {key: daily[key][index] for key in UNITS}
        if (any(type(value) not in (float, int) or not isfinite(value) for value in values.values())
                or not -90 <= values["temperature_2m_min"] <= values["temperature_2m_mean"]
                <= values["temperature_2m_max"] <= 60
                or not -120 <= values["apparent_temperature_mean"] <= 70
                or not 0 <= values["relative_humidity_2m_mean"] <= 100
                or any(values[key] < 0 for key in ("wind_speed_10m_max", "wind_gusts_10m_max",
                                                  "precipitation_sum", "snowfall_sum"))):
            raise ValueError(f"invalid daily weather measurements for {day}")
        start = datetime.combine(day, time.min, utc_offset).astimezone(UTC)
        rows.append(ArchiveDay(f"OPEN-METEO-{manifest['raw_sha256'][:12]}-{day}", day, start, start + DAY, values))
    return tuple(rows), manifest


class Weather:
    """Forecast vintages are selected at the day-open cutoff. Archive values are retrospective only."""

    def __init__(self, mode, fallback_monthly_c, *, archive=(), forecasts=(), scenario_c=None):
        if mode not in {"retrospective", "operational_as_of", "controlled"}:
            raise ValueError("unknown weather mode")
        if (len(fallback_monthly_c) != 12 or not all(isfinite(x) and -90 <= x <= 60 for x in fallback_monthly_c)
                or (archive and mode != "retrospective") or (forecasts and mode != "operational_as_of")
                or (scenario_c is not None) != (mode == "controlled")
                or (scenario_c is not None and not -90 <= scenario_c <= 60)):
            raise ValueError("weather source is incompatible with the selected mode")
        self.mode = mode
        self.fallback = tuple(fallback_monthly_c)
        self.archive = tuple(sorted(archive, key=lambda row: row.start_at))
        self.breakpoints = tuple(sorted({t for row in archive for t in (row.start_at, row.end_at)}))
        self.starts = tuple(row.start_at for row in self.archive)
        if any(a.end_at > b.start_at for a, b in zip(self.archive, self.archive[1:])):
            raise ValueError("retrospective archive has overlapping intervals")
        self.forecasts = {}
        self.scenario_c = scenario_c
        ids = set()
        for row in forecasts:
            if (not row.source_id.strip() or row.source_id in ids or type(row.day) is not date
                    or not is_utc(row.issued_at) or not is_utc(row.available_at)
                    or row.issued_at > row.available_at or not -90 <= row.mean_c <= 60):
                raise ValueError("invalid forecast vintage")
            ids.add(row.source_id)
            if row.available_at <= midnight(row.day):
                current = self.forecasts.get(row.day)
                if current is None or (row.issued_at, row.available_at, row.source_id) > (
                        current.issued_at, current.available_at, current.source_id):
                    self.forecasts[row.day] = row

    def points(self, first, last):
        return self.breakpoints[bisect_right(self.breakpoints, first):bisect_left(self.breakpoints, last)]

    def at(self, instant):
        day = business_date(instant)
        if self.mode == "controlled":
            return Exposure(f"SYN-CONTROLLED-{self.scenario_c}", "controlled", self.scenario_c)
        if self.mode == "retrospective":
            index = bisect_right(self.starts, instant) - 1
            if index >= 0 and instant < self.archive[index].end_at:
                row = self.archive[index]
                return Exposure(row.source_id, "archive_reanalysis", row.values["temperature_2m_mean"])
        else:
            forecast = self.forecasts.get(day)
            if forecast:
                return Exposure(forecast.source_id, "issued_forecast", forecast.mean_c)
        return Exposure(f"SYN-SEASONAL-{day:%m}", "seasonal_fallback", self.fallback[day.month - 1])


def coverage(weather):
    start, end = midnight(HORIZON[0]), midnight(HORIZON[1] + DAY)
    sources = {"archive_reanalysis": 0, "seasonal_fallback": 0}
    by_day = {}
    day = HORIZON[0]
    while day <= HORIZON[1]:
        first, last = midnight(day), midnight(day + DAY)
        grid = (first, *weather.points(first, last), last)
        hours = {key: 0 for key in sources}
        for left, right in zip(grid, grid[1:]):
            hours[weather.at(left).kind] += int((right - left).total_seconds() / 3600)
        by_day[str(day)] = hours
        for key, count in hours.items():
            sources[key] += count
        day += DAY
    labels = {row.day for row in weather.archive}
    return {
        "horizon": [HORIZON[0], HORIZON[1]], "calendar_hours": (end - start).total_seconds() / 3600,
        "archive_date_labels": sum(HORIZON[0] <= day <= HORIZON[1] for day in labels),
        "missing_date_labels": [key for key in by_day if date.fromisoformat(key) not in labels],
        "hours_by_source": sources,
        "business_days_fully_archive": sum(not row["seasonal_fallback"] for row in by_day.values()),
        "business_days_fully_fallback": sum(not row["archive_reanalysis"] for row in by_day.values()),
        "mixed_business_days": {key: row for key, row in by_day.items() if all(row.values())},
        "unaligned_archive_labels": sum(midnight(row.day) != row.start_at or
                                       midnight(row.day + DAY) != row.end_at for row in weather.archive),
    }
