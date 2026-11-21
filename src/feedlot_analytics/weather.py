"""Acquire, validate and replay the single ERA5 weather reference."""

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .loaders import calendar_dates, sha256
from .relations import add_columns, require_key, safe_ratio

LOCATION = "Representative Southern Alberta Feedlot Weather Reference"
LATITUDE = 49.87672
LONGITUDE = -112.77983
GEOGRAPHIC_SOURCE = (
    "https://www.circularmaterials.ca/wp-content/uploads/2025/04/"
    "Appendix-M-Information_FA-03272025-addendum-5-tracked-changes-redlined.pdf#page=20"
)
MODEL = "era5"
TIMEZONE = "America/Edmonton"
START_DATE = "2024-01-01"
END_DATE = "2025-12-04"
COLD_THRESHOLD_C = 0.0
CLOSED_SHELTER = "Confinement Barn"
PROVIDER = "Open-Meteo Historical Weather API"
API_DOCUMENTATION = "https://open-meteo.com/en/docs/historical-weather-api"
ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"

DAILY_UNITS = {
    "temperature_2m_mean": "°C",
    "temperature_2m_min": "°C",
    "temperature_2m_max": "°C",
    "apparent_temperature_mean": "°C",
    "wind_speed_10m_max": "km/h",
    "wind_gusts_10m_max": "km/h",
    "precipitation_sum": "mm",
    "snowfall_sum": "cm",
    "relative_humidity_2m_mean": "%",
}
REQUEST_PARAMS = {
    "latitude": LATITUDE, "longitude": LONGITUDE, "models": MODEL, "timezone": TIMEZONE,
    "start_date": START_DATE, "end_date": END_DATE, "daily": ",".join(DAILY_UNITS),
    "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
    "timeformat": "iso8601", "cell_selection": "land",
}
REQUEST_URL = ENDPOINT + "?" + urlencode(REQUEST_PARAMS)
EXPECTED_DATES = pd.date_range(START_DATE, END_DATE, name="date")


class WeatherSourceError(ValueError):
    """The weather source could not be acquired or validated."""


def reference_metadata():
    return {
        "provider": PROVIDER, "label": LOCATION, "request_url": REQUEST_URL,
        "request_parameters": REQUEST_PARAMS.copy(), "model": MODEL, "timezone": TIMEZONE,
        "geography": {
            "place": "Picture Butte town centroid, Lethbridge County area, Alberta, Canada",
            "latitude": LATITUDE, "longitude": LONGITUDE, "source": GEOGRAPHIC_SOURCE,
            "relationship": "The coordinate is the published Picture Butte town centroid.",
        },
        "requested_date_count": len(EXPECTED_DATES), "expected_daily_units": DAILY_UNITS.copy(),
        "day_boundary": "Open-Meteo fixed UTC offset for the response; DST transitions are not applied.",
        "metadata_sources": {
            "api": API_DOCUMENTATION,
            "daily_variable_implementation": "https://github.com/open-meteo/open-meteo/blob/"
            "7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa/Sources/App/Controllers/VariableDaily.swift",
            "era5_variable_implementation": "https://github.com/open-meteo/open-meteo/blob/"
            "7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa/Sources/App/Era5/Era5Variables.swift",
        },
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "terms_url": "https://open-meteo.com/en/terms",
        "attribution": "Weather data by Open-Meteo, based on Copernicus Climate Change Service ERA5 reanalysis.",
        "missing_policy": "Reject absent or duplicate dates. Retain null measurements and flag variable coverage. "
        "Whole-window features require complete data for their respective variable.",
    }


def empty_weather():
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[ns]"),
        **{name: pd.Series(dtype="float64") for name in DAILY_UNITS},
    })


