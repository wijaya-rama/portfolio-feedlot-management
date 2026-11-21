# Phase 2B-2 · Feed, individual growth and historical weather

## Executive summary

- **Finisher feed dominates modeled spend.** Recorded deliveries totaled 28.544 million kg of dry matter (DM) and CAD 10.220 million. Finisher accounted for 67.7% of DM and 70.6% of cost. Concentrate accounted for 75.5% of DM and 78.5% of cost. Sold allocated feed conversion ratio (FCR) was 6.674 kg DM/kg liveweight gain and sold feed cost of gain (COG) was CAD 2.390/kg gain.
- **Paired growth improved through Day 105 before easing at closeout.** The largest stage-to-stage change was +0.231 kg/day from the Day 35 interval to the Day 70 interval across 14,832 matched animals. Of 14,794 animals observed at all three scheduled follow-ups, 162 ranked in the bottom within-lot ADG decile in all three. This group is a candidate for retrospective review of scale and health records.
- **Recorded pen utilization was 84.9% across delivery-observed capacity-days.** The 40 pens had 7,790 nominal places. There were 4,667 pen-days at 90% or more of nominal capacity and none at or above 100%. This is a measure of the simulated feed roster.
- **The raw weather and feed contrast was sensitive to the comparison.** The ratio of feed delivered to recorded head-days was 10.344 kg on cold dates and 10.838 kg on other dates in complete months. After accounting for month and active lot mix, the estimated cold-day difference was +0.052 kg/head-day, with a 28-day HAC interval of −0.018 to +0.121. Lot-level temperature associations with growth and FCR persisted in several calendar comparisons. Simulated outcomes and shared, overlapping exposure limit the management inference.

## Coverage and reconciliation

The analysis replays the committed snapshot using the Phase 2A `weather_snapshot` argument. It validates raw JSON and cleaned CSV checksums, matches the original CSV and workbook SHA-256 values, and checks reconciliation before using native ration-phase labels. The 661 controls passed. Financial, biological and feed baseline results are identical, including CAD 4,381,992.99 all-outcome margin, 14,760 sales, 240 deaths and 2,650,584 head-days. All 90 feed bridges meet the rounding bound of 0.005 kg DM or CAD per placed head for each metric. [Phase 2A checkpoint](../PHASE2A_CHECKPOINT.md) · [Baseline reconciliation](../phase2a/reconciliation.json)

| Records | Verified coverage | Calendar role |
|---|---:|---|
| Feed deliveries | 16,085 lot–pen–days and 16,085 distinct pen–days, across 90 lots and 40 pens | Recorded `feed_date` |
| Scale | 74,268 records, including 15,000 arrivals and 59,268 positive elapsed intervals | `weigh_date` and previous-to-current interval |
| Daily weather | 704/704 dates and nine complete variables | 1 January 2024–4 December 2025 |
| Animal exposure | 15,000/15,000 complete windows | Inclusive `entry_date` through `exit_date` |
| Lot exposure | 90/90 complete windows | Inclusive first through last recorded lot feed date |

The native feed facts reconcile at the complete pen–date key before adding pen labels. Animal attributes attach to the scale facts with a many-to-one join. Weather attaches to feed at calendar date and to scale intervals from distinct weather windows. Ledger comparisons aggregate each fact independently. The corresponding tests check row counts, additive measures and coverage. Two offline builds matched byte for byte across 11 tables and three JSON reports. The suite passed all 55 tests, including 11 for Phase 2B-2. All 11 notebook code cells executed and four figures rendered.

## Feeding · Where do feed dollars and efficiency vary?

| Measure | Delivered ledger | Estimated animal allocation | Delivered less allocated |
|---|---:|---:|---:|
| DM, kg | 28,544,013.42 | 28,544,013.02 | +0.40 |
| Feed expenditure, CAD | 10,219,542.92 | 10,219,543.49 | −0.57 |
| Head-days | 2,650,584 recorded | 2,650,584 inclusive financial | 0 |

Delivery intensity was **10.769 kg DM and CAD 3.856 per recorded head-day**. Deliveries are a proxy for consumption. The allocation is an estimate booked to each animal, including animals that died. Sold efficiency excludes mortality placeholders and uses matching positive-gain denominators. The unweighted individual means were 6.695 FCR and CAD 2.400/kg COG, versus 6.674 and CAD 2.390 from the ratio of totals. [KPI definitions](../analysis_audit/04_KPI_DEFINITIONS.md)

