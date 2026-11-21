# Phase 2B-4 · Management scenarios, break-even and sensitivity

Highwood Feeders closed 90 simulated placement lots. All money is nominal CAD. The analysis covers modeled closeout margin from purchase, allocated feed, yardage and veterinary costs. Commercial earnings would also require freight, shrink, financing, overhead and other costs outside the booked model. The default shocks and outcome assumptions are illustrative. [Management notebook](../notebooks/04_management_scenarios.ipynb) · [Editable scenario configuration](04_MANAGEMENT_SCENARIOS_CONFIG.json)

## Booked baseline

| Verified control | Booked value |
|---|---:|
| Placed cattle | 15,000 |
| Sold cattle with eligible HCW | 14,760 |
| Deaths | 240 (1.60%) |
| Purchased entry liveweight | 5,084,801.2 kg |
| Sold hot carcass weight (HCW) | 5,655,693.9 kg |
| Gross revenue | 45,710,188.31 |
| Purchase cost | 29,105,106.59 |
| Allocated feed expense | 10,219,543.49 |
| Yardage | 1,590,350.40 |
| Veterinary cost | 413,194.84 |
| **Total modeled costs** | **41,328,195.32** |
| **All-outcome modeled margin** | **4,381,992.99** |
| **Modeled margin per head placed** | **292.13** |
| Recorded death cost burden, already in the ledger | 512,194.64 |

All 90 booked lot margins were positive. The animal-level historical downside was 404 negative-margin placements, of which 240 were deaths and 164 were sold cattle. Losses before offsets totaled CAD 522,476.25 across those records. Scenario lot losses below describe a different, hypothetical downside. [Phase 2B-1 closeout](01_CLOSEOUT_FINDINGS.md) · [KPI definitions](../analysis_audit/04_KPI_DEFINITIONS.md)

## Management scenario comparison

Revenue, costs, total margin and changes are displayed to the nearest CAD. The denominator for CAD/head is 15,000 placements in every row. The loss count is the number of lots below CAD 0 at cent precision. Operational costs include the explicit other expense in the applicable scenario. [Full inputs and limitations by row](04_MANAGEMENT_SCENARIOS_CONFIG.json)

| Case | Main assumption | Revenue | Costs | Margin | CAD/head placed | Δ margin | Loss lots |
|---|---|---:|---:|---:|---:|---:|---:|
| Booked base | Observed outcomes and settlement | 45,710,188 | 41,328,195 | 4,381,993 | 292.13 | 0 | 0/90 (0.0%) |
| Higher feeder basis | +0.25 CAD/kg live | 45,710,188 | 42,599,396 | 3,110,793 | 207.39 | −1,271,200 | 1/90 (1.1%) |
| Higher allocated feed | +10% across allocated expense | 45,710,188 | 42,350,150 | 3,360,039 | 224.00 | −1,021,954 | 0/90 (0.0%) |
| Finisher feed repriced | +15% for Finisher | 45,710,188 | 42,410,393 | 3,299,795 | 219.99 | −1,082,198 | 0/90 (0.0%) |
| Concentrate repriced | +15% for concentrate | 45,710,188 | 42,531,712 | 3,178,476 | 211.90 | −1,203,517 | 0/90 (0.0%) |
| Lower carcass CAD/kg | −0.35 CAD/kg HCW | 43,730,695 | 41,328,195 | 2,402,500 | 160.17 | −1,979,493 | 2/90 (2.2%) |
| Lower carcass percentage | −5% of eligible revenue | 43,424,679 | 41,328,195 | 2,096,484 | 139.77 | −2,285,509 | 3/90 (3.3%) |
| Adverse prices | +0.30 live, +15% feed, −0.40 HCW | 43,447,911 | 44,386,567 | −938,656 | −62.58 | −5,320,649 | 74/90 (82.2%) |
| Favorable prices | −0.15 live, −5% feed, +0.20 HCW | 46,841,327 | 40,054,498 | 6,786,829 | 452.46 | +2,404,836 | 0/90 (0.0%) |
| Lower mortality, conservative finish | 60 more sales, conservative terms | 45,859,506 | 41,384,954 | 4,474,552 | 298.30 | +92,559 | 0/90 (0.0%) |
| Lower mortality, favorable finish | Same 60, favorable terms | 45,906,865 | 41,368,705 | 4,538,161 | 302.54 | +156,168 | 0/90 (0.0%) |
| Higher mortality | 60 fewer sales, 20% feed and yardage avoidable | 45,521,458 | 41,323,018 | 4,198,440 | 279.90 | −183,553 | 0/90 (0.0%) |
| Adverse prices and higher mortality | Adverse prices plus 60 fewer sales | 43,268,503 | 44,380,132 | −1,111,629 | −74.11 | −5,493,622 | 76/90 (84.4%) |