def validate_response(raw: bytes):
    """Return a typed daily series and response metadata, without imputing gaps."""
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise WeatherSourceError("Expected a JSON response") from error
    if not isinstance(payload, dict) or payload.get("error"):
        raise WeatherSourceError(f"Open-Meteo response error: {payload.get('reason') if isinstance(payload, dict) else 'not an object'}")
    if payload.get("timezone") != TIMEZONE or payload.get("utc_offset_seconds") not in (-25200, -21600):
        raise WeatherSourceError("Unexpected timezone or UTC offset")
    if "model" in payload and payload["model"] != MODEL:
        raise WeatherSourceError("Unexpected weather model")
    for name, expected in (("latitude", LATITUDE), ("longitude", LONGITUDE)):
        value = payload.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value - expected) > .35:
            raise WeatherSourceError(f"Unexpected ERA5 grid {name}")
    elevation = payload.get("elevation")
    if elevation is not None and (type(elevation) not in (int, float) or not math.isfinite(elevation)):
        raise WeatherSourceError("Invalid grid elevation")
    if payload.get("daily_units") != {"time": "iso8601", **DAILY_UNITS}:
        raise WeatherSourceError("Unexpected daily weather units or variables")
    daily = payload.get("daily")
    if not isinstance(daily, dict) or set(daily) != {"time", *DAILY_UNITS}:
        raise WeatherSourceError("Missing or unexpected daily weather fields")
    if not all(isinstance(values, list) for values in daily.values()):
        raise WeatherSourceError("Daily weather fields must be arrays")
    try:
        dates = calendar_dates(pd.Series(daily["time"], name="date", dtype="string"))
    except ValueError as error:
        raise WeatherSourceError("Invalid weather date labels") from error
    if dates.duplicated().any():
        raise WeatherSourceError("Duplicate weather dates")
    if not pd.DatetimeIndex(dates).equals(EXPECTED_DATES):
        raise WeatherSourceError(f"Expected all {len(EXPECTED_DATES)} ordered dates {START_DATE} through {END_DATE}")
    daily_frame = dates.to_frame()
    for name in DAILY_UNITS:
        values = daily[name]
        if len(values) != len(dates) or any(
            value is not None and (type(value) not in (int, float) or not math.isfinite(value))
            for value in values
        ):
            raise WeatherSourceError(f"Invalid data array for {name}")
        daily_frame[name] = np.asarray(values, dtype="float64")
    for name, values in daily_frame[list(DAILY_UNITS)].items():
        lower, upper = (-90, 65) if "temperature" in name else (0, 500)
        if name == "relative_humidity_2m_mean":
            upper = 100
        if (values.notna() & ~values.between(lower, upper)).any():
            raise WeatherSourceError(f"Implausible daily measurements for {name}")
    for lower, upper in (
        ("temperature_2m_min", "temperature_2m_mean"),
        ("temperature_2m_mean", "temperature_2m_max"),
        ("temperature_2m_min", "temperature_2m_max"),
    ):
        if daily_frame[lower].gt(daily_frame[upper]).any():
            raise WeatherSourceError(f"Invalid temperature order: {lower} > {upper}")
    metadata = {
        "grid_latitude": payload["latitude"], "grid_longitude": payload["longitude"],
        "elevation_m": elevation, "utc_offset_seconds": payload["utc_offset_seconds"],
        "first_date": START_DATE, "last_date": END_DATE, "date_count": len(daily_frame),
        "daily_units": DAILY_UNITS.copy(),
        "missing_by_variable": {name: int(daily_frame[name].isna().sum()) for name in DAILY_UNITS},
    }
    return daily_frame, metadata


def _download(timeout, attempts):
    request = Request(REQUEST_URL, headers={"Accept": "application/json", "User-Agent": "feedlot-analytics/0.2"})
    for attempt in range(attempts):
        delay = min(2 ** attempt, 8)
        try:
            with urlopen(request, timeout=timeout) as response:
                if (response.status != 200 or response.geturl() != REQUEST_URL
                        or response.headers.get_content_type() != "application/json"):
                    raise WeatherSourceError("Expected HTTP 200 JSON from the exact Open-Meteo archive URL")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise WeatherSourceError("Unexpected response size")
                return raw
        except HTTPError as error:
            retryable = error.code in (408, 429, 500, 502, 503, 504)
            retry_after = error.headers.get("Retry-After", "")
            if retry_after.isdigit() and int(retry_after) > 30:
                retryable = False
            if retry_after.isdigit():
                delay = max(delay, int(retry_after))
            if not retryable or attempt + 1 == attempts:
                raise WeatherSourceError(f"Open-Meteo HTTP {error.code}: {error.reason}") from error
        except (URLError, TimeoutError) as error:
            if "403 Forbidden" in str(error) or attempt + 1 == attempts:
                raise WeatherSourceError(f"Open-Meteo connection failed: {error}") from error
        time.sleep(delay)
    raise WeatherSourceError("No Open-Meteo request attempted")


