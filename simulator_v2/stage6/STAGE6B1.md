# Stage 6B.1 · Mortality Review, Cross-Domain Audit Optimization & Pilot Readiness

Stage 6B.1 continues directly from Stage 6B commit `6629a55456d63d1202f8f4d1776e2963a04d8774` on branch `stage6b1-antigravity`. All historical V1 and Stage 1–6B evidence (`evidence/diagnostic/`, `evidence/stage6b/`, and `configs/preflight-*.json`) is preserved untouched.

## 1. Mortality Root-Cause Analysis & Epidemiological Event Bridge

Stage 6B observed high crude mortality proportions on 24-month runs: `19` deaths out of `123` animals (`100` placements + `23` carry-in) and `44` deaths out of `308` animals (`250` placements + `58` carry-in). Profiling the exact clinical transition code ([`health.py`](health.py)) and Markov chain mechanics revealed **both structural software defects and aggressive synthetic parameters**:

### Confirmed Structural Defects in `health.py`

1. **Chronic episodes retained the acute severe daily death hazard (`0.085/day`).** Once an episode transitioned to `Action.CHRONIC` and returned to production with reduced biological burden (`chronic_burden`), `Health.day()` continued applying `detected_death_daily[ep.severity]`. In `preflight-250`, **`6` of `6` (100%) severe chronic episodes died** after transitioning to chronic.
2. **Reassessment-gated recovery vs daily death hazard (2× hazard-to-recovery mismatch).** `recovery_daily` (`[0.42, 0.25, 0.12]`) was evaluated only every `reassess_days = 2` days during `Action.REASSESS`, while `detected_death_daily` (`[0.0005, 0.004, 0.085]`) was applied **every single day** (including onset day and non-reassessment days). For severe cases, 2-day survival failure accumulated as $1 - (1 - 0.085)^2 = 16.28\%$ against a single $12\%$ recovery draw — producing an exact analytical Markov case-fatality rate (CFR) of **`65.60%`** (`61.84%` post-detection).
3. **Detection and treatment did not reduce death hazard in Stage 6B configs.** `detected_death_daily` was set identical to `untreated_death_daily` (`[0.0005, 0.004, 0.085]`). In `preflight-250`, **`20` of `44` deaths** occurred in detected, hospital-admitted, treated severe episodes.

### Confirmed Aggressive Synthetic Parameters in Legacy Stage 6A/6B Configs

- `onset_daily = 0.007` with `receiving_multiplier = 3.0` and `post_recovery_multiplier = 2.2` (30 days) generated **278–302 onset episodes per 100 animal-years** (~59–63% of animals affected at least once).
- `severity_weights = [0.50, 0.32, 0.18]` classified 18% of onsets as severe; combined with 65.6% severe CFR, severe episodes drove **73–79% of all deaths** (`32/44` at 250 placements; `15/19` at 100 placements).
- `background_death_daily = 0.00013` added `4.75` non-disease deaths per 100 animal-years (`8/44` deaths at 250 placements).
- Stage 6A's 99-day `diagnostic` run (`4` deaths / `108` animals = `3.70%` crude) already had the same elevated exposure-adjusted mortality rate (**`31.50` deaths per 100 animal-years**, `4,638.6` elapsed animal-days); the crude proportion looked small only because mean exposure was `42.95` days vs `140+` days in 24-month runs.

### RNG Stream Independence

All nine health RNG draws (`health/background-death`, `health/onset`, `health/severity`, `health/episode-death`, `health/detection`, `health/treatment`, `health/recovery`, `health/chronic`, `health/repeat`) use distinct SHA-256 stream namespaces keyed by `(seed, stream, animal_id, day_or_episode)`, independent of feed, weight, carcass, and financial streams.

## 2. Structural Repairs & Versioned Health Scenario (`stage6b1-baseline-health.1`)

- **Backwards-compatible repairs in [`health.py`](health.py) and [`config.py`](config.py):**
  - Added optional `chronic_death_daily` (applied when `ep.chronic` is true; falls back to legacy `detected_death_daily[i]` when omitted so Stage 6A/6B configs remain bit-identical).
  - Added optional `recovery_basis`: `"daily_compounded"` computes $1 - (1 - r)^{\text{reassess\_days}}$ at reassessment; defaults to `"per_reassessment"` when omitted for legacy configs.
  - Added optional `scenario_version` metadata field.