The purchase, feed and carcass cases are fixed-volume accounting sensitivities. All placements, biological volumes, recorded grades and outcomes stay fixed in those rows. The operational rows change sold head and HCW. The two lower-mortality endpoints span CAD 63,608.80 in incremental margin for the same selected records. That span reflects the stated assumptions and carries no probability. The adverse and favorable prices support a margin cushion review across procurement, feed budgets and sales. They use concurrent shocks with no estimated joint distribution.

## Feeder procurement

An entry basis increase of CAD 0.10/kg adds CAD 508,480.12 of purchase cost on the actual entry weight of all placements. That is CAD 33.90 per placed head. The default CAD 0.25/kg increase adds CAD 1,271,200.30, equivalent to 4.37% of booked purchase expenditure. Margin falls to CAD 3,110,792.69 (CAD 207.39 per placed head). The model holds all other unit costs, weights, volumes and lot mix fixed.

The booked portfolio basis was CAD 5.723942/kg live. The modeled maximum is CAD 6.585724/kg, with CAD 0.861783/kg of headroom. It supports an all-outcome procurement budget under the fixed ledger assumptions. A market bid requires delivered cost and realistic risk allowance, including freight, financing and shrink. The notebook exposes the lot, regional, quarter and region-by-quarter kilogram denominators and comparable carcass thresholds. Sparse origin-by-quarter cells and lot composition limit sourcing comparisons.

| Procurement cohort | Placed | Feeder headroom (CAD/kg live) | Carcass headroom (CAD/kg HCW) | CAD/placed at +0.25 live | CAD/placed at −0.35 HCW |
|---|---:|---:|---:|---:|---:|
| Central Saskatchewan | 4,423 | 0.839 | 0.754 | 200.20 | 152.79 |
| Manitoba Foothills | 2,997 | 0.874 | 0.790 | 211.78 | 165.18 |
| Peace River BC | 2,369 | 0.896 | 0.797 | 218.21 | 169.66 |
| Southern Alberta | 5,211 | 0.859 | 0.774 | 206.04 | 159.23 |
| 2024Q1 | 3,370 | 0.989 | 0.899 | 248.68 | 203.29 |
| 2024Q2 | 3,094 | 0.757 | 0.669 | 173.07 | 123.13 |
| 2024Q3 | 1,820 | 0.750 | 0.700 | 173.30 | 130.00 |
| 2024Q4 | 1,285 | 0.892 | 0.823 | 208.59 | 166.64 |
| 2025Q1 | 1,593 | 1.014 | 0.892 | 257.36 | 207.47 |
| 2025Q2 | 3,838 | 0.817 | 0.726 | 193.81 | 144.67 |

Southern Alberta has the greatest total CAD exposure to the feeder move (CAD 441,139) because it has the most entry kg. Central Saskatchewan has the narrowest pooled regional feeder and carcass cushions. The narrowest quarterly cushions are 2024Q3 for purchase and 2024Q2 for carcass. The sole feeder loss at +0.25 is LOT-2025-027, in Southern Alberta. Investigate net delivered basis and placement specifications at lot grain before using a pooled cohort figure as a budget.

## Feed budgets and ration exposures

Each 1% uniform rise changes margin by −CAD 102,195.43, or −CAD 6.81 per placement. A 42.8786% uniform rise would use the entire modeled baseline margin with all else fixed. Finisher and concentrate exposures are CAD 7.215 million (70.6%) and CAD 8.023 million (78.5%) of allocated feed respectively. Their +15% cases add CAD 1,082,197.78 and CAD 1,203,516.72 of modeled expense. They overlap because some concentrate is in Finisher deliveries. A simultaneous shock uses compounded factors on the overlapping exposure.

All 90 lots pass the feed reconciliation bound. The delivered ledger was CAD 10,219,542.92, or CAD 0.57 below booked allocated feed. Cost shares originate from the three components of each native lot–pen–day feed row. Daily component totals are adjusted proportionally to match the recorded delivery row's total cost. The phase and ingredient subtotals are then scaled within lot to the exact booked allocation. They estimate exposure because the animal ledger provides only total allocated feed by animal. The deployed financial calculation uses the allocated feed expense once.

