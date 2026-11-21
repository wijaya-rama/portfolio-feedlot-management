# Phase 2B-3 · Animal health, mortality and carcass

## Executive summary

- **Early arrival surveillance covers most recorded first pulls.** Of 15,000 placements, 2,100 cattle had 2,220 recorded treatment events. The median first pull was DOF 22, and 1,632/2,100 occurred through DOF 30. Direct treatment cost was CAD 143,194.84, already included in CAD 413,194.84 of booked veterinary expense.
- **Mortality consumed CAD 34.15 per placement.** The 240 deaths cost CAD 512,194.64, of which 91.4% was purchase cost. Recorded treatment and repeat treatment preceded higher same-lot, same-DOF mortality intensity. Timing and illness severity matter because 26 deaths share the date of first treatment and eight share the date of second treatment.
- **Persistent low growth is useful for reviewing existing health histories.** Of 165 animals that repeatedly ranked in their within-lot ADG bottom decile using stage-day rankings, 67 had already been treated before the Day 105 weigh. There was one new first pull among the 98 remaining animals at risk over the next 30 days.
- **Carcass tonnage and grade both help explain booked revenue.** The 14,760 sales delivered 5.656 million kg HCW at 61.005% dressing yield and CAD 8.082/kg realized revenue. Prime + AAA represented 76.57% of sales. In comparable entry cohorts, treated survivors averaged 5.94 kg less HCW and CAD 104.01 less modeled margin than their standardized reference. Survival, disease selection and shared cost components constrain interpretation.

## Source coverage and eligibility

| Grain | Verified population | Date or eligibility rule |
|---|---:|---|
| Animal closeout and health summary | 15,000 animals, 90 lots, 40 pens | Entry to recorded sale or death. One biological and financial record per `animal_id`. |
| Treatment fact | 2,220 distinct events, 2,100 animals | Calendar date within the animal's entry–exit window. Sort by treatment date and then ID. |
| Scale fact and elapsed intervals | 74,268 weights, 59,268 positive elapsed intervals | Arrival has no interval. Recorded Day 35, 70 and 105 counts were 14,882, 14,832 and 14,794. Closeout has all 14,760 sales. |
| Carcass | 14,760 finished sales | All have positive HCW and live exit weight and an eligible grade. |
| Weather snapshot | 704/704 dates, 15,000 animal windows, 90 lot windows | Original verified snapshot replayed as a baseline control. |

Health dates and outcomes come from the native treatment fact. Its ledger is independently summed in cents before the one-row animal comparison. The scale link retains the animal–stage key while distinguishing events strictly before a weighing interval, on its start date, inside it and on its end date. DOF is inclusive from entry for treatment and mortality. Scale ADG uses elapsed days between weights. Carcass ratios and booked costs use Phase 2A definitions. [Checkpoint](../PHASE2A_CHECKPOINT.md) · [KPI definitions](../analysis_audit/04_KPI_DEFINITIONS.md) · [Notebook](../notebooks/03_health_mortality_carcass.ipynb)

## First pulls, repeat treatments and veterinary cost

| Lifetime record | Placed head | Events | Deaths | Mortality | Direct treatment CAD |
|---|---:|---:|---:|---:|---:|
| No recorded treatment | 12,900 | 0 | 87 | 0.67% | 0.00 |
| One event | 1,980 | 1,980 | 126 | 6.36% | 127,055.94 |
| Two events | 120 | 240 | 27 | 22.50% | 16,138.90 |
| All placements | 15,000 | 2,220 | 240 | 1.60% | 143,194.84 |

The 2,100 treated cattle represent 14.00% of placements. The 120 repeats represent 5.71% of treated animals. Every repeat was a second event, seven to 14 elapsed days after the first, with a median gap of 10 days. Direct cost averaged CAD 64.50 per recorded event and CAD 68.19 per treated animal. CAD 18 of base veterinary cost per placement totals CAD 270,000. Adding CAD 143,194.84 for direct care reproduces the booked veterinary total.

First-pull DOF ranged from 5 to 124, with quartiles 14, 22 and 30. The 1,632 early pulls represented 77.7% of treated cattle and 10.88% of placements. The 468 later pulls represented 22.3% of treated cattle. Of cattle present after the first-pull date, 90/1,613 early and 37/461 later first pulls were followed by a recorded death on days 1–30. An additional 19 early and seven later first pulls shared a date with death. Ninety-three early and 27 later cattle received a second treatment within 30 days. After the second pull, 19/112 cattle present the next day died over days 1–30, and eight died on the index date. There were no competing sales in the 30-day windows after either index. Early and later first pulls index cattle at different stages and may reflect differences in illness and detection.

