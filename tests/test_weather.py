import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pandas as pd
from pandas.testing import assert_frame_equal

from feedlot_analytics.weather import (
    DAILY_UNITS, END_DATE, EXPECTED_DATES, LATITUDE, LONGITUDE, MODEL, REQUEST_URL, START_DATE, TIMEZONE,
    WeatherSourceError, empty_weather, exposure_windows, fetch_snapshot, load_snapshot, map_weather_date,
    reference_metadata, validate_response,
)


def example_response():
    """Synthetic technical fixture. The tests never publish it as historical data."""
    values = {
        "temperature_2m_mean": -2, "temperature_2m_min": -5, "temperature_2m_max": 1,
        "apparent_temperature_mean": -6, "wind_speed_10m_max": 30, "wind_gusts_10m_max": 45,
        "precipitation_sum": 1, "snowfall_sum": .3, "relative_humidity_2m_mean": 60,
    }
    return {
        "timezone": TIMEZONE, "utc_offset_seconds": -25200,
        "elevation": 914, "latitude": 49.75, "longitude": -112.75,
        "daily_units": {"time": "iso8601", **DAILY_UNITS},
        "daily": {
            "time": EXPECTED_DATES.strftime("%Y-%m-%d").tolist(),
            **{key: [value] * len(EXPECTED_DATES) for key, value in values.items()},
        },
    }


def as_json(value):
    return json.dumps(value).encode("utf-8")


