"""Build a synthetic Stage 1 run and its validation evidence."""

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import TZPATH

import pyarrow

from .expected import december_checks, fixture_checks
from .export import write_table
from .fixture import END, FINAL_CUTOFF, LATE_CUTOFF, ORIGINAL_CUTOFF, REVISED_CUTOFF, START, fixture, local
from .ledger import known_events
from .model import CALENDAR, UTC, Animal, AnimalEvent, LocationVersion, Lot
from .provenance import canonical, sha256
from .replay import replay
from .snapshots import RevisionApproval, SnapshotStore, publish_directory
from .soh import calculate_soh
from .validation import Check, ValidationError, reject_failures


def validation_checks(ledger):
    checks = [Check("RAW_LEDGER", "run", "valid synthetic keys, master data and correction links",
                    {"animals": len(ledger.animals), "lots": len(ledger.lots),
                     "location_versions": len(ledger.location_versions), "events": len(ledger.events)})]
    for name, cutoff in (("original", ORIGINAL_CUTOFF), ("late", LATE_CUTOFF), ("revised", REVISED_CUTOFF)):
        _, daily, _, report = calculate_soh(ledger, START, START, cutoff)
        checks.extend(replace(check, scope=f"december-{name}/{check.scope}") for check in report)
        checks.extend(december_checks(daily, name))
    result, daily, monthly, report = calculate_soh(ledger, START, END, FINAL_CUTOFF)
    checks.extend(replace(check, scope=f"full-horizon/{check.scope}") for check in report)
    checks.extend(fixture_checks(result, daily, monthly))
    availability = sorted({record.available_at for record in
                           (*ledger.events, *ledger.animals.values(), *ledger.lots.values(),
                            *ledger.location_versions.values())})
    violations = []
    for cutoff in availability:
        state = replay(ledger, FINAL_CUTOFF, cutoff)
        violations.extend(f"{cutoff.isoformat()}/{check.check_id}/{','.join(check.sample_ids)}"
                          for check in state.checks if check.failed_count)
    checks.append(Check("AVAILABILITY_REPLAY", "fixture", "valid at every eligibility boundary",
                        {"cutoffs": len(availability), "violations": len(violations)},
                        len(violations), tuple(violations[:10])))
    checks.append(Check("EVENT_SELECTION", "fixture", {"known": 37, "effective": 34},
                        {"known": len(known_events(ledger.events, FINAL_CUTOFF)),
                         "effective": len(result.events)},
                        int((len(result.known_events), len(result.events)) != (37, 34))))
    return tuple(checks)


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def runtime():
    zone = next((Path(root) / CALENDAR for root in TZPATH if (Path(root) / CALENDAR).is_file()), None)
    if zone:
        zone_bytes = zone.read_bytes()
    else:
        from importlib.resources import files
        zone_bytes = files("tzdata.zoneinfo").joinpath(*CALENDAR.split("/")).read_bytes()
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "machine": platform.machine(), "pyarrow": pyarrow.__version__,
            "calendar_tzif_sha256": sha256(zone_bytes)}


def build(output, seed):
    if output.exists():
        raise FileExistsError(f"build directory already exists: {output}")
    ledger = fixture(seed)
    checks = validation_checks(ledger)
    reject_failures(checks)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".stage1-", dir=output.parent) as temp:
        stage = Path(temp) / "run"
        stage.mkdir()
        snapshots = SnapshotStore(stage / "snapshots", ledger)
        original_path, original = snapshots.publish(START, START, ORIGINAL_CUTOFF)
        revised_path, _ = snapshots.publish(
            START, START, REVISED_CUTOFF, revises=original,
            approval=RevisionApproval("SYN-APPROVAL-DEC", "SYN-FIXTURE-REVIEWER",
                                      local("2024-01-04 11:00"), "Validate corrected December placements"))
        latest_path, _ = snapshots.publish(START, END, FINAL_CUTOFF)
        tables = {name: write_table(stage, name, cls, rows, snapshots.run_id, jsonl=name == "animal_events")
                  for name, cls, rows in (
                      ("lots", Lot, ledger.lots.values()), ("animals", Animal, ledger.animals.values()),
                      ("locations", LocationVersion, ledger.location_versions.values()),
                      ("animal_events", AnimalEvent, ledger.events),
                  )}
        (stage / "validation.json").write_bytes(canonical(
            {"run_id": snapshots.run_id, "synthetic": True, "status": "passed", "checks": checks}))
        versions = {}
        for name, path in (("december_original", original_path), ("december_revised", revised_path),
                           ("full_horizon", latest_path)):
            meta = snapshots.metadata(path)
            versions[name] = {"snapshot_id": meta["snapshot_id"], "revises_snapshot_id": meta["revises_snapshot_id"],
                              "knowledge_cutoff": meta["knowledge_cutoff"], "path": str(path.relative_to(stage)),
                              "tables": meta["tables"], "synthetic": True}
        hashes = {
            "run_id": snapshots.run_id, "synthetic": True, "tables": tables, "snapshots": versions,
            "files": {str(path.relative_to(stage)): sha256(path.read_bytes())
                      for path in sorted(stage.rglob("*")) if path.is_file()},
        }
        hashes_bytes = canonical(hashes)
        (stage / "hashes.json").write_bytes(hashes_bytes)
        modules = sorted(Path(__file__).parent.glob("*.py"))
        source_hashes = {path.name: sha256(path.read_bytes()) for path in modules}
        manifest = {
            "run_id": snapshots.run_id, "config": ledger.config, "config_sha256": sha256(canonical(ledger.config)),
            "git_commit": git_commit(), "generator_sha256": sha256(canonical(source_hashes)),
            "generator_files": source_hashes, "input_batch": "SYN-FIXTURE",
            "seed_streams": ["fixture-rfid"], "built_at": datetime.now(UTC), "runtime": runtime(),
            "knowledge_cutoff": FINAL_CUTOFF, "synthetic": True, "status": "passed",
            "hashes_sha256": sha256(hashes_bytes),
        }
        (stage / "run_manifest.json").write_bytes(canonical(manifest))
        if not publish_directory(stage, output):
            raise FileExistsError(f"build directory already exists: {output}")
    return snapshots.run_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, dedicated output directory")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        run_id = build(args.output, args.seed)
    except ValidationError as exc:
        report = {"synthetic": True, "status": "failed", "checks": exc.checks}
        print(canonical(report).decode().rstrip(), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"run_id": run_id, "output": str(args.output), "status": "passed", "synthetic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
