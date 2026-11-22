"""Export a new immutable Stage 3 build with typed Parquet and machine-readable gates."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from ..stage1.__main__ import git_commit, runtime
from ..stage1.model import Animal, AnimalEvent, LocationVersion, Lot, UTC
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.snapshots import RevisionApproval, publish_directory
from ..stage2.biology import GrowthStep, Profile, WeatherDay
from ..stage2.estimation import Estimate, EstimateSnapshot
from ..stage2.export import _write_table
from ..stage2.health import HealthEvent
from ..stage2.observations import Observation, WeighAttempt
from .allocation import AccessSnapshot, Allocation, BunkTicket, Exposure, Plan, Settlement, WeightInput
from .biology import GrowthInput
from .fixture import stage3_fixture
from .ration import Component, Delivery, FormulaComparison, Mix, MixInput, MixIssue, MixOrder, Recipe, TruckTicket
from .reconciliation import (ActiveSettlement, FeedBridge, WipCandidate, active_settlements,
                             feed_bridges, wip_candidates)
from .validation import validate
from .warehouse import (FIFO_VERSION, Assay, Balance, Batch, Bin, Entry, Equipment, Ingredient, InvoiceSplit,
                        Layer, Price, PurchaseOrder, PurchaseStatus, ReceiptLine, StockBridge, StockCount,
                        Supplier, Transaction, WarehouseLocation)

SCHEMA_VERSION = "stage3.1"


@dataclass(frozen=True)
class WarehouseVersion:
    snapshot_id: str
    effective_before: datetime
    knowledge_cutoff: datetime
    revises_snapshot_id: str | None
    approval_id: str | None


@dataclass(frozen=True)
class SnapshotDocument:
    snapshot_id: str
    transaction_id: str


def tables(fixture, candidates, feed_totals):
    masters, schedule = fixture.warehouse.masters, fixture.schedule
    settlements = fixture.settlements
    weights = {row.weight_input_id: row for snapshot in schedule.frozen_weights.values()
               for row in snapshot.values()}
    weights.update((row.weight_input_id, row) for settlement in settlements for row in settlement.weights)
    access = {result.access.access_snapshot_id: result.access for result in settlements}
    yield from (
        ("livestock", "animals", Animal, tuple(fixture.ledger.animals.values())),
        ("livestock", "lots", Lot, tuple(fixture.ledger.lots.values())),
        ("livestock", "location_versions", LocationVersion, tuple(fixture.ledger.location_versions.values())),
        ("livestock", "movement_events", AnimalEvent, fixture.ledger.events),
        ("warehouse", "ingredients", Ingredient, masters.ingredients),
        ("warehouse", "suppliers", Supplier, masters.suppliers),
        ("warehouse", "locations", WarehouseLocation, masters.warehouses),
        ("warehouse", "bins", Bin, masters.bins),
        ("warehouse", "batches", Batch, masters.batches),
        ("warehouse", "batch_assays", Assay, masters.assays),
        ("warehouse", "prices", Price, masters.prices),
        ("warehouse", "purchase_orders", PurchaseOrder, masters.orders),
        ("warehouse", "equipment", Equipment, masters.equipment),
        ("warehouse", "transactions", Transaction, fixture.warehouse.transactions),
        ("warehouse", "stock_bridges", StockBridge, fixture.stock_bridges),
        ("warehouse", "warehouse_snapshots", WarehouseVersion, tuple(
            WarehouseVersion(row.snapshot_id, row.effective_before, row.knowledge_cutoff,
                             row.revises_snapshot_id, row.approval_id) for row in fixture.warehouse_snapshots)),
        ("warehouse", "snapshot_documents", SnapshotDocument, tuple(
            SnapshotDocument(row.snapshot_id, key)
            for row in fixture.warehouse_snapshots for key in row.transaction_ids)),
        ("operational", "weigh_attempts", WeighAttempt, fixture.attempts),
        ("operational", "weight_observations", Observation, fixture.observations),
        ("operational", "estimate_snapshots", EstimateSnapshot, schedule.snapshots),
        ("operational", "weight_estimates", Estimate, schedule.estimates),
        ("operational", "feeding_weight_inputs", WeightInput, tuple(weights.values())),
        ("feed", "ration_versions", Recipe, fixture.formulas.recipes),
        ("feed", "ration_ingredients", Component, fixture.formulas.components),
        ("feed", "mix_orders", MixOrder, schedule.mix_orders),
        ("feed", "mix_issue_links", MixIssue, schedule.mix_issues),
        ("feed", "mix_batches", Mix, fixture.mixes),
        ("feed", "mix_inputs", MixInput, fixture.mix_inputs),
        ("feed", "formula_comparisons", FormulaComparison, fixture.comparisons),
        ("feed", "delivery_plans", Plan, schedule.plans),
        ("feed", "truck_tickets", TruckTicket, schedule.truck_tickets),
        ("feed", "deliveries", Delivery, fixture.deliveries),
        ("feed", "bunk_tickets", BunkTicket, schedule.bunk_tickets),
        ("feed", "bunk_settlements", Settlement, tuple(result.row for result in settlements)),
        ("feed", "access_snapshots", AccessSnapshot, tuple(access.values())),
        ("feed", "exposures", Exposure, tuple(row for result in settlements for row in result.exposures)),
        ("feed", "allocations", Allocation, tuple(row for result in settlements for row in result.allocations)),
        ("feed", "active_settlements", ActiveSettlement, active_settlements(fixture)),
        ("feed", "wip_candidates", WipCandidate, candidates),
        ("feed", "feed_bridges", FeedBridge, feed_totals),
        ("feed", "revision_approvals", RevisionApproval, fixture.approvals),
        ("diagnostic", "animal_profiles", Profile, fixture.profiles),
        ("diagnostic", "weather", WeatherDay, fixture.weather),
        ("diagnostic", "health_events", HealthEvent, fixture.health),
        ("diagnostic", "growth_steps", GrowthStep, fixture.biology.steps),
        ("diagnostic", "growth_inputs", GrowthInput, fixture.growth_inputs),
    )
    for snapshot in fixture.warehouse_snapshots:
        folder = f"warehouse/{snapshot.snapshot_id}"
        yield from (
            (folder, "receipt_lines", ReceiptLine, snapshot.receipts),
            (folder, "purchase_status", PurchaseStatus, snapshot.purchase_status),
            (folder, "inventory_cost_layers", Layer, snapshot.layers),
            (folder, "inventory_movements", Entry, snapshot.entries),
            (folder, "inventory_balances", Balance, snapshot.balances),
            (folder, "stock_counts", StockCount, snapshot.counts),
            (folder, "invoice_splits", InvoiceSplit, snapshot.invoice_splits),
        )


def build(output, seed=42):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"build directory already exists: {output}")
    fixture = stage3_fixture(seed)
    candidates = wip_candidates(fixture)
    totals = feed_bridges(fixture, candidates)
    checks = validate(fixture, totals)
    inputs = canonical({
        "synthetic": True, "scenario": fixture.scenario, "biology_config": fixture.biology_config,
        "stage1_config": fixture.ledger.config, "stage1_events_sha256": sha256(canonical(fixture.ledger.events)),
        "warehouse_transactions_sha256": sha256(canonical(fixture.warehouse.transactions)),
        "scale_observation_sha256": sha256(canonical(fixture.observations)),
        "health_event_sha256": sha256(canonical(fixture.health)), "weather_sha256": sha256(canonical(fixture.weather)),
        "physical_snapshot_id": fixture.timeline.snapshot_id,
    })
    run_id = stable_id("STAGE3-RUN", [SCHEMA_VERSION, FIFO_VERSION, fixture.timeline.run_id, sha256(inputs)])
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".stage3-", dir=output.parent) as temp:
        stage = Path(temp) / "build"
        index = {}
        for category, name, record_type, rows in tables(fixture, candidates, totals):
            folder = stage / category
            folder.mkdir(parents=True, exist_ok=True)
            index[f"{category}/{name}"] = _write_table(folder, name, record_type, rows, run_id)
            index[f"{category}/{name}"]["path"] = f"{category}/{name}.parquet"
        (stage / "inputs.json").write_bytes(inputs)
        (stage / "reconciliation.json").write_bytes(canonical({
            "run_id": run_id, "synthetic": True, "feed_bridges": totals,
            "warehouse_snapshot_id": fixture.warehouse_snapshots[0].snapshot_id,
            "active_allocation_method": fixture.scenario["method"],
        }))
        (stage / "validation.json").write_bytes(canonical({
            "run_id": run_id, "synthetic": True, "status": "passed", "checks": checks,
        }))
        files = {str(path.relative_to(stage)): sha256(path.read_bytes())
                 for path in sorted(stage.rglob("*")) if path.is_file()}
        hashes = canonical({"run_id": run_id, "synthetic": True, "tables": index, "files": files})
        (stage / "hashes.json").write_bytes(hashes)
        repo = Path(__file__).resolve().parents[2]
        sources = [source for stage_name in ("stage1", "stage2", "stage3")
                   for source in (repo / "simulator_v2" / stage_name).iterdir()
                   if source.suffix in {".py", ".json"}]
        code = {str(path.relative_to(repo)): sha256(path.read_bytes()) for path in sorted(sources)}
        (stage / "run_manifest.json").write_bytes(canonical({
            "run_id": run_id, "schema_version": SCHEMA_VERSION, "scenario_version": fixture.scenario["version"],
            "fifo_version": FIFO_VERSION, "biology_version": fixture.biology_config["biology_version"],
            "feed_adapter_version": fixture.biology.adapter.version, "default_allocation_method": fixture.scenario["method"],
            "stage1_run_id": fixture.timeline.run_id, "physical_snapshot_id": fixture.timeline.snapshot_id,
            "warehouse_snapshot_id": fixture.warehouse_snapshots[0].snapshot_id,
            "warehouse_knowledge_cutoff": fixture.warehouse_snapshots[0].knowledge_cutoff,
            "seed": seed, "git_commit": git_commit(), "runtime": runtime(), "built_at": datetime.now(UTC),
            "generator_files": code, "generator_sha256": sha256(canonical(code)),
            "input_sha256": sha256(inputs), "hashes_sha256": sha256(hashes), "status": "passed", "synthetic": True,
        }))
        if not publish_directory(stage, output):
            raise FileExistsError(f"build directory already exists: {output}")
    return run_id