| Ration phase | Head-days | Delivered DM, kg/head-day | CAD/head-day | CAD/kg DM | Forage / concentrate / supplement, % of DM |
|---|---:|---:|---:|---:|---:|
| Starter | 209,910 | 7.869 | 2.146 | 0.273 | 55 / 39 / 6 |
| Transition | 209,213 | 8.351 | 2.610 | 0.312 | 38 / 56 / 6 |
| Grower | 624,105 | 9.325 | 3.218 | 0.345 | 24 / 70 / 6 |
| Finisher | 1,607,356 | 12.023 | 4.489 | 0.373 | 12 / 82 / 6 |

Concentrate contributed 21.543 million kg and CAD 8.023 million. Forage contributed 5.288 million kg and CAD 0.740 million, and supplement contributed 1.713 million kg and CAD 1.456 million. The higher Finisher spend per head-day reflects both DM volume and CAD/kg DM. A 1% change in booked allocated feed cost at fixed volume, growth, survival and other costs changes modeled margin by about CAD 102,195. This is a ledger sensitivity. For field validation, reconcile phase timing and invoices to bunk deliveries, refusals and shrink.

Seasonally, September–November averaged **11.938 kg DM and CAD 4.446/head-day**, compared with **9.787 kg and CAD 3.376** in March–May. The autumn concentrate share was 79.0% versus 71.6% in spring. December–February averaged 10.429 kg and CAD 3.855. The seasonal pools use complete months. November 2025 represented 24,305 head-days over eight pens and averaged 13.921 kg and CAD 5.053. The 1–4 December 2025 tail had 1,029 head-days over two pens and averaged 14.757 kg and CAD 5.357. Declining yard volume and a changing active lot mix are important context for the late-period intensity.

### Allocation efficiency and modeled margin

| Individual breed | Eligible sold head | Allocated FCR | Feed COG, CAD/kg gain | Financial ADG, kg/day |
|---|---:|---:|---:|---:|
| Black Angus | 6,372 | 6.827 | 2.448 | 1.582 |
| Charolais Cross | 3,823 | 6.546 | 2.358 | 1.669 |
| Hereford | 1,992 | 6.819 | 2.424 | 1.502 |
| Simmental Cross | 2,573 | 6.406 | 2.279 | 1.724 |

The breed comparison uses `Dim_Cattle.breed` and booked individual allocations. All 90 lots were mixed-breed. Lot, sex, entry weight, duration and ration exposure contribute to the pooled differences. Lot FCR ranged from 6.114 to 7.501 and lot delivery intensity from 9.569 to 11.495 kg DM/head-day. Across 40 pens, delivery intensity ranged from 9.665 to 11.433 kg DM/head-day and cost from CAD 3.441 to 4.106/head-day.

For triage, compare lots to the median of other lots in the same placement quarter. **LOT-2024-046** had 136 eligible sold animals, FCR 7.501 versus a peer median of 7.007, CAD 2.912/kg feed COG, ADG 1.504 kg/day, and CAD 200.27 margin per placed head. Prioritize verifying ration history, weight records and how feed was allocated. Across individual sales, FCR had median 6.681, interquartile range 6.461–6.907, and 90th percentile 7.155. Including ties at 7.155 flagged 1,479 sales. A portfolio decile is a screening threshold and is sensitive to lot composition.

Within the 90 lots and 40 pens, after accounting for individual breed, frame and entry weight, +0.10 kg/day financial ADG was associated with **−0.143 kg DM/kg FCR** and **+CAD 67.45/sold head**. An extra kg DM/kg FCR was associated with **−CAD 455.53/sold head**. Leaving one whole pen out gave ranges of −0.144 to −0.142, CAD 67.15–67.84 and −CAD 459.63 to −452.19, respectively. Sex and sold DOF are constant within lot here. A separate 90-lot fit conditioned on placement month, pen type and composition associated ten additional inclusive DOF with +0.122 FCR, with a leave-pen range of +0.117 to +0.128. The earlier quarter-conditioned sold margin fit was +CAD 13.36 per ten inclusive days (leave-one-lot range CAD 7.35–16.64). More time can add carcass value and feed expense together. Gain is shared by ADG and FCR, and allocation costs and revenue enter margin mechanically. [Closeout findings](01_CLOSEOUT_FINDINGS.md)

## Growth · Where does trajectory or consistency change?

Every animal at risk at its scheduled stage had a recorded weight. All sold animals had a closeout reading. The stage labels reflect scheduled inclusive days, so the first follow-up uses 34 elapsed days. The final interval ranges from 60 to 90 elapsed days. The elapsed cumulative ADG at closeout means 1.627 kg/day across sales. The 1.618 kg/day financial ADG ratio uses the sum of inclusive financial days and answers a different question.

