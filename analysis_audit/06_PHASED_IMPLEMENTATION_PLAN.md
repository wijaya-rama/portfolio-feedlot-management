# 06 · Phased implementation plan

| Phase | Objective and work | Exit criteria |
|---|---|---|
| 1 · Audit | Inventory the source and dashboard, run read-only checks, explain confirmed gaps, document business decisions and metric contracts | Six reports and the audit script under `analysis_audit/`. Git diff limited to audit files. Findings traceable to the versioned input snapshot. Review requested before proceeding |
| 2 · Metric sign-off and Pandas notebooks | Agree the all-outcome accounting scope, closeout cohort dates, sold vs placed KPIs and known exception policy. Implement source contracts and reconciliation modules, then notebooks for closeout economics, procurement, feed/growth and health/carcass. Quantify highest-priority comparisons and label simulator assumptions | Reproducible notebook execution. All margin and headcount controls tie. Document the cent-scale feed allocation bridge and inclusive roster convention. Independent review of denominators, filters and representative cohorts |
| 3 · Excel analytical delivery | Generate the reviewed workbook from approved tables, define control totals and test drill-downs, date roles and exports | Workbook controls reproduce Pandas for matched cohorts, including mortality and two separate feed ledgers |
| 4 · HTML revision | Rebuild visuals and interactions against the shared outputs after metric sign-off. Validate legacy comparisons and management language against agreed scopes | Filtered parity against reference results, audience review and separate deployment authorization |
| 5 · Power BI model | Implement star schema and approved measures. Test filters, totals and interactions | Conformed filters and tested parity across cohort and time slices |
| 6 · Tableau revision | Locate the original Tableau source and validate its dependencies. Map the same derived data into the approved workbook | Original workbook and connectors available, or a scope decision for a future replacement. Validated parity on shared measures |

## First work after approval

1. Publish the closeout bridge for all outcomes and survivors, ranked by lot, procurement cohort and cost drivers. Use paired paid/revenue volume and price metrics and show cohort size.
2. Carry the verified delivered and allocated feed bridge forward. Report partial-month exposure and label occupancy as simulated and ledger-implied.
3. Compare sold ADG, FCR and feed COG using ratio-of-totals and publish coverage. Contrast health timing, direct cost, and weight outcomes with survivor bias and lot mix made explicit.
4. Validate breed, frame and origin comparisons on the correct grains. Use these as descriptive simulated findings.
5. Begin simple break-even and shock scenarios only after the base economics and definitions are approved.

## Decisions for Phase 2 review

- Approve separate CAD/placed, all-outcome CAD/sold and sold-only CAD/sold KPIs.
- Choose the default closeout period, with an explicit date role and alternate procurement and feed views.
- Confirm whether original feed allocation logic, assignments/transfers, settlement pricing precision and simulator provenance are available.
- Confirm whether mortality cost allocation and omitted expenses should stay as modeled conventions or receive documented supplemental inputs.
- Validate discovery of an original Tableau workbook before planning Tableau migration effort.