def fetch_snapshot(destination: Path, *, timeout=20, attempts=3) -> Path:
    """Store a validated, immutable version with raw response, clean CSV and provenance."""
    raw = _download(timeout, attempts)
    daily, response = validate_response(raw)
    extracted = datetime.now(timezone.utc)
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()
        raw_path = staging / "open_meteo_raw.json"
        clean_path = staging / "weather_daily.csv"
        raw_path.write_bytes(raw)
        daily.to_csv(clean_path, index=False, date_format="%Y-%m-%d", lineterminator="\n")
        digest = sha256(raw_path)
        manifest = {
            **reference_metadata(), **response, "status": "verified",
            "extracted_at_utc": extracted.isoformat(), "raw_sha256": digest,
            "clean_sha256": sha256(clean_path),
        }
        (staging / "weather_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        version = destination / f"era5-{extracted.strftime('%Y%m%dT%H%M%S%fZ')}-{digest[:12]}"
        staging.rename(version)
    return version


def load_snapshot(directory: Path):
    """Replay the archived response and validate its request and hashes."""
    with (directory / "weather_manifest.json").open(encoding="utf-8") as file:
        manifest = json.load(file)
    raw = directory / "open_meteo_raw.json"
    clean = directory / "weather_daily.csv"
    if (manifest.get("status") != "verified" or manifest.get("request_url") != REQUEST_URL
            or manifest.get("request_parameters") != REQUEST_PARAMS
            or manifest.get("model") != MODEL or manifest.get("timezone") != TIMEZONE
            or manifest.get("raw_sha256") != sha256(raw) or manifest.get("clean_sha256") != sha256(clean)):
        raise WeatherSourceError("Weather snapshot provenance or checksum mismatch")
    daily, metadata = validate_response(raw.read_bytes())
    if any(manifest.get(name) != value for name, value in metadata.items()):
        raise WeatherSourceError("Weather response metadata differs from its archived manifest")
    return daily, manifest


def map_weather_date(frame, weather, *, date_role):
    """Attach weather by feed or placement date without adding rows."""
    if date_role not in ("feed_date", "entry_date", "arrival_date"):
        raise ValueError("Use feed_date, entry_date or arrival_date for point exposure")
    dates = weather.rename(columns={"date": date_role}).assign(weather_date_available=True)
    mapped = add_columns(frame, dates, key=(date_role,), cardinality="many_to_one", require_match=False)
    mapped["weather_date_available"] = mapped.weather_date_available.eq(True)
    return mapped


def exposure_windows(frame, weather, *, id_col, start_col, end_col):
    """Reduce inclusive windows to one row per animal or lot, with full-window eligibility."""
    require_key(frame, (id_col,), "exposure population")
    require_key(weather, ("date",), "weather_daily")
    windows = frame[[id_col, start_col, end_col, "pen_type"]].copy()
    if windows[[start_col, end_col]].isna().any(axis=None) or windows[end_col].lt(windows[start_col]).any():
        raise ValueError("Exposure windows require ordered, non-null dates")
    windows["expected_exposure_days"] = (windows[end_col] - windows[start_col]).dt.days + 1
    windows["cold_threshold_c"] = COLD_THRESHOLD_C
    windows["weather_date_count"] = 0
    for field in ("temperature_days", "wind_days", "snow_days"):
        windows[field] = 0
    for field in ("mean_temperature_c", "cold_day_proportion", "maximum_wind_kmh", "snowfall_exposure_cm"):
        windows[field] = np.nan
    for field in ("cold_days", "cold_days_outside_confinement"):
        windows[field] = pd.Series(pd.NA, index=windows.index, dtype="Int64")
    if weather.empty or windows.empty:
        return windows

    daily = weather.sort_values("date").set_index("date")
    calendar = daily.index.to_numpy()
    start = np.searchsorted(calendar, windows[start_col].to_numpy(), side="left")
    end = np.searchsorted(calendar, windows[end_col].to_numpy(), side="right")
    windows["weather_date_count"] = end - start

    temperature = daily.temperature_2m_mean
    temperature_values = temperature.to_numpy()
    wind = daily.wind_speed_10m_max.to_numpy()
    snow = daily.snowfall_sum.to_numpy()
    for name, values in (("temperature", temperature_values), ("wind", wind), ("snow", snow)):
        count = np.r_[0, np.cumsum(np.isfinite(values))]
        windows[f"{name}_days"] = count[end] - count[start]

    def window_sum(values):
        cumulative = np.r_[0, np.cumsum(np.nan_to_num(values))]
        return cumulative[end] - cumulative[start]

    days = windows.expected_exposure_days
    temp_complete = windows.temperature_days.eq(days)
    wind_complete = windows.wind_days.eq(days)
    snow_complete = windows.snow_days.eq(days)
    windows["mean_temperature_c"] = (window_sum(temperature_values) / days).where(temp_complete)
    windows["cold_days"] = pd.Series(window_sum(temperature_values < COLD_THRESHOLD_C),
                                    index=windows.index, dtype="Int64").where(temp_complete)
    windows["cold_day_proportion"] = safe_ratio(windows.cold_days, days).astype("float64")
    windows["maximum_wind_kmh"] = [
        wind[left:right].max() if complete else np.nan
        for left, right, complete in zip(start, end, wind_complete, strict=True)
    ]
    windows["snowfall_exposure_cm"] = pd.Series(window_sum(snow), index=windows.index).where(snow_complete)
    # Explicit proxy for shelter strata. Windbreak and open dirt remain separate pen types.
    windows["cold_days_outside_confinement"] = (
        windows.cold_days.where(windows.pen_type.ne(CLOSED_SHELTER), 0)
        .where(windows.pen_type.notna() & temp_complete)
    )
    return windows
