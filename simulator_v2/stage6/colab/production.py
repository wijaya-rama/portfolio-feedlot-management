"""Explicitly authorized Stage 7 production with verified Drive phase boundaries."""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
from fcntl import LOCK_EX, LOCK_NB, flock
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from googleapiclient.errors import HttpError
import psutil

from ...stage1.provenance import canonical
from ...stage1.snapshots import publish_directory
from ..__main__ import build_identity
from ..config import HERE, load
from ..export import digest
from ..recovery import Checkpoints, PHASES, file_info
from ..release_preflight import inspect as inspect_capacity
from .drive_storage import blob_matches, checked_id, connect, require
from .production_audit import POLICY, verify_dataset
from .production_resources import LIVE_DISK_RESERVE, Resources

CONFIG = HERE / "configs" / "stage7-production-15000.json"
CONFIG_SHA256 = "0fc8340ceebf54756876bfba10ace3dc097c8d10a8464083011437b6615ff375"
SOURCE = HERE.parents[1]
VERSION = "feedlot-colab-production.1"
ARTIFACTS = {
    "operations": "checkpoint-operations.tar",
    "finance": "checkpoint-finance.tar",
    "dataset": "dataset-integrity-only.tar",
}
CONFIRMATIONS = {"start": "MULAI 15000", "resume": "LANJUT 15000", "recover": "PULIHKAN 15000"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def production_config():
    require(digest(CONFIG) == CONFIG_SHA256, "SHA-256 konfigurasi produksi terpin berbeda.")
    config = load(CONFIG)
    first, last = date(2024, 1, 1), date(2025, 12, 31)
    require((config["start"], config["end"]) == (first.isoformat(), last.isoformat())
            and config["seed"] == 42 and config["required_placements"] == 15_000
            and sum(row["head"] for row in config["placements"]) == 15_000
            and all(first <= date.fromisoformat(row["date"]) <= last for row in config["placements"]),
            "Konfigurasi harus menjadwalkan tepat 15.000 placement baru selama 2024–2025.")
    return config


def size_of(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def pack(root, archive, resources):
    files = sorted(path for path in root.rglob("*") if path.is_file())
    resources.staging(archive.parent, sum(path.stat().st_size + 4096 for path in files) + 1024**2)

    def portable(info):
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ""
        info.mode = 0o600
        return info

    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as output:
        for path in files:
            require(not path.is_symlink(), f"Tautan simbolik di arsip {path.name}.")
            output.add(path, arcname=(Path(root.name) / path.relative_to(root)).as_posix(),
                       recursive=False, filter=portable)


def unpack(archive, destination, top):
    with tarfile.open(archive, "r:") as stream:
        names = set()
        for member in stream:
            path = PurePosixPath(member.name)
            require(member.isfile() and not member.sparse and len(path.parts) >= 2 and path.parts[0] == top
                    and ".." not in path.parts and member.name == path.as_posix() and member.name not in names,
                    "Arsip checkpoint berisi path atau tipe berkas yang tidak diizinkan.")
            names.add(member.name)
            stream.extract(member, destination, filter="data")


def verify_release(dataset, config, identity):
    receipt = verify_dataset(dataset, config, identity)
    require(receipt["financial_closes"] == 48 and receipt["head"]["placements"] == 15_000,
            "Produksi memerlukan 48 close dan 15.000 placement baru.")
    return receipt


class Attempt:
    def __init__(self, drive, folder, manifest, local, identity, resources):
        self.drive, self.folder, self.manifest = drive, checked_id(folder), manifest
        self.work = local / folder
        self.checkpoints = Checkpoints(self.work / "checkpoints", identity, retain=True)
        self.dataset = self.work / "dataset"
        self.resources = resources
        self.slots = manifest["slots"]
        self.saved = {}
        self.claim_id = self.next_claim = None
        self.phase, self.state, self.last_update = None, None, 0

    @classmethod
    def create(cls, drive, local, identity, resources):
        folder = drive.folder(f"Feedlot_V2_Production_15000_{datetime.now(timezone.utc):%Y%m%d-%H%M%S}_{uuid4().hex[:8]}")
        slots = dict(zip(("attempt", "status", "claim", *ARTIFACTS), drive.ids(6), strict=True))
        manifest = {"version": VERSION, "folder": folder, "created_at": now(), "identity": identity,
                    "release_policy": POLICY, "slots": slots}
        drive.write_json(slots["attempt"], manifest, folder=folder, name="attempt.json")
        return cls(drive, folder, manifest, local, identity, resources)

    @classmethod
    def open(cls, drive, folder, local, identity, resources, *, read_only=False):
        manifest_id = drive.find(folder, "attempt.json")
        manifest = drive.read_json(manifest_id)
        require(manifest and manifest["version"] == VERSION and manifest["folder"] == folder
                and manifest["release_policy"] == POLICY,
                "Manifest percobaan atau keputusan rilis berbeda.")
        saved_identity = manifest["identity"]
        required = ("commit", "config_sha256", "run_id") if read_only else identity.keys()
        require(all(saved_identity[key] == identity[key] for key in required),
                "Manifest percobaan berbeda. Gunakan commit, konfigurasi, dan versi runtime semula.")
        slots = manifest["slots"]
        require(slots.keys() == {"attempt", "status", "claim", *ARTIFACTS} and slots["attempt"] == manifest_id
                and len(set(slots.values())) == len(slots), "Slot manifest percobaan tidak valid.")
        for file_id in slots.values():
            checked_id(file_id)
        return cls(drive, folder, manifest, local, saved_identity, resources)

    @contextmanager
    def lock(self, recover):
        self.work.mkdir(parents=True, exist_ok=True)
        with (self.work / ".lock").open("a") as local_lock:
            try:
                flock(local_lock, LOCK_EX | LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Percobaan masih berjalan di runtime ini.") from None
            slot = self.slots["claim"]
            visited = set()
            previous = None
            while (current := self.drive.get(slot)) is not None:
                require(slot not in visited and not current.get("trashed") and current["parents"] == [self.folder],
                        "Rantai penguncian Drive tidak valid.")
                visited.add(slot)
                previous = current
                claim = self.drive.read_json(slot)
                slot = checked_id(claim["next"])
            if previous and previous.get("appProperties", {}).get("released") != "yes":
                require(recover, "Percobaan masih terkunci. Putuskan runtime lama, lalu gunakan STOP/RECOVER.")
            successor, = self.drive.ids(1)
            try:
                self.drive.write_json(slot, {"next": successor, "acquired_at": now()}, folder=self.folder,
                                      name=f".claim-{slot}")
            except HttpError as error:
                if error.resp.status != 409:
                    raise
                raise RuntimeError("Percobaan sudah diambil oleh runtime lain. Periksa Status.") from error
            self.claim_id, self.next_claim = slot, successor
            try:
                yield local_lock.fileno()
            finally:
                try:
                    self.drive.release_claim(slot)
                except Exception as error:
                    print(f"Penguncian Drive belum dilepas ({error}). Gunakan STOP/RECOVER setelah runtime berhenti.",
                          flush=True)

    def still_owner(self):
        require(self.claim_id and self.drive.get(self.next_claim) is None,
                "Percobaan sudah diambil alih. Hentikan runtime ini.")

    def status(self, state, **details):
        self.state = state
        self.last_update = time.monotonic()
        status = {"folder_id": self.folder, "run_id": self.checkpoints.identity["run_id"],
                  "code_sha": self.checkpoints.identity["commit"], "status": state, "phase": self.phase,
                  "updated_at": now(), "checkpoints": {phase: self.saved[phase] for phase in PHASES if phase in self.saved},
                  "last_verified_checkpoint": next((phase for phase in reversed(PHASES) if phase in self.saved), None),
                  "dataset": self.saved.get("dataset"), **POLICY, **details}
        try:
            file_id = self.slots["status"]
            if self.drive.get(file_id) is None:
                self.drive.write_json(file_id, status, folder=self.folder, name="status.json")
            else:
                self.drive.write_json(file_id, status)
        except Exception as error:
            print(f"Status Drive sementara tidak dapat diperbarui ({error}).", flush=True)

    def heartbeat(self, **details):
        if time.monotonic() - self.last_update >= 120:
            self.still_owner()
            self.status(self.state, **details)
            print(f"{self.phase} · {self.state} · {details}", flush=True)

    def artifact(self, phase, parent, *, promote=False):
        file_id = self.slots[phase]
        blob = self.drive.get(file_id)
        if blob is None:
            return None
        name = ARTIFACTS[phase]
        require(blob["parents"] == [self.folder] and not blob.get("trashed")
                and blob["name"] in {name, f".{name}.partial"}, f"Slot arsip Drive berbeda ({phase}).")
        props = blob["appProperties"]
        require(props["phase"] == phase and props["parent"] == (parent or "none")
                and all(re.fullmatch(r"[0-9a-f]{64}", props[key]) for key in ("sha256", "seal")),
                f"Manifest transfer Drive berbeda ({phase}).")
        size = int(props["bytes"])
        if blob["name"] != name:
            if not promote or not blob_matches(blob, size, props["sha256"]):
                return None
            self.still_owner()
            self.drive.rename(file_id, name)
            blob = self.drive.get(file_id)
        require(blob_matches(blob, size, props["sha256"]) and blob["name"] == name and size > 0
                and blob["appProperties"] == props and blob["parents"] == [self.folder],
                f"SHA-256 atau ukuran arsip Drive berbeda ({phase}).")
        return {"id": file_id, "file": name, "sha256": props["sha256"], "bytes": size, "seal": props["seal"]}

    def save(self, phase, parent, root, seal):
        self.status("uploading")
        with TemporaryDirectory(prefix=".transfer-", dir=self.work) as temporary:
            archive = Path(temporary) / ARTIFACTS[phase]
            pack(root, archive, self.resources)
            info = file_info(archive)
            props = {**info, "bytes": str(info["bytes"]), "seal": seal, "phase": phase, "parent": parent or "none"}
            self.resources.upload(self.drive, info["bytes"])
            self.still_owner()
            file_id = self.slots[phase]
            current = self.drive.get(file_id)
            partial = f".{archive.name}.partial"
            require(current is None or (current["name"] == partial and current["parents"] == [self.folder]),
                    f"Slot transfer sudah dipublikasikan ({phase}). Muat ulang Status.")
            self.drive.upload(file_id, self.folder, partial, props, archive,
                              lambda fraction: self.heartbeat(percent=round(fraction * 100, 1)), replace=current is not None)
            require(blob_matches(self.drive.get(file_id), info["bytes"], info["sha256"]),
                    f"SHA-256 atau ukuran unggahan Drive berbeda ({phase}).")
            saved = self.artifact(phase, parent, promote=True)
            require(saved and saved["sha256"] == info["sha256"] and saved["seal"] == seal,
                    f"Publikasi Drive belum terverifikasi ({phase}).")
            return saved

    def restore(self, phase, parent, info):
        local = self.checkpoints.root / phase
        if local.exists():
            meta = self.checkpoints.verify(phase, parent)
            require(digest(local / "checkpoint.json") == info["seal"], f"Checkpoint lokal berbeda dari Drive ({phase}).")
            return meta
        self.status("restoring")
        self.resources.staging(self.work, info["bytes"] * 2)
        with TemporaryDirectory(prefix=".restore-", dir=self.checkpoints.root) as temporary:
            temporary = Path(temporary)
            archive = temporary / "download.tar"
            with archive.open("wb") as stream:
                self.drive.download(info["id"], stream,
                                    lambda fraction: self.heartbeat(percent=round(fraction * 100, 1)))
            require(file_info(archive) == {key: info[key] for key in ("bytes", "sha256")},
                    f"SHA-256 unduhan checkpoint Drive berbeda ({phase}).")
            unpack(archive, temporary, phase)
            meta = Checkpoints(temporary, self.checkpoints.identity, retain=True).verify(phase, parent)
            require(meta and digest(temporary / phase / "checkpoint.json") == info["seal"],
                    f"Marker checkpoint hasil unduhan berbeda ({phase}).")
            require(publish_directory(temporary / phase, local), f"Workspace checkpoint sudah terisi ({phase}).")
            return meta

    def check_resources(self, *, staging=0):
        return self.resources.check(self.work, self.drive, local_credit=size_of(self.checkpoints.root) + size_of(self.dataset),
                                    drive_credit=sum(item["bytes"] for item in self.saved.values()), staging=staging)

    def worker(self, phase, config_path, lock_fd, staging=0):
        available = self.check_resources(staging=staging)["available_ram_bytes"]
        self.still_owner()
        self.status("running")
        print(f"Fase {phase} dimulai.", flush=True)
        command = [sys.executable, "-u", "-m", "simulator_v2.stage6", "--config", str(config_path),
                   "--output", str(self.dataset), "--checkpoint-dir", str(self.checkpoints.root)]
        if phase in PHASES:
            command.extend(("--stop-after", phase))
        log = self.work / f"{phase}.log"
        started = time.monotonic()
        with log.open("wb") as stream:
            # Retain the local lock if the notebook process dies before the worker exits.
            with subprocess.Popen(command, cwd=SOURCE, stdout=stream, stderr=subprocess.STDOUT,
                                  pass_fds=(lock_fd,)) as process:
                try:
                    monitor = psutil.Process(process.pid)
                    while True:
                        try:
                            code = process.wait(timeout=5)
                            break
                        except subprocess.TimeoutExpired:
                            try:
                                rss = monitor.memory_info().rss
                            except psutil.NoSuchProcess:
                                continue
                            self.resources.active(self.work, rss, available)
                            self.heartbeat(elapsed_seconds=round(time.monotonic() - started), worker_rss_bytes=rss)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
        if code != 0:
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 5000))
                print(stream.read().decode(errors="replace"), flush=True)
            raise RuntimeError(f"Fase {phase} berhenti dengan kode {code}. Log lokal {log}.")

    def run(self, config, config_path, *, recover=False):
        print(f"Folder Drive https://drive.google.com/drive/folders/{self.folder}", flush=True)
        with self.lock(recover) as lock_fd:
            try:
                self._run(config, config_path, lock_fd)
            except BaseException as error:
                failed = ("interrupted" if isinstance(error, KeyboardInterrupt)
                          else "save_failed" if self.state == "uploading" else "failed")
                self.status(failed, error=f"{type(error).__name__}: {error}"[:4000],
                            retry="Perbaiki penyebab dan jalankan RESUME dengan ID folder yang sama. "
                                  "Jika terkunci, putuskan runtime lama, lalu jalankan STOP/RECOVER.")
                print(f"Tertahan pada {self.phase}. Perbaiki penyebab, lalu gunakan RESUME dengan ID folder "
                      f"{self.folder}. Jika terkunci, putuskan runtime lama dan gunakan STOP/RECOVER.", flush=True)
                raise

    def _run(self, config, config_path, lock_fd):
        self.saved.clear()
        self.checkpoints.root.mkdir(exist_ok=True)
        for base, pattern in ((self.checkpoints.root, ".*-*"), (self.work, ".release-*"),
                              (self.work, ".transfer-*"), (self.work, ".stage6-publish-*")):
            for path in base.glob(pattern):
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)

        parent = None
        phases = tuple(ARTIFACTS)
        for index, phase in enumerate(phases):
            self.phase = phase
            self.state = "checking"
            info = self.artifact(phase, parent, promote=True)
            if info is None:
                for downstream in phases[index + 1:]:
                    require(self.drive.get(self.slots[downstream]) is None,
                            f"Arsip {downstream} kehilangan checkpoint induk {phase}.")
                break
            self.saved[phase] = info
            parent = info["seal"]
        if "dataset" in self.saved:
            self.complete(**self.previous_receipt())
            return

        self.check_resources()
        parent = None
        parquet = 0
        tar_overhead = 1024**2
        for phase in PHASES:
            self.phase = phase
            self.state = "checking"
            if phase in self.saved:
                meta = self.restore(phase, parent, self.saved[phase])
            else:
                root = self.checkpoints.root / phase
                meta = self.checkpoints.verify(phase, parent)
                if meta is None:
                    self.worker(phase, config_path, lock_fd)
                    meta = self.checkpoints.verify(phase, parent)
                require(meta is not None, f"Checkpoint lokal belum tersegel ({phase}).")
                self.saved[phase] = self.save(phase, parent, root, digest(root / "checkpoint.json"))
            self.status("checkpoint_verified")
            print(f"Checkpoint {phase} terverifikasi di Drive (SHA-256 {self.saved[phase]['sha256']}).", flush=True)
            parquet += sum(info["bytes"] for info in meta["partitions"].values())
            tar_overhead += 4096 * len(meta["partitions"])
            parent = self.saved[phase]["seal"]

        self.phase = "audit"
        if not self.dataset.exists():
            self.resources.upload(self.drive, parquet + tar_overhead)
            self.worker("audit", config_path, lock_fd, 2 * parquet + tar_overhead + LIVE_DISK_RESERVE)
        self.status("validating")
        receipt = verify_release(self.dataset, config, self.checkpoints.identity)
        release = {"version": VERSION, "folder_id": self.folder, **POLICY, **receipt,
                   "identity": self.checkpoints.identity, "checkpoints": self.saved}
        # Keep the audit receipt inside the reproducible archive without modifying the audited local dataset.
        self.phase = "dataset"
        with TemporaryDirectory(prefix=".release-", dir=self.work) as temporary:
            package_root = Path(temporary) / "dataset"
            shutil.copytree(self.dataset, package_root, copy_function=os.link)
            (package_root / "release_manifest.json").write_bytes(canonical(release))
            self.saved["dataset"] = self.save("dataset", parent, package_root,
                                              digest(package_root / "release_manifest.json"))
        self.complete(**receipt)

    def previous_receipt(self):
        try:
            status = self.drive.read_json(self.slots["status"]) or {}
        except Exception:
            return {}
        if status.get("dataset") != self.saved["dataset"]:
            return {}
        return {key: status[key] for key in ("gate_count", "financial_closes", "head", "hashes_sha256") if key in status}

    def complete(self, **receipt):
        self.phase = "dataset"
        self.status("completed", validation_status="passed", complete_independent_audit=True, **{
            key: value for key, value in receipt.items() if key not in {"validation_status", "complete_independent_audit"}})
        print(f"Dataset integritas terverifikasi di Drive (SHA-256 {self.saved['dataset']['sha256']}).", flush=True)

    def inspect(self):
        status = self.drive.read_json(self.slots["status"]) or {"status": "prepared"}
        verified = {}
        parent = None
        for phase in ARTIFACTS:
            info = self.artifact(phase, parent)
            if info is None:
                break
            verified[phase] = info
            parent = info["seal"]
        if "dataset" in verified:
            status.update(status="completed", validation_status="passed", complete_independent_audit=True)
        elif status["status"] == "completed":
            status.update(status="publication_unverified", validation_status="unverified",
                          complete_independent_audit=False)
        elif status["status"] in {"running", "restoring", "uploading", "validating", "checkpoint_verified"}:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(status["updated_at"])
            if age.total_seconds() > 900:
                status["status"] = "possibly_interrupted"
        return {**status, "dataset": verified.get("dataset"),
                "checkpoints": {phase: verified[phase] for phase in PHASES if phase in verified},
                "last_verified_checkpoint": next((phase for phase in reversed(PHASES) if phase in verified), None)}


