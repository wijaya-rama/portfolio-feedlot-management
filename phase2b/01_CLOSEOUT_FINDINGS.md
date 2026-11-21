# Phase 2B-1 · Closeout economics and procurement

Highwood Feeders closed 90 simulated placement lots covering 15,000 animals across 40 recorded pens. Placements ran from 1 January 2024 to 5 June 2025. The final exit was 4 December 2025. All financial amounts are nominal CAD. The [closeout notebook](../notebooks/01_closeout_economics.ipynb) rebuilds the verified Phase 2A tables from source and reproduces the calculations and charts.

## Margin and mortality

| Measure | Observed result | Basis |
|---|---:|---|
| Booked revenue | $45,710,188.31 | 14,760 sales and zero revenue on 240 deaths |
| Modeled production cost | $41,328,195.32 | All outcomes, four booked cost components |
| All-outcome margin | **$4,381,992.99** | Revenue less modeled costs |
| All-outcome margin per placed head | **$292.13** | $4,381,992.99 / 15,000 placements |
| All-outcome margin per sold head | $296.88 | Same margin / 14,760 sales |
| Sold-only margin per sold head | $331.58 | $4,894,187.63 / 14,760 sales |
| Recorded mortality loss | **$512,194.64** | $4,894,187.63 sold margin less $4,381,992.99 all-outcome margin |
| Mortality loss per placed head | $34.15 | $512,194.64 / 15,000 placements |

| Component | All outcomes | Share of cost | On mortality records |
|---|---:|---:|---:|
| Purchase | $29,105,106.59 | 70.42% | $468,056.07 |
| Allocated feed | $10,219,543.49 | 24.73% | $20,534.64 |
| Yardage | $1,590,350.40 | 3.85% | $7,707.00 |
| Veterinary | $413,194.84 | 1.00% | $15,896.93 |

Use all-outcome CAD per placed head as the primary placement closeout KPI. Publish the sold-only rate alongside its denominator so reviewers can see survivor economics and the cost burden carried by sales. Purchase and feed account for 95.15% of modeled cost. Purchase alone accounts for 91.38% of death loss. The loss is already in the all-outcome ledger. The modeled veterinary figure already includes direct treatment expenses. Sold feed and non-purchase cost of gain were $2.390 and $2.854 per kg of gain, respectively, using the same eligible sold gain denominators for each ratio.

## Lot review and realized downside

Rank complete lots within entry quarter by all-outcome CAD per placed head. Eligibility requires at least 100 placements in a lot and at least five eligible lots in the quarter. All 90 lots qualify, with 140–219 head each and 8–23 lots per quarter. Peer deltas divide the other lots' additive totals by their combined placements. Revenue deviations enter positively and cost deviations inversely. This controls the comparison window and normalizes lot size. Origin, mix and settlement differences remain.

| Entry quarter | Best lot | CAD/placed | Worst lot | CAD/placed | Lots |
|---|---|---:|---|---:|---:|
| 2024Q1 | LOT-2024-002 | $499.98 | LOT-2024-021 | $197.43 | 21 |
| 2024Q2 | LOT-2024-023 | $373.97 | LOT-2024-034 | $128.72 | 18 |
| 2024Q3 | LOT-2024-042 | $322.80 | LOT-2024-040 | $196.09 | 11 |
| 2024Q4 | LOT-2024-056 | $371.29 | LOT-2024-055 | $158.45 | 8 |
| 2025Q1 | LOT-2025-004 | $452.16 | LOT-2025-009 | $174.18 | 9 |
| 2025Q2 | LOT-2025-016 | $481.56 | LOT-2025-027 | $75.51 | 23 |