class WeatherTest(unittest.TestCase):
    def test_request_geography_model_and_units(self):
        url = urlsplit(REQUEST_URL)
        self.assertEqual(url.netloc, "archive-api.open-meteo.com")
        params = parse_qs(url.query)
        self.assertEqual(params["latitude"], [str(LATITUDE)])
        self.assertEqual(params["longitude"], [str(LONGITUDE)])
        self.assertEqual(params["models"], ["era5"])
        self.assertEqual(params["timezone"], ["America/Edmonton"])
        self.assertEqual(params["start_date"], [START_DATE])
        self.assertEqual(params["end_date"], [END_DATE])
        self.assertEqual(params["daily"][0].split(","), list(DAILY_UNITS))
        reference = reference_metadata()
        self.assertEqual(reference["geography"]["latitude"], 49.87672)
        self.assertEqual(reference["geography"]["longitude"], -112.77983)
        self.assertIn("circularmaterials.ca", reference["geography"]["source"])
        self.assertEqual(reference["model"], MODEL)
        self.assertEqual(reference["license"], "CC BY 4.0")

    def test_complete_unique_dates_and_null_coverage(self):
        payload = example_response()
        payload["daily"]["temperature_2m_mean"][4] = None
        daily, manifest = validate_response(as_json(payload))
        self.assertEqual(len(daily), 704)
        self.assertFalse(daily.date.duplicated().any())
        self.assertEqual(manifest["first_date"], "2024-01-01")
        self.assertEqual(manifest["last_date"], "2025-12-04")
        self.assertEqual(manifest["elevation_m"], 914)
        self.assertEqual(manifest["missing_by_variable"]["temperature_2m_mean"], 1)
        self.assertTrue(pd.isna(daily.temperature_2m_mean.iloc[4]))

    def test_reject_duplicate_or_missing_dates(self):
        payload = example_response()
        payload["daily"]["time"][1] = payload["daily"]["time"][0]
        with self.assertRaisesRegex(WeatherSourceError, "Duplicate"):
            validate_response(as_json(payload))
        payload = example_response()
        payload["daily"]["time"].pop()
        with self.assertRaisesRegex(WeatherSourceError, "Expected all 704"):
            validate_response(as_json(payload))

    def test_reject_units_wrong_region_model_timezone_and_physical_values(self):
        for key, value, reason in (
            ("timezone", "UTC", "timezone"), ("model", "era5_land", "model"),
            ("latitude", 37, "latitude"), ("daily_units", {"time": "iso8601"}, "units"),
        ):
            with self.subTest(key=key):
                payload = example_response()
                payload[key] = value
                with self.assertRaisesRegex(WeatherSourceError, reason):
                    validate_response(as_json(payload))
        payload = example_response()
        payload["daily"]["relative_humidity_2m_mean"][0] = 200
        with self.assertRaisesRegex(WeatherSourceError, "Implausible"):
            validate_response(as_json(payload))
        payload = example_response()
        payload["daily"]["temperature_2m_min"][0] = 0
        with self.assertRaisesRegex(WeatherSourceError, "Invalid temperature order"):
            validate_response(as_json(payload))

    def test_reject_api_error_and_non_observations(self):
        for data in (b"", b"[]", b'{"error":true,"reason":"invalid"}'):
            with self.subTest(data=data), self.assertRaises(WeatherSourceError):
                validate_response(data)
        payload = example_response()
        payload["daily"]["snowfall_sum"][0] = False
        with self.assertRaisesRegex(WeatherSourceError, "Invalid data array"):
            validate_response(as_json(payload))

    def test_retry_recoverable_connections_and_report_blocked_tunnel(self):
        with patch("feedlot_analytics.weather.urlopen", side_effect=URLError("temporary failure")) as network:
            with patch("feedlot_analytics.weather.time.sleep") as backoff:
                with TemporaryDirectory() as directory, self.assertRaisesRegex(WeatherSourceError, "temporary"):
                    fetch_snapshot(Path(directory), attempts=3)
                self.assertEqual(network.call_count, 3)
                self.assertEqual(backoff.call_count, 2)
        with patch("feedlot_analytics.weather.urlopen", side_effect=URLError("Tunnel connection failed: 403 Forbidden")) as network:
            with TemporaryDirectory() as directory, self.assertRaisesRegex(WeatherSourceError, "403 Forbidden"):
                fetch_snapshot(Path(directory))
            self.assertEqual(network.call_count, 1)

    def test_save_then_replay_verified_request_and_bytes(self):
        raw = as_json(example_response())
        with TemporaryDirectory() as directory:
            with patch("feedlot_analytics.weather._download", return_value=raw):
                snapshot = fetch_snapshot(Path(directory))
            self.assertTrue(snapshot.name.startswith("era5-"))
            self.assertEqual((snapshot / "open_meteo_raw.json").read_bytes(), raw)
            daily, manifest = load_snapshot(snapshot)
            self.assertEqual(manifest["request_url"], REQUEST_URL)
            self.assertIsNotNone(manifest["extracted_at_utc"])
            assert_frame_equal(daily, validate_response(raw)[0])
            (snapshot / "open_meteo_raw.json").write_bytes(b"{}")
            with self.assertRaisesRegex(WeatherSourceError, "checksum"):
                load_snapshot(snapshot)

    def test_safe_point_mapping_by_feed_and_entry_dates(self):
        daily, _ = validate_response(as_json(example_response()))
        records = pd.DataFrame({
            "animal_id": ["one", "two"], "entry_date": [pd.Timestamp(START_DATE)] * 2, "margin_cad": [25.0, -30.0],
        })
        mapped = map_weather_date(records, daily, date_role="entry_date")
        assert_frame_equal(records, mapped[records.columns])
        self.assertTrue(mapped.weather_date_available.all())
        feed = pd.DataFrame({"pen_id": ["01", "02"], "feed_date": [pd.Timestamp(END_DATE)] * 2})
        self.assertEqual(len(map_weather_date(feed, daily, date_role="feed_date")), len(feed))
        dup = pd.concat([daily, daily.iloc[:1]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "unique, non-null"):
            map_weather_date(records, dup, date_role="entry_date")

    def test_window_features_and_partial_coverage(self):
        daily, _ = validate_response(as_json(example_response()))
        windows = pd.DataFrame({
            "animal_id": ["barn", "yard", "edge"], "pen_type": [
                "Confinement Barn", "Open Dirt w/ Windbreak", "Standard Open Dirt",
            ],
            "entry_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2025-12-04"]),
            "exit_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2025-12-05"]),
        })
        fields = {"id_col": "animal_id", "start_col": "entry_date", "end_col": "exit_date"}
        exposure = exposure_windows(windows, daily, **fields).set_index("animal_id")
        self.assertEqual(exposure.expected_exposure_days.tolist(), [2, 2, 2])
        self.assertEqual(exposure.weather_date_count.tolist(), [2, 2, 1])
        self.assertEqual(exposure.loc["yard", "cold_days"], 2)
        self.assertEqual(exposure.loc["yard", "cold_day_proportion"], 1)
        self.assertEqual(exposure.loc["yard", "maximum_wind_kmh"], 30)
        self.assertAlmostEqual(exposure.loc["yard", "snowfall_exposure_cm"], .6)
        self.assertEqual(exposure.loc["barn", "cold_days_outside_confinement"], 0)
        self.assertTrue(pd.isna(exposure.loc["edge", "cold_days"]))
        unavailable = exposure_windows(windows, empty_weather(), **fields)
        self.assertTrue(unavailable.cold_days.isna().all())
        self.assertTrue(unavailable.weather_date_count.eq(0).all())

    @unittest.skipUnless(os.environ.get("FEEDLOT_WEATHER_SNAPSHOT"), "No verified live ERA5 snapshot supplied")
    def test_actual_archive_integration(self):
        from feedlot_analytics import build
        from feedlot_analytics.weather import map_weather_date

        root = Path(__file__).resolve().parents[1]
        result = build(root, weather_snapshot=Path(os.environ["FEEDLOT_WEATHER_SNAPSHOT"]))
        weather = result.tables["weather_daily"]
        animals = result.tables["animal_closeout"]
        manifest = result.transformation_manifest["weather"]
        self.assertEqual(manifest["status"], "verified")
        self.assertEqual(len(weather), 704)
        self.assertFalse(weather.date.duplicated().any())
        self.assertEqual(manifest["daily_units"], DAILY_UNITS)
        result_map = map_weather_date(animals, weather, date_role="entry_date")
        assert_frame_equal(animals, result_map[animals.columns])
        with_weather = result.tables["animal_weather_exposure"]
        self.assertTrue(with_weather.weather_date_count.eq(with_weather.expected_exposure_days).all())
        self.assertEqual(result.reconciliation["summary"]["modeled_ledger_cad"]["all_outcomes"]["all_outcome_margin_cad"],
                         4381992.99)