def probe_drive(drive):
    folder = drive.folder(f"Feedlot_V2_Drive_Test_{uuid4().hex[:8]}")
    print(f"Folder uji https://drive.google.com/drive/folders/{folder}", flush=True)
    try:
        file_id, manifest_id = drive.ids(2)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "probe.bin"
            path.write_bytes(b"Feedlot V2: Drive upload + SHA-256 + download\n")
            info = file_info(path)
            drive.upload(file_id, folder, ".probe.partial", {"sha256": info["sha256"]}, path, lambda _: None)
            require(blob_matches(drive.get(file_id), info["bytes"], info["sha256"]),
                    "Uji SHA-256 unggahan Drive gagal.")
            drive.rename(file_id, "probe.bin")
            remote = drive.get(file_id)
            require(remote["name"] == "probe.bin" and blob_matches(remote, info["bytes"], info["sha256"]),
                    "Uji publikasi Drive gagal.")
            drive.write_json(manifest_id, info, folder=folder, name="probe.json")
            require(drive.read_json(manifest_id) == info, "Uji manifest Drive gagal.")
            with path.open("wb") as stream:
                drive.download(file_id, stream, lambda _: None)
            require(file_info(path) == info, "Uji SHA-256 unduhan Drive gagal.")
        print("Uji Drive lulus. Tidak ada simulasi yang dijalankan.", flush=True)
    finally:
        drive.trash(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "probe-drive", "status", *CONFIRMATIONS))
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="full reviewed Git commit")
    parser.add_argument("--folder", help="Google Drive attempt folder ID")
    parser.add_argument("--accept-integrity-only", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    try:
        if args.action in CONFIRMATIONS:
            require(args.accept_integrity_only and args.confirm == CONFIRMATIONS[args.action],
                    "Diperlukan persetujuan rilis integritas dan otorisasi tindakan eksplisit.")
        if args.action in {"status", "resume", "recover"}:
            checked_id(args.folder)
        config = production_config()
        identity = build_identity(config)
        require(re.fullmatch(r"[0-9a-f]{40}", args.commit) and identity["commit"] == args.commit,
                "Commit simulator berbeda dari pin notebook.")
        require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=SOURCE),
                "Checkout simulator memiliki perubahan. Gunakan sumber terpin yang bersih.")
        drive = connect()
        resources = Resources()
        args.local.mkdir(parents=True, exist_ok=True)
        if args.action == "probe-drive":
            probe_drive(drive)
        elif args.action == "preflight":
            print(json.dumps({"resources": resources.check(args.local, drive), "capacity": inspect_capacity(config),
                              "identity": identity}, indent=2))
        elif args.action == "start":
            resources.check(args.local, drive)
            inspect_capacity(config)
            Attempt.create(drive, args.local, identity, resources).run(config, CONFIG)
        else:
            attempt = Attempt.open(drive, args.folder, args.local, identity, resources,
                                   read_only=args.action == "status")
            if args.action == "status":
                print(json.dumps(attempt.inspect(), indent=2))
            else:
                attempt.run(config, CONFIG, recover=args.action == "recover")
    except (ValueError, KeyError, OSError, RuntimeError, HttpError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