- **New versioned synthetic baseline (`stage6b1-baseline-health.1`):**
  - `onset_daily = 0.0022`, `receiving_multiplier = 3.5`, `post_recovery_multiplier = 2.0`, `severity_weights = [0.60, 0.30, 0.10]`, `detection_daily = [0.40, 0.70, 0.90]`, `untreated_death_daily = [0.0002, 0.0025, 0.025]`, `detected_death_daily = [0.0001, 0.0010, 0.010]`, `chronic_death_daily = 0.0015`, `background_death_daily = 0.00004`, `recovery_daily = [0.38, 0.24, 0.14]`, `recovery_basis = "daily_compounded"`, `reassess_days = 2`, `chronic_after_days = 9`.
  - Documented sensitivity ranges (`STAGE6B1_HEALTH_SENSITIVITY_RANGES` in [`benchmark_configs.py`](benchmark_configs.py)): `onset_daily ∈ [0.0015, 0.0040]`, `detected_death_daily_severe ∈ [0.005, 0.020]`, `chronic_death_daily ∈ [0.0008, 0.0030]`, `background_death_daily ∈ [0.00002, 0.00007]`.
  - **Synthetic disclaimer:** These are mechanistically coherent synthetic operational assumptions — **not** empirically calibrated to commercial feedlot datasets, and deaths are not forced to match any predetermined target percentage.
  - **Preserved stress-test scenario:** The original adverse-health parameters remain explicitly available as `stage6b-adverse-health.1` (e.g., [configs/stage6b1-adverse-health-250.json](configs/stage6b1-adverse-health-250.json) and untouched `configs/preflight-*.json`).

### Epidemiological Comparison (Seed 42, 731 Calendar Days)

| Scenario (Version) | Animals at Risk (Open + Placed) | Elapsed Animal-Days (AY) | Sold / Died / Carry-out | Crude Mort % | Deaths / 1,000 AD | Deaths / 100 AY | Affected Animals (Attack %) | Onset Episodes (Ep / 100 AY) | Severe Onsets / Deaths (CFR %) |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| `diagnostic` legacy (99d) | 108 (8+100) | 4,638.6 (12.70) | 64 / 4 / 40 | 3.70% | 0.8623 | 31.50 | 28 (25.9%) | 36 (283.5) | 5 / 2 (40.0%) |
| `preflight-25` legacy | 31 (6+25) | 4,558.9 (12.48) | 25 / 1 / 5 | 3.23% | 0.2194 | 8.01 | 19 (61.3%) | 37 (296.4) | 3 / 1 (33.3%) |
| `stage6b1-baseline-25` | 31 (6+25) | 4,633.2 (12.69) | 26 / 0 / 5 | 0.00% | 0.0000 | 0.00 | 10 (32.3%) | 12 (94.6) | 0 / 0 (0.0%) |
| `preflight-100` legacy | 123 (23+100) | 17,048.0 (46.68) | 82 / 19 / 22 | 15.45% | 1.1145 | 40.71 | 77 (62.6%) | 141 (302.1) | 24 / 15 (62.5%) |
| `stage6b1-baseline-100` | 123 (23+100) | 18,058.2 (49.44) | 100 / 1 / 22 | 0.81% | 0.0554 | 2.02 | 35 (28.5%) | 49 (99.1) | 5 / 0 (0.0%) |
| `preflight-250` legacy | 308 (58+250) | 43,147.8 (118.13) | 212 / 44 / 52 | 14.29% | 1.0198 | 37.25 | 181 (58.8%) | 329 (278.5) | 51 / 32 (62.8%) |
| `stage6b1-baseline-250` | 308 (58+250) | 45,552.5 (124.72) | 248 / 5 / 55 | 1.62% | 0.1098 | 4.01 | 86 (27.9%) | 114 (91.4) | 13 / 1 (7.7%) |

Full event bridges (including onset by pen kind, detection/recovery/death medians, chronic outcomes, censoring, and Markov expectations) are stored in [evidence/stage6b1/epidemiology-and-supply.json](evidence/stage6b1/epidemiology-and-supply.json) and reproducible via `python -m simulator_v2.stage6.epidemiology <dataset_dir>`.

## 3. Profiled Cross-Domain Audit & Posting Optimizations

`cProfile` profiling of untouched Stage 6B (`preflight-25`, seed 42) identified four dominant CPU hotspots:

1. **Parquet `to_pylist()` + `pytz` timestamp conversion in `validation.py` (`55.8s` / 66% of audit time, 1.92M `pytz.UTC.fromutc` calls).** Replaced row-dict iteration with columnar PyArrow `RecordBatch` streaming (`Audit.batches`), casting UTC timestamps directly to `int64` microseconds, vectorizing ME/CP biological reserve and warehouse bridge checks in NumPy with exact `math.isclose` semantics, replacing linear close-cutoff scans with `bisect_left`, and using bitmasks instead of `set` objects for two-line journal balance checks.
2. **Repeated `dataclasses.asdict()` (`copy.deepcopy()`) and `json.JSONEncoder` allocation in `provenance.py` (`48.9s` across operations + finance) and `close_index.py` + `validation.py` journal fingerprinting (`13.6s` in audit + `16.4s` in close index).** Eliminated `deepcopy` via non-copying shallow dataclass field dicts, reused a module-level `JSONEncoder`, added a fast flat-list canonicalizer, fast-pathed `is_utc`/`business_date`/`midnight` in [`stage1/model.py`](../stage1/model.py), and implemented exact byte-identical `canonical_journal_bytes` / `canonical_journal_from_columns` with cached UTC ISO formatting in [`close_index.py`](close_index.py).
3. **Per-row `is_dataclass()` reflection (22.2M calls) and Python dict construction in `export.py` (`73.8s` total).** Buffered raw dataclass rows and built Arrow tables columnarly via `pa.Table.from_arrays(...)` with precomputed schema specs.
4. **SQLite per-row inserts, uncached `key in self.rows` misses, and redundant `Book.run` lookups in `finance_store.py` and `stage4/ledger.py` (`~49s`).** Added O(1) key membership set, batched SQLite `executemany` writes (`WRITE_BATCH = 4096`), private temporary SQLite pragmas (`synchronous=OFF`, `journal_mode=OFF`, 64 MiB cache), streaming `financial_sources` emission on insert, O(1) approval verification, cached calendar locks, and single-pass source resolution per action in `Book.run`.

Zero controls were removed; all 59 hard-gate categories and integer CAD cent reconciliations remain enforced.

## 4. Validation Contract: Full (`Mode A`) vs Incremental (`Mode B`)

Implemented in [`validation.py`](validation.py):

- **Mode A (`reconcile` / `reconcile_with_mode(..., mode="full")`):** Complete independent disk-based audit over all partitions, both `as_known` and `restated` journal SHA-256 fingerprints, locks, approvals, lineage, FIFO, WIP, COGS, mortality releases, clearing, and conservation. Every published build runs Mode A and tags `validation.json` with `"mode": "full", "complete_independent_audit": true`.
- **Mode B (`reconcile_incremental` / `reconcile_with_mode(..., mode="incremental", changed_months=..., prior_partition_digests=...)`):** Validates changed monthly partitions (`audit_feeding`), dependent monthly closes/balances (`month >= min(changed_months)`), cumulative fingerprints, global movement/outcome/observation/weather invariants, and verifies SHA-256 digests of unchanged immutable partitions. Explicitly tags `"mode": "incremental", "complete_independent_audit": false` and raises on tampering in either unchanged or changed partitions.

| Benchmark Dataset | Mode A Full (s / assertions) | Mode B Incremental 1-Month (s / assertions) | Speedup | Unchanged Partitions Digest-Verified |
|---|---:|---:|---:|---:|
| `diagnostic` (4 months, `2026-02`) | 9.33 s / 1,003,469 | 6.54 s / 389,670 | 1.43× | 186 |
| `stage6b1-baseline-25` (24 months, `2025-12`) | 22.45 s / 1,914,323 | 12.30 s / 498,195 | 1.82× | 1,357 |

Evidence: [evidence/stage6b1/validation-modes-and-regression.json](evidence/stage6b1/validation-modes-and-regression.json).

## 5. Before / After Performance Benchmarks & Semantic Equivalence

Remote execution environment: **Linux x86_64, Intel Xeon @ 2.30 GHz, 2 vCPU, 7.8 GiB RAM, 85 GiB free disk, Python 3.12.16, PyArrow 19.0.1**. Note that single-core Python throughput on this VM is ~`3.04×` slower than Stage 6B's AMD EPYC 9V74 machine (`105.50s` vs `34.67s` on untouched `diagnostic.json`), so all before/after comparisons are measured on this identical VM.

### Before vs After on Identical Config (`diagnostic.json`, Seed 42, Same VM)