- **Review marketed volume, settlement and deaths for LOT-2025-027.** It earned $16,386.50 across 217 placements, including seven deaths, and was $215.91 per placed head below its quarter peers. The revenue shortfall was $513.17 per placement, partly offset by $187.13 lower purchase and $106.38 lower feed cost. The books support this additive bridge. Identifying individual packer adjustments requires settlement detail.
- **Investigate purchase and feed for LOT-2024-040.** Revenue exceeded 2024Q3 peers by $131.93 per placement. Purchase and feed were $155.45 and $40.45 higher, respectively. Those components explain most of the $71.24 per placement margin shortfall.
- **Track negative-margin animals even when every lot is profitable.** There were 404 loss-making placements (2.69%), totaling $522,476.25 before profitable animals offset the loss. Deaths contributed 98.0% of that amount. The 164 loss-making sold animals represented 1.11% of sales and $10,281.61 in gross loss. The 750 observations at or below the fifth percentile of placed margin averaged −$674.82. All 90 lots, all 40 pen aggregates and all observed region–quarter groups remained profitable. The bottom five lots by total margin averaged $21,238.45 in positive margin. The observed tail describes the snapshot and provides no independent estimate of future loss risk.
- **Publish the ranking denominator.** Changing from all-outcome CAD per placement to sold-only CAD per sale changes 61 ranks. Survivor selection and the switch in denominator both matter.

## Procurement and performance

**Review bids by placement quarter.** Pooled margins ranged from $285.15 per placement in Central Saskatchewan (26 lots, 4,423 head) to $302.65 in Peace River BC (14 lots, 2,369 head). All four regional lot-margin interquartile ranges overlap. Lowest modeled cost was Manitoba Foothills at $2,729.15 per placement, versus $2,788.55 in Peace River BC. Across quarters, modeled costs ranged from $2,600.86 to $2,841.21 per placement and margin from $258.32 to $341.54. The region–quarter table shows two empty cells and four single-lot cells. Within 2024Q3, Manitoba was ahead of Peace River BC, with two lots in each group. Treat the regional figures as sourcing review prompts given the changing mix and limited overlap. The booked purchase basis is live-weight weighted and excludes freight and shrink.

**Distinguish fitted relationships from repricing.** Across 90 equally weighted lots, separate regressions centered within six placement quarters associated $0.10/kg higher lot purchase quote with $20.77 lower margin per placement (leave-one-lot-out range −$23.20 to −$18.47). A 5 kg higher mean entry weight was associated with $9.26 higher margin per placement (range $8.35–$10.25). The ranges measure sensitivity to individual lots. Centering jointly by quarter and lot sex gave −$35.16 and +$10.20 per stated increment. Lot mean entry weights fell in separate bands for heifers (306–312 kg) and steers (346–354 kg). This limits comparisons across sex classes. Price is a component of the response, and the separate fits leave price, weight and other traits free to co-vary. Use the fixed-volume price sensitivity for direct budget exposure.

**Use ADG and FCR for diagnostics, then check the feed and weight records.** Sold aggregate ADG was 1.618 kg/day and allocated FCR was 6.674 kg DM/kg gain. Across 14,760 sold animals in 90 lots, within-lot single-metric fits associated an extra 0.10 kg/day ADG with $70.68 higher margin per sold head (95% whole-lot bootstrap interval $68.85–$72.39). An extra kg DM/kg gain was associated with $395.95 lower margin per sold head (interval −$410.97 to −$380.97). Both measures share gain, and feed allocation and carcass volume enter the margin ledger. Treat the intervals as snapshot sensitivity. Every lot shares a single sold DOF value within the lot. The lot-level comparison after quarter centering gave a $13.36 increase in sold margin per sold head per ten additional days (leave-one-lot-out range $7.35–$16.64). Timing is a management choice and can follow weight targets and market bookings.

**Evaluate purchase specifications on economics and carcass outcomes together.** Charolais Cross individuals averaged $375.87 per placement (3,879 head) and Hereford individuals $159.51 (2,023 head). Black Angus had 86.96% Prime + AAA among 6,372 graded sales, while Charolais Cross sold carcasses averaged 393.61 kg versus 378.99 kg for Black Angus. Steers averaged $308.94 per placement versus $247.07 for heifers. Large-frame cattle averaged $312.33 versus $270.86 for medium. These descriptive results overlap on weight, sex, breed and placement timing. All lots were single-sex. All were mixed-breed, with 84.3%–96.4% in the leading individual breed. The 41 lots below a 90% leading-share threshold pooled at $310.23 per placement, versus $277.19 for the 49 other lots. The exploratory threshold and overlapping lot distributions support a mix review. They provide no basis to prescribe a breed mix or to reclassify individual animals.

## Conditional price thresholds

