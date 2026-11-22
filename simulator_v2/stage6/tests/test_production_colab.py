"""Exercise Colab phase boundaries with a small real build and a Drive API double."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

from googleapiclient.errors import HttpError
from httplib2 import Response
import pytest

from simulator_v2.stage6.__main__ import build, build_identity
from simulator_v2.stage6.colab import production as prod, production_resources as guards
from simulator_v2.stage6.colab.production_audit import verify_dataset
from simulator_v2.stage6.tests.test_stage6 import controlled


class FakeDrive:
    def __init__(self):
        self.files = {}
        self.count = 0
        self.bytes_free = 100 * guards.GIB
        self.fault = None
        self.events = []

    def ids(self, count):
        ids = [f"DriveSlot{index:06}" for index in range(self.count, self.count + count)]
        self.count += count
        return ids

    def folder(self, _name):
        return self.ids(1)[0]

    def free_bytes(self):
        return self.bytes_free

    def find(self, folder, name):
        return next(key for key, (meta, _) in self.files.items()
                    if meta["name"] == name and meta["parents"] == [folder])

    def get(self, file_id):
        return deepcopy(self.files[file_id][0]) if file_id in self.files else None

    def read_json(self, file_id):
        return json.loads(self.files[file_id][1]) if file_id in self.files else None

    def write_json(self, file_id, value, *, folder=None, name=None):
        if folder is not None and file_id in self.files:
            raise HttpError(Response({"status": "409"}), b"already exists")
        metadata = {"name": name, "parents": [folder]} if folder else self.get(file_id)
        self.files[file_id] = metadata, json.dumps(value).encode()

    def release_claim(self, file_id):
        self.files[file_id][0]["appProperties"] = {"released": "yes"}

    def upload(self, file_id, folder, name, properties, archive, progress, *, replace=False):
        phase = properties["phase"]
        if self.fault == (phase, "before_server_commit"):
            raise ConnectionError("interrupted after partial data")
        raw = archive.read_bytes()
        if self.fault == (phase, "bad_sha"):
            raw = raw[:-1] + b"!"
        assert replace == (file_id in self.files)
        self.files[file_id] = ({"name": name, "parents": [folder], "appProperties": dict(properties),
                                "size": str(len(raw)), "sha256Checksum": sha256(raw).hexdigest()}, raw)
        progress(0.99)
        if self.fault == (phase, "after_server_commit"):
            raise ConnectionError("response lost after server commit")

    def rename(self, file_id, name):
        self.files[file_id][0]["name"] = name
        self.events.append(name)

    def download(self, file_id, stream, progress):
        raw = self.files[file_id][1]
        stream.write(raw)
        progress(1)


@pytest.fixture
def attempt_setup(tmp_path, monkeypatch):
    config = controlled(capacities={"receiving": [3], "production": [4, 4], "hospital": [2]},
                        lot_segregation=True, required_placements=3, hospital_planning_head=1)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    drive = FakeDrive()
    resources = guards.Resources({"ram": 0, "local_disk": 0, "drive": 0})
    attempt = prod.Attempt.create(drive, tmp_path / "from", build_identity(config), resources)
    actual_worker = prod.Attempt.worker

    def worker(self, phase, *args):
        if phase == "finance":
            assert "checkpoint-operations.tar" in drive.events
        if phase == "audit":
            assert "checkpoint-finance.tar" in drive.events
        drive.events.append(phase)
        return actual_worker(self, phase, *args)

    monkeypatch.setattr(prod.Attempt, "worker", worker)
    monkeypatch.setattr(prod, "verify_release",
                        lambda root, config, identity, progress: verify_dataset(
                            root, config, identity, {"exact_placements"}, progress=progress))
    return attempt, path, config, drive


def reopen(attempt, local):
    return prod.Attempt.open(attempt.drive, attempt.folder, local, attempt.checkpoints.identity, attempt.resources)


@pytest.mark.parametrize("fault", ["before_server_commit", "after_server_commit", "bad_sha"])
def test_operations_transfer_failure_gates_finance_and_resumes(attempt_setup, tmp_path, fault, capsys):
    attempt, path, config, drive = attempt_setup
    drive.fault = ("operations", fault)
    with pytest.raises((ConnectionError, ValueError)):
        attempt.run(config, path)
    assert drive.events == ["operations"]
    assert drive.get(attempt.slots["finance"]) is None
    assert attempt.inspect()["status"] == "save_failed"
    assert attempt.inspect()["last_verified_checkpoint"] is None
    assert "Checkpoint operations terverifikasi" not in capsys.readouterr().out

    drive.fault = None
    local = tmp_path / "new-runtime" if fault == "after_server_commit" else attempt.work.parent
    resumed = reopen(attempt, local)
    resumed.run(config, path)
    assert drive.events == ["operations", "checkpoint-operations.tar", "finance", "checkpoint-finance.tar",
                            "audit", "dataset-integrity-only.tar"]
    assert resumed.inspect()["status"] == "completed"
    assert resumed.inspect()["head"]["placements"] == 3
    assert resumed.inspect()["financial_closes"] == 4

    if fault == "after_server_commit":
        reference = tmp_path / "reference"
        build(config, reference)
        assert (reference / "hashes.json").read_bytes() == (resumed.dataset / "hashes.json").read_bytes()
        before = drive.events[:]
        reopen(attempt, tmp_path / "again").run(config, path)
        assert drive.events == before
        assert resumed.inspect()["financial_closes"] == 4


def test_finance_and_final_transfer_gate_completion(attempt_setup, tmp_path):
    attempt, path, config, drive = attempt_setup
    drive.fault = ("finance", "after_server_commit")
    with pytest.raises(ConnectionError):
        attempt.run(config, path)
    assert "audit" not in drive.events
    assert attempt.inspect()["last_verified_checkpoint"] == "operations"
    assert attempt.inspect()["dataset"] is None

    drive.fault = ("dataset", "after_server_commit")
    resumed = reopen(attempt, tmp_path / "resume")
    with pytest.raises(ConnectionError):
        resumed.run(config, path)
    assert resumed.inspect()["status"] == "save_failed"
    assert resumed.inspect()["dataset"] is None
    assert resumed.inspect()["last_verified_checkpoint"] == "finance"

    drive.fault = None
    reopen(attempt, tmp_path / "fresh").run(config, path)
    assert drive.events.count("finance") == drive.events.count("audit") == 1
    assert resumed.inspect()["status"] == "completed"
    archive = drive.files[attempt.slots["dataset"]][1]
    import tarfile
    with tarfile.open(fileobj=BytesIO(archive)) as stream:
        release = json.load(stream.extractfile("dataset/release_manifest.json"))
    assert release["stage5_status"] == "not_promoted"
    assert release["complete_independent_audit"] is True
    assert release["financial_closes"] == 4


def test_corruption_and_identity_changes_are_rejected(attempt_setup, tmp_path):
    attempt, path, config, drive = attempt_setup
    drive.fault = ("finance", "before_server_commit")
    with pytest.raises(ConnectionError):
        attempt.run(config, path)
    for key in ("commit", "config_sha256", "runtime"):
        identity = {**attempt.checkpoints.identity, key: "changed"}
        with pytest.raises(ValueError, match="versi runtime"):
            prod.Attempt.open(drive, attempt.folder, tmp_path, identity, attempt.resources)

    file_id = attempt.slots["operations"]
    metadata, raw = drive.files[file_id]
    drive.files[file_id] = ({**metadata, "sha256Checksum": "0" * 64}, raw)
    drive.fault = None
    with pytest.raises(ValueError, match="SHA-256"):
        reopen(attempt, tmp_path / "new-runtime").run(config, path)
    assert "audit" not in drive.events
    assert drive.get(attempt.slots["dataset"]) is None


def test_lock_rejects_duplicate_and_recovers_abandoned_claim(attempt_setup, tmp_path):
    attempt, _, _, drive = attempt_setup
    other = reopen(attempt, tmp_path / "other")
    with attempt.lock(recover=False):
        with pytest.raises(RuntimeError, match="runtime ini"), attempt.lock(recover=False):
            pass
        with pytest.raises(ValueError, match="masih terkunci"), other.lock(recover=False):
            pass
    abandoned = attempt.next_claim
    next_slot, = drive.ids(1)
    drive.write_json(abandoned, {"next": next_slot}, folder=attempt.folder, name=".abandoned")
    with pytest.raises(ValueError, match="masih terkunci"), other.lock(recover=False):
        pass
    with other.lock(recover=True):
        assert other.claim_id == next_slot
        with pytest.raises(ValueError, match="masih terkunci"), reopen(attempt, tmp_path / "third").lock(recover=False):
            pass


@pytest.mark.parametrize("ram,drive_gib,pattern", [(23, 90, "RAM efektif"), (24, 84, "Google Drive")])
def test_resource_limits_prevent_worker(attempt_setup, monkeypatch, ram, drive_gib, pattern):
    attempt, path, config, drive = attempt_setup
    drive.bytes_free = drive_gib * guards.GIB
    attempt.resources = guards.Resources({"ram": 24 * guards.GIB, "local_disk": 0, "drive": 85 * guards.GIB})
    monkeypatch.setattr(guards, "memory", lambda: {"available_ram_bytes": ram * guards.GIB})
    with pytest.raises(ValueError, match=pattern):
        attempt.run(config, path)
    assert not drive.events


def test_cgroup_headroom_accounts_for_parent_and_leaf(tmp_path):
    point = tmp_path / "cgroup"
    leaf = point / "tenant" / "job"
    leaf.mkdir(parents=True)
    for directory, limit, used in [(point, "max", 0), (leaf.parent, "100", 70), (leaf, "60", 20)]:
        (directory / "memory.max").write_text(limit)
        (directory / "memory.current").write_text(str(used))
    assert guards.cgroup_headroom("0::/delegated/tenant/job",
                                  f"1 0 0:1 /delegated {point} ro - cgroup2 cgroup rw") == 30


def test_failed_audit_blocks_final_publication(attempt_setup, monkeypatch):
    attempt, path, config, drive = attempt_setup

    def audit_fails(*args):
        raise ValueError("fixture audit gate failed")

    monkeypatch.setattr(prod, "verify_release", audit_fails)
    with pytest.raises(ValueError, match="audit gate failed"):
        attempt.run(config, path)
    assert drive.get(attempt.slots["dataset"]) is None
    assert attempt.inspect()["status"] == "failed"
    assert attempt.inspect()["last_verified_checkpoint"] == "finance"
