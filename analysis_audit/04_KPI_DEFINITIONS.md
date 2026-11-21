# 04 · KPI definitions

The proposed definitions use nominal CAD, live weight in kg, and dry matter (DM) in kg. Resolve zero or absent denominators to an unavailable metric and display the eligible population. Preserve raw values and flag ineligible observations in derived outputs. Use “head placed”, “head sold” or “head-day” explicitly in labels. Field sources and grains are in [01_SOURCE_INVENTORY.md](01_SOURCE_INVENTORY.md) and audit results are in [02_DATA_QUALITY_AND_RECONCILIATION.md](02_DATA_QUALITY_AND_RECONCILIATION.md).

## Inventory, cohorts and timing

| KPI | Numerator / rule | Denominator, cohort and controls |
|---|---|---|
| Head placed | Count distinct `Dim_Cattle.animal_id` with placement in the selected cohort | `entry_date`. Cross-check to `Dim_Lot.head_count_in` once per lot. Never sum repeated flat `head_count_in` on animal rows |
| Head sold | Count distinct closeout animal IDs with `exit_type = Finished Sale` | For sales activity use `exit_date`. For closed-lot cohort analysis use the selected lots' final exit dates and all eligible records |
| Deaths / mortality | Count distinct closeout animals with `exit_type = Mortality` | For mortality risk divide by head placed in the same eligible cohort. Separately report deaths observed by calendar date. No independent movement ledger |
| Sold share | Head sold | Head placed in the same cohort, with censoring shown if applicable. Reconcile placed = sold + deaths when a lot is fully closed and there are no other recorded exits |
| Financial DOF | `(exit_date - entry_date).days + 1` from the animal ledger | Sold mean DOF = sum sold financial DOF / sold head. Report death DOF separately where needed. Keep inclusive financial DOF distinct from elapsed weigh intervals |
| Ledger-implied active inventory | Count placed animals with `entry_date <= d <= exit_date` at the recorded lot/pen on day `d` | Audit comparison under an inclusive, no-transfer convention. Coverage and timing of feed vs movements need verification before interpreting this as pen census |
| Recorded head-days | Sum `Fact_Feed_Daily.head_count_active` over eligible lot–pen–days | Reconcile to ledger-implied head-days. Sum counts on pen-days with overlapping lots only as a recorded proxy. Report nominal `Dim_Pen.capacity_head` once per pen |

## Economics

| KPI | Numerator / rule | Denominator, cohort and controls |
|---|---|---|
| Purchase cost and basis | Sum `purchase_cost_cad`. Purchase basis = sum cost / sum `entry_weight_kg` | All eligible placements for procurement analysis. `feeder_purchase_price_per_kg` is a lot quote. Price×volume recalculation uses available displayed precision |
| Production cost, ledger scope | `purchase_cost_cad + allocated_feed_cost_cad + yardage_cost_cad + vet_cost_cad` | All outcome records for a fully closed cohort. Four modeled components only. Yardage is CAD 0.60 per inclusive financial day |
| Closeout revenue | Sum `gross_revenue_cad` | All outcomes, with zero for deaths. Preserve exact booked source revenue. Product of displayed HCW and grid price ties within half a cent per record |
| All-outcome net margin | Sum booked `net_margin_cad`, verified against recorded revenue less the four ledger costs | No head denominator. Include death loss. For period comparison name placement, animal exit or final lot exit date explicitly |
| Margin per head placed | All-outcome net margin | Distinct placed head across the same completed lot cohort |
| All-outcome margin per head sold | All-outcome net margin | Distinct sold head in the same cohort. Allocates full recorded cost burden over output |
| Sold-only margin per head sold | Sum sold `net_margin_cad` | Distinct sold head. Survivor economics and a separate reporting measure |
| Recorded death loss | Sum of four ledger costs on mortality rows minus recorded revenue | Report as positive burden or use negative contribution in the margin bridge. Never add it twice to an all-outcome ledger |
| Realized price per kg carcass | Sum sold `gross_revenue_cad` | Sum sold `hot_carcass_weight_kg`. Separate from unweighted average of recorded grid prices. No premium-by-component data |
| Conditional break-even price | Sum modeled costs less any scenario credits | Per kg HCW, divide by sold HCW with stated volume/mix. For maximum feeder basis deduct projected non-purchase costs from projected revenue and divide by placed entry kg. Explicitly state scenario assumptions |