| Stage | Recorded (eligible) | % of placements | Median kg | Elapsed interval ADG mean ± SD, kg/day |
|---|---:|---:|---:|---:|
| Arrival | 15,000 (15,000) | 100.0% | 340.6 | — |
| Day 35 | 14,882 (14,882) | 99.2% | 391.2 | 1.448 ± 0.205 |
| Day 70 | 14,832 (14,832) | 98.9% | 451.7 | 1.679 ± 0.194 |
| Day 105 | 14,794 (14,794) | 98.6% | 513.7 | 1.733 ± 0.182 |
| Closeout | 14,760 (14,760) | 98.4% | 633.7 | 1.634 ± 0.167 |

| Same-animal interval comparison | Matched head | Change, kg/day | 95% pen-resampling interval | Rank correlation |
|---|---:|---:|---:|---:|
| Day 35 → Day 70 | 14,832 | +0.231 | +0.221 to +0.242 | 0.738 |
| Day 70 → Day 105 | 14,794 | +0.055 | +0.040 to +0.070 | 0.688 |
| Day 105 → Closeout | 14,760 | −0.099 | −0.111 to −0.087 | 0.858 |

Each comparison includes 90 lots in 40 pens. Whole-pen bootstrap intervals describe variability within the simulated snapshot. Matched animals remove changes in composition *within a comparison*. The 240 mortalities progressively leave the later-stage risk sets, and the closeout comparison applies to sellers only. The final interval is longer and can average away short-term shifts. Faster or slower intervals cannot by themselves establish a profitable timing change.

At Day 105, observed mean interval ADG ranged from 1.609 kg/day for Hereford (1,995 head, SD 0.150) to 1.856 for Simmental Cross (2,580 head, SD 0.146). Heifers (4,021) averaged 1.546 versus 1.803 for steers (10,773). Large-frame (7,598) averaged 1.753 versus 1.712 for medium-frame (7,196). Animals below 310 kg at entry (2,428) averaged 1.587 versus 1.800 for those at or above 370 kg (1,958). These are observed group means with correlated starting profiles. Sex is single-valued within lot, so raw sex differences are also between-lot comparisons. The notebook displays every group by stage with counts and standard deviations.

Of 14,794 cattle with all three scheduled follow-ups, differences in lot means account for 63–70% of the observed sums of squares across early interval ADGs. Pooled within-lot SD fell from 0.125 to 0.102 kg/day. The median within-animal range across those three ADGs was 0.294 kg/day. With ties included, 1,524 cattle flagged low at Day 35, 259 also flagged at Day 70, and 162 flagged at all three stages. A single low rank and a persistent pattern lead to different review queues. Validate a review threshold against weighed gains, shrink, treatment timing and marketed results before using it operationally.

## Pen utilization · Which records warrant a capacity review?

| Recorded pen type | Pens | Nominal places | Recorded head-days | Occupancy on observed capacity-days | Days at ≥90% | DM kg/head-day | CAD/head-day |
|---|---:|---:|---:|---:|---:|---:|---:|
| Confinement Barn | 6 | 1,220 | 383,711 | 80.0% | 173 | 10.874 | 3.906 |
| Open Dirt w/ Windbreak | 25 | 4,805 | 1,670,310 | 86.2% | 3,217 | 10.730 | 3.843 |
| Standard Open Dirt | 9 | 1,765 | 596,563 | 84.7% | 1,277 | 10.810 | 3.857 |

Nominal capacity ranged from 155 to 250 head per pen. Occupancy across individual pens ranged from 71.3% to 95.7% (median 85.3%) and 4,667 of 16,085 observed pen-days reached 90%. No recorded pen-day reached full nominal capacity or contained overlapping lots. The yard's highest monthly recorded volume was 184,548 head-days at 85.8% observed occupancy in June 2025. November reached 90.3% on observed days as recorded volume fell to 24,305 head-days. Zone occupancy ranged from 83.7% in East Sheltered to 85.4% in North Yard. The denominator excludes unobserved pen-days. Verify dated movements, pen counts and usable capacity before staffing or building decisions. The allocation-based sold FCRs of 6.496 for barns (2,122 sales) and 6.690 for standard open dirt (3,298) also reflect different lots and composition.

## Historical weather · What exposure did the reference grid record?

