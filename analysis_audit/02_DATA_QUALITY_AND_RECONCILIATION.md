# 02 · Data quality and reconciliation

## Ringkasan eksekutif

Audit terhadap CSV, sepuluh lembar Excel, dan data yang tertanam dalam HTML mengonfirmasi 15.000 sapi masuk, 14.760 terjual, dan 240 mati (1,60%) dalam 90 lot dan 40 kandang. Margin tercatat untuk seluruh hasil closeout adalah **CAD 4.381.992,99**. Margin khusus sapi terjual adalah **CAD 4.894.187,63** sebelum memasukkan **CAD 512.194,64** biaya pada sapi yang mati. Pembulatan margin per lot menambah **CAD 3,89** pada perhitungan ulang dari HTML.

Total pakan harian dan alokasi ke sapi hampir sama. Selisih agregat sebesar 0,40 kg bahan kering dan CAD 0,57 masih sesuai dengan batas pembulatan per ekor. Data perawatan mencatat 2.220 kejadian pada 2.100 sapi. Proporsi tarikan pertama hingga hari ke-30 adalah 77,71%. Perbedaan performa antarkelompok hanya menunjukkan asosiasi dalam data simulasi.

Prioritas berikutnya adalah membangun analisis margin per lot dan asal pembelian, menyepakati penyebut KPI, serta menguji efisiensi pakan dan biaya kesehatan per kelompok sebelum memperbarui dashboard.

## How the checks were run

From the repository root, with Python 3.12.14, Pandas 2.2.3, NumPy 2.3.5 and openpyxl 3.1.5:

```sh
python -W error analysis_audit/audit_sources.py > /tmp/feedlot-phase1.json
python -W error analysis_audit/audit_sources.py > /tmp/feedlot-phase1-repeat.json
cmp /tmp/feedlot-phase1.json /tmp/feedlot-phase1-repeat.json
git diff --check
```

The script reads the CSV, every workbook sheet and the embedded HTML JSON independently, joining and aggregating in memory. It emits aggregate evidence, file hashes and per-column dtypes and null counts to stdout. Dates use ISO parsing. Numeric comparisons use zero relative tolerance. Flat-copy parity uses a 1e-8 absolute tolerance. Formula checks with residuals include their absolute tolerance in the JSON. The source bundle is identified in [01_SOURCE_INVENTORY.md](01_SOURCE_INVENTORY.md).

**Severity** reflects reporting impact. High affects economics, material cohort comparisons or validity of operational claims. Medium affects interpretation, timing or reproducibility. Low represents display precision or an expected source convention. **Verified** denotes a direct computation or code inspection. **Unverified** indicates that required provenance or external inputs are absent.

## Margin bridge

**High · Verified definition mismatch across dashboard measures.** `index.html` embeds `D.LOTS[].totMargin` and `margin`, and `computeMetrics` displays both. In all 90 lots, `totMargin` equals the sum of `net_margin_cad` across all outcomes, to cents. `margin` equals the sold-only mean rounded to cents in all 90 lots. Both source flat copies and workbook closeout rows match by animal.

| Reconciliation | CAD |
|---|---:|
| Source sold-only closeout margin, 14,760 animals | 4,894,187.63 |
| Source mortality margin, 240 animals | -512,194.64 |
| Source all-outcome margin and sum of embedded `totMargin` | **4,381,992.99** |
| Sum of embedded rounded `sold × margin` | **4,894,191.52** |
| Difference between embedded calculations | **512,198.53** |
| Explained by source mortality burden | 512,194.64 |
| Explained by rounding the embedded lot means | 3.89 |

For `LOT-2024-001`, the exact sold margin is CAD 67,220.13 across 142 sales. One mortality contributes −CAD 1,856.52, yielding CAD 65,363.61. The embedded calculation `142 × 473.38` gives CAD 67,219.96. Across lots the largest absolute rounded subtotal difference is CAD 0.86.

| Closed-cohort ledger component | Sold | Mortality | All outcomes |
|---|---:|---:|---:|
| Purchase cost | 28,637,050.52 | 468,056.07 | 29,105,106.59 |
| Allocated feed cost | 10,199,008.85 | 20,534.64 | 10,219,543.49 |
| Yardage | 1,582,643.40 | 7,707.00 | 1,590,350.40 |
| Veterinary cost | 397,297.91 | 15,896.93 | 413,194.84 |
| Production cost | 40,816,000.68 | 512,194.64 | 41,328,195.32 |
| Revenue | 45,710,188.31 | 0.00 | 45,710,188.31 |
| Net margin | 4,894,187.63 | -512,194.64 | 4,381,992.99 |

Three useful KPI bases are **CAD 292.13/placed**, **CAD 296.88/sold with all-outcome costs**, and **CAD 331.58/sold on sold records only**. The summary worksheet matches the first and third bases. Ledger costs cover only the four stated modeled components. Open balances, overhead beyond modeled yardage, freight, financing and cash timing are absent.