All 2,220 events have an outcome label. The event counts are 1,957 `Recovered`, 120 `Chronic / Repeat` and 143 `Mortality`. Ten `Recovered` events belong to cattle that subsequently died. The record lacks dates and definitions for assessing recovery. A second treatment is the only documented repeat visit and is distinct from later scale or closeout observation.

## Growth around the first and second treatment

Of 2,220 events, 2,037 fell strictly between observed weights, 18 shared a weigh date and 165 were after the last observed weight. At Day 35, first treatment was before the weigh for 1,563 cattle, after it for 424 and on the same date for seven. There were 106 first-pull cattle with no Day 35 weight. At Day 70 the respective counts were 1,827, 132, six and 135. At Day 105 they were 1,911, 36, two and 151. All 1,947 treated sellers had treatment before their closeout weight. The 153 treated cattle that died lacked that closeout measurement.

| Index | Indexed head | Strictly pre-index interval | Strictly post-index interval | Both | Paired ADG change, kg/day (95% pen bootstrap) |
|---|---:|---:|---:|---:|---:|
| First treatment | 2,100 | 424 | 1,911 | 350 | +0.166 (+0.138 to +0.196) |
| Second treatment | 120 | 47 | 90 | 29 | +0.362 (+0.298 to +0.425) |

A pre-index interval must end before the event date. A post-index interval must start after it. Intervals with the index on a boundary or inside are omitted from the pair. None of the 1,632 early first pulls had a full pre-pull interval, and neither paired sample includes any cattle that died. The 261 most common first-pull pairs gained +0.237 kg/day from the interval ending Day 35 to the interval ending Day 105. The 83 pairs from Day 70 to Closeout fell −0.060 kg/day. The Day 35 to Day 105 pairs typically ended their pre-interval 18 days before the pull and started their post-interval 17 days later. The repeat-pull pre-interval may reflect earlier treatment. Scheduled growth changes, regression toward the mean and selection into later weighings all contribute to the observed changes. [Phase 2B-2 stage trajectory](02_FEED_GROWTH_FINDINGS.md)

**Day 35 landmark.** Time zero is the recorded Day 35 weigh for 14,882 cattle still present afterward. Seven same-day first pulls were removed because their order is unknown. Of 1,563 cattle with prior treatment, six died through Day 70 and 1,557 had the next observed interval. Among 13,312 without prior recorded treatment, 43 died, 13,271 had the next interval and 292 received their first pull during follow-up. Within lot, sex, breed, frame and fixed 20 kg entry bands, there were 1,453 previously treated and 9,828 reference cattle with comparable observed next intervals. The standardized Day 35 interval difference was −0.296 kg/day at the landmark (95% whole-pen range −0.304 to −0.288). The following interval differed by +0.006 kg/day (+0.001 to +0.011). The paired change contrast of +0.303 kg/day mostly reflects the lower growth already measured at Day 35. For death, common support included 1,459 and 9,859 cattle, with a difference of +0.081 percentage points (−0.250 to +0.445). Early deaths before the landmark and the absence of comparable pre-pull weights limit what the comparison can establish.

**Persistent low rank.** At each stage, the main analysis ranks all measured cattle on that lot's actual weigh date. With ties included, 165/14,794 cattle observed at all three stages were in the bottom decile each time. Before Day 105, 67/165 (40.6%) had a treatment record versus 1,844/14,629 (12.6%) among the other cattle. The common-support gap was +31.84 points (95% whole-pen range +23.02 to +41.56), using 135 flagged and 2,225 reference cattle over 73 lots and 40 pens. A 10 kg entry band produced +32.61 points. Replaying the Phase 2B-2 complete-case cutoff gave 162 flagged cattle and +32.88 points in the same type of comparison. Among cattle still present and treatment-free after Day 105, 1/98 flagged and 35/12,783 other cattle received a first pull over days 1–30, with 20 competing deaths in the reference and no competing sales. The common-support gap was +1.17 points (−0.32 to +3.95), with just one new pull in each supported arm. The persistent flag is a prompt to review scale and treatment histories. Its value as a forward-looking alert remains uncertain.

## Mortality and the modeled cost bridge

