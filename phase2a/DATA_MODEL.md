# Phase 2A data model

The sources are the original flat CSV and star-schema workbook. `load_sources()` returns both as loaded, including workbook display sheets. Headers and calendar labels are retained. Blank cells are missing. Identifiers and operational dates arrive as Pandas strings. The CSV's literal `None` and the embedded flat sheet's blank cells in untreated diagnosis and protocol are equivalent only for the parity check. This distinction is visible in the source manifest. The seven operational workbook relations supply the canonical facts and dimensions. [Source contracts from Phase 1](../analysis_audit/01_SOURCE_INVENTORY.md)

## Keys and units

- `Dim_Pen → Dim_Lot → Dim_Cattle` gives the recorded placement hierarchy. Closeout, scale and health attach through `animal_id`. Feed attaches through `lot_id, pen_id, feed_date`. Workbook grain, key presence, unique RFID, parent paths, fact keys and source domains are checked before transforming.
- Raw source labels with the `_date` suffix become timezone-naive calendar dates in the canonical tables. CSV exports use ISO date strings. The transformation manifest enumerates exact Pandas column types and null counts. Programmatic analysis should use `build().tables` for typed data. Consumers of the CSVs should import IDs as text and use the date and dtype specifications in the manifest.
- Recorded money is nominal CAD. Finance aggregation uses integer cents derived from validated two-decimal ledger amounts. Animal closeout retains the recorded source CAD columns. Closeout cost uses purchase, allocated feed, yardage and veterinary components. The loss on mortality rows is already included in all-outcome margin.
- `animal_closeout` retains source mortality zeros. Sold growth, feed-efficiency and carcass ratios apply explicit sale and measurement eligibility before summing metric components. Report eligible head and denominator alongside the result. `kpi_catalog` ties directly to the functions. Zero or missing denominators produce missing ratios.
- `animal_scale_stage` preserves all 74,268 source events on the animal-stage key. Recorded cumulative ADG uses inclusive time from entry. Derived interval ADG uses weight change and positive elapsed days since the previous event. Arrival has no interval. The elapsed cumulative ADG is supplied separately. Compare stages with recorded and at-risk population counts, accounting for exits before each stage.
- `animal_health_summary` rolls up the 2,220 treatment events before any financial join. Source events remain available from the workbook. Treated counts refer to unique animals. Direct treatment costs plus CAD 18 per placed animal tie to modeled veterinary cost. Lifetime health labels are retrospective. Use dated source events for period-specific or as-of analyses.
- `lot_feed_reconciliation` independently sums delivered and allocated amounts by lot. The bound uses 0.005 per animal for each measure at the precision accepted in Phase 1. `pen_day_feed` reports head-days, delivered feed, and nominal capacity on recorded delivery dates. Missing pen-days have no imputed deliveries or census counts. Use documented individual allocation values for breed analyses. Record the role of any new allocation model before using shared feed across breeds.
- `weather_daily` is a separate fact. Exposure outputs carry only dates, shelter and weather features. The weather source, request and coverage policy are described in [the weather reference](WEATHER_REFERENCE.md).

## Cohorts and safe aggregation

`entry_date` defines a placement cohort, with outcomes observed through exit. `lot_closeout_date` defines completed lots by their last individual exit, retaining the associated cohort. `exit_date` defines closeout activity. An exit-date slice counts distinct represented animals. A head-placed denominator for a placement-cohort KPI needs the corresponding placement cohort. Use `feed_date` for feed activity, `weigh_date` for scale records, and `treatment_date` for health event activity.

Aggregate from the same selected animal rows for both numerator and denominator. Use `breed` for individual cattle. To reference a procurement grouping by predominant breed, select lot IDs from `lot_closeout` and filter animals by lot membership. For lot- or pen-level rollups, sum eligible additive components before computing ratios. Nominal pen capacity is a dimension attribute and repeats across days. Use weight, breed, sex, frame, dates and lot keys for later stratification. Report sample sizes and common support before comparing cohorts. Consider lot clustering for uncertainty and account for survival and follow-up when comparing outcomes.

```python
from pathlib import Path
from feedlot_analytics import build
from feedlot_analytics.metrics import aggregate_closeout, aggregate_pen_feed, select_period

tables = build(Path.cwd()).tables
placed = select_period(
    tables["animal_closeout"], date_role="entry_date",
    start="2024-01-01", end="2024-03-31",
)
breed = aggregate_closeout(placed, tables["animal_health_summary"], by=("breed", "sex"))
feed_month = aggregate_pen_feed(tables["pen_day_feed"], by=("feed_month",))
```

The build uses the distinct health and scale records at their original event grains. A naive combined join yields 74,783 rows and inflates the animal ledger. A daily-feed join on `lot_id` expands to 2,680,547 matched rows. Transformations enforce explicit join cardinality, reduce the event fact before attaching one-row summaries and reject duplicate animal keys at financial aggregation. The reconciled totals and exceptions are reviewable from the generated JSON and CSV outputs. [Reconciliation summary](reconciliation.json)