**Medium · Verified additional legacy cost-scope issue.** `D.LOTS[].pCost` and `entryW` are placed means in all lots. The five-step panel weights purchase by head placed and the other components by sold head, despite the sold-head caption. At full scope the displayed inputs imply about CAD 331.42/head before display formatting, while `margin` is CAD 331.58. The component rows of the source ledger close exactly when all costs and revenue use the same cohort.

## Integrity and operating controls

| Check and source evidence | Severity · Status and result |
|---|---|
| CSV vs workbook `Feedlot_Flat_15000` and `Fact_Closeout_Sales`, keyed on `animal_id` | High · Verified. Both flat copies have the same 15,000 IDs in the same order and all 51 columns agree within numeric tolerance. All 25 closeout fields agree, including the key. Shared cattle, lot and pen attributes agree |
| Primary/foreign keys, RFID, and full-row duplicates | High · Verified. Zero blank/duplicate keys, duplicate operational rows, orphans or lot/pen path conflicts. All 15,000 RFIDs are unique 15-digit strings. Workbook summary repeats a blank display row outside the operational tables |
| Required fields, domains and calendar checks | Medium · Verified. All operational dates parse. The only nulls are 240 grades on mortality rows and three flat treatment detail fields blank on 12,900 untreated animals. Sold weight, gain, DOF, FCR, HCW and grid/financial positivity checks passed. No negative animal cost records. Death rows use zero output/growth placeholders while retaining prior costs and allocated intake |
| Cattle movement and lot closeout | High · Verified for the snapshot. `Dim_Lot.head_count_in` matches animal counts in every lot. All 15,000 cattle have exactly one closeout. `Finished Sale` matches `Dim_Cattle.status = Sold`, and `Mortality` matches directly. All 90 lots reconcile placed = sold + deaths. Sold animals share one sold date per lot. Mortality can occur earlier. Independent transfer and inventory journals are absent |
| Date and pen delivery span | High · Verified under an inclusive ledger convention. `Fact_Feed_Daily` starts on lot arrival and ends on last exit with no missing internal days. All 16,085 active-head records agree with inclusive entry/exit counts. Head-days total 2,650,584 on both sides. No pen-days have overlapping lots or exceed nominal capacity. That result describes the recorded simulated assignments |
| Weight, gain, DOF and closeout ratios | High · Verified. All financial DOF values equal elapsed days + 1. Sold gain equals exit less entry weight to displayed precision. Sold ADG and FCR recalculate within 0.0005 at displayed precision, and feed COG and non-purchase COG within 0.005 CAD/kg. No nonpositive sold measures in the tested fields |
| Closeout money and carcass formulas | High · Verified. Purchase equals displayed entry weight × lot price within half a cent per animal. Yardage equals CAD 0.60 × inclusive DOF. Recorded cost and margin tie to the component ledger to cents for all 15,000. HCW equals live exit weight × dressing fraction within 0.05 kg. Recorded sold revenue equals HCW × grid price within half a cent per row, with CAD 1.158 summed residual before per-row rounding |
| Feed delivery fields and allocation | Medium · Verified with rounding residuals. DM is a fraction in (0, 1]. Calculated DMI from as-fed kg × DM fraction ties within 0.005 kg. DMI and cost components sum, and ration labels match inclusive phases 1–14, 15–28, 29–70 and 71+. Delivered totals are 28,544,013.42 kg DM and CAD 10,219,542.92. Animal allocated totals are 28,544,013.02 kg and CAD 10,219,543.49. For each metric, 65 lots differ by over 0.01. Maxima are 0.09 kg and CAD 0.10. Every lot is within its rounding bound of 0.005 kg or CAD 0.005 per animal. The allocation algorithm is unverified |
| Weigh events and time convention | Medium · Verified. Counts by stage are 15,000 arrival, 14,882 Day 35, 14,832 Day 70, 14,794 Day 105 and 14,760 closeout. No nonpositive weights, negative weight changes between weigh events, or out-of-lifetime weigh dates. Arrival and sold closeout weights/dates tie for all animals. Stage labels Day 35/70/105 are elapsed days 34/69/104. Period ADG uses elapsed time since prior weighing. Cumulative ADG uses inclusive time from entry and matches within 0.0005, while 59,268 non-arrival rows differ by over 0.003 using elapsed days |
| Health events and modeled veterinary spend | High · Verified. 2,220 events on 2,100 cattle, with 1,980 treated once and 120 treated twice. Dates fall within animal lifetimes and DOF agrees. Flat counts, first diagnosis/protocol, chronic flag and direct cost tie. Direct treatment cost is CAD 143,194.84. Add CAD 18 × 15,000 for total closeout vet spend of CAD 413,194.84. Of 240 deaths, 153 had a prior or same-day treatment and 27 had repeat treatment |
| Carcass and grade coverage | Medium · Verified. All 14,760 sold animals are graded. Prime 1,239, AAA 10,063, AA 3,002 and B/discount 456. Prime + AAA = 76.57% of sold. Mean HCW is 383.18 kg. The sold dressing fraction ranges from 0.575 to 0.6452. No independent packer confirmations or premium-component data |
| Additivity across lot, pen and dates | High · Verified. Grouping the closeout ledger by lot, pen, placement quarter or exit month preserves CAD 4,381,992.99. Use feed date for delivery metrics and exit date for individual closeout activity. Calendar months can contain partial operational coverage |
| Join fan-out | High · Verified from key multiplicities. A left join to scale and health on animal creates 74,783 rows from 15,000 closeouts. Joining daily deliveries to closeout on lot creates 2,680,547 matched rows. Summing original money on either joined table overstates it. Aggregate each fact to the requested reporting grain first |

