# Representative Southern Alberta Feedlot Weather Reference

The point is the published centroid of Picture Butte in the Lethbridge County area, Alberta, Canada, at WGS84 **49.87672° N, 112.77983° W**. It is a town-scale proxy for the simulated case study. Local dates use `America/Edmonton`. The API manifest captures the returned grid coordinate and elevation when available. [Circular Materials Alberta RFP #2025-01, Appendix M, p. 20](https://www.circularmaterials.ca/wp-content/uploads/2025/04/Appendix-M-Information_FA-03272025-addendum-5-tracked-changes-redlined.pdf#page=20) · [Town of Picture Butte infrastructure assessment](https://picturebutte.ca/docs/files/Master%20Plans/Picture%20Butte%20-%20Infrastructure%20Assessment%20-%20Final%20Report%20%28Permitted%29.pdf)

## Source and validation

The public Open-Meteo Historical Weather API request uses `models=era5` for the full **2024-01-01 through 2025-12-04** inclusive interval. Under the provider's terms, the free endpoint is used for this non-commercial educational case study. Weather data are attributed to Open-Meteo and Copernicus Climate Change Service ERA5, under CC BY 4.0. [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) · [Terms](https://open-meteo.com/en/terms) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · [Copernicus ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)

| Fields | Units |
|---|---|
| `temperature_2m_mean`, `temperature_2m_min`, `temperature_2m_max`, `apparent_temperature_mean` | °C |
| `wind_speed_10m_max`, `wind_gusts_10m_max` | km/h |
| `precipitation_sum`, `snowfall_sum` | mm and cm, respectively |
| `relative_humidity_2m_mean` | % |

The provider's daily parameter implementation confirms the exact field names. Its ERA5 implementation includes wind gust source fields. Actual deployment coverage and unit checks are performed on the archived response. For ISO dates Open-Meteo documents a fixed UTC offset for the response, including across daylight saving changes. The ingestion records the actual offset. [Daily field definitions](https://github.com/open-meteo/open-meteo/blob/7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa/Sources/App/Controllers/VariableDaily.swift) · [ERA5 variables](https://github.com/open-meteo/open-meteo/blob/7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa/Sources/App/Era5/Era5Variables.swift)

The versioned archive contains the user-supplied Open-Meteo JSON, all 704 dates and all nine variables. It returned grid coordinates `50.0, -112.75` and elevation 906 m. The response uses `America/Edmonton` at fixed UTC−06:00 (`GMT-6`). The archived JSON contains the returned grid but does not identify the original request URL, requested coordinates or model. The manifest records the documented request with `models=era5`, the reported iPhone download, and the response fields separately. The independent repeat request received proxy CONNECT 403 before any provider response. [Weather acquisition report](../phase2b/00_WEATHER_ACQUISITION.md) · [Snapshot manifest](weather/era5-20261121T143547299379Z-fd9571517552/weather_manifest.json) · [Historical attempt record](weather_attempt.json)

With the package installed, run from the repository root to replay the tracked snapshot offline.

```sh
snapshot=phase2a/weather/era5-20261121T143547299379Z-fd9571517552
python -W error -m feedlot_analytics.cli build --output work/phase2a-with-weather --weather-snapshot "$snapshot"
python -W error -m unittest discover -s tests -v
```

For a new acquisition, `python -m feedlot_analytics.cli fetch-weather --output work/weather` requests the exact URL and requires an HTTP 200 JSON response. It uses a 20-second timeout and retries transient errors up to three attempts. Validation checks grid proximity, ordered unique dates, units and physical bounds. Missing daily labels fail ingestion. Null measurements are retained and counted by variable. Each snapshot contains the raw response, cleaned daily CSV and manifest with grid metadata and SHA-256 checksums. The manifest records extraction time for a direct fetch. The upload's original extraction time is unknown, so its manifest records the UTC archive time separately. Replay validates the archived bytes offline. The suite exercises the tracked archive by default and accepts a `FEEDLOT_WEATHER_SNAPSHOT` override. Fixtures supply artificial values for separate software tests.

## Date mappings and features

| Role | Mapping |
|---|---|
| Feed event | Match `feed_date` to the single daily reference on the native lot–pen–day fact or the pen-day rollup |
| Placement | Match animal `entry_date` or lot `arrival_date` to the daily reference |
| Animal exposure | Aggregate the inclusive `entry_date` to `exit_date` range to one row per `animal_id` |
| Lot exposure | Aggregate the inclusive first to last recorded feed date to one row per `lot_id`. Source validation ties this interval to lot arrival and final exit |

`map_weather_date()` enforces a many-to-one point mapping. `exposure_windows()` aggregates date windows before any join to a finance table. Each feature carries expected days and observed coverage. Cold means daily mean air temperature **strictly below 0°C**, a descriptive threshold for this build. Features are cold-day count and share, mean air temperature, maximum daily wind speed, and summed snowfall. A shelter proxy counts such cold days outside confinement and retains recorded pen type. There is no adjustment for windbreak effectiveness, microclimate or time outdoors. Each window metric requires complete coverage for its variable. Missing coverage produces null values and an explicit count of dates and valid observations.

ERA5 is gridded reanalysis and the cattle outcomes are simulated. Descriptive exposure reports what the reference series contains over a recorded window. An association study would compare exposure with simulated outcomes under stated cohort and confounding controls. Scenario analysis would require separate assumptions about exposure effects. The available sources do not identify a causal link between actual weather and simulated cattle performance. Seasonal variation in the deliveries and the legacy dashboard's placement-quarter labels were inspected. The simulator code and seed are unavailable, so the data-generation mechanism remains unverified. [Phase 1 seasonal evidence](../analysis_audit/02_DATA_QUALITY_AND_RECONCILIATION.md#additional-legacy-and-narrative-findings)
