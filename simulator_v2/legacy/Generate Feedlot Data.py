#!/usr/bin/env python3
"""
Highwood Feeders Ltd. — Commercial Beef Cattle Feedlot Synthetic Dataset Generator
Location: Southern Alberta, Canada
Reporting Window: 2024-01-01 to 2025-12-31 (24 Months, 15,000 Head)

Generates 7 relational CSV tables in ./output_feedlot_data/:
  1. dim_pen.csv
  2. dim_lot.csv
  3. dim_cattle.csv
  4. fact_feed_daily.csv
  5. fact_scale_weights.csv
  6. fact_health_treatments.csv
  7. fact_closeout_sales.csv
"""

from pathlib import Path
import numpy as np
import pandas as pd

# 1. Reproducibility
np.random.seed(42)

OUTPUT_DIR = Path("./output_feedlot_data")
TOTAL_CATTLE = 15_000
NUM_PENS = 40
NUM_LOTS = 90


def is_alberta_winter(dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """
    Returns boolean mask for Alberta Winter Penalty dates (Nov 15 to Mar 15 inclusive).
    """
    dt = pd.DatetimeIndex(dates)
    month = dt.month
    day = dt.day
    return np.asarray(
        ((month == 11) & (day >= 15))
        | (month.isin([12, 1, 2]))
        | ((month == 3) & (day <= 15)),
        dtype=bool,
    )


def generate_dim_pen() -> pd.DataFrame:
    """Generates 40 feedlot pens across 3 yard zones."""
    pen_ids = [f"PEN-{i:02d}" for i in range(1, NUM_PENS + 1)]

    site_zones = np.random.choice(
        ["North Yard", "South Yard", "East Sheltered"],
        size=NUM_PENS,
        p=[0.40, 0.35, 0.25],
    )

    pen_types = []
    for zone in site_zones:
        if zone == "East Sheltered":
            pt = np.random.choice(
                ["Confinement Barn", "Open Dirt w/ Windbreak"],
                p=[0.65, 0.35],
            )
        elif zone == "North Yard":
            pt = np.random.choice(
                ["Open Dirt w/ Windbreak", "Standard Open Dirt", "Confinement Barn"],
                p=[0.55, 0.35, 0.10],
            )
        else:
            pt = np.random.choice(
                ["Open Dirt w/ Windbreak", "Standard Open Dirt"],
                p=[0.45, 0.55],
            )
        pen_types.append(pt)

    # Capacities between 150 and 250 head (step of 5)
    capacity_head = np.random.choice(np.arange(155, 255, 5), size=NUM_PENS)
    bunk_space_m = np.round(capacity_head * 0.30, 2)

    return pd.DataFrame(
        {
            "pen_id": pen_ids,
            "site_zone": site_zones,
            "pen_type": pen_types,
            "capacity_head": capacity_head.astype(int),
            "bunk_space_m": bunk_space_m,
        }
    )


def generate_dim_lot(dim_pen: pd.DataFrame) -> pd.DataFrame:
    """
    Generates 90 commercial lots arriving between 2024-01-01 and 2025-07-15
    such that all lots complete closeout on or before 2025-12-31 without pen overlaps,
    and head_count_in sums to exactly 15,000 head.
    """
    turns_per_pen = np.full(NUM_PENS, 2, dtype=int)
    three_turn_pens = np.random.choice(
        NUM_PENS, size=NUM_LOTS - 2 * NUM_PENS, replace=False
    )
    turns_per_pen[three_turn_pens] = 3

    pen_records = dim_pen.set_index("pen_id").to_dict("index")
    raw_lots = []

    start_epoch = pd.Timestamp("2024-01-01")
    max_arrival = pd.Timestamp("2025-07-15")
    latest_allowed_closeout = pd.Timestamp("2025-12-31")

    for pen_idx, pen_id in enumerate(dim_pen["pen_id"]):
        n_turns = turns_per_pen[pen_idx]
        cap = pen_records[pen_id]["capacity_head"]

        if n_turns == 3:
            first_offset = int(np.random.randint(0, 42))
            planned_dofs = np.random.randint(165, 180, size=3)
            turn_gaps = np.random.randint(45, 78, size=2)
        else:
            first_offset = int(np.random.randint(0, 185))
            planned_dofs = np.random.randint(172, 196, size=2)
            turn_gaps = np.random.randint(95, 200, size=1)

        curr_arrival = start_epoch + pd.Timedelta(days=first_offset)
        for t in range(n_turns):
            if curr_arrival > max_arrival:
                curr_arrival = max_arrival - pd.Timedelta(
                    days=int(np.random.randint(0, 12))
                )
            dof_target = int(planned_dofs[t])
            if curr_arrival + pd.Timedelta(days=dof_target - 1) > latest_allowed_closeout:
                dof_target = (latest_allowed_closeout - curr_arrival).days + 1

            raw_lots.append(
                {
                    "pen_id": pen_id,
                    "pen_capacity": cap,
                    "arrival_date": curr_arrival,
                    "planned_dof": dof_target,
                }
            )
            if t < n_turns - 1:
                curr_arrival = (
                    curr_arrival
                    + pd.Timedelta(days=dof_target)
                    + pd.Timedelta(days=int(turn_gaps[t]))
                )

    lots_df = (
        pd.DataFrame(raw_lots)
        .sort_values(["arrival_date", "pen_id"])
        .reset_index(drop=True)
    )

    lot_ids = []
    year_counters = {2024: 0, 2025: 0}
    for dt in lots_df["arrival_date"]:
        yr = dt.year
        year_counters[yr] += 1
        lot_ids.append(f"LOT-{yr}-{year_counters[yr]:03d}")
    lots_df["lot_id"] = lot_ids

    # Allocate exact 15,000 head across the 90 lots within [140, min(220, pen_capacity)]
    min_heads = np.full(NUM_LOTS, 140, dtype=int)
    max_heads = np.minimum(220, lots_df["pen_capacity"].to_numpy(dtype=int))

    raw_weights = np.random.uniform(0.85, 1.15, size=NUM_LOTS) * (max_heads / 200.0)
    heads = np.round(raw_weights / raw_weights.sum() * TOTAL_CATTLE).astype(int)
    heads = np.clip(heads, min_heads, max_heads)

    diff = TOTAL_CATTLE - int(heads.sum())
    while diff != 0:
        if diff > 0:
            eligible = np.where(heads < max_heads)[0]
            idx = np.random.choice(eligible)
            heads[idx] += 1
            diff -= 1
        else:
            eligible = np.where(heads > min_heads)[0]
            idx = np.random.choice(eligible)
            heads[idx] -= 1
            diff += 1

    lots_df["head_count_in"] = heads

    lots_df["origin_region"] = np.random.choice(
        [
            "Southern Alberta",
            "Central Saskatchewan",
            "Peace River BC",
            "Manitoba Foothills",
        ],
        size=NUM_LOTS,
        p=[0.48, 0.25, 0.15, 0.12],
    )

    lots_df["lot_sex"] = np.random.choice(
        ["Steer", "Heifer"],
        size=NUM_LOTS,
        p=[0.60, 0.40],
    )

    lots_df["predominant_breed"] = np.random.choice(
        ["Black Angus", "Charolais Cross", "Simmental Cross", "Hereford"],
        size=NUM_LOTS,
        p=[0.40, 0.25, 0.20, 0.15],
    )

    # Target finish weight: Steers ~660 kg, Heifers ~585 kg, +25 kg for Charolais/Simmental
    base_target = np.where(lots_df["lot_sex"] == "Steer", 660.0, 585.0)
    breed_adj = np.where(
        lots_df["predominant_breed"].isin(["Charolais Cross", "Simmental Cross"]),
        25.0,
        0.0,
    )
    target_noise = np.random.normal(0.0, 4.5, size=NUM_LOTS)
    lots_df["target_finish_weight_kg"] = np.round(
        base_target + breed_adj + target_noise, 1
    )

    # Feeder purchase price ($5.20 to $6.10 CAD/kg) with realistic 24-month market wave
    days_from_start = (lots_df["arrival_date"] - start_epoch).dt.days.to_numpy(
        dtype=float
    )
    market_wave = (
        5.52
        + 0.26 * np.sin(2.0 * np.pi * (days_from_start - 45.0) / 365.25)
        + 0.22 * (days_from_start / 550.0)
        + np.where(lots_df["lot_sex"] == "Steer", 0.06, -0.05)
        + np.random.normal(0.0, 0.05, size=NUM_LOTS)
    )
    lots_df["feeder_purchase_price_per_kg"] = np.round(
        np.clip(market_wave, 5.20, 6.10), 2
    )

    cols = [
        "lot_id",
        "pen_id",
        "origin_region",
        "arrival_date",
        "lot_sex",
        "predominant_breed",
        "head_count_in",
        "target_finish_weight_kg",
        "feeder_purchase_price_per_kg",
        "planned_dof",
    ]
    return lots_df[cols]


def generate_dim_cattle(dim_lot: pd.DataFrame) -> pd.DataFrame:
    """Generates 15,000 individual animal records across the 90 lots."""
    lot_indices = np.repeat(
        np.arange(len(dim_lot)), dim_lot["head_count_in"].to_numpy()
    )

    animal_ids = [f"HW-{i:06d}" for i in range(1, TOTAL_CATTLE + 1)]
    # 15-digit Canadian CCIA RFID format starting with 124000
    rfid_steps = np.random.randint(15, 120, size=TOTAL_CATTLE)
    rfid_offsets = 240_100_000 + np.cumsum(rfid_steps)
    rfid_tags = [f"124000{num:09d}" for num in rfid_offsets]

    lot_ids = dim_lot["lot_id"].to_numpy()[lot_indices]
    pen_ids = dim_lot["pen_id"].to_numpy()[lot_indices]
    sexes = dim_lot["lot_sex"].to_numpy()[lot_indices]
    entry_dates = dim_lot["arrival_date"].to_numpy()[lot_indices]
    lot_breeds = dim_lot["predominant_breed"].to_numpy()[lot_indices]
    feeder_prices = dim_lot["feeder_purchase_price_per_kg"].to_numpy()[lot_indices]

    # Inherit breed from lot with 10% individual crossbreed variation
    all_breeds = np.array(
        ["Black Angus", "Charolais Cross", "Simmental Cross", "Hereford"]
    )
    breeds = lot_breeds.copy()
    mutate_mask = np.random.rand(TOTAL_CATTLE) < 0.10
    random_breeds = np.random.choice(
        all_breeds, size=TOTAL_CATTLE, p=[0.40, 0.25, 0.20, 0.15]
    )
    same_mask = mutate_mask & (random_breeds == breeds)
    while same_mask.any():
        random_breeds[same_mask] = np.random.choice(
            all_breeds, size=int(same_mask.sum())
        )
        same_mask = mutate_mask & (random_breeds == breeds)
    breeds[mutate_mask] = random_breeds[mutate_mask]

    # Entry weight: Steers N(350, 22), Heifers N(310, 20)
    is_steer = sexes == "Steer"
    entry_weights = np.where(
        is_steer,
        np.random.normal(350.0, 22.0, size=TOTAL_CATTLE),
        np.random.normal(310.0, 20.0, size=TOTAL_CATTLE),
    )
    entry_weights = np.where(
        is_steer,
        np.clip(entry_weights, 280.0, 425.0),
        np.clip(entry_weights, 245.0, 375.0),
    )
    entry_weights = np.round(entry_weights, 1)

    purchase_costs = np.round(entry_weights * feeder_prices, 2)

    large_prob = np.where(
        np.isin(breeds, ["Charolais Cross", "Simmental Cross"]),
        0.68,
        0.38,
    )
    frame_scores = np.where(
        np.random.rand(TOTAL_CATTLE) < large_prob, "Large", "Medium"
    )

    return pd.DataFrame(
        {
            "animal_id": animal_ids,
            "rfid_tag": rfid_tags,
            "lot_id": lot_ids,
            "pen_id": pen_ids,
            "breed": breeds,
            "sex": sexes,
            "entry_date": pd.to_datetime(entry_dates),
            "entry_weight_kg": entry_weights,
            "purchase_cost_cad": purchase_costs,
            "frame_score": frame_scores,
            "status": "Sold",
        }
    )


def simulate_health_and_mortality(
    dim_cattle: pd.DataFrame, dim_lot: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """
    Simulates ~14% morbidity across the population (mostly Days 5-30) and ~1.6% total mortality.
    Fully vectorized without .iterrows().
    """
    lot_dof_map = dim_lot.set_index("lot_id")["planned_dof"].to_dict()
    planned_dofs = dim_cattle["lot_id"].map(lot_dof_map).to_numpy(dtype=int)
    entry_dates = pd.to_datetime(dim_cattle["entry_date"])

    # Select ~14% of animals (2,100 animals) to experience morbidity
    morbidity_rate = 0.14
    num_sick_animals = int(round(TOTAL_CATTLE * morbidity_rate))
    sick_animal_indices = np.sort(
        np.random.choice(TOTAL_CATTLE, size=num_sick_animals, replace=False)
    )

    # Treatment timing: 78% in Days 5-30, 15% in Days 31-70, 7% in Days 71-125
    phase_bucket = np.random.choice(
        [1, 2, 3], size=num_sick_animals, p=[0.78, 0.15, 0.07]
    )
    dof_at_trt = np.zeros(num_sick_animals, dtype=int)
    b1 = phase_bucket == 1
    b2 = phase_bucket == 2
    b3 = phase_bucket == 3
    dof_at_trt[b1] = np.random.randint(5, 31, size=int(b1.sum()))
    dof_at_trt[b2] = np.random.randint(31, 71, size=int(b2.sum()))
    dof_at_trt[b3] = np.random.randint(71, 126, size=int(b3.sum()))
    dof_at_trt = np.minimum(dof_at_trt, planned_dofs[sick_animal_indices] - 5)

    # Diagnosis distribution: BRD 65%, Foot Rot 15%, Bloat / Acidosis 12%, Buller / Injury 8%
    diagnoses = np.random.choice(
        [
            "BRD - Bovine Respiratory",
            "Foot Rot",
            "Bloat / Acidosis",
            "Buller / Injury",
        ],
        size=num_sick_animals,
        p=[0.65, 0.15, 0.12, 0.08],
    )

    drug_protocols = np.empty(num_sick_animals, dtype=object)
    vet_costs = np.zeros(num_sick_animals, dtype=float)

    brd_m = diagnoses == "BRD - Bovine Respiratory"
    fr_m = diagnoses == "Foot Rot"
    bloat_m = diagnoses == "Bloat / Acidosis"
    bull_m = diagnoses == "Buller / Injury"

    drug_protocols[brd_m] = np.random.choice(
        ["Tulathromycin", "Florfenicol", "Ceftiofur", "Oxytetracycline"],
        size=int(brd_m.sum()),
        p=[0.45, 0.30, 0.15, 0.10],
    )
    vet_costs[brd_m] = np.random.uniform(52.0, 95.0, size=int(brd_m.sum()))

    drug_protocols[fr_m] = np.random.choice(
        ["Oxytetracycline", "Ceftiofur"], size=int(fr_m.sum()), p=[0.65, 0.35]
    )
    vet_costs[fr_m] = np.random.uniform(28.0, 58.0, size=int(fr_m.sum()))

    drug_protocols[bloat_m] = np.random.choice(
        ["Supportive Therapy", "Oxytetracycline"],
        size=int(bloat_m.sum()),
        p=[0.75, 0.25],
    )
    vet_costs[bloat_m] = np.random.uniform(32.0, 68.0, size=int(bloat_m.sum()))

    drug_protocols[bull_m] = np.random.choice(
        ["Supportive Therapy", "Ceftiofur", "Oxytetracycline"],
        size=int(bull_m.sum()),
        p=[0.60, 0.20, 0.20],
    )
    vet_costs[bull_m] = np.random.uniform(30.0, 72.0, size=int(bull_m.sum()))
    vet_costs = np.round(vet_costs, 2)

    # Outcome distribution: Recovered ~89%, Chronic / Repeat ~6%, Mortality ~5%
    outcomes = np.random.choice(
        ["Recovered", "Chronic / Repeat", "Mortality"],
        size=num_sick_animals,
        p=[0.89, 0.06, 0.05],
    )

    trt_records = pd.DataFrame(
        {
            "animal_idx": sick_animal_indices,
            "animal_id": dim_cattle["animal_id"].to_numpy()[sick_animal_indices],
            "lot_id": dim_cattle["lot_id"].to_numpy()[sick_animal_indices],
            "pen_id": dim_cattle["pen_id"].to_numpy()[sick_animal_indices],
            "dof_at_treatment": dof_at_trt,
            "diagnosis": diagnoses,
            "drug_protocol": drug_protocols,
            "vet_cost_cad": vet_costs,
            "outcome": outcomes,
        }
    )

    # Add repeat treatment events for Chronic / Repeat cases (7-14 days later)
    chronic_rows = trt_records[trt_records["outcome"] == "Chronic / Repeat"].copy()
    if len(chronic_rows) > 0:
        chronic_rows["dof_at_treatment"] = np.minimum(
            chronic_rows["dof_at_treatment"]
            + np.random.randint(7, 15, size=len(chronic_rows)),
            planned_dofs[chronic_rows["animal_idx"].to_numpy()] - 2,
        )
        chronic_rows["drug_protocol"] = np.random.choice(
            ["Florfenicol", "Ceftiofur", "Supportive Therapy"],
            size=len(chronic_rows),
            p=[0.45, 0.35, 0.20],
        )
        chronic_rows["vet_cost_cad"] = np.round(
            np.random.uniform(45.0, 92.0, size=len(chronic_rows)), 2
        )
        chronic_rows["outcome"] = np.random.choice(
            ["Recovered", "Mortality"],
            size=len(chronic_rows),
            p=[0.82, 0.18],
        )
        trt_records = pd.concat([trt_records, chronic_rows], ignore_index=True)

    # Target total mortality ~1.6% of 15,000 = 240 head
    target_total_mortalities = int(round(TOTAL_CATTLE * 0.016))
    treated_mort_indices = trt_records.loc[
        trt_records["outcome"] == "Mortality", "animal_idx"
    ].unique()

    remaining_morts_needed = max(
        0, target_total_mortalities - len(treated_mort_indices)
    )
    if remaining_morts_needed > 0:
        non_mort_candidates = np.setdiff1d(
            np.arange(TOTAL_CATTLE), treated_mort_indices
        )
        extra_mort_indices = np.random.choice(
            non_mort_candidates, size=remaining_morts_needed, replace=False
        )
        in_trt_mask = np.isin(
            extra_mort_indices, trt_records["animal_idx"].to_numpy()
        )
        acute_only_indices = extra_mort_indices[~in_trt_mask]
        acute_death_dofs = np.random.randint(
            8, np.maximum(15, planned_dofs[acute_only_indices] - 5)
        )
        all_mort_indices = np.concatenate([treated_mort_indices, extra_mort_indices])
    else:
        acute_only_indices = np.array([], dtype=int)
        acute_death_dofs = np.array([], dtype=int)
        all_mort_indices = treated_mort_indices[:target_total_mortalities]

    trt_entry_dates = entry_dates.to_numpy()[trt_records["animal_idx"].to_numpy()]
    trt_records["treatment_date"] = pd.to_datetime(trt_entry_dates) + pd.to_timedelta(
        trt_records["dof_at_treatment"] - 1, unit="D"
    )
    trt_records = trt_records.sort_values(["treatment_date", "animal_id"]).reset_index(
        drop=True
    )
    trt_records["treatment_id"] = [
        f"TRT-{i:05d}" for i in range(1, len(trt_records) + 1)
    ]

    # Vectorized exit_dofs calculation
    exit_dofs = planned_dofs.copy()

    mort_trt = trt_records[trt_records["outcome"] == "Mortality"]
    m_a_idx = mort_trt["animal_idx"].to_numpy(dtype=int)
    m_dof_trt = mort_trt["dof_at_treatment"].to_numpy(dtype=int)
    death_dofs = np.minimum(
        m_dof_trt + np.random.randint(0, 4, size=len(m_a_idx)),
        planned_dofs[m_a_idx] - 1,
    )
    exit_dofs[m_a_idx] = np.maximum(2, death_dofs)

    if len(acute_only_indices) > 0:
        exit_dofs[acute_only_indices] = acute_death_dofs

    if remaining_morts_needed > 0 and in_trt_mask.any():
        extra_trt_morts = extra_mort_indices[in_trt_mask]
        max_trt_dof_per_animal = (
            trt_records.groupby("animal_idx")["dof_at_treatment"].max().to_dict()
        )
        for a_idx in extra_trt_morts:
            last_dof = int(max_trt_dof_per_animal[int(a_idx)])
            exit_dofs[int(a_idx)] = min(
                last_dof + int(np.random.randint(1, 5)), planned_dofs[int(a_idx)] - 1
            )

    dim_cattle = dim_cattle.copy()
    status_arr = np.full(TOTAL_CATTLE, "Sold", dtype=object)
    status_arr[all_mort_indices] = "Mortality"
    dim_cattle["status"] = status_arr

    animal_exit_dates = (
        entry_dates + pd.to_timedelta(exit_dofs - 1, unit="D")
    ).to_numpy()

    fact_health_cols = [
        "treatment_id",
        "animal_id",
        "lot_id",
        "pen_id",
        "treatment_date",
        "dof_at_treatment",
        "diagnosis",
        "drug_protocol",
        "vet_cost_cad",
        "outcome",
    ]
    return dim_cattle, trt_records[fact_health_cols], animal_exit_dates


def simulate_scale_weights(
    dim_cattle: pd.DataFrame,
    dim_lot: pd.DataFrame,
    dim_pen: pd.DataFrame,
    fact_health: pd.DataFrame,
    animal_exit_dates: np.ndarray,
) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Vectorized simulation of individual cattle weights at:
      Arrival (Day 1), Day 35, Day 70, Day 105, and Closeout.
    """
    pen_type_map = dim_pen.set_index("pen_id")["pen_type"].to_dict()
    lot_dof_map = dim_lot.set_index("lot_id")["planned_dof"].to_dict()

    pen_types = dim_cattle["pen_id"].map(pen_type_map).to_numpy()
    is_confinement = pen_types == "Confinement Barn"
    planned_dofs = dim_cattle["lot_id"].map(lot_dof_map).to_numpy(dtype=int)

    entry_dates = pd.to_datetime(dim_cattle["entry_date"]).to_numpy()
    entry_weights = dim_cattle["entry_weight_kg"].to_numpy(dtype=float)
    sexes = dim_cattle["sex"].to_numpy()
    breeds = dim_cattle["breed"].to_numpy()
    statuses = dim_cattle["status"].to_numpy()

    # Base genetic ADG potential per animal
    base_sex_adg = np.where(sexes == "Steer", 1.68, 1.46)
    breed_adg_mult = np.where(
        np.isin(breeds, ["Charolais Cross", "Simmental Cross"]),
        1.06,
        np.where(breeds == "Hereford", 0.98, 1.00),
    )
    indiv_genetic_mult = np.clip(
        np.random.normal(1.0, 0.045, size=TOTAL_CATTLE), 0.88, 1.12
    )
    animal_base_adg = base_sex_adg * breed_adg_mult * indiv_genetic_mult

    # Precompute winter fraction for each lot and each interval
    lot_ids_unique = dim_lot["lot_id"].to_numpy()
    lot_arrivals = pd.to_datetime(dim_lot["arrival_date"]).to_numpy()
    lot_p_dofs = dim_lot["planned_dof"].to_numpy(dtype=int)

    lot_winter_fracs = {}
    for l_id, l_arr, l_dof in zip(lot_ids_unique, lot_arrivals, lot_p_dofs):
        stage_offsets = [0, 34, 69, 104, l_dof - 1]
        fracs = []
        for s_idx in range(4):
            d_start = pd.Timestamp(l_arr) + pd.Timedelta(days=stage_offsets[s_idx] + 1)
            d_end = pd.Timestamp(l_arr) + pd.Timedelta(days=stage_offsets[s_idx + 1])
            rng = pd.date_range(d_start, d_end, freq="D")
            w_frac = float(is_alberta_winter(rng).mean()) if len(rng) > 0 else 0.0
            fracs.append(w_frac)
        lot_winter_fracs[l_id] = fracs

    cattle_lot_ids = dim_cattle["lot_id"].to_numpy()
    winter_frac_matrix = np.array([lot_winter_fracs[lid] for lid in cattle_lot_ids])

    # Vectorized Morbidity Drag mapping per animal & weigh period
    morbidity_drag_matrix = np.zeros((TOTAL_CATTLE, 4), dtype=float)
    trt_a_idx = (
        fact_health["animal_id"].str.slice(3).astype(int).to_numpy() - 1
    )
    trt_dofs = fact_health["dof_at_treatment"].to_numpy(dtype=int)
    trt_period_idx = np.select(
        [trt_dofs <= 35, trt_dofs <= 70, trt_dofs <= 105],
        [0, 1, 2],
        default=3,
    )
    drags = np.random.uniform(0.15, 0.25, size=len(fact_health))
    np.maximum.at(morbidity_drag_matrix, (trt_a_idx, trt_period_idx), drags)

    stage_curve = np.array([0.94, 1.05, 1.07, 1.01])
    stage_names = ["Arrival", "Day 35", "Day 70", "Day 105", "Closeout"]
    stage_offsets_matrix = np.column_stack(
        [
            np.zeros(TOTAL_CATTLE, dtype=int),
            np.full(TOTAL_CATTLE, 34, dtype=int),
            np.full(TOTAL_CATTLE, 69, dtype=int),
            np.full(TOTAL_CATTLE, 104, dtype=int),
            planned_dofs - 1,
        ]
    )

    weights_matrix = np.zeros((TOTAL_CATTLE, 5), dtype=float)
    weights_matrix[:, 0] = entry_weights

    for p_idx in range(4):
        days_in_period = (
            stage_offsets_matrix[:, p_idx + 1] - stage_offsets_matrix[:, p_idx]
        ).astype(float)

        raw_winter_penalty = np.random.uniform(0.14, 0.20, size=TOTAL_CATTLE)
        effective_winter_penalty = np.where(
            is_confinement, raw_winter_penalty * 0.5, raw_winter_penalty
        )
        winter_mult = 1.0 - winter_frac_matrix[:, p_idx] * effective_winter_penalty
        morb_mult = 1.0 - morbidity_drag_matrix[:, p_idx]
        period_noise = np.clip(
            np.random.normal(1.0, 0.03, size=TOTAL_CATTLE), 0.91, 1.09
        )

        realized_period_adg = (
            animal_base_adg * stage_curve[p_idx] * winter_mult * morb_mult * period_noise
        )
        realized_period_adg = np.clip(realized_period_adg, 0.45, 2.45)

        weights_matrix[:, p_idx + 1] = np.round(
            weights_matrix[:, p_idx] + realized_period_adg * days_in_period, 1
        )

    stage_frames = []
    for s_idx, s_name in enumerate(stage_names):
        weigh_dates = entry_dates + pd.to_timedelta(
            stage_offsets_matrix[:, s_idx], unit="D"
        )
        if s_idx == 0:
            days_since_last = np.zeros(TOTAL_CATTLE, dtype=int)
            period_adg = np.zeros(TOTAL_CATTLE, dtype=float)
            cum_adg = np.zeros(TOTAL_CATTLE, dtype=float)
        else:
            days_since_last = (
                stage_offsets_matrix[:, s_idx] - stage_offsets_matrix[:, s_idx - 1]
            ).astype(int)
            period_adg = np.round(
                (weights_matrix[:, s_idx] - weights_matrix[:, s_idx - 1])
                / days_since_last,
                3,
            )
            dof_at_weigh = (stage_offsets_matrix[:, s_idx] + 1).astype(float)
            cum_adg = np.round(
                (weights_matrix[:, s_idx] - entry_weights) / dof_at_weigh,
                3,
            )

        if s_name == "Closeout":
            alive_mask = statuses == "Sold"
        else:
            alive_mask = weigh_dates <= animal_exit_dates

        df_stage = pd.DataFrame(
            {
                "animal_id": dim_cattle["animal_id"].to_numpy()[alive_mask],
                "lot_id": cattle_lot_ids[alive_mask],
                "pen_id": dim_cattle["pen_id"].to_numpy()[alive_mask],
                "weigh_date": weigh_dates[alive_mask],
                "weigh_stage": s_name,
                "days_since_last_weigh": days_since_last[alive_mask],
                "weight_kg": weights_matrix[alive_mask, s_idx],
                "period_adg_kg": period_adg[alive_mask],
                "cumulative_adg_kg": cum_adg[alive_mask],
            }
        )
        stage_frames.append(df_stage)

    fact_scale = (
        pd.concat(stage_frames, ignore_index=True)
        .sort_values(["weigh_date", "animal_id"])
        .reset_index(drop=True)
    )
    fact_scale.insert(
        0, "weigh_id", [f"WGH-{i:06d}" for i in range(1, len(fact_scale) + 1)]
    )

    exit_dofs = np.asarray(
        (pd.DatetimeIndex(animal_exit_dates) - pd.DatetimeIndex(entry_dates)).days + 1,
        dtype=int,
    )
    final_exit_weights = weights_matrix[:, 4].copy()
    mort_mask = statuses == "Mortality"
    mort_dofs = exit_dofs[mort_mask]
    final_exit_weights[mort_mask] = np.round(
        entry_weights[mort_mask] + np.maximum(0.0, (mort_dofs - 1) * 0.85), 1
    )

    return fact_scale, final_exit_weights


def generate_fact_feed_daily_and_allocate(
    dim_lot: pd.DataFrame,
    dim_pen: pd.DataFrame,
    dim_cattle: pd.DataFrame,
    animal_exit_dates: np.ndarray,
    final_exit_weights: np.ndarray,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """
    Vectorized generation of daily pen-lot feed logs (fact_feed_daily.csv)
    and exact allocation of DMI and feed cost to individual animals.
    """
    pen_type_map = dim_pen.set_index("pen_id")["pen_type"].to_dict()

    cattle_df = dim_cattle.copy()
    cattle_df["exit_date"] = pd.to_datetime(animal_exit_dates)
    cattle_df["exit_weight_kg"] = final_exit_weights
    cattle_df["financial_dof"] = (
        cattle_df["exit_date"] - cattle_df["entry_date"]
    ).dt.days + 1
    cattle_df["mid_weight_kg"] = 0.5 * (
        cattle_df["entry_weight_kg"] + cattle_df["exit_weight_kg"]
    )
    cattle_df["total_gain_kg"] = np.maximum(
        1.0, cattle_df["exit_weight_kg"] - cattle_df["entry_weight_kg"]
    )

    lot_ids = dim_lot["lot_id"].to_numpy()
    pen_ids = dim_lot["pen_id"].to_numpy()
    arrivals = pd.to_datetime(dim_lot["arrival_date"]).to_numpy()
    p_dofs = dim_lot["planned_dof"].to_numpy(dtype=int)
    heads_in = dim_lot["head_count_in"].to_numpy(dtype=int)

    lot_rep_idx = np.repeat(np.arange(len(dim_lot)), p_dofs)
    dof_current = (
        np.arange(len(lot_rep_idx))
        - np.repeat(np.cumsum(p_dofs) - p_dofs, p_dofs)
        + 1
    )
    feed_dates = pd.to_datetime(arrivals[lot_rep_idx]) + pd.to_timedelta(
        dof_current - 1, unit="D"
    )

    mort_cattle = cattle_df[cattle_df["status"] == "Mortality"]
    mort_counts = (
        mort_cattle.groupby(["lot_id", "exit_date"])
        .size()
        .rename("deaths_on_day")
        .reset_index()
    )

    daily_df = pd.DataFrame(
        {
            "feed_date": feed_dates,
            "lot_id": lot_ids[lot_rep_idx],
            "pen_id": pen_ids[lot_rep_idx],
            "dof_current": dof_current,
            "head_count_in": heads_in[lot_rep_idx],
            "planned_dof": p_dofs[lot_rep_idx],
        }
    )

    daily_df = daily_df.merge(
        mort_counts,
        left_on=["lot_id", "feed_date"],
        right_on=["lot_id", "exit_date"],
        how="left",
    )
    daily_df["deaths_on_day"] = daily_df["deaths_on_day"].fillna(0).astype(int)
    daily_df["cum_morts_prior"] = (
        daily_df.groupby("lot_id")["deaths_on_day"].cumsum()
        - daily_df["deaths_on_day"]
    )
    daily_df["head_count_active"] = (
        daily_df["head_count_in"] - daily_df["cum_morts_prior"]
    )

    dof_arr = daily_df["dof_current"].to_numpy()
    conds = [
        dof_arr <= 14,
        (dof_arr >= 15) & (dof_arr <= 28),
        (dof_arr >= 29) & (dof_arr <= 70),
        dof_arr >= 71,
    ]
    ration_phases = np.select(
        conds, ["Starter", "Transition", "Grower", "Finisher"], default="Finisher"
    )
    base_dm = np.select(conds, [0.58, 0.65, 0.71, 0.77], default=0.77)
    forage_share = np.select(conds, [0.55, 0.38, 0.24, 0.12], default=0.12)
    conc_share = np.select(conds, [0.39, 0.56, 0.70, 0.82], default=0.82)

    dm_pct = np.round(base_dm + np.random.uniform(-0.01, 0.01, size=len(daily_df)), 4)

    lot_mean_entry_w = cattle_df.groupby("lot_id")["entry_weight_kg"].mean().to_dict()
    lot_mean_exit_w = (
        cattle_df[cattle_df["status"] == "Sold"]
        .groupby("lot_id")["exit_weight_kg"]
        .mean()
        .to_dict()
    )
    lot_breed_map = dim_lot.set_index("lot_id")["predominant_breed"].to_dict()

    entry_w_vec = daily_df["lot_id"].map(lot_mean_entry_w).to_numpy()
    exit_w_vec = daily_df["lot_id"].map(lot_mean_exit_w).to_numpy()
    progress_frac = (dof_arr - 1.0) / np.maximum(
        1.0, daily_df["planned_dof"].to_numpy() - 1.0
    )
    est_current_bw = entry_w_vec + progress_frac * (exit_w_vec - entry_w_vec)

    # DMI Rule: Average animal DMI roughly 2.15% to 2.45% of current estimated body weight
    lot_breeds_vec = daily_df["lot_id"].map(lot_breed_map).to_numpy()
    base_dmi_pct_bw = np.where(
        np.isin(lot_breeds_vec, ["Charolais Cross", "Simmental Cross"]),
        np.random.uniform(0.0215, 0.0222, size=len(daily_df)),
        np.random.uniform(0.0217, 0.0227, size=len(daily_df)),
    )

    winter_mask = is_alberta_winter(daily_df["feed_date"])
    pen_types_vec = daily_df["pen_id"].map(pen_type_map).to_numpy()
    winter_dmi_mult = np.where(
        winter_mask,
        np.where(pen_types_vec == "Confinement Barn", 1.03, 1.06),
        1.00,
    )

    per_head_dmi_kg = est_current_bw * base_dmi_pct_bw * winter_dmi_mult
    total_dmi_kg = np.round(
        per_head_dmi_kg * daily_df["head_count_active"].to_numpy(), 2
    )
    total_as_fed_kg = np.round(total_dmi_kg / dm_pct, 2)
    total_dmi_kg = np.round(total_as_fed_kg * dm_pct, 2)

    forage_dmi_kg = np.round(total_dmi_kg * forage_share, 2)
    concentrate_dmi_kg = np.round(total_dmi_kg * conc_share, 2)
    supplement_dmi_kg = np.round(total_dmi_kg - forage_dmi_kg - concentrate_dmi_kg, 2)

    f_dates = daily_df["feed_date"]
    barley_spike_mask = (f_dates >= pd.Timestamp("2024-10-01")) & (
        f_dates <= pd.Timestamp("2025-03-31")
    )
    barley_price = np.where(barley_spike_mask, round(0.36 * 1.15, 4), 0.36)

    forage_cost_cad = np.round(forage_dmi_kg * 0.14, 2)
    concentrate_cost_cad = np.round(concentrate_dmi_kg * barley_price, 2)
    supplement_cost_cad = np.round(supplement_dmi_kg * 0.85, 2)
    total_feed_cost_cad = np.round(
        forage_cost_cad + concentrate_cost_cad + supplement_cost_cad, 2
    )

    fact_feed_daily = pd.DataFrame(
        {
            "feed_date": daily_df["feed_date"],
            "lot_id": daily_df["lot_id"],
            "pen_id": daily_df["pen_id"],
            "dof_current": daily_df["dof_current"],
            "head_count_active": daily_df["head_count_active"],
            "ration_phase": ration_phases,
            "total_as_fed_kg": total_as_fed_kg,
            "dm_pct": dm_pct,
            "total_dmi_kg": total_dmi_kg,
            "forage_dmi_kg": forage_dmi_kg,
            "concentrate_dmi_kg": concentrate_dmi_kg,
            "supplement_dmi_kg": supplement_dmi_kg,
            "forage_cost_cad": forage_cost_cad,
            "concentrate_cost_cad": concentrate_cost_cad,
            "supplement_cost_cad": supplement_cost_cad,
            "total_feed_cost_cad": total_feed_cost_cad,
        }
    )

    fact_feed_daily["per_head_dmi"] = (
        fact_feed_daily["total_dmi_kg"] / fact_feed_daily["head_count_active"]
    )
    fact_feed_daily["per_head_cost"] = (
        fact_feed_daily["total_feed_cost_cad"] / fact_feed_daily["head_count_active"]
    )
    fact_feed_daily["cum_per_head_dmi"] = fact_feed_daily.groupby("lot_id")[
        "per_head_dmi"
    ].cumsum()
    fact_feed_daily["cum_per_head_cost"] = fact_feed_daily.groupby("lot_id")[
        "per_head_cost"
    ].cumsum()

    lookup_df = fact_feed_daily[
        ["lot_id", "dof_current", "cum_per_head_dmi", "cum_per_head_cost"]
    ].rename(columns={"dof_current": "financial_dof"})

    cattle_alloc = cattle_df[
        [
            "animal_id",
            "lot_id",
            "financial_dof",
            "mid_weight_kg",
            "total_gain_kg",
            "breed",
        ]
    ].merge(lookup_df, on=["lot_id", "financial_dof"], how="left")

    # Allocate DMI proportional to cumulative active days and individual gain/metabolic weight
    lot_mean_gain = cattle_alloc.groupby("lot_id")["total_gain_kg"].transform("mean")
    lot_mean_mid_w = cattle_alloc.groupby("lot_id")["mid_weight_kg"].transform("mean")
    intake_weight = 0.55 * (cattle_alloc["total_gain_kg"] / lot_mean_gain) + 0.45 * (
        (cattle_alloc["mid_weight_kg"] / lot_mean_mid_w) ** 0.75
    )
    cattle_alloc["raw_dmi"] = cattle_alloc["cum_per_head_dmi"] * intake_weight
    cattle_alloc["raw_cost"] = cattle_alloc["cum_per_head_cost"] * intake_weight

    lot_total_dmi = fact_feed_daily.groupby("lot_id")["total_dmi_kg"].sum()
    lot_total_cost = fact_feed_daily.groupby("lot_id")["total_feed_cost_cad"].sum()

    cattle_alloc["lot_sum_raw_dmi"] = cattle_alloc.groupby("lot_id")[
        "raw_dmi"
    ].transform("sum")
    cattle_alloc["lot_sum_raw_cost"] = cattle_alloc.groupby("lot_id")[
        "raw_cost"
    ].transform("sum")
    cattle_alloc["lot_target_dmi"] = cattle_alloc["lot_id"].map(lot_total_dmi)
    cattle_alloc["lot_target_cost"] = cattle_alloc["lot_id"].map(lot_total_cost)

    allocated_dmi_kg = np.round(
        cattle_alloc["raw_dmi"]
        / cattle_alloc["lot_sum_raw_dmi"]
        * cattle_alloc["lot_target_dmi"],
        2,
    ).to_numpy()
    allocated_feed_cost_cad = np.round(
        cattle_alloc["raw_cost"]
        / cattle_alloc["lot_sum_raw_cost"]
        * cattle_alloc["lot_target_cost"],
        2,
    ).to_numpy()

    drop_helper_cols = [
        "per_head_dmi",
        "per_head_cost",
        "cum_per_head_dmi",
        "cum_per_head_cost",
    ]
    fact_feed_daily = fact_feed_daily.drop(columns=drop_helper_cols)

    return fact_feed_daily, allocated_dmi_kg, allocated_feed_cost_cad


def generate_fact_closeout_sales(
    dim_cattle: pd.DataFrame,
    fact_health: pd.DataFrame,
    animal_exit_dates: np.ndarray,
    final_exit_weights: np.ndarray,
    allocated_dmi_kg: np.ndarray,
    allocated_feed_cost_cad: np.ndarray,
) -> pd.DataFrame:
    """
    Generates the 15,000-row individual closeout & financial ledger (fact_closeout_sales.csv).
    """
    entry_dates = pd.Series(
        pd.to_datetime(dim_cattle["entry_date"]), index=dim_cattle.index
    )
    exit_dates = pd.Series(pd.to_datetime(animal_exit_dates), index=dim_cattle.index)
    statuses = dim_cattle["status"].to_numpy()
    is_sold = statuses == "Sold"
    breeds = dim_cattle["breed"].to_numpy()

    exit_types = np.where(is_sold, "Finished Sale", "Mortality")

    # STRICT FORMULA: (exit_date - entry_date).days + 1
    financial_dof = ((exit_dates - entry_dates).dt.days + 1).to_numpy(dtype=int)

    entry_weights = dim_cattle["entry_weight_kg"].to_numpy(dtype=float)
    exit_weights = np.where(is_sold, final_exit_weights, 0.0)

    total_gain_kg = np.where(is_sold, np.round(exit_weights - entry_weights, 1), 0.0)
    safe_gain_kg = np.where(total_gain_kg > 0, total_gain_kg, 1.0)
    lifetime_adg_kg = np.where(
        is_sold, np.round(total_gain_kg / financial_dof, 3), 0.0
    )

    fcr = np.where(
        is_sold & (total_gain_kg > 0),
        np.round(allocated_dmi_kg / safe_gain_kg, 3),
        0.0,
    )

    purchase_cost_cad = dim_cattle["purchase_cost_cad"].to_numpy(dtype=float)
    yardage_cost_cad = np.round(financial_dof * 0.60, 2)

    trt_vet_sum = fact_health.groupby("animal_id")["vet_cost_cad"].sum()
    animal_trt_cost = (
        dim_cattle["animal_id"].map(trt_vet_sum).fillna(0.0).to_numpy(dtype=float)
    )
    vet_cost_cad = np.round(animal_trt_cost + 18.00, 2)

    total_cost_of_gain_per_kg = np.where(
        is_sold & (total_gain_kg > 0),
        np.round(
            (allocated_feed_cost_cad + yardage_cost_cad + vet_cost_cad) / safe_gain_kg,
            2,
        ),
        0.0,
    )
    feed_cost_of_gain_per_kg = np.where(
        is_sold & (total_gain_kg > 0),
        np.round(allocated_feed_cost_cad / safe_gain_kg, 2),
        0.0,
    )

    base_dressing = np.select(
        [
            breeds == "Charolais Cross",
            breeds == "Simmental Cross",
            breeds == "Black Angus",
            breeds == "Hereford",
        ],
        [0.618, 0.612, 0.608, 0.598],
        default=0.605,
    )
    dressing_pct = np.where(
        is_sold,
        np.round(
            np.clip(
                np.random.normal(base_dressing, 0.008, size=TOTAL_CATTLE),
                0.575,
                0.648,
            ),
            4,
        ),
        0.0,
    )

    hot_carcass_weight_kg = np.where(
        is_sold, np.round(exit_weights * dressing_pct, 1), 0.0
    )

    quality_grades = np.full(TOTAL_CATTLE, "N/A", dtype=object)
    grade_choices = ["Canada Prime", "Canada AAA", "Canada AA", "B-Grade/Discount"]

    angus_sold = is_sold & (breeds == "Black Angus")
    other_sold = is_sold & (breeds != "Black Angus")

    quality_grades[angus_sold] = np.random.choice(
        grade_choices,
        size=int(angus_sold.sum()),
        p=[0.13, 0.74, 0.11, 0.02],
    )
    quality_grades[other_sold] = np.random.choice(
        grade_choices,
        size=int(other_sold.sum()),
        p=[0.047, 0.640, 0.276, 0.037],
    )

    days_from_start = (exit_dates - pd.Timestamp("2024-01-01")).dt.days.to_numpy(
        dtype=float
    )
    base_carcass_price = (
        7.85
        + 0.28 * (days_from_start / 730.0)
        + 0.12 * np.sin(2.0 * np.pi * days_from_start / 365.25)
        + np.random.normal(0.0, 0.05, size=TOTAL_CATTLE)
    )
    base_carcass_price = np.clip(base_carcass_price, 7.60, 8.30)

    grade_bonus = np.select(
        [
            quality_grades == "Canada Prime",
            quality_grades == "Canada AAA",
            quality_grades == "Canada AA",
            quality_grades == "B-Grade/Discount",
        ],
        [0.35, 0.15, 0.00, -0.60],
        default=0.0,
    )
    grid_price_per_kg_carcass = np.where(
        is_sold, np.round(base_carcass_price + grade_bonus, 2), 0.0
    )

    gross_revenue_cad = np.where(
        is_sold, np.round(hot_carcass_weight_kg * grid_price_per_kg_carcass, 2), 0.0
    )
    total_animal_cost = (
        purchase_cost_cad + allocated_feed_cost_cad + yardage_cost_cad + vet_cost_cad
    )
    net_margin_cad = np.round(gross_revenue_cad - total_animal_cost, 2)

    return pd.DataFrame(
        {
            "animal_id": dim_cattle["animal_id"],
            "lot_id": dim_cattle["lot_id"],
            "pen_id": dim_cattle["pen_id"],
            "entry_date": entry_dates,
            "exit_date": exit_dates,
            "exit_type": exit_types,
            "financial_dof": financial_dof,
            "entry_weight_kg": entry_weights,
            "exit_weight_kg": exit_weights,
            "total_gain_kg": total_gain_kg,
            "lifetime_adg_kg": lifetime_adg_kg,
            "allocated_dmi_kg": allocated_dmi_kg,
            "fcr": fcr,
            "purchase_cost_cad": purchase_cost_cad,
            "allocated_feed_cost_cad": allocated_feed_cost_cad,
            "yardage_cost_cad": yardage_cost_cad,
            "vet_cost_cad": vet_cost_cad,
            "total_cost_of_gain_per_kg": total_cost_of_gain_per_kg,
            "feed_cost_of_gain_per_kg": feed_cost_of_gain_per_kg,
            "hot_carcass_weight_kg": hot_carcass_weight_kg,
            "dressing_pct": dressing_pct,
            "quality_grade": quality_grades,
            "grid_price_per_kg_carcass": grid_price_per_kg_carcass,
            "gross_revenue_cad": gross_revenue_cad,
            "net_margin_cad": net_margin_cad,
        }
    )


def print_validation_summary(tables: dict[str, pd.DataFrame]) -> None:
    """Prints a comprehensive console summary of table stats and domain KPIs."""
    print("=" * 78)
    print("HIGHWOOD FEEDERS LTD. — SYNTHETIC DATASET VALIDATION SUMMARY")
    print("=" * 78)
    print(f"{'Table Name':<30} | {'Row Count':>12} | {'Memory (MB)':>12}")
    print("-" * 78)

    total_rows = 0
    total_mem_mb = 0.0
    for name, df in tables.items():
        rows = len(df)
        mem_mb = df.memory_usage(deep=True).sum() / (1024**2)
        total_rows += rows
        total_mem_mb += mem_mb
        print(f"{name:<30} | {rows:>12,d} | {mem_mb:>12.2f}")

    print("-" * 78)
    print(f"{'TOTAL ACROSS ALL TABLES':<30} | {total_rows:>12,d} | {total_mem_mb:>12.2f}")
    print("=" * 78)

    closeout = tables["fact_closeout_sales.csv"]
    cattle = tables["dim_cattle.csv"]
    health = tables["fact_health_treatments.csv"]
    sold = closeout[closeout["exit_type"] == "Finished Sale"]

    avg_adg = sold["lifetime_adg_kg"].mean()
    avg_fcr = sold["fcr"].mean()
    avg_dof = closeout["financial_dof"].mean()
    avg_sold_dof = sold["financial_dof"].mean()
    avg_cog = sold["total_cost_of_gain_per_kg"].mean()
    avg_fcog = sold["feed_cost_of_gain_per_kg"].mean()
    mortality_rate_pct = (closeout["exit_type"] == "Mortality").mean() * 100.0
    morbidity_rate_pct = cattle["animal_id"].isin(health["animal_id"]).mean() * 100.0
    gross_margin_all = closeout["net_margin_cad"].mean()
    gross_margin_sold = sold["net_margin_cad"].mean()

    print("\nKEY FEEDLOT PERFORMANCE & FINANCIAL METRICS:")
    print(f"  - Total Cattle Head Count       : {len(cattle):,d} head")
    print(f"  - Overall Average ADG (Sold)    : {avg_adg:.3f} kg/day")
    print(f"  - Overall Average FCR (Sold)    : {avg_fcr:.2f} kg DM / kg gain")
    print(
        f"  - Average Financial DOF (All)   : {avg_dof:.1f} days (Sold: {avg_sold_dof:.1f} days)"
    )
    print(
        f"  - Total Cost of Gain (COG)      : ${avg_cog:.2f} CAD/kg gain (Feed COG: ${avg_fcog:.2f} CAD/kg)"
    )
    print(f"  - Population Morbidity Rate     : {morbidity_rate_pct:.2f}%")
    print(f"  - Population Mortality Rate     : {mortality_rate_pct:.2f}%")
    print(
        f"  - Net/Gross Margin per Head     : ${gross_margin_all:.2f} CAD/head (All) | ${gross_margin_sold:.2f} CAD/head (Sold)"
    )

    sold_with_breed = sold.merge(cattle[["animal_id", "breed", "sex"]], on="animal_id")
    steer_adg = sold_with_breed[sold_with_breed["sex"] == "Steer"][
        "lifetime_adg_kg"
    ].mean()
    heifer_adg = sold_with_breed[sold_with_breed["sex"] == "Heifer"][
        "lifetime_adg_kg"
    ].mean()
    cont_adg = sold_with_breed[
        sold_with_breed["breed"].isin(["Charolais Cross", "Simmental Cross"])
    ]["lifetime_adg_kg"].mean()
    brit_adg = sold_with_breed[
        sold_with_breed["breed"].isin(["Black Angus", "Hereford"])
    ]["lifetime_adg_kg"].mean()
    angus_prime_aaa = (
        sold_with_breed[sold_with_breed["breed"] == "Black Angus"]["quality_grade"]
        .isin(["Canada Prime", "Canada AAA"])
        .mean()
        * 100.0
    )
    other_prime_aaa = (
        sold_with_breed[sold_with_breed["breed"] != "Black Angus"]["quality_grade"]
        .isin(["Canada Prime", "Canada AAA"])
        .mean()
        * 100.0
    )

    print("\nEMBEDDED DOMAIN CORRELATION CHECKS:")
    print(f"  - Sex ADG (Steer vs Heifer)     : {steer_adg:.3f} kg/d vs {heifer_adg:.3f} kg/d")
    print(f"  - Breed ADG (Char/Simm vs Brit) : {cont_adg:.3f} kg/d vs {brit_adg:.3f} kg/d")
    print(
        f"  - Angus Prime+AAA vs Other      : {angus_prime_aaa:.1f}% vs {other_prime_aaa:.1f}%"
    )
    print("=" * 78)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. dim_pen
    dim_pen = generate_dim_pen()

    # 2. dim_lot
    dim_lot_full = generate_dim_lot(dim_pen)
    dim_lot = dim_lot_full.drop(columns=["planned_dof"]).copy()

    # 3. dim_cattle & 6. fact_health_treatments
    dim_cattle_init = generate_dim_cattle(dim_lot_full)
    dim_cattle, fact_health_treatments, animal_exit_dates = (
        simulate_health_and_mortality(dim_cattle_init, dim_lot_full)
    )

    # 5. fact_scale_weights
    fact_scale_weights, final_exit_weights = simulate_scale_weights(
        dim_cattle, dim_lot_full, dim_pen, fact_health_treatments, animal_exit_dates
    )

    # 4. fact_feed_daily
    fact_feed_daily, allocated_dmi_kg, allocated_feed_cost_cad = (
        generate_fact_feed_daily_and_allocate(
            dim_lot_full, dim_pen, dim_cattle, animal_exit_dates, final_exit_weights
        )
    )

    # 7. fact_closeout_sales
    fact_closeout_sales = generate_fact_closeout_sales(
        dim_cattle,
        fact_health_treatments,
        animal_exit_dates,
        final_exit_weights,
        allocated_dmi_kg,
        allocated_feed_cost_cad,
    )

    tables = {
        "dim_pen.csv": dim_pen,
        "dim_lot.csv": dim_lot,
        "dim_cattle.csv": dim_cattle,
        "fact_feed_daily.csv": fact_feed_daily,
        "fact_scale_weights.csv": fact_scale_weights,
        "fact_health_treatments.csv": fact_health_treatments,
        "fact_closeout_sales.csv": fact_closeout_sales,
    }

    for filename, df in tables.items():
        out_path = OUTPUT_DIR / filename
        df.to_csv(out_path, index=False)

    print_validation_summary(tables)


if __name__ == "__main__":
    main()