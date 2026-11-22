"""Immutable publication with one explicitly authorized successor per snapshot."""

import errno
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .export import write_table
from .ledger import is_id, synthetic_id
from .model import Animal, AnimalEvent, LocationVersion, Lot, is_utc
from .provenance import canonical, sha256, stable_id
from .replay import AnimalState, LocationInterval
from .soh import StockRow, calculate_soh
from .validation import reject_failures, require


@dataclass(frozen=True)
class RevisionApproval:
    approval_id: str
    approved_by: str
    approved_at: datetime
    reason: str
    synthetic: bool = True


def publish_directory(stage, target):
    """Publish a complete directory atomically. Return false if another writer won."""
    try:
        os.rename(stage, target)
        return True
    except OSError as exc:
        if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY} or not target.is_dir():
            raise
    return False


class SnapshotStore:
    def __init__(self, root, ledger):
        self.root = Path(root)
        self.ledger = ledger
        self.run_id = stable_id("RUN", ledger.config)

    @staticmethod
    def metadata(folder):
        return json.loads((folder / "snapshot.json").read_bytes())

    def publish(self, start, end, knowledge_cutoff, *, revises=None, approval=None):
        result, daily, monthly, checks = calculate_soh(self.ledger, start, end, knowledge_cutoff)
        reject_failures(checks)
        period = self.root / self.run_id / f"{start.isoformat()}_{end.isoformat()}"
        target = period / "original"
        if revises is not None:
            valid_id = isinstance(revises, str) and bool(re.fullmatch(r"SYN-SNAPSHOT-[0-9a-f]{24}", revises))
            require(valid_id, "REVISION_PARENT", "snapshot", "published snapshot ID", revises)
            require(isinstance(approval, RevisionApproval) and approval.synthetic is True
                    and synthetic_id(approval.approval_id) and synthetic_id(approval.approved_by)
                    and is_id(approval.reason) and is_utc(approval.approved_at)
                    and approval.approved_at >= knowledge_cutoff,
                    "REVISION_APPROVAL", "snapshot", "explicit approval at or after cutoff", str(approval))
            parent_path = target
            parent = None
            while parent_path.is_dir():
                metadata = self.metadata(parent_path)
                if metadata["snapshot_id"] == revises:
                    parent = metadata
                    break
                parent_path = period / "revisions" / metadata["snapshot_id"]
            require(parent is not None, "REVISION_PARENT", "snapshot", "published same-period parent", revises)
            parent_cutoff = datetime.fromisoformat(parent["knowledge_cutoff"])
            require(knowledge_cutoff > parent_cutoff, "REVISION_CUTOFF", "snapshot",
                    "later knowledge cutoff", str(knowledge_cutoff))
            target = period / "revisions" / revises
        else:
            require(approval is None, "REVISION_PARENT", "snapshot", "parent for approval", str(approval))

        inputs = [result.known_events, result.animals, result.lots, result.location_versions]
        metadata = {
            "run_id": self.run_id,
            "schema_version": self.ledger.config.schema_version,
            "policy_version": self.ledger.config.policy_version,
            "calendar": self.ledger.config.calendar,
            "period_start": start, "period_end": end,
            "effective_before": result.effective_before, "knowledge_cutoff": knowledge_cutoff,
            "input_sha256": sha256(canonical(inputs)),
            "result_sha256": sha256(canonical([result.events, result.states, result.intervals, daily, monthly])),
            "revises_snapshot_id": revises, "approval": approval,
            "synthetic": True,
        }
        snapshot_id = stable_id("SNAPSHOT", metadata)
        metadata["snapshot_id"] = snapshot_id

        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".snapshot-", dir=target.parent) as temp:
            stage = Path(temp) / "snapshot"
            stage.mkdir()
            tables = (
                ("lots", Lot, result.lots), ("animals", Animal, result.animals),
                ("locations", LocationVersion, result.location_versions),
                ("effective_events", AnimalEvent, result.events),
                ("animal_state", AnimalState, result.states),
                ("animal_location_intervals", LocationInterval, result.intervals),
                ("daily_soh", StockRow, daily), ("monthly_soh", StockRow, monthly),
            )
            metadata["tables"] = {name: write_table(stage, name, cls, rows, self.run_id, snapshot_id)
                                  for name, cls, rows in tables}
            checks_bytes = canonical({"run_id": self.run_id, "snapshot_id": snapshot_id,
                                      "synthetic": True, "checks": checks})
            (stage / "validation.json").write_bytes(checks_bytes)
            metadata["validation_sha256"] = sha256(checks_bytes)
            encoded = canonical(metadata)
            (stage / "snapshot.json").write_bytes(encoded)
            if not publish_directory(stage, target):
                require((target / "snapshot.json").read_bytes() == encoded and
                        all((target / file).is_file() and sha256((target / file).read_bytes()) == digest
                            for table in metadata["tables"].values()
                            for file, digest in table["files"].items()) and
                        (target / "validation.json").read_bytes() == checks_bytes,
                        "SNAPSHOT_LOCKED", "snapshot", "matching immutable snapshot",
                        self.metadata(target)["snapshot_id"])
        return target, snapshot_id