| One-at-a-time scenario | Volume denominator | Booked or realized | Conditional break-even | Margin impact of $0.10/kg adverse move |
|---|---|---:|---:|---:|
| Maximum feeder basis | Entry live kg of all 15,000 placements | $5.724/kg live | **$6.586/kg live** | −$508,480 |
| Minimum carcass price | Hot carcass kg of all 14,760 sold animals | $8.082/kg HCW | **$7.307/kg HCW** | −$565,569 |

Feeder break-even deducts non-purchase modeled costs from booked revenue and divides by placed live kg. Carcass break-even divides all-outcome modeled costs by eligible sold HCW at full coverage, holding any other booked revenue fixed. Mortality remains in the costs and has zero booked revenue in the snapshot. Both scenarios hold survival, weights, grades and all other booked economics fixed. LOT-2025-027 has the narrowest observed headroom, $0.244/kg live and $0.233/kg HCW. Review headroom at lot grain before using a portfolio average. A live bid or revenue plan also needs freight, financing, overhead, risk allowance and settlement terms.

## Review of the 164 original exceptions

| Severity · status | Rule | Count | Cause and consequence |
|---|---|---:|---|
| Low · qualified | Feed cost rounding | 83 | Delivered minus allocated cost across flagged lots was −$0.57. Largest absolute lot residual was $0.10. All were within the lot-specific bound of $0.005 per placed head, consistent with source precision. The financial ledger uses allocated cost. |
| Low · qualified | Feed DM rounding | 77 | Delivered minus allocated DM totaled +0.40 kg. Largest absolute lot residual was 0.09 kg DM. All were within the bound of 0.005 kg DM per placed head. Use delivered DM for delivery analysis and allocated DM for sold FCR. |
| Low · verified | Untreated encoding | 1 | For 12,900 untreated animals, CSV `None` and Excel blanks encode the same state in diagnosis and protocol. Phase 2A source parity accounts for the difference. |
| Medium · blocked | Weather unavailable | 1 | The archived proxy attempt blocked ERA5 coverage before a provider response, leaving 0 of 704 requested days. Exposure windows remain available with missing weather measures. |
| High · verified | Individual breed scope | 1 | Individual breed differs from the lot label for 1,447 animals. Reporting follows `Dim_Cattle` at animal grain and uses observed shares for lot composition. |
| High · open | Simulator provenance | 1 | Simulator code, seed and independent farm records are absent. The source cannot verify allocation methods, intervention effects, seasonal rules or actual occupancy. |
| **Total** | | **164** | **161 low, 1 medium, 2 high.** One lot can appear under both feed rules. |

The notebook reconciles every original exception key and retains the full register with its original observations and interpretations. All 661 hard controls passed, and the Phase 2A exports, including the exception register and the full control list, matched the baseline byte for byte. The Phase 1 audit JSON was also identical on replay. The clean Python environment executed all 12 notebook code cells and rendered four figures. Of 43 automated tests, 42 passed and the live ERA5 integration test was skipped because the verified archive was unavailable.

## Dashboard candidates

| Candidate | Reporting specification |
|---|---|
| Margin and mortality bridge | Booked revenue, four modeled costs, sold-only margin and mortality loss. Display all three margin/head denominators. |
| Lot peer review | Entry quarter, eligible lot and head counts, all-outcome CAD per placement, alternate sold-only rank, and the five additive peer deltas. |
| Procurement variation | Region and entry-quarter basis, cost and margin. Show pooled per-head figures, observed lot quartiles and small-cell counts. |
| Downside and pricing | Negative-margin animals, gross loss, bottom-tail realized margin and lot-specific feeder and carcass headroom with kg exposure. |
| Carcass and composition | Individual breed, sex and frame groups with eligible HCW and grade counts. Show actual breed share separately on each lot. |

The next phase is **Phase 2B-2 · Feed, growth and exposure**. Start with the delivered-to-allocated feed bridge, stage-level growth coverage and the difference between inclusive financial DOF and elapsed weigh intervals. Add weather exposure only when a verified snapshot is available and its coverage is documented.

## Reproduce

Run from the repository root with Python 3.11 or later. The verification environment used Python 3.12.14. The notebook rebuilds from the tracked CSV, workbook and archived Phase 2A weather status.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[notebook]'
python -W error -m unittest discover -s tests -v
mkdir -p work
python -m nbconvert --to notebook --execute notebooks/01_closeout_economics.ipynb \
  --output-dir work --output 01_closeout_economics.executed.ipynb --ExecutePreprocessor.timeout=180
```