The reference is the Picture Butte centroid (49.87672, −112.77983), with returned grid **50.0, −112.75**. The response uses `America/Edmonton` at fixed UTC−06:00. ERA5 attribution follows the documented request and acquisition provenance. The archived JSON does not independently identify the model. The archived reference spans 704 days, with no new acquisition. [Weather reference](../phase2a/WEATHER_REFERENCE.md) · [Acquisition and provenance](00_WEATHER_ACQUISITION.md)

- **Cold and extreme cold.** The exploratory daily mean below 0°C threshold identified 152/704 days (21.6%) in 24 spells. Two spells lasted 21 days (2–22 January 2024 and 31 January–20 February 2025). Daily minimum at or below −20°C identified 41 days across 11 spells. The longest lasted 18 days (2–19 February 2025). The lowest daily minimum was −44.9°C on 13 January 2024.
- **Seasonality and apparent temperature.** The average daily mean was 7.03°C air and 3.57°C apparent. Daily air means ranged from −39.9°C to 26.5°C. Among complete months, mean air temperature ranged from −12.20°C in February 2025 to 21.19°C in July 2024. Complete winter months had 97 cold days out of 150, versus zero out of 184 summer days. The four December 2025 days included two cold days with mean air −2.03°C and mean apparent −6.73°C.
- **Wind and moisture.** Mean daily maximum wind was 17.5 km/h, peak daily maximum wind was 40.4 km/h, and the peak gust was 81.0 km/h on 27 October 2024. The grid recorded 153.09 cm snowfall and 928.4 mm precipitation. The snowfall value sums daily snowfall. The precipitation value uses the source’s separate millimeter series.
- **Placement and lot exposure.** Calendar dates yield 60.8 cold days per animal in the 2024Q3 placement cohort (1,820 animals across 42 distinct entry–exit schedules) and 1.7 in 2025Q2 (3,838 animals across 86 schedules). The corresponding shares of animal exposure-days were 35.5% and 0.9%. Lot cold-day shares ranged from 0% (including LOT-2024-025) to 44.6% (78 of 175 feed-window days in LOT-2024-051). Across 13 barn, 57 windbreak, and 20 standard open lots, the reference cold shares weighted by lot-window days were 15.0%, 15.1%, and 13.3%. These differences come from recorded dates at a common grid. Establishing an animal's experienced temperature requires pen-level measurements, time outdoors and shelter use.

## Statistical interpretation · Do the associations survive fairer comparisons?

**Daily feed.** Compare a single outcome per feed date against the common grid. The 700 dates in complete operational months include 150 cold and 41 extreme-cold dates. The raw cold-date delivery gap of −0.495 kg/head-day is a ratio-of-totals comparison weighted by head-days. An equally weighted daily fit gave −0.726 kg/head-day pooled, +0.077 within year–month, and **+0.052** within year–month and adjusted for phases, lot DOF, pen categories and the entry weight, breed, sex and frame mix of active lots. Composition uses each lot's placement profile weighted by its recorded current head-days. The 28-day HAC range for the adjusted slope was −0.018 to +0.121. The adjusted DM slope was −0.026 kg/head-day per 10°C of warmer mean air (14-day HAC −0.050 to −0.002, 28-day HAC −0.055 to +0.003). Adjusted extreme cold was +0.040 kg/head-day (28-day HAC −0.011 to +0.091). The adjusted cold-day cost association was +CAD 0.019/head-day (28-day HAC −0.008 to +0.046). These small, bandwidth-sensitive differences provide weak evidence for a material delivered feed response in this snapshot. Within-month models account for seasonal levels and slower trends. Serial intervals approximate uncertainty for this one observed time series.

**Open and sheltered categories.** The day-matched barn-minus-standard-open contrast used 658 concurrent dates, including 142 cold dates. The mean difference was +0.189 kg DM/head-day. After removing year–month means, the contrast widened by +0.093 kg/head-day per 10°C warmer (leave-one-month range +0.074 to +0.108). Differences in which lots, ration phases and animals were present within the two categories can contribute. Use the comparison to frame a matched field study with independent census, actual pen weather and comparable feeding records.

**Scale intervals and sold outcomes.** All 59,268 positive intervals matched complete weather over the actual elapsed span, excluding the previous weigh date and including the current one. These intervals use only 310 distinct calendar date pairs. Regressions use one row per lot for each stage and one row per lot for lifetime sold outcomes. The lifetime fits use 90 lots, 14,760 sales and 88 distinct entry–exit date pairs. Month and quarter comparisons condition on pen type and lot composition derived from the eligible animals. The variable-duration closeout interval adjusts for mean elapsed interval length and lifetime models adjust for financial DOF. Comparisons use equally weighted lots. Early intervals precede the future closeout duration, so early-stage fits omit that control.