Four lots meet the exploratory screen of at least CAD 732.48 feed per placement and at most CAD 238.20 booked margin per placement, the upper and lower quartiles respectively. LOT-2024-029, LOT-2024-040, LOT-2024-046 and LOT-2024-043 absorb CAD 46,278.62 combined under the uniform +10% case, leaving between CAD 102.16 and CAD 126.89 of margin per placement. Review dated ration invoices, ingredient usage, delivery and refusal/shrink records before adjusting the feed budget. The accounting response holds ration composition, delivered and consumed DM, feed conversion, ADG and survival fixed. [Phase 2B-2 feed reconciliation](02_FEED_GROWTH_FINDINGS.md)

## Marketed carcass value

A CAD 0.10/kg HCW decrease removes CAD 565,569.39, or CAD 37.70 per placement. A 1% decline in realized price removes CAD 457,101.88 (CAD 30.47 per placement). The CAD 0.35/kg decrease removes about CAD 1.979 million, leaving CAD 160.17 per placed head. LOT-2025-027 and LOT-2024-025 become loss-making. The 5% case removes CAD 2.286 million and leaves CAD 139.77 per placed head. Sales volume, grade mix and mortality remain at observed levels.

The HCW-weighted booked price was CAD 8.082154/kg. The conditional minimum is CAD 7.307361/kg, a cushion of CAD 0.774793/kg or 9.5865% of eligible booked revenue. Booked realized price uses total eligible receipts divided by eligible HCW. A proposed market price or grid quote needs settlement schedules, premiums, discounts and marketing terms. The model uses no separately estimated premium or penalty. Use these thresholds to set revenue stress and settlement review priorities. [Phase 2B-3 carcass findings](03_HEALTH_CARCASS_FINDINGS.md)

## Mortality economics

The two lower-mortality cases turn 60 observed deaths into hypothetical sales, leaving 180 deaths (1.20%). Whole outcomes are assigned by sorting IDs within original outcome and lot, then pooling the midpoint fractional ranks `(position + 0.5) / eligible count` with zero-based position and ties broken by lot and animal ID. This spreads the assignments and keeps cohort filters consistent. The sensitivity endpoints use the same selected 60 across 56 lots. The selected records carry CAD 128,000.33 of already incurred purchase, feed, yardage and veterinary costs. Those costs stay in modeled closeout, within the recorded total death burden of CAD 512,194.64.

| Incremental item | Conservative finish | Favorable finish |
|---|---:|---:|
| Conditional inclusive days on feed at finish | 195 | 185 |
| Additional days per hypothetical survivor, mean (range) | 144.82 (57–189) | 134.82 (47–179) |
| Finish live kg / dressing / HCW kg per head | 570 / 59.0% / 336.30 | 650 / 61.5% / 399.75 |
| Assumed realized CAD/kg HCW | 7.40 | 8.20 |
| Additional HCW, kg | 20,178 | 23,985 |
| Potential additional sale revenue, CAD | 149,317.20 | 196,677.00 |
| Additional feed, CAD (5.00 / 4.00 CAD per extra day) | 43,445.00 | 32,356.00 |
| Additional yardage, CAD (0.60 CAD per extra day) | 5,213.40 | 4,853.40 |
| Additional veterinary expense, CAD (85 / 30 CAD per head) | 5,100.00 | 1,800.00 |
| Other incremental expense, CAD (50 / 25 CAD per head) | 3,000.00 | 1,500.00 |
| **Change in modeled margin, CAD** | **92,558.80** | **156,167.60** |
| Change in CAD per all 15,000 placements | 6.17 | 10.41 |

The finish terms are conditional planning inputs. The observed sellers had median live weight of 633.7 kg, median HCW of 386.4 kg and median inclusive financial DOF of 177. Those figures provide scale. A previously ill animal's course, grade, capacity usage and sale date need independent evidence. The other expense is an editable allowance. A real intervention budget would cover all eligible animals, incremental capital or pen capacity, transport and any program costs outside the four booked categories. The CAD 92.6–156.2 thousand range is suitable for a conditional budget conversation. It gives no treatment effect or forecast of avoided deaths.

The higher-mortality case replaces 60 sales (23,305.4 kg HCW) with hypothetical deaths, raising deaths to 300 (2.00%). It removes CAD 188,730.31 of sales and credits CAD 8,389.33 of feed and CAD 1,287.84 of yardage under 20% avoidable shares. It adds CAD 3,000 of veterinary and CAD 1,500 of other costs. Purchase and all other booked costs stay in the portfolio. The modeled change is −CAD 183,553.14. Actual avoided costs depend on when and how animals die. Late-loss timing records, treatment histories, bunk and pen usage, and disposal costs would improve the assumptions.