Across all placements, mortality was 240/15,000 (1.60%). The lifetime treated cohort recorded 153/2,100 deaths (7.29%) versus 87/12,900 (0.67%) for cattle with no recorded treatment. Those labels are assigned at closeout and are descriptive. Median death was DOF 37.5 (IQR 22–78, range 6–183). Through DOF 30 there were 108 deaths on 448,927 animal-days. DOF 15–30 had the highest listed interval rate, 78 deaths on 239,017 animal-days.

Daily risk sets count entry and exit days and update exposure on the day after an event. They allocate all 2,650,584 animal-days and 240 deaths once. The zero, one and two-prior-event states recorded 113/2,356,592, 108/280,810 and 19/13,182 deaths per animal-day, respectively. Same-date attribution is uncertain. After matching by lot and inclusive DOF, the reference is weighted to the exposed support:

| Prior treatment state | Exposed deaths / animal-days | Reference deaths / supported animal-days | Exposed vs standardized reference, deaths/1,000 days | Difference (95% pen bootstrap) |
|---|---:|---:|---:|---:|
| One or more vs zero | 127 / 293,992 | 113 / 2,263,289 | 0.432 vs 0.046 | +0.386 (+0.321 to +0.452) |
| Two vs exactly one | 19 / 13,182 | 26 / 166,357 | 1.441 vs 0.215 | +1.226 (+0.593 to +2.033) |

The contrasts use 90 and 67 lots respectively. Through DOF 105 the gaps were +0.779 and +2.362 per 1,000 days. Crediting treatment on the same date increased the full-window gaps to +0.476 and +1.752. These time-updated comparisons avoid assigning pre-treatment days to the treated state. They do not account for unrecorded disease severity or the timing of clinical decisions inside a day. Low counts after the second event limit precision.

The notebook gives mortality, placements, costs and pen-bootstrap uncertainty by actual breed, sex, frame, placement quarter and region. Pooled breed mortality ranged from 56/3,879 for Charolais Cross (1.44%) to 48/2,621 for Simmental Cross (1.83%), with overlapping intervals. Heifers recorded 63/4,075 and steers 177/10,925. Large and medium frames recorded 115/7,695 and 125/7,305. Placement-quarter rates ranged from 38/3,094 (2024Q2) to 60/3,370 (2024Q1), and four regional-quarter cells had only one pen. Lot mortality ranged from zero in four lots to 7/186 in LOT-2024-048 (3.76%, versus 1.53% in other 2024Q3 lots). LOT-2024-057 and LOT-2025-005 also exceeded their quarter peers by more than two points. These realized exceptions are audit priorities and depend on a few animals per lot.

| Modeled ledger, CAD | Sales | Deaths | All outcomes |
|---|---:|---:|---:|
| Revenue | 45,710,188.31 | 0.00 | 45,710,188.31 |
| Purchase | 28,637,050.52 | 468,056.07 | 29,105,106.59 |
| Allocated feed | 10,199,008.85 | 20,534.64 | 10,219,543.49 |
| Yardage | 1,582,643.40 | 7,707.00 | 1,590,350.40 |
| Veterinary | 397,297.91 | 15,896.93 | 413,194.84 |
| Total costs | 40,816,000.68 | 512,194.64 | 41,328,195.32 |
| **Margin** | **4,894,187.63** | **−512,194.64** | **4,381,992.99** |

Of the veterinary cost on death records, CAD 11,576.93 was direct and CAD 4,320.00 was base cost. Spread over placements, sales contributed CAD 326.28 per head before the CAD 34.15 death burden, leaving CAD 292.13. Sold-only margin was CAD 331.58 per sale. The death burden is 10.47% of the booked survivor margin and measures recorded costs on mortality rows. The value of hypothetical avoided deaths requires assumptions about sale revenue, additional feeding and other costs. [Closeout findings](01_CLOSEOUT_FINDINGS.md)

## Protocol record review

| Diagnosis | Unique animals | Events (repeat events) | Direct CAD | Deaths on days 1–30 / first-pull cattle present next day |
|---|---:|---:|---:|---:|
| BRD | 1,366 | 1,446 (80) | 105,832.34 | 77 / 1,346 |
| Bloat / Acidosis | 265 | 286 (21) | 14,834.41 | 20 / 263 |
| Buller / Injury | 160 | 167 (7) | 8,346.43 | 12 / 160 |
| Foot Rot | 309 | 321 (12) | 14,181.66 | 18 / 305 |