| Weather comparison, per 1°C warmer | Within placement month | Within placement quarter | Delete overlapping six-month block range, month model |
|---|---:|---:|---:|
| Day 35 interval ADG, kg/day | +0.0032 | +0.0057 | +0.0030 to +0.0041 |
| Day 70 interval ADG, kg/day | +0.0166 | +0.0122 | +0.0149 to +0.0186 |
| Day 105 interval ADG, kg/day | +0.0032 | +0.0071 | +0.0015 to +0.0110 |
| Closeout interval ADG, kg/day | +0.0046 | +0.0056 | +0.0030 to +0.0066 |
| Lifetime financial ADG, kg/day | +0.0102 | +0.0094 | +0.0089 to +0.0104 |
| Lifetime allocated FCR, kg DM/kg gain | −0.0366 | −0.0393 | −0.0479 to −0.0288 |

Removing one full pen at a time gave +0.0096 to +0.0112 for lifetime ADG and −0.0428 to −0.0348 for FCR. Replacing mean temperature with an additional 10 percentage points of cold days gave −0.038 kg/day ADG and +0.138 FCR within placement month. The residual exposure SD after conditioning was 0.86°C and 2.2 percentage points of cold days in the lifetime month models. Large changes are extrapolations. The calendar ranges remove all windows intersecting each six-month block in turn, and whole-pen deletion checks concentration by pen. These ranges describe sensitivity, with substantial overlap among retained windows. They are neither independent replications nor population confidence intervals.

The stronger Day 70 and lifetime coefficients could reflect remaining time-varying lot composition, survival, modeled feeding or simulator rules. The daily feeding and interval-growth questions use different grains, so these results cannot quantify a feed-mediated response. The simulator and seed are unavailable. Real weather paired retrospectively with simulated outcomes cannot establish a biological response, a shelter benefit, or a CAD return from modifying cold exposure.

## Dashboard candidates

| Candidate | Management use and display |
|---|---|
| Delivered-to-allocated feed bridge | DM and CAD residuals by lot alongside rounding bounds and recorded head-days. Keep delivered quantities and estimated allocations visible. |
| Ration spend and peer efficiency | Delivered DM and CAD/head-day by phase, concentrate share and CAD/kg DM. Show sold allocated FCR and COG with eligible gain and quarter-peer median. |
| Matched growth and persistent low rank | Stage coverage and mortality attrition, paired elapsed ADG changes, and repeat low ranks within lot. Display matched heads and pens. |
| Recorded capacity use | Monthly head-days, observed pen-days, nominal places and ≥90% flags for each pen. Mark partial periods and show pen types separately. |
| Weather exposure and feed context | Realized cold days, spells, apparent temperature, gust and snow by operational date. Compare the raw and mix-adjusted daily feed associations with uncertainty and observed calendar coverage. |

## Limitations and Phase 2B-3 handoff

Feed deliveries lack refusals, shrink, bunk measurements and a validated individual allocation method. Pen observations lack transfers and independent roll calls. The representative weather grid lacks pen microclimate and exposure hours. A short calendar, shared dates, lot and pen clustering, survivor selection and unavailable simulator rules constrain inference. Closeout CAD lacks complete settlement and overhead detail.

For Phase 2B-3, link dated treatments to the prior weight and next observed interval. Keep first pulls, repeats and individual animals distinct. Define eligibility at treatment time and show subsequent deaths or lost follow-up. Stratify carcass comparisons by breed, sex, frame and relevant lot composition, and track mortality alongside survivor-only grade and yield. Prioritize independent pen movements, dated ration and bunk records, scale protocols, clinical severity, necropsy and packer settlement details before interpreting intervention economics. Phase 2B-2 ends with this report.

## Reproduce

From the repository root with Python 3.11 or later, install the package and run the offline replay, tests and notebook. The verified execution used Python 3.12.14. The notebook builds the same tables from the tracked source and snapshot. Outputs under `work/` are local.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[notebook]'
snapshot=phase2a/weather/era5-20261121T143547299379Z-fd9571517552
python -W error -m feedlot_analytics.cli build --weather-snapshot "$snapshot" --output work/phase2b2-validated
python -W error -m unittest discover -s tests -v
python -m nbconvert --to notebook --execute notebooks/02_feed_growth_exposure.ipynb \
  --output-dir work --output 02_feed_growth_exposure.executed.ipynb --ExecutePreprocessor.timeout=240
```