With adverse repricing, the same 60 sales were worth CAD 179,408.15 and the credit for avoidable feed was CAD 9,647.73. The incremental decline relative to adverse prices alone was CAD 172,972.58. Applying the base-price mortality impact on top of the combined price stress would miss the repriced sale and feed overlap.

## Break-even frontier and vulnerable lots

Let `M₀` be the booked modeled margin, `W` purchased live kg, `H` sold eligible HCW, `F` booked allocated feed CAD, `p` the purchase CAD/kg live change, `q` the carcass CAD/kg HCW change and `f` the uniform feed fraction. At fixed volume and no granular feed repricing, the scenario margin is `M₀ − W × p − F × f + H × q`. The zero-margin frontier is `q = (W × p + F × f − M₀) / H`. At +15% feed, the maximum tolerated carcass decline is about CAD 0.504/kg HCW with booked feeder prices, or CAD 0.234/kg HCW at +0.30/kg live. The tested −0.40/kg HCW is beyond that latter cushion. The notebook plots the two feed-cost frontiers and the adverse case, with placements, sold volumes, grades and mortality held fixed.

| Lot | Booked CAD/placed | Feeder headroom CAD/kg live | Carcass headroom CAD/kg HCW | Adverse prices CAD/placed | Adverse prices and higher mortality CAD/placed |
|---|---:|---:|---:|---:|---:|
| LOT-2025-027 | 75.51 | 0.244 | 0.233 | −231.27 | −243.52 |
| LOT-2024-034 | 128.72 | 0.413 | 0.382 | −194.98 | −208.41 |
| LOT-2024-025 | 129.50 | 0.372 | 0.346 | −223.31 | −223.31 |
| LOT-2024-028 | 153.20 | 0.438 | 0.403 | −208.13 | −225.05 |
| LOT-2024-055 | 158.45 | 0.515 | 0.488 | −161.57 | −177.25 |

LOT-2025-027 has the smallest cushions for both price legs and the worst combined modeled margin per placement. Review its seven recorded deaths, marketed volume and settlement. LOT-2024-025 already crosses zero under the individual −0.35 HCW shock. The feed cost screen identifies LOT-2024-029 and LOT-2024-040 for additional review under combined stress. Lot rankings reflect the stated settings and assignment of hypothetical deaths. They support record review and financial triage across lots. They cannot establish an optimal procurement, ration, treatment or pen policy.

## Equations and inputs

Zero shocks reproduce each lot's booked amounts to source cent precision. All booked amounts start in integer cents in the existing KPI aggregation. The engine carries unrounded hypothetical deltas in CAD and rounds for display or lot loss classification. It computes the portfolio and cohort ratios from summed totals. Call `evaluate(...).select(lot_ids)` after assigning outcomes to select complete lots. Equivalent cohort and lot selections use the same scenario outcome assignment.

| Input | Units and accepted domain | Application |
|---|---|---|
| `purchase_cad_per_live_kg` | Finite signed CAD/kg entry liveweight. The implied individual purchase basis must stay ≥0. | Purchase cost change equals the offset × eligible placed entry kg. |
| `carcass_cad_per_hcw_kg` or `carcass_fraction` | Finite signed CAD/kg, or decimal fraction ≥−1. Use one nonzero input. Eligible original and hypothetical sale prices must stay ≥0. | Revenue change equals offset × eligible sold HCW, or fraction × eligible booked revenue. Other booked revenue remains fixed for accounting shocks. |
| `feed_fraction` | Finite decimal fraction ≥−1. | Uniform cost change equals fraction × booked allocated feed. |
| `feed_phase_fractions`, `feed_component_fractions` | Maps of finite fractions ≥−1. Phases are Starter, Transition, Grower and Finisher. Ingredients are forage, concentrate and supplement. Missing entries imply a zero change. | Reprice each allocated exposure cell by `(1 + uniform) × (1 + phase) × (1 + ingredient)`. |
| Mortality `direction`, `head` | `lower` or `higher` and a positive integer count within the original death or sale pool (240 or 14,760 in this snapshot). Omit mortality to preserve booked outcomes. | Change the stated number of original outcomes. Keep placements fixed. |
| Lower mortality finish DOF, live kg, dressing and price | `finish_financial_dof` is an inclusive positive integer after each selected death DOF. `finish_live_kg` is positive and at least each selected animal's entry kg. `dressing_fraction` is in (0, 1]. `price_cad_per_hcw_kg` is finite and ≥0. | Additional days = assumed finish DOF − original death DOF. Additional HCW = finish live kg × dressing. Reprice assumed sale proceeds with the scenario carcass setting. |
| Lower mortality daily feed and yardage | `feed_cad_per_extra_day`, `yardage_cad_per_extra_day` are finite CAD per additional financial head-day, ≥0. | Multiply each by extra days. Apply the scenario feed multiplier to the extra feed rate. Use the lot price blend as a proxy when phase or ingredient shocks are active. |
| Higher mortality avoidable shares | `avoidable_feed_fraction`, `avoidable_yardage_fraction` are decimal fractions in [0, 1]. | Credit those shares of the repriced feed and booked yardage of the replaced sale. Remove its whole revenue at scenario prices and its recorded HCW. |
| Incremental vet and other expenses | `vet_cad_per_head`, `other_cad_per_head` are finite CAD per changed outcome, ≥0. | Add to costs after repricing. Purchase is retained through either outcome change. |