## Growth, feed and carcass

| KPI | Numerator | Denominator, cohort and controls |
|---|---|---|
| Sold liveweight gain | Sum sold `total_gain_kg` with reconciliation to `exit_weight_kg - entry_weight_kg` | No denominator for total. Per sold head divide by eligible sold head. Death rows carry zero placeholders. Sign and interval checks are separate |
| Sold ADG | Sum sold eligible `total_gain_kg` | Sum the same sold animals' `financial_dof`. Individual mean ADG is separately labeled. For period scales use signed weight change and actual elapsed days |
| Allocated feed and feed cost | Sum `allocated_dmi_kg` or `allocated_feed_cost_cad` | Animal closeout scope. All outcomes for the financial bridge or sold only for standard sold efficiency measures |
| Delivered feed and feed spend | Sum `Fact_Feed_Daily.total_dmi_kg` or `total_feed_cost_cad` | Lot–pen–day. Treat deliveries as a proxy for consumption. Reconcile to animal allocations by lot separately |
| Delivered DM and cost per head-day | Delivered total DM or delivered cost | Recorded head-days for the same feed dates and grain. Label as based on recorded feed headcount and disclose partial months |
| Sold FCR | Sum sold allocated DM | Sum the same sold animals' valid gain. Report kg DM / kg gain. Optional death-inclusive allocated DM per sold kg gain is a different KPI |
| Sold feed COG | Sum sold allocated feed cost | Sum the same sold animals' valid gain. CAD per kg gain |
| Sold non-purchase COG | Sum sold allocated feed cost + yardage + closeout veterinary cost | Sum the same sold animals' valid gain. Source `total_cost_of_gain_per_kg` excludes feeder purchase. A death-inclusive cost burden per sold kg requires a separate label |
| Mean hot carcass weight | Sum eligible sold `hot_carcass_weight_kg` | Eligible sold head, with HCW coverage shown |
| Dressing yield | Sum sold `hot_carcass_weight_kg` | Sum corresponding sold `exit_weight_kg`. Multiply by 100 to display percent. Source `dressing_pct` is a fraction. Mean animal dressing % must be labeled as an individual mean |
| Grade mix and premium-grade share | Sold counts by `quality_grade`. Count Prime + AAA for premium-grade share | Graded sold head. Report ungraded sold head independently. Display references to grades as supplied in the simulator |

## Health

| KPI | Numerator / rule | Denominator, cohort and controls |
|---|---|---|
| Recorded morbidity | Unique placed cattle with one or more linked treatment events | Head placed in the same cohort. Reflects recorded treatment, with no independent surveillance count |
| First pull through Day 30 | One first event per animal ordered by treatment date and treatment ID, inclusive DOF 1–30 | Treated head for timing share, all placed for cohort incidence. All-event timing is a separately labeled series |
| Diagnosis distribution | Count first recorded diagnoses per treated animal, or count all diagnosis events | For first diagnoses divide by treated head, for all events by event count. State method next to result |
| Re-treatment share | Distinct animals with two or more total treatment events | Treated head. For comparisons across time, require comparable follow-up or account for censoring |
| Treatment cost | Sum `Fact_Health_Treatments.vet_cost_cad` | Per event divide by recorded events, per treated head divide by treated animals. Closeout veterinary cost includes simulated base processing, so do not sum both as expenses |
| Recorded outcome share | Count recorded outcome rows within protocol and diagnosis | Event count for the same protocol and diagnosis, with sample size. This is a recorded outcome proportion with case selection and potential repeat events |
| Associated health performance difference | Compare sold cohort mean weights and CAD/sold by event ever recorded, and track mortality separately | Define comparable cohorts and account for differences in starting profile and treatment timing. Interpret associations with survivor selection in view |

Store additive numerators and denominators until the final presentation step. A ratio of totals uses the underlying economic or biological denominator. Average individual ratios answer a different question. Weighting lot means by sold heads reproduces an individual mean only for consistently defined sold snapshots and introduces small rounding differences if only rounded means are available.