BRD accounts for 65.1% of events and 73.9% of direct spend, making it the highest-volume record audit. The notebook shows event outcomes, first and repeat counts, 30-day deaths and later booked growth and economics by diagnosis and protocol. Subsequent outcomes and ledger amounts use exclusive first-event cohorts. Ever-recorded protocol counts overlap across codes. For BRD, the recorded labels show that all 586 Tulathromycin and 126 Oxytetracycline events were first pulls, while all 15 Supportive Therapy events were repeats. Such imbalances indicate treatment selection. Audit event coding, assignment, same-day death chronology and how recovery was recorded. Cohorts with fewer than 30 first pulls or five follow-up deaths are flagged for sparse evidence. Severity, dose, assignment rules and standardized outcomes are unavailable, so the records cannot establish comparative clinical efficacy.

## Carcass volume, yield and grade

Mean HCW was 383.18 kg (SD 31.95), with median 386.40, IQR 360.60–406.30 and 5th–95th percentiles 327.30–431.50 kg. Dressing yield is 5,655,693.9 kg HCW / 9,270,867.1 kg exit live weight (61.0050%). The individual dressing mean is 60.9907%. Realized price is CAD 45,710,188.31 / 5,655,693.9 kg HCW (CAD 8.0822/kg).

| Grade | Eligible sales | Share | Mean HCW, kg | Pooled dressing | Realized CAD/kg HCW | Margin CAD/sold |
|---|---:|---:|---:|---:|---:|---:|
| Canada Prime | 1,239 | 8.39% | 381.24 | 60.93% | 8.314 | 405.55 |
| Canada AAA | 10,063 | 68.18% | 382.94 | 60.99% | 8.120 | 344.02 |
| Canada AA | 3,002 | 20.34% | 384.82 | 61.07% | 7.970 | 300.20 |
| B-Grade/Discount | 456 | 3.09% | 382.90 | 61.03% | 7.371 | 62.72 |

| Individual cohort | Eligible sales | Mean HCW, kg | Pooled dressing | Prime + AAA | Realized CAD/kg HCW |
|---|---:|---:|---:|---:|---:|
| Black Angus | 6,372 | 378.99 | 60.79% | 86.96% | 8.109 |
| Charolais Cross | 3,823 | 393.61 | 61.79% | 68.85% | 8.070 |
| Hereford | 1,992 | 356.14 | 59.80% | 66.82% | 8.027 |
| Simmental Cross | 2,573 | 398.98 | 61.23% | 69.88% | 8.074 |
| Heifer | 4,012 | 344.61 | 60.74% | 76.02% | 8.081 |
| Steer | 10,748 | 397.57 | 61.09% | 76.78% | 8.082 |
| Large frame | 7,580 | 386.39 | 61.15% | 74.53% | 8.080 |
| Medium frame | 7,180 | 379.78 | 60.85% | 78.73% | 8.085 |

Every lot has mixed breeds, and sex is uniform within lot. At the low and high ends of lot mean HCW, LOT-2024-011 sold 196 head at 326.12 kg, with 90.4% Hereford among placements, 307.31 kg mean placement weight and CAD 5.43/kg purchase basis. LOT-2025-016 sold 181 head at 429.66 kg, with 89.1% Charolais Cross, 348.53 kg placement weight and CAD 5.88/kg basis. The lots entered in different quarters. These composition and timing differences matter when reviewing procurement. The notebook tabulates both region and quarter alongside entry/exit weight bands and actual breed shares.

Within lots, modeled associations across 14,760 sales control for individual breed, frame and entry weight where applicable. An extra 10 kg at entry was associated with +6.09 kg HCW (95% pen-clustered interval +6.02 to +6.17), and an extra 10 kg at exit with +6.09 kg (+6.03 to +6.15). An increase of 0.10 kg/day in financial ADG was associated with +10.88 kg HCW (+10.71 to +11.04). One additional kg DM/kg gain in allocated FCR was associated with −73.58 kg HCW (−76.16 to −70.99), where gain enters the ratio and contributes to finish weight. Neither efficiency measure showed a clear fitted Prime + AAA relationship. An extra 10 kg HCW corresponded to CAD 81.19 more booked revenue (+80.06 to +82.32). Prime + AAA versus other grades was associated with CAD 95.58 more revenue at comparable HCW (+92.05 to +99.10). Price and volume contribute mechanically to revenue. The grade comparison also reflects the booked mix and cannot isolate a packer premium.

## Integrated management review

