# 01 · Source inventory and legacy baseline

Audited production baseline `0653424b1bd820a368de2253c8091a803df3f6f8`. Input file hashes, parser dtypes and per-column null counts are emitted by [audit_sources.py](audit_sources.py).

## Repository assets and provenance

| Asset | Observed role |
|---|---|
| [Flat CSV](../data/Feedlot_Management_Flat_15000.csv) | Wide animal closeout projection, 15,000 rows × 51 columns, 6,592,909 bytes. Use the run manifest for file identity |
| [Star schema workbook](../data/Feedlot_Management_StarSchema.xlsx) | Ten sheets, including seven related data tables, embedded summary and dictionary, and the Tableau-oriented flat copy added in `abaea2b`. Workbook size 11,735,737 bytes |
| [Dashboard](../index.html) | Standalone HTML, CSS, vanilla JavaScript and SVG. Loads pre-aggregated lot and monthly payloads from `const D` and filters in browser. Legacy comparison fixture |
| [README](../README.md) | Describes the Feedlot Engine Simulator, the Southern Alberta case framing, claims, site and structure. Check all cited figures against the inputs |
| `assets/`, `LICENSE`, `.gitignore` | 265 tracked display assets, license and ignore rules. No tracked notebooks, simulator source, upstream relational CSVs, Power BI or Tableau workbook files in this checkout |

**Provenance · High · Documented as simulated.** The README's architecture explicitly identifies a Feedlot Engine Simulator. The repository contains outputs and narrative but no generator, seed, source-system export manifests, original feed/bunk records, clinical records, market series, weather observations or actual packer settlements. The source business identity, CCIA-style RFID format and grades are scenario context. No independent verification of real operating or market performance is possible from these files.

**Documentation drift · Medium · Verified.** There are ten worksheets. The README lists nine. README counts of 15,700 feed rows, 75,000 weigh rows and 2,100 health rows differ from 16,085, 74,268 and 2,220, respectively. The last health figure describes unique treated cattle. README cites placements through July 2025. The last recorded placement was 2025-06-05. Workbook metadata correctly reports event counts, but its dictionary omits several fields below.

## Grains, keys and dates

| Sheet or file | Rows × columns | Grain and observed key | Calendar coverage |
|---|---:|---|---|
| CSV and `Feedlot_Flat_15000` | 15,000 × 51 each | One animal outcome, `animal_id` | Entry 2024-01-01 to 2025-06-05. Exit 2024-01-08 to 2025-12-04 |
| `Dim_Pen` | 40 × 5 | One pen, `pen_id` | No effective-dated attributes |
| `Dim_Lot` | 90 × 9 | One placed lot, `lot_id`, pen FK | 2024-01-01 to 2025-06-05 |
| `Dim_Cattle` | 15,000 × 11 | One placed animal, `animal_id`, unique `rfid_tag`, lot and pen FKs | 2024-01-01 to 2025-06-05 |
| `Fact_Closeout_Sales` | 15,000 × 25 | One closeout per animal, `animal_id`, animal, lot and pen FKs. Includes mortality | Same entry and exit ranges as flat copies |
| `Fact_Feed_Daily` | 16,085 × 16 | One lot–pen–date delivery, `lot_id, pen_id, feed_date`, lot and pen FKs | 2024-01-01 to 2025-12-04 |
| `Fact_Health_Treatments` | 2,220 × 10 | One treatment, `treatment_id`, animal, lot and pen FKs | 2024-01-05 to 2025-08-29 |
| `Fact_Scale_Weights` | 74,268 × 10 | One weigh event, `weigh_id`, animal, lot and pen FKs. `animal_id, weigh_stage` also unique on snapshot | 2024-01-01 to 2025-12-04 |
| `Executive_Summary` | 29 × 2 | Mixed titles, reported metrics and explanatory labels, including blank display rows | Workbook labels 2024-01-01 through 2025-12-31 |
| `Data_Dictionary` | 59 × 4 | `Table, Column Name, Data Type, Description & Formula` | No time dimension |

Pen → lot → animal is one-to-many at each step in the data. Feed hangs from lot and pen, while closeout, health and weigh events hang from animal and carry lot and pen keys. The three paths agree with parent mappings. Review the tests for grain and join behavior. [Reconciliation and grain checks](02_DATA_QUALITY_AND_RECONCILIATION.md).

## Observed fields and units

Pandas read IDs/categories as text-like objects and measured fields as `float64` except the integer counts shown below. RFID was explicitly loaded as a string. Dates are calendar strings in the snapshots and parsed as ISO `YYYY-MM-DD` for tests. A field ending in `_pct` is fractional here. Monetary fields use nominal CAD. There are no event times or timezones.