| Subsystem | Stage 6B Before (`6629a554`) | Stage 6B.1 After | Change |
|---|---:|---:|---:|
| Wall clock (incl. atomic publish) | 105.50 s | 56.93 s | **−46.0%** (1.85×) |
| Operations | 28.34 s | 20.07 s | **−29.2%** |
| Accounting & close | 43.87 s | 25.05 s | **−42.9%** |
| Financial source expansion | 25.88 s | 14.06 s | **−45.7%** |
| Journal posting | 8.45 s | 6.77 s | **−19.9%** |
| Close journal fingerprints | 4.38 s | 1.13 s | **−74.2%** (3.89×) |
| **Cross-domain validation (`reconcile`)** | **29.55 s** | **8.88 s** | **−70.0%** (3.33×) |
| Physical validation (`audit_feeding`) | 12.41 s | 2.80 s | **−77.4%** (4.43×) |
| Financial validation (`audit_finance`) | 16.56 s | 5.50 s | **−66.8%** (3.01×) |
| Diagnostics & manifest | 2.37 s | 1.31 s | **−44.7%** |
| Peak RSS | 265.3 MiB | 346.9 MiB | +81.6 MiB (32K cache + SQLite page cache) |

**Semantic Equivalence Proof:** Holding `run_id` fixed via `--comparison-manifest`:
- `diagnostic.json` (seed 42): **100% passed across all 78 tables**, `250 / 263` partitions byte-identical, all remaining partitions row-identical ([evidence/stage6b1/before-after-diagnostic.json](evidence/stage6b1/before-after-diagnostic.json)).
- `preflight-25.json` (seed 42, full 24 months): **100% passed across all 78 tables**, `1,343 / 1,446` partitions byte-identical, all remaining partitions row-identical ([evidence/stage6b1/equivalence-25.json](evidence/stage6b1/equivalence-25.json)).

### Full-Calendar 24-Month Stage 6B.1 Measurements (This 2.30 GHz VM)

| Run (Seed 42, 731d) | Animal-Days | Sources | Journals / View | Wall (s) | Ops (s) | Acct+Close (s) | Audit (s) | Fingerprints (s) | Peak RSS (MiB) | Parquet (MiB) | Closing WIP (CAD) | Warehouse Closing (CAD) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `preflight-25` (optimized) | 4,578 | 137,201 | 73,276 | 148.75 | 53.87 | 60.60 | 25.04 | 2.12 | 420.2 | 65.22 | 10,696.38 | 812.81 |
| `stage6b1-baseline-25` | 4,652 | 139,796 | 74,655 | 143.85 | 53.81 | 60.74 | 21.03 | 2.04 | 416.1 | 66.06 | 10,548.81 | 909.66 |
| `stage6b1-baseline-100` | 18,132 | 342,529 | 200,917 | 365.51 | 138.45 | 161.25 | 52.75 | 5.21 | 538.1 | 177.79 | 47,900.58 | 2,192.09 |

*Remote execution limit note (Phase 6):* A full 250-placement `stage6b1-baseline-250` build (`45,738` animal-days) projects to `~819.5s` on this 2.30 GHz Xeon VM (`~269.3s` estimated on EPYC), exceeding this remote runner's `600s` single-command timeout. Operations, epidemiology, supply sufficiency, and pen headroom were measured directly at 250 placements (`45,738` animal-days), while full end-to-end 250-placement and 500-placement builds were deferred honestly under compute discipline.

## 6. Inventory, Feed Supply & Capacity Assessment

Stage 6B cancelled `2` feed loads on `preflight-250` (`2025-01-31` and `2025-11-28`) because all three ingredients shared a uniform target (`64 kg AF/design-head`), giving low-DM `SILAGE` (`45%` DM, 31–70% of DM ration) only `6,784 kg AF` against `6,789.9 kg AF` peak 12-day (`order_cycle 7d + lead 5d`) demand, while high-DM `OATS` (`89%` DM) sat at `85%+` idle stock.

Stage 6B.1 adds material-specific opening stock, order-up-to targets, bin capacities, and explicit reorder points in [`warehouse.py`](warehouse.py) (`SILAGE: 115/130/95/180`, `BARLEY: 70/80/58/115`, `OATS: 22/26/18/45` kg AF/design-head):

