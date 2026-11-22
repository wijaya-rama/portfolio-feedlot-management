"""Verify a sealed Stage 6 dataset before the production archive can be made."""

from datetime import date, datetime, timedelta
import json

from ...stage1.model import EDMONTON
from ...stage4.ledger import periods
from ..config import MODEL, SCHEMA
from ..export import digest
from .drive_storage import require

REPORTS = {"config.json", "diagnostics.json", "monthly_summary.json", "validation.json", "weather.json"}
REQUIRED_GATES = {
    "balanced_paired_entries", "balanced_two_line_journal", "biological_reserve_balance",
    "financial_close_publication", "warehouse_replay_publication", "warehouse_af_value",
    "warehouse_dm", "stock_equation", "period_end_stock_reporting", "final_simulation_stock_reporting",
    "snapshot_publication", "stable_original_snapshot", "stable_restated_snapshot",
    "exact_placements", "lot_segregation", "baseline_operating_capacity", "hospital_headroom",
}
def read(path):
    return json.loads(path.read_bytes())


def verify_dataset(root, config, identity, required_gates=REQUIRED_GATES, *, progress=None):
    manifest, index = (read(root / name) for name in ("run_manifest.json", "hashes.json"))
    require(manifest["code_checkout_commit_at_build"] == identity["commit"] and manifest["synthetic"] is True
            and manifest["input_hashes"] == identity["inputs"] and manifest["runtime"] == identity["runtime"]
            and identity["run_id"] == manifest["run_id"] == index["run_id"]
            and manifest["model_version"] == MODEL and manifest["schema_version"] == index["schema_version"] == SCHEMA
            and manifest["hashes_sha256"] == digest(root / "hashes.json")
            and identity["config_sha256"] == manifest["config_sha256"] == digest(root / "config.json")
            and read(root / "config.json") == config, "Provenance, manifest, atau konfigurasi dataset berbeda.")

    first, last = (date.fromisoformat(config[key]) for key in ("start", "end"))
    end = datetime.fromisoformat(manifest["effective_before"])
    cutoff = datetime.fromisoformat(manifest["final_knowledge_cutoff"])
    require(end.astimezone(EDMONTON).date() == last + timedelta(days=1)
            and cutoff - end == timedelta(days=max(config["shipment"]["settlement_lag_days"]) + 4),
            "Horizon efektif atau cutoff penutupan berbeda.")

    partitions, reports = index["partitions"], index["artifacts"]
    require(bool(partitions) and set(reports) == REPORTS, "Indeks partisi atau laporan belum lengkap.")
    expected = partitions.keys() | REPORTS | {"run_manifest.json", "hashes.json", "performance.json"}
    files = set()
    for path in root.rglob("*"):
        require(not path.is_symlink(), f"Tautan simbolik pada dataset {path.name}.")
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    require(files == expected, "Inventaris berkas dataset berbeda dari indeks.")
    for name, item in partitions.items():
        path = root / name
        require(path.stat().st_size == item["bytes"] and digest(path) == item["sha256"],
                f"Ukuran atau SHA-256 partisi berbeda ({name}).")
        if progress is not None:
            progress()
    for name, checksum in reports.items():
        require(digest(root / name) == checksum, f"SHA-256 laporan berbeda ({name}).")

    audit = read(root / "validation.json")
    gates = audit["hard_gates"]
    require(audit["mode"] == "full" and audit["complete_independent_audit"] is True
            and required_gates <= gates.keys() and all(row["passed"] is True for row in gates.values())
            and all(audit[key] and all(row["failed_count"] == 0 for row in audit[key])
                    for key in ("movement", "financial")), "Dataset memerlukan audit penuh yang lulus.")

    months = {period.month for period in periods(first, last)}
    closes = read(root / "monthly_summary.json")
    expected_closes = {(month, view) for month in months for view in ("as_known", "restated")}
    require(len(closes) == len(expected_closes) and {(row["month"], row["view"]) for row in closes} == expected_closes,
            "Penutupan original/restated belum lengkap.")

    diagnostics = read(root / "diagnostics.json")
    head, stock = diagnostics["head"], diagnostics["stock_reporting"]
    require(head["placements"] == config["required_placements"]
            and head["opening"] == sum(row["head"] for row in config["carry_in"])
            and stock["final_simulation_date"] == config["end"]
            and head["carry_out"] == stock["final_simulation_soh"]
            and head["opening"] + head["placements"] == head["sale"] + head["death"] + head["carry_out"],
            "Rekonsiliasi jumlah ternak atau batas kalender berbeda.")
    return {"validation_status": "passed", "complete_independent_audit": True, "gate_count": len(gates),
            "financial_closes": len(closes), "head": head, "hashes_sha256": manifest["hashes_sha256"]}
