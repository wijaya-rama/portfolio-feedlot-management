"""Local restart boundaries for one chronological Stage 6 build.

Checkpoint payloads are private, trusted build state. File hashes detect corruption;
they do not authenticate a checkpoint supplied by a third party.
"""

from fcntl import LOCK_EX, LOCK_NB, flock
import json
from pathlib import Path, PurePosixPath
import pickle
from tempfile import TemporaryDirectory

from ..stage1.ledger import Ledger
from ..stage1.provenance import canonical
from ..stage1.snapshots import publish_directory
from .export import digest

PHASES = ("operations", "finance")
CHECKPOINT_VERSION = "stage6-phase-checkpoint.1"


def file_info(path):
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def restore_ledger(config, lots, animals, locations, events):
    ledger = Ledger(config, lots, animals, locations)
    ledger.ingest(events)
    return ledger


class PhasePickler(pickle.Pickler):
    def reducer_override(self, value):
        if isinstance(value, Ledger):
            return restore_ledger, (value.config, tuple(value.lots.values()), tuple(value.animals.values()),
                                    tuple(value.location_versions.values()), value.events)
        return NotImplemented


class Checkpoints:
    def __init__(self, root, identity, retain):
        self.root, self.identity, self.retain = Path(root).resolve(), identity, retain

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / ".lock").open("a")
        try:
            flock(self.lock, LOCK_EX | LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError(f"a build is already using {self.root}") from None
        return self

    def __exit__(self, *exc):
        self.lock.close()

    def verify(self, phase, parent):
        root = self.root / phase
        marker = root / "checkpoint.json"
        if not root.exists():
            return None
        if root.is_symlink() or not marker.is_file() or marker.is_symlink():
            raise ValueError(f"missing checkpoint marker: {phase}")
        meta = json.loads(marker.read_bytes())
        if (meta["version"], meta["phase"], meta["identity"], meta["parent"]) != (
            CHECKPOINT_VERSION, phase, self.identity, parent
        ):
            raise ValueError(f"checkpoint identity or phase dependency mismatch: {phase}")
        partitions = meta["partitions"]
        others = meta["files"]
        expected = {f"dataset/{name}": info for name, info in partitions.items()} | others
        allowed = {"state.pickle", "feed-accounting-checkpoints.pickle"} if phase == "operations" else {"state.pickle"}
        if "state.pickle" not in others or not others.keys() <= allowed:
            raise ValueError(f"unexpected checkpoint state files: {phase}")
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"symbolic link in checkpoint: {path}")
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
        if actual != expected.keys() | {"checkpoint.json"}:
            raise ValueError(f"incomplete or unexpected checkpoint files: {phase}")
        for relative, info in expected.items():
            name = PurePosixPath(relative)
            if name.is_absolute() or ".." in name.parts or info["bytes"] != (root / name).stat().st_size:
                raise ValueError(f"invalid checkpoint file: {phase}/{relative}")
            if digest(root / name) != info["sha256"]:
                raise ValueError(f"checkpoint hash mismatch: {phase}/{relative}")
        return meta

    def run(self, phase, parent, generate):
        root = self.root / phase
        if self.retain and (meta := self.verify(phase, parent)) is not None:
            print(f"Restored {phase} checkpoint", flush=True)
            with (root / "state.pickle").open("rb") as stream:
                return meta, pickle.load(stream)
        with TemporaryDirectory(prefix=f".{phase}-", dir=self.root) as temporary:
            pending = Path(temporary)
            (pending / "dataset").mkdir()
            partitions, state, performance = generate(pending)
            if self.retain:
                with (pending / "state.pickle").open("wb") as stream:
                    PhasePickler(stream, protocol=5).dump(state)
            files = {file.name: file_info(file) for file in pending.iterdir() if file.is_file()} if self.retain else {}
            meta = {"version": CHECKPOINT_VERSION, "phase": phase, "identity": self.identity,
                    "parent": parent, "partitions": partitions, "files": files, "performance": performance}
            (pending / "checkpoint.json").write_bytes(canonical(meta))
            if not publish_directory(pending, root):
                raise FileExistsError(root)
        if self.retain:
            print(f"Saved {phase} checkpoint", flush=True)
        return meta, state