| Table | Column groups and units |
|---|---|
| `Dim_Pen` | Text `pen_id, site_zone, pen_type`. Integer head `capacity_head`. Meters `bunk_space_m` |
| `Dim_Lot` | Text `lot_id, pen_id, origin_region, lot_sex, predominant_breed`. Date `arrival_date`. Integer head `head_count_in`. Live kg `target_finish_weight_kg`. CAD/kg live `feeder_purchase_price_per_kg` |
| `Dim_Cattle` | Text `animal_id, rfid_tag, lot_id, pen_id, breed, sex, frame_score, status`. Date `entry_date`. Live kg `entry_weight_kg`. CAD `purchase_cost_cad` |
| `Fact_Closeout_Sales` | Text `animal_id, lot_id, pen_id, exit_type, quality_grade`. Dates `entry_date, exit_date`. Integer days `financial_dof`. Live kg `entry_weight_kg, exit_weight_kg, total_gain_kg`. kg/day `lifetime_adg_kg`. kg DM `allocated_dmi_kg`. kg DM/kg gain `fcr`. CAD `purchase_cost_cad, allocated_feed_cost_cad, yardage_cost_cad, vet_cost_cad, gross_revenue_cad, net_margin_cad`. CAD/kg gain `total_cost_of_gain_per_kg, feed_cost_of_gain_per_kg`. Carcass kg `hot_carcass_weight_kg`. Fraction `dressing_pct`. CAD/kg HCW `grid_price_per_kg_carcass` |
| `Fact_Feed_Daily` | Text `lot_id, pen_id, ration_phase`. Date `feed_date`. Integer `dof_current` (days), `head_count_active` (head). As-fed kg `total_as_fed_kg`. DM fraction `dm_pct`. kg DM `total_dmi_kg, forage_dmi_kg, concentrate_dmi_kg, supplement_dmi_kg`. CAD `forage_cost_cad, concentrate_cost_cad, supplement_cost_cad, total_feed_cost_cad` |
| `Fact_Health_Treatments` | Text `treatment_id, animal_id, lot_id, pen_id, diagnosis, drug_protocol, outcome`. Date `treatment_date`. Integer days `dof_at_treatment`. Direct CAD `vet_cost_cad` |
| `Fact_Scale_Weights` | Text `weigh_id, animal_id, lot_id, pen_id, weigh_stage`. Date `weigh_date`. Integer elapsed days `days_since_last_weigh`. Live kg `weight_kg`. kg/day `period_adg_kg, cumulative_adg_kg` |
| Flat copies | All 25 closeout fields plus 17 nonduplicate attributes from cattle, lot and pen. Nine derived fields are integer `treatment_count`, text `primary_diagnosis, primary_drug_protocol, has_chronic_outcome, morbidity_flag, adg_tier, fcr_efficiency_tier, margin_category`, and CAD `total_vet_cost_cad, total_production_cost_cad` |
| `Executive_Summary` | `Metric / Dimension, Value / Description` read as mixed display content |
| `Data_Dictionary` | All dimensions documented. Fact coverage is closeout 16/25, feed 6/16, health 6/10 and scale 6/10. No flat field dictionary. Derived tier and category bands need independent confirmation before reuse |

## Legacy dashboard inventory

All pages use the 90 embedded lots. Filters intersect yard zone, predominant lot breed, lot sex and pen type. Controls include reset, ID/EN, light/dark and lot table sort/limit. Month and placement quarter are display groupings. Browser storage persists display preferences. The source is the HTML snapshot, with no CSV fetch or workbook reads.

| Section | Existing KPIs and visuals | Narratives and open validation |
|---|---|---|
| Overview, `p0` | Sold count/share, deaths, CAD/head, total CAD, ADG and FCR cards. Links to three stories. Five-step cost/revenue panel, breed and zone comparisons, sortable lot report card with top/all limit | Margin and cost scopes differ. Fixed headline values do not respond to filters. Breed means are for predominant-breed lots |
| Feed and winter, `p1` | DMI/day, FCR, feed COG and barn vs open margin gap. SVG monthly DMI with cost tooltips, shelter comparison, origin and placement-quarter tables, fixed ration-phase table | Monthly arrays match full-yard delivery ratios at display precision and stay fixed under lot filters. `winterFCR` uses Q3/Q4 2024 placement cohorts. `2.28% BW` is fixed. Shelter comparison pools both open pen types. Phase boundaries tie, but exact barley recipes, the price spike and weather mechanism need independent records |
| Growth and pulls, `p2` | Treated count/share, BRD count/share, fixed first-treatment recovery and margin gap. Five-stage SVG weight comparison, diagnosis and drug tables | Distinguish head from events. Validate chart stage denominators, assumed mortality allocation to sick cattle, diagnosis cohorts and hard-coded recovery copy. Day 5–25 monitoring, before-Day-45 culling and preferred drug comments are narrative claims, with no intervention evidence |
| Carcass and grade, `p3` | Prime + AAA, dressing, HCW and margin cards, breed grid table, frame margin/HCW/ADG panels | Claims on tonnage versus grid value require premium-component data. A 60/40 procurement shift and barn allocation under 310 kg need counterfactual assumptions and operating costs. Breed filters use lot labels although animals vary within lots |

Specific test results and severity are in [02_DATA_QUALITY_AND_RECONCILIATION.md](02_DATA_QUALITY_AND_RECONCILIATION.md).
