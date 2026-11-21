"""Phase 1 snapshot contracts. Source files remain read-only."""

from dataclasses import dataclass

CSV = "data/Feedlot_Management_Flat_15000.csv"
BOOK = "data/Feedlot_Management_StarSchema.xlsx"
SOURCE_BASELINE = "bb313f30fa1c8fbe632e1a665cd06f54c14e5619"
SCHEMA_VERSION = "2a.1"

COSTS = (
    "purchase_cost_cad", "allocated_feed_cost_cad", "yardage_cost_cad", "vet_cost_cad",
)
FINANCE = (*COSTS, "gross_revenue_cad", "net_margin_cad")
FINISHED = "Finished Sale"
MORTALITY = "Mortality"
GRADES = ("Canada Prime", "Canada AAA", "Canada AA", "B-Grade/Discount")
STAGE_DAYS = {"Arrival": 0, "Day 35": 34, "Day 70": 69, "Day 105": 104}
EXPECTED_COUNTS = {
    "head_placed": 15000, "head_sold": 14760, "head_mortality": 240,
    "lots": 90, "pens": 40, "head_treated": 2100, "treatment_events": 2220,
    "financial_head_days": 2650584, "recorded_head_days": 2650584,
}
EXPECTED_MARGIN_CENTS = {
    "sold_only_margin_cents": 489418763,
    "mortality_loss_cents": 51219464,
    "all_outcome_margin_cents": 438199299,
}


@dataclass(frozen=True)
class SourceSpec:
    columns: tuple[str, ...]
    rows: int
    key: tuple[str, ...] = ()


def spec(columns, rows, *key):
    return SourceSpec(tuple(columns.split()), rows, key)


FLAT = spec(
    "animal_id lot_id pen_id entry_date exit_date exit_type financial_dof entry_weight_kg "
    "exit_weight_kg total_gain_kg lifetime_adg_kg allocated_dmi_kg fcr purchase_cost_cad "
    "allocated_feed_cost_cad yardage_cost_cad vet_cost_cad total_cost_of_gain_per_kg "
    "feed_cost_of_gain_per_kg hot_carcass_weight_kg dressing_pct quality_grade "
    "grid_price_per_kg_carcass gross_revenue_cad net_margin_cad rfid_tag breed sex "
    "frame_score status origin_region arrival_date lot_sex predominant_breed head_count_in "
    "target_finish_weight_kg feeder_purchase_price_per_kg site_zone pen_type capacity_head "
    "bunk_space_m treatment_count primary_diagnosis primary_drug_protocol "
    "total_vet_cost_cad has_chronic_outcome morbidity_flag adg_tier fcr_efficiency_tier "
    "margin_category total_production_cost_cad",
    15000, 'animal_id',
)

SHEETS = {
    'Executive_Summary': SourceSpec(('Metric / Dimension', 'Value / Description'), 29),
    'Dim_Pen': spec(
        "pen_id site_zone pen_type capacity_head bunk_space_m",
        40, 'pen_id',
    ),
    'Dim_Lot': spec(
        "lot_id pen_id origin_region arrival_date lot_sex predominant_breed head_count_in "
        "target_finish_weight_kg feeder_purchase_price_per_kg",
        90, 'lot_id',
    ),
    'Dim_Cattle': spec(
        "animal_id rfid_tag lot_id pen_id breed sex entry_date entry_weight_kg "
        "purchase_cost_cad frame_score status",
        15000, 'animal_id',
    ),
    'Fact_Closeout_Sales': spec(
        "animal_id lot_id pen_id entry_date exit_date exit_type financial_dof entry_weight_kg "
        "exit_weight_kg total_gain_kg lifetime_adg_kg allocated_dmi_kg fcr purchase_cost_cad "
        "allocated_feed_cost_cad yardage_cost_cad vet_cost_cad total_cost_of_gain_per_kg "
        "feed_cost_of_gain_per_kg hot_carcass_weight_kg dressing_pct quality_grade "
        "grid_price_per_kg_carcass gross_revenue_cad net_margin_cad",
        15000, 'animal_id',
    ),
    'Fact_Feed_Daily': spec(
        "feed_date lot_id pen_id dof_current head_count_active ration_phase total_as_fed_kg "
        "dm_pct total_dmi_kg forage_dmi_kg concentrate_dmi_kg supplement_dmi_kg "
        "forage_cost_cad concentrate_cost_cad supplement_cost_cad total_feed_cost_cad",
        16085, 'lot_id', 'pen_id', 'feed_date',
    ),
    'Fact_Health_Treatments': spec(
        "treatment_id animal_id lot_id pen_id treatment_date dof_at_treatment diagnosis "
        "drug_protocol vet_cost_cad outcome",
        2220, 'treatment_id',
    ),
    'Fact_Scale_Weights': spec(
        "weigh_id animal_id lot_id pen_id weigh_date weigh_stage days_since_last_weigh "
        "weight_kg period_adg_kg cumulative_adg_kg",
        74268, 'weigh_id',
    ),
    'Data_Dictionary': SourceSpec(('Table', 'Column Name', 'Data Type', 'Description & Formula'), 59),
    'Feedlot_Flat_15000': FLAT,
}