- All replenishment occurs strictly through documented `PurchaseOrder` + split `Kind.RECEIPT` + `Kind.TRANSFER` transactions (zero unrecorded stock).
- On `stage6b1-baseline-250` (with `+2,392` more animal-days than `preflight-250`): **0 cancelled feed loads**, `SILAGE` min bin = `6,530.1 kg AF` (peak `63.9%` bin utilization, `105` POs, `208` receipts), `BARLEY` min bin = `3,864.1 kg AF` (peak `60.9%`, `106` POs incl. 1 reorder-point trigger), `OATS` min bin = `1,698.6 kg AF` (peak `48.9%`, `105` POs).
- Pen & equipment headroom at 250 placements (`stage6b1-baseline-250`): peak concurrent yard `69 / 106` (`production 67/90 = 74.4%`, `hospital 2/6 = 33.3%`, `receiving 5/10 = 50.0%`), zero placement backlogs, zero hospital/production overflow exceptions; `5,000 kg AF` mixer/truck capacity easily covers 150 kg AF (250-scale) and 900 kg AF (1,500-scale) pen-window loads.
- `configs/adversarial-shortage.json` remains intact as the dedicated shortage stress-test scenario.

## 7. Regression & Baseline Preservation

- **Full test suite:** `249 passed, 62 subtests passed, 0 failed` (`188 passed, 62 subtests` across `tests` + `stage1`–`stage3_5`; `61 passed` across `stage4`–`stage6`, including 8 new Stage 6B.1 tests in [`test_stage6b1.py`](tests/test_stage6b1.py)).
- **Accepted Stage 1–4 baseline hashes:** Rebuilt Stage 1 (`36`), Stage 2 (`14`), Stage 3 (`70`), Stage 3.5 (`86`), and Stage 4 (`35`) — **all 241 indexed entries match published `hashes.json` 100% byte-for-byte**.
- **Cold-run determinism:** `PYTHONHASHSEED=107` and `218` on `adversarial-shortage.json` produced identical `hashes.json` SHA-256 (`9a5a1984d47ba50d3cb9dfb33b4d9c8687571af256efc0934a5a35f999b8cd95`).

## 8. Pilot Readiness Projection (1,500 Placements, 24 Months)

| Planning Target (Stage 5) | Stage 6B EPYC 1,500 Proj. | Stage 6B.1 Xeon 2.30 GHz Proj. (Measured Anchors 25→100) | Stage 6B.1 EPYC 2-vCPU Est. (Not Executed) | Budget Target | Status |
|---|---:|---:|---:|---:|---|
| Wall clock | 1,923–2,279 s | 4,074–4,842 s | ~1,339–1,591 s | 600 s | **Over budget** |
| Peak RSS | 1.12–1.26 GiB | 2.52–2.93 GiB | 2.52–2.93 GiB | 6 GiB | **Pass** |
| Parquet output | 1.80–2.14 GiB | 2.00–2.38 GiB | 2.00–2.38 GiB | 2 GiB | **Borderline / Over** |
| Cross-domain audit | 607–720 s | 583–693 s | ~192–228 s | 120 s | **Over budget** |
| Fingerprint + file hash | 68.7–81.4 s | 82.4–98.1 s | **~27.1–32.2 s** | 45 s | **Pass on EPYC** |

### Separation of Failure Classes & Remaining Blockers

1. **Correctness blockers:** **None** on tested scales (`25`, `100`, `diagnostic`, `adversarial-shortage`, plus `250` operations/epidemiology/supply). All 59 hard-gate categories, Stage 4 controls, and integer CAD cent reconciliations passed.
2. **Performance blockers (why pilot remains HOLD under current budgets):**
   - Single-process build wall clock (`~22–26 min` estimated on EPYC, `>65 min` on 2.30 GHz Xeon) still exceeds the `600s` target; full cross-domain audit (`~192–228s` EPYC estimate) exceeds the `120s` reconciliation target; Parquet output (`2.00–2.38 GiB`) is right above the `2 GiB` target due to higher survival (+5.5% animal-days).
   - Full end-to-end 250-placement and 500-placement builds have not yet been executed under Stage 6B.1 on an uninterrupted runner (blocked on this VM by the `600s` single-command limit).
   - *Resource-aware recommendation:* Either (a) accept a longer uninterrupted pilot build window (`~30 min` wall / `~4 min` full audit / `2.5 GiB` Parquet) on a dedicated 4-vCPU / 16 GiB EPYC-class runner (note that `600s` is an engineering planning target, not a GitHub/billing hard limit), OR (b) parallelize month-independent validation (`audit_feeding` across months) and compress/prune diagnostic growth granularity before attempting 1,500 placements.
3. **Modeling & governance blockers:**
   - Health, growth, intake, carcass, and pricing parameters remain **explicitly synthetic** (not calibrated against licensed commercial data).
   - Stage 5 holdout estimator evaluation (7/30/60-day horizons, 5-seed protocol) and operational acceptance of 1,500-placement pen/hospital overflow and lot-segregation rules remain open.

**Decision: 1,500-placement pilot remains `HOLD`.**