The survivor contribution equals its scenario sale proceeds less incremental feed, yardage, veterinary and other expenses. The hypothetical sale and original death both retain the same incurred costs. The higher-mortality contribution equals avoidable feed and yardage less foregone sales and additional veterinary and other expenses. Both apply after accounting repricing. The adjusted cost and revenue delta entries sum to the modeled margin change.

The conditional maximum feeder basis equals (booked revenue − booked nonpurchase costs) / placed live kg. The conditional minimum carcass price equals (booked costs − any other booked revenue) / eligible sold HCW with full sold coverage. Denominators with no exposure remain unavailable following the published closeout calculation. Headroom is the difference from the booked basis in the adverse direction. [Approved price thresholds](01_CLOSEOUT_FINDINGS.md#conditional-price-thresholds)

## Persistent low-growth screen

Use Phase 2B-3 `persistent_growth(..., landmark_ranks=True)` as the cross-notebook definition. Rank contemporaneous measured peers within lot, stage and actual weigh date at Day 35, Day 70 and Day 105. Flag an eligible interval at or below the 10th-percentile interval ADG cutoff, keeping ties. Require all three measured intervals and all three flags to classify persistence. This gives 165 of 14,794 animals and uses only information available on each stage date when deriving its cutoff. Phase 2B-2 keeps 162 under its retrospective convention, where each cutoff draws from cattle complete through all three stages. Different reference sets shift the empirical cutoff and which tied observations qualify. Both historical results remain documented. [Phase 2B-2 screen](02_FEED_GROWTH_FINDINGS.md) · [Phase 2B-3 landmark screen](03_HEALTH_CARCASS_FINDINGS.md)

## Reproduce and verify

Run from the repository root with Python 3.11 or later. The supplied weather archive is replayed offline. The scenario notebook uses the financial ledger and the native feed delivery rows after running the existing controls. Edit the JSON inputs for the illustrative cases or add cases to its array. Keep the names of the supplied scenarios used by the notebook's focused exhibits. For programmatic use, import `ScenarioEngine.from_repository(Path.cwd())` and evaluate any validated `Scenario` directly. The notebook contains editable sensitivity sweep ranges.

```sh
mkdir -p work
python -m venv work/scenario-venv
. work/scenario-venv/bin/activate
python -m pip install -e '.[notebook]'
snapshot=phase2a/weather/era5-20261121T143547299379Z-fd9571517552
python -W error -m feedlot_analytics.cli build --weather-snapshot "$snapshot" --output work/phase2b4-canonical
python -W error -m unittest discover -s tests -v
python -m nbconvert --to notebook --execute notebooks/04_management_scenarios.ipynb \
  --output-dir work --output 04_management_scenarios.executed.ipynb --ExecutePreprocessor.timeout=240
```

The Python 3.12.14 replay passed all 661 original controls and verified all 704 weather dates, including complete animal and lot weather windows. The 11 canonical tables and three JSON files match a fresh rebuild from starting commit `ca76f2d8` byte for byte, including the source manifests and published financial, biological and weather measures. The full suite passed 74 tests, including 12 new scenario tests, with zero failures, errors or skips on the final replay. The clean notebook ran nine code cells and rendered four figures. The initial regression run exposed a dtype mismatch between equivalent aggregation paths and an invalid dtype cast in the test. Both were corrected before rerunning the full suite.

## Phase 2B-5 validation and export scope

Validate scenario input versioning, source hashes, cent precision, lot and cohort filter parity, and additivity of modeled revenue, costs, outcome deltas and exposure denominators. Design the export around the observed ledger, lot–scenario results, ingredient and phase exposure, and the operational bridge with assumptions and inclusion rules. Compare exported and source totals after representative filters before adapting them for Excel, Power BI, Tableau or web use. Carry the canonical timing and low-growth definitions into cross-notebook displays. Phase 2B-4 ends with the verified analysis.