DATE_BOUNDS = {
    "entry_date": ("2024-01-01", "2025-06-05"),
    "exit_date": ("2024-01-08", "2025-12-04"),
    "arrival_date": ("2024-01-01", "2025-06-05"),
    "feed_date": ("2024-01-01", "2025-12-04"),
    "treatment_date": ("2024-01-05", "2025-08-29"),
    "weigh_date": ("2024-01-01", "2025-12-04"),
}
INT_FIELDS = frozenset({
    "capacity_head", "days_since_last_weigh", "dof_at_treatment", "dof_current",
    "financial_dof", "head_count_active", "head_count_in", "treatment_count",
})
TEXT_FIELDS = (
    "adg_tier", "animal_id", "breed", "diagnosis", "drug_protocol", "exit_type",
    "fcr_efficiency_tier", "frame_score", "has_chronic_outcome", "lot_id", "lot_sex",
    "margin_category", "morbidity_flag", "origin_region", "outcome", "pen_id",
    "pen_type", "predominant_breed", "primary_diagnosis", "primary_drug_protocol",
    "quality_grade", "ration_phase", "rfid_tag", "sex", "site_zone", "status",
    "treatment_id", "weigh_id", "weigh_stage",
)
FLAT_NULLABLE = ('quality_grade', 'primary_diagnosis', 'primary_drug_protocol', 'total_vet_cost_cad')

BREEDS = ("Black Angus", "Charolais Cross", "Hereford", "Simmental Cross")
SEXES = ("Heifer", "Steer")
PEN_TYPES = ("Confinement Barn", "Open Dirt w/ Windbreak", "Standard Open Dirt")
DOMAINS = {
    "Dim_Pen": {
        "pen_type": PEN_TYPES, "site_zone": ("East Sheltered", "North Yard", "South Yard"),
    },
    "Dim_Lot": {
        "predominant_breed": BREEDS, "lot_sex": SEXES,
        "origin_region": ("Central Saskatchewan", "Manitoba Foothills",
                          "Peace River BC", "Southern Alberta"),
    },
    "Dim_Cattle": {
        "breed": BREEDS, "sex": SEXES, "frame_score": ("Large", "Medium"),
        "status": ("Sold", MORTALITY),
    },
    "Fact_Closeout_Sales": {"exit_type": (FINISHED, MORTALITY), "quality_grade": GRADES},
    "Fact_Feed_Daily": {"ration_phase": ("Starter", "Transition", "Grower", "Finisher")},
    "Fact_Health_Treatments": {
        "diagnosis": ("BRD - Bovine Respiratory", "Bloat / Acidosis", "Buller / Injury", "Foot Rot"),
        "drug_protocol": ("Ceftiofur", "Florfenicol", "Oxytetracycline", "Supportive Therapy",
                          "Tulathromycin"),
        "outcome": ("Chronic / Repeat", MORTALITY, "Recovered"),
    },
    "Fact_Scale_Weights": {"weigh_stage": (*STAGE_DAYS, "Closeout")},
}
