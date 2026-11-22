"""Validate and publish an immutable Stage 4 evidence directory."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from ..stage1.__main__ import git_commit, runtime
from ..stage1.export import write_table
from ..stage1.fixture import END, FINAL_CUTOFF, START
from ..stage1.model import UTC
from ..stage1.provenance import canonical, sha256, stable_id
from ..stage1.snapshots import publish_directory
from ..stage1.soh import calculate_soh
from ..stage1.validation import Check, reject_failures
from ..stage3.export import tables as upstream_tables
from ..stage3.reconciliation import ActiveSettlement, WipCandidate, active_settlements, feed_bridges, wip_candidates
from ..stage3_5.fixture import integrated_fixture
from .chart import CHART, ChartRow
from .close import (AnimalComponent, AnimalWip, Close, CloseDelta, ExceptionRow, Monthly, Stock, Trial,
                    Warehouse, animal_components, compare_closes)
from .feed import FeedCost
from .fixture import Approval, Fixture, WarehouseMovement, YardageDay, settings
from .ledger import Journal, JournalLine, Link, Source, journal_lines
from .market import MarketCoverage, MarketValue, Quote, coverage, valuation
from .recovery import RecoveryLot
from .report import (FeedBridge, InvoiceImpact, InvoiceRoute, MonthlyWarehouseDM, Sensitivity,
                     WarehouseVintage, close_series, dry_matter,
                     feed_bridge, invoice_impact, invoice_routes, journal_sets, reconciliation, recoverable,
                     sensitivity, validation, warehouse_vintages)

SCHEMA_VERSION = "stage4.1"
BASE_COMMIT = "7e3c9954403fddfa826781dee2aadf85499f5c00"
V2 = Path(__file__).resolve().parents[1]
SOURCE_EVIDENCE = V2 / "stage3_5" / "evidence"


def verify_source(fixture):
    """Check the archive and the accounting inputs rebuilt from its scenario."""
    published = (SOURCE_EVIDENCE / "hashes.json").read_bytes()
    archived = SOURCE_EVIDENCE / "fixture-seed42.zip"
    index = json.loads(published)
    with ZipFile(archived) as package:
        manifest = json.loads(package.read("run_manifest.json"))
        if (package.read("hashes.json") != published
                or manifest["hashes_sha256"] != sha256(published)
                or manifest["run_id"] != index["run_id"]
                or manifest["scenario_version"] != fixture.scenario["version"]
                or any(sha256(package.read(name)) != digest for name, digest in index["files"].items())):
            raise ValueError("authoritative Stage 3.5 package failed verification")
    candidates = wip_candidates(fixture)
    totals = feed_bridges(fixture, candidates)
    required = {
        "livestock/animals", "livestock/movement_events", "warehouse/transactions",
        "warehouse/stock_bridges", "feed/bunk_tickets", "feed/bunk_settlements", "feed/exposures",
        "feed/allocations", "feed/mix_inputs", "feed/mix_batches", "feed/deliveries",
        "feed/active_settlements", "feed/wip_candidates", "feed/feed_bridges", "feed/revision_approvals",
        "operational/weight_observations", "diagnostic/health_events",
    }
    for snap in fixture.warehouse_snapshots:
        for name in ("inventory_movements", "inventory_balances", "invoice_splits"):
            required.add(f"warehouse/{snap.snapshot_id}/{name}")
    rebuilt = {f"{category}/{name}": rows
               for category, name, _, rows in upstream_tables(fixture, candidates, totals)}
    _, daily, monthly, checks = calculate_soh(fixture.ledger, START, END, FINAL_CUTOFF)
    reject_failures(checks)
    rebuilt.update({"livestock/daily_soh": daily, "livestock/monthly_soh": monthly})
    required.update({"livestock/daily_soh", "livestock/monthly_soh"})
    for key in sorted(required):
        rows = rebuilt[key]
        digest = sha256(b"".join(canonical({"run_id": index["run_id"], **asdict(row)}) for row in rows))
        if (digest != index["tables"][key]["canonical_sha256"]
                or len(rows) != index["tables"][key]["rows"]):
            raise ValueError(f"rebuilt input differs from authoritative Stage 3.5 source: {key}")
    return {"run_id": index["run_id"], "hashes_sha256": sha256(published),
            "archive_sha256": sha256(archived.read_bytes()), "verified_files": len(index["files"]),
            "verified_rebuilt_tables": len(required), "warehouse_snapshot_id": fixture.warehouse_snapshots[0].snapshot_id}


def tables(fixture, journals, alternate, original, revised, bridge, comparison, invoices, recovery):
    quotes, market = valuation(fixture)
    all_closes = (*original, *revised)
    yield from (
        ("control", "chart_of_accounts", ChartRow, CHART),
        ("control", "sources", Source, tuple(sorted(fixture.sources.rows.values(), key=lambda row: row.source_id))),
        ("control", "lineage", Link, tuple(sorted(fixture.sources.links, key=lambda row: (row.source_id, row.parent_id)))),
        ("control", "approvals", Approval, fixture.approvals),
        ("ledger", "journal", Journal, journals),
        ("ledger", "journal_lines", JournalLine, tuple(journal_lines(journals))),
        ("ledger", "restatement_projection", Journal, alternate),
        ("ledger", "supplier_invoice_routes", InvoiceRoute, invoices),
        ("ledger", "supplier_invoice_horizon_impact", InvoiceImpact, tuple(invoice_impact(invoices, journals))),
        ("subledgers", "yardage", YardageDay, fixture.yardage),
        ("subledgers", "warehouse_movements", WarehouseMovement, fixture.warehouse),
        ("subledgers", "warehouse_source_vintages", WarehouseVintage, tuple(warehouse_vintages(fixture))),
        ("subledgers", "recoverable_lots", RecoveryLot, recovery),
        ("feed", "settlement_cost_dispositions", FeedCost, fixture.all_feed),
        ("feed", "active_settlements", ActiveSettlement, active_settlements(fixture.operations)),
        ("feed", "physical_wip_basis", WipCandidate, wip_candidates(fixture.operations)),
        ("monthly", "animal_cost_components", AnimalComponent, tuple(
            row for batch in original for row in animal_components(batch, journals)) + tuple(
            row for batch in revised for row in animal_components(batch, alternate))),
        ("feed", "financial_bridge", FeedBridge, bridge),
        ("feed", "policy_sensitivity", Sensitivity, comparison),
        ("monthly", "close_versions", Close, tuple(summary[0] for summary in all_closes)),
        ("monthly", "financial_summary", Monthly, tuple(summary[6] for summary in all_closes)),
        ("monthly", "restatement_bridge", CloseDelta, tuple(
            delta for parent, child in zip(original, revised, strict=True) for delta in compare_closes(parent, child))),
        ("monthly", "warehouse_dm", MonthlyWarehouseDM, tuple(dry_matter(fixture, all_closes))),
        ("market", "quotes", Quote, quotes),
        ("market", "liveweight_view", MarketValue, market),
        ("market", "monthly_coverage", MarketCoverage, tuple(coverage(market, fixture.calendar))),
    )
    for index, (name, record) in enumerate((
            ("animal_wip", AnimalWip), ("stock_on_hand", Stock), ("warehouse", Warehouse),
            ("trial_balance", Trial), ("exceptions", ExceptionRow)), 1):
        yield "monthly", name, record, tuple(row for summary in all_closes for row in summary[index])


def publish(output, inputs, source, checks, records, artifacts):
    run_id = stable_id("STAGE4-RUN", [SCHEMA_VERSION, sha256(canonical(inputs))])
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".stage4-", dir=output.parent) as temp:
        stage = Path(temp) / "build"
        index = {}
        for folder_name, name, record, rows in records:
            folder = stage / folder_name
            folder.mkdir(parents=True, exist_ok=True)
            index[f"{folder_name}/{name}"] = write_table(folder, name, record, rows, run_id)
        (stage / "inputs.json").write_bytes(canonical(inputs))
        (stage / "validation.json").write_bytes(canonical({
            "run_id": run_id, "synthetic": True, "status": "passed", "checks": checks,
        }))
        for name, artifact in artifacts.items():
            (stage / name).write_bytes(canonical(artifact))
        files = {path.relative_to(stage).as_posix(): sha256(path.read_bytes())
                 for path in sorted(stage.rglob("*")) if path.is_file()}
        hashes = canonical({"run_id": run_id, "synthetic": True, "tables": index, "files": files})
        (stage / "hashes.json").write_bytes(hashes)
        code = {path.relative_to(V2.parent).as_posix(): sha256(path.read_bytes())
                for directory in ("stage1", "stage2", "stage3", "stage3_5", "stage4")
                for path in sorted((V2 / directory).iterdir()) if path.suffix in {".py", ".json"}}
        manifest = {
            "run_id": run_id, "synthetic": True, "status": "passed", "seed": 42,
            "schema_version": SCHEMA_VERSION, "policy_version": inputs["policy"]["version"],
            "currency": "CAD", "calendar": "America/Edmonton", "starting_commit": BASE_COMMIT,
            "git_commit": git_commit(), "runtime": runtime(), "built_at": datetime.now(UTC),
            "stage35_source": source, "input_sha256": sha256(canonical(inputs)),
            "generator_files": code, "generator_sha256": sha256(canonical(code)),
            "hashes_sha256": sha256(hashes),
        }
        (stage / "run_manifest.json").write_bytes(canonical(manifest))
        if not publish_directory(stage, output):
            raise FileExistsError(f"build directory already exists: {output}")
    return run_id


def build(output, seed=42):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"build directory already exists: {output}")
    if seed != 42:
        raise ValueError("Stage 4 is scoped to the authoritative seed-42 fixture")
    operations = integrated_fixture(seed)
    source = verify_source(operations)
    config = settings()
    fixture = Fixture(operations, config, "selected")
    original_journals = journal_sets(fixture)
    alternate = journal_sets(fixture, corrected=True)
    original = close_series(fixture, original_journals)
    revised = close_series(fixture, alternate, originals=original)
    bridge = tuple(feed_bridge(fixture))
    invoices = tuple(invoice_routes(fixture, original_journals))
    recovery = tuple(recoverable(fixture, invoices))
    checks = list(validation(fixture, original_journals, original, revised, bridge, invoices, recovery))
    cases = list(sensitivity(fixture, original_journals, original))
    all_bridges = list(bridge)
    for name in config["loss_policies"]:
        if name == "selected":
            continue
        comparison = Fixture(operations, config, name)
        journals = journal_sets(comparison)
        cases.extend(sensitivity(comparison, journals, close_series(comparison, journals)))
        all_bridges.extend(feed_bridge(comparison))
    for month in ("horizon", *(period.month for period in fixture.calendar)):
        costs = {case.cumulative_accounted_cost_cents for case in cases if case.month == month}
        checks.append(Check("POLICY_COST_CONSERVATION", month, 1, len(costs), int(len(costs) != 1)))
    checks.append(Check("AUTHORITATIVE_SOURCE", "Stage 3.5 archive and rebuilt tables",
                        "verified", "verified"))
    reject_failures(checks)
    records = tables(fixture, original_journals, alternate, original, revised,
                     all_bridges, cases, invoices, recovery)
    return publish(output, {"policy": config, "stage35_source": source}, source, checks, records, {
        "reconciliation.json": reconciliation(fixture, original_journals, original, revised, invoices, bridge),
        "policy_sensitivity.json": cases,
    })