- **Use growth and health records together at closeout.** Among 1,947 previously treated and 12,813 other sellers, the comparable entry cells supported 1,809 and 9,916 cattle across 90 lots. Previously treated cattle had −0.0565 kg/day financial ADG, −5.94 kg HCW (95% whole-pen range −6.40 to −5.49), −2.71 points Prime + AAA (−4.84 to −0.37), −CAD 51.46 per sale of gross revenue (−56.81 to −46.69), and −CAD 104.01 per sale of modeled margin (−109.10 to −99.14). Differences in mean individual dressing yield and realized CAD/kg were near zero. Mortality is analyzed separately at entry and at the event risk sets. The sold contrast describes selected survivors and includes booked treatment cost.
- **Triage weak lots using the ledger components.** Nine lots combined treatment incidence above their placement quarter's 75th percentile with below-median sold ADG and modeled margin per placement. LOT-2024-025 recorded 22/145 treated, three deaths and CAD 129.50/placed, comprising CAD 174.51 of sold contribution less CAD 45.01 of death costs. LOT-2025-009 recorded 26/151 treated, one death and 1.450 kg/day sold ADG, pointing the review toward survivor performance and costs as well as health. LOT-2025-027, a top mortality exception, returned CAD 75.51/placed from CAD 138.83 of sold contribution less CAD 63.32 for deaths. Review its marketed volume and sales records alongside the seven deaths. The joint screen uses exploratory quarter-relative thresholds. [Prior lot economics](01_CLOSEOUT_FINDINGS.md)
- **Prioritize record audits with measurable follow-up.** Reconcile first-pull dates, weigh dates, repeat ordering and deteriorating animals that miss the next scale. Use death-date and treatment-date matches to request time-of-day logs and case notes. Separate large-dollar source and volume differences from grade before comparing procurement options.

## Limitations and bias safeguards

Treatment absence means no event in this source. Clinical severity, dose, case onset, treatment decision logic, recovery assessment, necropsies and independent follow-up are missing. Disease selection, regression toward the mean, calendar-stage differences and survivor selection may explain observed changes. Procurement groups pool different lot mixes and timing. Lot is included in matched contrasts with support counts, and uncertainty resamples whole pens or clusters regression scores by pen. Intervals describe variation in the simulated snapshot. Sparse stratum and lot estimates remain exploratory. The all-outcome ledger covers four costs and lacks full commercial expense and settlement detail. The recorded outcome bridge, survivor differences and any hypothetical intervention economics are distinct quantities.

## Dashboard candidates

| Candidate | Measures and denominators |
|---|---|
| First-pull and repeat review | Unique animals per placement, event count and direct CAD, DOF, index-day deaths and next-day denominators |
| Growth and scale coverage | Interval ADG by known prior status, interior and boundary events, unobserved intervals, same-stage comparable cohorts and persistent low ranks |
| Mortality exceptions | Deaths per placement and per 1,000 animal-days, matched DOF reference, cohort and pen coverage, CAD burden by component |
| Carcass value and lot mix | Eligible grades and HCW, pooled dressing and realized CAD/kg, individual breed and separate lot shares, entry weight and purchase basis |
| Integrated lot review | Quarter reference, health events, sold ADG, sold contribution and death burden per placed head |

## Reproduce and verify

Use Python 3.11 or newer from the repository root. This verification used Python 3.12.14 and the tracked weather snapshot. The 661 baseline controls passed, with 704/704 weather dates and original cattle and weather hashes verified. All 11 tables and three JSON reports matched the starting revision byte for byte. The Phase 2B-1 and 2B-2 notebook analytical outputs and figures matched their starting-revision replays. All 62 tests passed, with zero failures and zero skips. All 12 Phase 2B-3 code cells executed and two figures rendered.

```sh
python -m pip install -e '.[notebook]'
snapshot=phase2a/weather/era5-20261121T143547299379Z-fd9571517552
python -W error -m feedlot_analytics.cli build --output work/phase2b3-canonical --weather-snapshot "$snapshot"
python -W error -m unittest discover -s tests -v
mkdir -p work
python -m nbconvert --to notebook --execute notebooks/03_health_mortality_carcass.ipynb \
  --output-dir work --output 03_health_mortality_carcass.executed.ipynb --ExecutePreprocessor.timeout=240
```

Phase 2B-4 can assess conditional break-even and sensitivities for feeder basis, allocated feed cost, carcass price and mortality. Start from the four-component ledger and distinguish booked death costs from the assumed revenue and incremental costs of a hypothetical additional survivor.
