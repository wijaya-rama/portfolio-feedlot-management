# 05 · Analytical architecture

## Proposed Pandas pipeline

| Layer | Proposed behavior | Controls |
|---|---|---|
| Source manifest | Register immutable CSV/XLSX file hashes, Git source ref, ingest settings, sheet names, date ranges and schema version. Keep the HTML snapshot as an independent comparison fixture | Keep inputs read-only. Preserve RFID as text and parse ISO calendar dates explicitly. Preserve missing values and mortality placeholders before classification |
| Contract and validation | Load each relation at its own grain, validate keys, domains and relational paths, and assign severity to variants and exceptions | Schema and FK tests, snapshot row and balance checks, numeric rounding policy and explicit void or zero-denominator reasons. Keep exceptions visible with source path, sheet, key and rule |
| Conforming facts | Keep a one-row-per-animal closeout ledger, distinct animal/lot/pen dimensions, separate daily feed and animal scale/health event facts. Document the flat projection as a cross-check | Validate one-to-one and many-to-one merges in Pandas. Reconcile feed delivery and allocation as separate measures before using their respective analytical scopes |
| Derived tables | Materialize reusable additive numerators, denominators, dimensions, coverage counts, reconciliation status and dates | Aggregate each fact to its intended grain before combining. Attach definitions, population, source lineage and rule version to outputs |
| Channel exports | Produce Excel tables, compact HTML data and a shared model import set for Power BI and Tableau from one build | Record input hashes and output row counts. Validate identical slice totals across exports. Recompute ratios from sanctioned additive components where interactive slicing requires it |
| Review workflow | Keep exploratory findings and business sign-off separate from transformations. Version metric changes and approve exceptions before interpreting outputs | Fail build for unintended key/balance regressions. Expose known open source issues as separately tracked exceptions. Retain review history and reproducibility instructions |

### Proposed derived tables and grain

| Table | Grain and purpose |
|---|---|
| `animal_closeout` | One animal, additive costs, revenue, margin, sold gain, DOF, grade counts and allocated feed. Keep source decimal precision and isolate mortality fields semantically |
| `animal_health_summary` | One animal, event count, first treatment and first diagnosis, repeat indicator, direct costs and treatment outcomes. Supports unique head counts in animal slices |
| `animal_scale_stage` | One animal × recorded stage, date, weight, elapsed interval, signed gain and coverage. Keep as-of availability for later models |
| `lot_closeout` | One lot, placed/sold/dead counts, all/sold/death ledger totals, denominators and observation coverage. Use lot attributes for lot cohort slicing |
| `lot_feed_reconciliation` | One lot, separate delivered vs allocated DM and costs, deltas, status and qualification flags |
| `pen_day_feed` | One pen × feed date after aggregating each lot–pen–day, with delivered feed and recorded head-days. Keep callable lot–day facts for phase and lot slices. Label occupancy as ledger-implied and keep independent roster validation as an open provenance check |
| `cohort_closeout` and `feed_month` | Explicitly named grain and dates per export. Closeout periods by entry, animal exit or final lot exit. Feed months by feed event date. Carry common slicing attributes only where source grain supports them |
| `kpi_catalog` and `audit_exceptions` | One metric/version or rule/key respectively. Provide formula, unit, eligibility, aggregation method, lineage and issue status. Keep raw exception rows in the controlled environment |

Preserve the date roles of entry, treatment, weighing, feed, individual exit and final lot closeout. A single time filter should specify which role it applies to. Individual breed is at animal grain and predominant breed is at lot grain. Filters by individual breed cannot estimate its share of a shared pen delivery without a documented allocation model.

Do not join scale and health at event grain under the same animal key and then sum animal costs. Pre-aggregate independently to animal or the intended reporting grain. Do the same before connecting daily feed to animal closeouts. For BI relationships, prefer conformed dimensions filtering separate facts in one direction. Require explicit validation for ambiguous many-to-many paths. Prepare exact unique-head counts at their supported grain or use the sanctioned distinct-count logic on the animal-grain table.

## Proposed notebook sequence

| Notebook | Future purpose |
|---|---|
| 00 · Source validation | Run reusable load/contract modules, verify snapshot, show eligibility and known exceptions |
| 01 · Closeout economics | Build accounting bridge, reconcile mortality and denominators, compare procurement, lots and tails |
| 02 · Feeding and growth | Compare delivery and allocation, evaluate cohort ADG/FCR/COG, assess scale timing, phase and seasonal exposure |
| 03 · Health and carcass | Track first pulls vs events, descriptive health costs, grade and price/volume analysis |
| 04 · Management scenarios | Apply explicit shocks and break-even assumptions. Explore forecasting only after time-aware validation is feasible |
| 05 · Export validation | Compare shared closeout, feed, health and portfolio control totals after export |

Keep calculation functions in importable Pandas modules. Notebooks call those modules and export reviewed tables with metadata. For future delivery, Excel imports prebuilt tables and a metric glossary. HTML consumes versioned JSON. Power BI and Tableau import the same approved grain and additive components. Where a tool must calculate a ratio for an interactive slice, use the registered numerator and denominator and validate parity with reference slices. Do not implement independent definition logic in each presentation layer.