### Sold KPI aggregation comparisons

| Metric | Mean of animal ratios | Ratio of underlying totals |
|---|---:|---:|
| ADG, kg/day | 1.617826 | 1.618056 |
| FCR, kg DM/kg gain | 6.695244 | 6.673576 |
| Feed COG, CAD/kg gain | 2.399625 | 2.389641 |
| Non-purchase COG, CAD/kg gain | 2.869231 | 2.853543 |
| Dressing yield | 60.9908% | 61.0050% |

The workbook summary rounds the individual means. The HTML's sold-weighted lot means approximate the same population means at embedded precision. A ratio of totals weights by animal days, gain or live kg as appropriate. Including DM allocated to deaths in the numerator yields 6.687898 kg DM per sold kg gain, a separately scoped burden measure. Summing `head_count_in` or `capacity_head` across animal rows repeats lot and pen values.

## Additional legacy and narrative findings

| Finding | Evidence and status |
|---|---|
| Lot identities, filters and carcass rollup | Medium · Verified. Embedded IDs, lot attributes, pen, arrival, placement quarter, headcounts and grade counts tie for all 90 lots. Individual `breed` differs from `predominant_breed` on 1,447 records. Sold individual Black Angus grade share is 86.96% Prime/AAA vs 85.19% in predominantly Angus lots. Individual Charolais CAD 412.35/sold vs CAD 405.21 in Charolais lots. The README gives Angus CAD 318.40. The source individual and HTML lot figures are CAD 305.22 and CAD 307.41 |
| Seasonal story vs data | High · Mixed. All 24 `DMI_HEAD_DAY` and `COST_HEAD_DAY` values tie to full-yard daily delivery ÷ recorded head-days within 0.005 of display rounding and ignore lot filters. December 2025's 14.76 kg DM/head-day covers only through December 4. `winterFCR` selects placement-quarter indices 2 and 3, i.e. Q3 and Q4 2024, without testing weather exposure. Sold ledger barn margin exceeds both open types combined by CAD 47.91/head. The claimed CAD 49.82 winter savings, barley price spike and causal cold/pen effects are unverified |
| Pull timing and diagnosis | Medium · Verified. Embedded counts are first diagnoses, so 1,366/2,100 = 65.05% first BRD diagnoses. There are 1,446/2,220 = 65.14% BRD events. Through Day 30 there are 1,632/2,100 first events (77.71%) and 1,685/2,220 events (75.90%). The 78% narrative rounds the first-pull share. Repeat-treated animals account for 27/240 = 11.25% of all deaths and 27/153 = 17.65% of treated deaths |
| Growth and morbidity weighting | High · Verified scope issue. `computeMetrics` subtracts all deaths from treated head and weights both scale cohorts by total sold per lot. Source mortality includes 87 animals with no treatment. This leaves 1,947 treated survivors versus 1,860 implied by the HTML weights. The displayed scale aggregation implies a 10.59 kg exit gap. Source sold cohort averages are 629.42 vs 619.50 kg and CAD 345.21 vs CAD 241.90 for untreated vs treated. The respective differences are 9.92 kg and CAD 103.31/head. These are associations through closeout in a simulated cohort |
| Treatment outcome and recommendations | High · Mixed. Embedded protocol case, recovery and death counts tie by lot and protocol. Treatment cost totals tie within CAD 0.05 per lot/protocol. The first-event recovery outcome is 1,864/2,100 = 88.76%. All-event recovery is 1,957/2,220 = 88.15%. The hard-coded recovery labels in `p2` and drug text lack a documented denominator and case adjustment. Treatment selection, permanence of weight deficits and culling thresholds cannot be established from simulated outcomes |
| Breed and carcass recommendations | High · Unverified for interventions. Breed and frame comparisons are descriptive. Realized price, weight and grade are recorded. Base grid, packer terms and individual premium/discount components are absent, so isolated grid economics and an optimal 60/40 purchase mix cannot be proven |

## Verification record

The audit executed the source load, key, parity, null, domain, ledger, feed, scale, health, timing, HTML reconciliation and join-cardinality checks above. Repeated runs produced identical JSON. The inspected source artifacts were verified unchanged against the Git baseline. Observed precision residuals, denominator differences and missing provenance are retained as findings. Source records were read without correction.
