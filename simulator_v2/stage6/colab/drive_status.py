"""Read-only inspection of Stage 7 Drive manifests, claims, and archive checksums."""

import argparse
from datetime import datetime, timezone
import json
import re

from googleapiclient.errors import HttpError

from .drive_storage import blob_matches, checked_id, connect, require

VERSION = "feedlot-colab-production.1"
SIMULATOR_COMMIT = "9afdbb6cf413395a3fb0b7b4ed5d2f0fa0e6da2e"
POLICY = {"purpose": "integrity_only", "stage5_status": "not_promoted", "promotion_eligible": False}
ARTIFACTS = {
    "operations": "checkpoint-operations.tar",
    "finance": "checkpoint-finance.tar",
    "dataset": "dataset-integrity-only.tar",
}
CHECKPOINTS = ("operations", "finance")
READ_ERRORS = (ValueError, KeyError, TypeError, HttpError, OSError)
ACTIVE_STATES = {"checking", "running", "restoring", "uploading", "validating", "checkpoint_verified"}


def attempt_manifest(drive, folder):
    manifest_id = drive.find(folder, "attempt.json")
    manifest = drive.read_json(manifest_id)
    require(manifest and manifest["version"] == VERSION and manifest["folder"] == folder
            and manifest["release_policy"] == POLICY, "Manifest percobaan atau keputusan rilis berbeda.")
    slots = manifest["slots"]
    require(slots.keys() == {"attempt", "status", "claim", *ARTIFACTS} and slots["attempt"] == manifest_id
            and len(set(slots.values())) == len(slots), "Slot manifest percobaan tidak valid.")
    for file_id in slots.values():
        checked_id(file_id)
    return manifest


def claim_chain(drive, folder, slot):
    visited = set()
    latest = {"state": "unclaimed", "count": 0}
    while (current := drive.get(slot)) is not None:
        require(slot not in visited and not current.get("trashed") and current["parents"] == [folder],
                "Rantai penguncian Drive tidak valid.")
        visited.add(slot)
        claim = drive.read_json(slot)
        latest = {"state": "released" if current.get("appProperties", {}).get("released") == "yes" else "unreleased",
                  "id": slot, "acquired_at": claim.get("acquired_at"), "count": len(visited)}
        slot = checked_id(claim["next"])
    return latest, slot


def archive_metadata(blob, folder, file_id, phase, parent):
    name = ARTIFACTS[phase]
    require(blob["parents"] == [folder] and not blob.get("trashed")
            and blob["name"] in {name, f".{name}.partial"}, f"Slot arsip Drive berbeda ({phase}).")
    props = blob["appProperties"]
    require(props["phase"] == phase and props["parent"] == (parent or "none")
            and all(re.fullmatch(r"[0-9a-f]{64}", props[key]) for key in ("sha256", "seal")),
            f"Manifest transfer Drive berbeda ({phase}).")
    size = int(props["bytes"])
    require(size > 0, f"Ukuran arsip Drive tidak valid ({phase}).")
    info = {"id": file_id, "file": name, "sha256": props["sha256"], "bytes": size, "seal": props["seal"]}
    return info, blob["name"] == name, blob_matches(blob, size, props["sha256"])


def inspect_drive(drive, folder, manifest):
    slots, identity = manifest["slots"], manifest["identity"]
    issues = []
    raw_status = None
    try:
        status_file = drive.get(slots["status"])
        if status_file is not None:
            require(not status_file.get("trashed") and status_file["name"] == "status.json"
                    and status_file["parents"] == [folder], "Lokasi status.json berbeda.")
            raw_status = drive.read_json(slots["status"])
            require((raw_status["folder_id"], raw_status["run_id"], raw_status["code_sha"]) ==
                    (folder, identity["run_id"], identity["commit"]), "Identitas status.json berbeda.")
            require(datetime.fromisoformat(raw_status["updated_at"]).tzinfo is not None,
                    "Zona waktu status.json tidak tersedia.")
    except READ_ERRORS as error:
        issues.append(f"status.json: {error}")
        raw_status = None

    try:
        lock, _ = claim_chain(drive, folder, slots["claim"])
    except READ_ERRORS as error:
        lock = {"state": "inconsistent", "error": str(error)}
        issues.append(f"Klaim: {error}")

    parent, parent_verified = None, True
    verified, archives = {}, {}
    for phase in ARTIFACTS:
        try:
            file_id = slots[phase]
            blob = drive.get(file_id)
            if blob is None:
                archives[phase] = {"state": "absent"}
            elif not parent_verified:
                archives[phase] = {"state": "parent_unverified", "name": blob["name"]}
                issues.append(f"{phase}: arsip ada tanpa rantai induk terverifikasi.")
            else:
                info, published, checksum = archive_metadata(blob, folder, file_id, phase, parent)
                if published:
                    require(checksum, f"SHA-256 atau ukuran arsip Drive berbeda ({phase}).")
                    verified[phase] = info
                archives[phase] = {"state": "verified" if published else
                                   "staged_verified" if checksum else "staged_unverified",
                                   "name": blob["name"], **info}
        except READ_ERRORS as error:
            archives[phase] = {"state": "inconsistent", "error": str(error)}
            issues.append(f"{phase}: {error}")
        parent_verified = phase in verified
        if parent_verified:
            parent = verified[phase]["seal"]

    status = dict(raw_status or {})
    recorded = status.get("checkpoints", {})
    if any(verified.get(phase) != entry for phase, entry in recorded.items()):
        issues.append("Checkpoint yang tercatat di status.json berbeda dari metadata arsip Drive.")
    if status.get("dataset") is not None and status["dataset"] != verified.get("dataset"):
        issues.append("Dataset yang tercatat di status.json berbeda dari metadata arsip Drive.")
    observed = status.get("status", "status_unverified" if issues else "prepared")
    heartbeat = status.get("last_heartbeat")
    if heartbeat is None and observed in ACTIVE_STATES and ("elapsed_seconds" in status or "percent" in status):
        heartbeat = {"at": status["updated_at"], "phase": status.get("phase"), "source": "legacy_status"}
    if "dataset" in verified:
        observed = "completed"
        status.update(validation_status="passed", complete_independent_audit=True)
    elif observed == "completed":
        observed = "publication_unverified"
        status.update(validation_status="unverified", complete_independent_audit=False)
    elif observed in ACTIVE_STATES:
        updated = datetime.fromisoformat(status["updated_at"])
        if (datetime.now(timezone.utc) - updated).total_seconds() > 900:
            observed = "possibly_interrupted"

    return {**status, "folder_id": folder, "code_sha": identity["commit"], "runtime": identity["runtime"],
            "status": observed, "recorded_status": raw_status.get("status") if raw_status else None,
            "status_json_verified": raw_status is not None, "phase": status.get("phase"),
            "last_heartbeat": heartbeat, "claim_lock": lock, "archives": archives, "issues": issues,
            "checkpoints": {phase: verified[phase] for phase in CHECKPOINTS if phase in verified},
            "last_verified_checkpoint": next((phase for phase in reversed(CHECKPOINTS) if phase in verified), None),
            "dataset": verified.get("dataset")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    args = parser.parse_args()
    try:
        folder = checked_id(args.folder)
        drive = connect(read_only=True)
        manifest = attempt_manifest(drive, folder)
        require(manifest["identity"]["commit"] == SIMULATOR_COMMIT, "Commit simulator berbeda dari produksi Stage 7.")
        print(json.dumps(inspect_drive(drive, folder, manifest), indent=2, ensure_ascii=False), flush=True)
    except READ_ERRORS as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
