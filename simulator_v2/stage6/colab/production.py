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
from ..config import HERE, load
from ..export import digest
from ..recovery import Checkpoints, PHASES, file_info
from ..release_preflight import inspect as inspect_capacity
from .drive_storage import blob_matches, checked_id, connect, require
from .drive_status import (ARTIFACTS, POLICY, SIMULATOR_COMMIT, VERSION, archive_metadata,
                           attempt_manifest, claim_chain, inspect_drive)
from .production_audit import verify_dataset
from .production_resources import GIB, LIVE_DISK_RESERVE, Resources, discard_checkpoint_cache

CONFIG = HERE / "configs" / "stage7-production-15000.json"
CONFIG_SHA256 = "0fc8340ceebf54756876bfba10ace3dc097c8d10a8464083011437b6615ff375"
SOURCE = HERE.parents[1]
CONFIRMATIONS = {"start": "MULAI 15000", "resume": "LANJUT 15000", "recover": "PULIHKAN 15000"}
REGISTER_CONFIRMATION = "DAFTARKAN OPERATIONS"
FIRST_HEARTBEAT = 15
HEARTBEAT_INTERVAL = 120


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


def verify_checkout(source, expected):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    require(actual == expected, f"Commit checkout berbeda ({source}).")
    require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source),
            f"Checkout sumber memiliki perubahan ({source}).")


def simulator_identity(source, config_path):
    verify_checkout(source, SIMULATOR_COMMIT)
    return json.loads(subprocess.check_output([sys.executable, "-c", """
import json
from pathlib import Path
import sys
from simulator_v2.stage6.__main__ import build_identity, load
print(json.dumps(build_identity(load(Path(sys.argv[1])))))
""", str(config_path)], cwd=source))


def folder_url(folder):
    return f"https://drive.google.com/drive/folders/{folder}"


def size_of(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def pack(root, archive, resources, progress):
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
            progress()


def unpack(archive, destination, top, progress):
    with tarfile.open(archive, "r:") as stream:
        names = set()
        for member in stream:
            path = PurePosixPath(member.name)
            require(member.isfile() and not member.sparse and len(path.parts) >= 2 and path.parts[0] == top
                    and ".." not in path.parts and member.name == path.as_posix() and member.name not in names,
                    "Arsip checkpoint berisi path atau tipe berkas yang tidak diizinkan.")
            names.add(member.name)
            stream.extract(member, destination, filter="data")
            progress()


def verify_release(dataset, config, identity, progress):
    receipt = verify_dataset(dataset, config, identity, progress=progress)
    require(receipt["financial_closes"] == 48 and receipt["head"]["placements"] == 15_000,
            "Produksi memerlukan 48 close dan 15.000 placement baru.")
    return receipt


class Attempt:
    def __init__(self, drive, folder, manifest, local, identity, resources, simulator_source=SOURCE):
        self.drive, self.folder, self.manifest = drive, checked_id(folder), manifest
        self.work = local / folder
        self.checkpoints = Checkpoints(self.work / "checkpoints", identity, retain=True)
        self.dataset = self.work / "dataset"
        self.resources = resources
        self.simulator_source = simulator_source
        self.slots = manifest["slots"]
        self.saved = {}
        self.claim_id = self.next_claim = None
        self.phase = self.state = self.last_heartbeat = None
        self.execution_started = self.phase_started = time.monotonic()
        self.next_heartbeat = self.execution_started + FIRST_HEARTBEAT

    @classmethod
    def create(cls, drive, local, identity, resources, simulator_source=SOURCE):
        folder = drive.folder(f"Feedlot_V2_Production_15000_{datetime.now(timezone.utc):%Y%m%d-%H%M%S}_{uuid4().hex[:8]}")
        print(f"Folder Drive {folder_url(folder)}", flush=True)
        slots = dict(zip(("attempt", "status", "claim", *ARTIFACTS), drive.ids(6), strict=True))
        manifest = {"version": VERSION, "folder": folder, "created_at": now(), "identity": identity,
                    "release_policy": POLICY, "slots": slots}
        drive.write_json(slots["attempt"], manifest, folder=folder, name="attempt.json")
        return cls(drive, folder, manifest, local, identity, resources, simulator_source)

    @classmethod
    def open(cls, drive, folder, local, identity, resources, *, check_runtime=True, simulator_source=SOURCE):
        manifest = attempt_manifest(drive, folder)
        saved_identity = manifest["identity"]
        required = identity.keys() if check_runtime else identity.keys() - {"runtime", "numpy"}
        require(all(saved_identity[key] == identity[key] for key in required),
                "Manifest percobaan berbeda. Gunakan commit, konfigurasi, dan versi runtime semula.")
        return cls(drive, folder, manifest, local, saved_identity, resources, simulator_source)

    @contextmanager
    def lock(self, recover):
        self.work.mkdir(parents=True, exist_ok=True)
        with (self.work / ".lock").open("a") as local_lock:
            try:
                flock(local_lock, LOCK_EX | LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Percobaan masih berjalan di runtime ini.") from None
            latest, slot = claim_chain(self.drive, self.folder, self.slots["claim"])
            if latest["state"] == "unreleased":
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

    def begin_phase(self, phase):
        if self.phase != phase:
            self.phase, self.phase_started = phase, time.monotonic()

    def elapsed(self):
        moment = time.monotonic()
        return {"phase_elapsed_seconds": round(moment - self.phase_started),
                "execution_elapsed_seconds": round(moment - self.execution_started)}

    def latest_checkpoint(self):
        return next((phase for phase in reversed(PHASES) if phase in self.saved), None)

    def status(self, state, *, pulse=False, **details):
        self.state = state
        self.next_heartbeat = time.monotonic() + (HEARTBEAT_INTERVAL if pulse else FIRST_HEARTBEAT)
        status = {"folder_id": self.folder, "run_id": self.checkpoints.identity["run_id"],
                  "code_sha": self.checkpoints.identity["commit"], "status": state, "phase": self.phase,
                  "updated_at": now(), "checkpoints": {phase: self.saved[phase] for phase in PHASES if phase in self.saved},
                  "last_verified_checkpoint": self.latest_checkpoint(), "claim_id": self.claim_id,
                  "last_heartbeat": self.last_heartbeat, "dataset": self.saved.get("dataset"),
                  **self.elapsed(), **POLICY, **details}
        try:
            file_id = self.slots["status"]
            if self.drive.get(file_id) is None:
                self.drive.write_json(file_id, status, folder=self.folder, name="status.json")
            else:
                self.drive.write_json(file_id, status)
        except Exception as error:
            print(f"Status Drive sementara tidak dapat diperbarui ({error}).", flush=True)

    def heartbeat(self, **details):
        if time.monotonic() >= self.next_heartbeat:
            elapsed = self.elapsed()
            self.last_heartbeat = {"at": now(), "phase": self.phase, "state": self.state, **elapsed, **details}
            print(f"Heartbeat {self.last_heartbeat['at']} · {self.phase} · {self.state} · "
                  f"fase {elapsed['phase_elapsed_seconds']} detik · eksekusi {elapsed['execution_elapsed_seconds']} detik · "
                  f"checkpoint Drive terakhir {self.latest_checkpoint() or 'belum ada'}", flush=True)
            self.still_owner()
            self.status(self.state, pulse=True, **details)

    def artifact(self, phase, parent, *, promote=False):
        file_id = self.slots[phase]
        blob = self.drive.get(file_id)
        if blob is None:
            return None
        info, published, checksum = archive_metadata(blob, self.folder, file_id, phase, parent)
        if not published:
            if not promote or not checksum:
                return None
            self.still_owner()
            self.drive.rename(file_id, info["file"])
            blob = self.drive.get(file_id)
            require(blob is not None, f"Arsip Drive belum tersedia ({phase}).")
            confirmed, published, checksum = archive_metadata(blob, self.folder, file_id, phase, parent)
            require(confirmed == info, f"Metadata arsip Drive berubah setelah publikasi ({phase}).")
        require(published and checksum,
                f"SHA-256 atau ukuran arsip Drive berbeda ({phase}).")
        return info

    def save(self, phase, parent, root, seal):
        print(f"Menyiapkan arsip {phase} untuk verifikasi Drive.", flush=True)
        self.status("uploading")
        with TemporaryDirectory(prefix=".transfer-", dir=self.work) as temporary:
            archive = Path(temporary) / ARTIFACTS[phase]
            pack(root, archive, self.resources, self.heartbeat)
            return self.publish_archive(phase, parent, archive, file_info(archive), seal)

    def publish_archive(self, phase, parent, archive, info, seal):
        file_id = self.slots[phase]
        partial = f".{ARTIFACTS[phase]}.partial"
        props = {"bytes": str(info["bytes"]), "sha256": info["sha256"], "seal": seal,
                 "phase": phase, "parent": parent or "none"}
        self.still_owner()
        current = self.drive.get(file_id)
        staged = False
        if current is not None:
            found, published, checksum = archive_metadata(current, self.folder, file_id, phase, parent)
            require(not published, f"Slot transfer sudah dipublikasikan ({phase}). Muat ulang Status.")
            staged = checksum and all(found[key] == value for key, value in info.items()) and found["seal"] == seal
            require(not checksum or staged, f"Slot sementara {phase} memuat arsip terverifikasi yang berbeda.")
        if not staged:
            self.resources.upload(self.drive, info["bytes"])
            self.drive.upload(file_id, self.folder, partial, props, archive, self.transfer_progress,
                              replace=current is not None)
        current = self.drive.get(file_id)
        require(blob_matches(current, info["bytes"], info["sha256"]) and current["appProperties"] == props
                and current["name"] == partial and current["parents"] == [self.folder],
                f"SHA-256, ukuran, atau metadata unggahan Drive berbeda ({phase}).")
        saved = self.artifact(phase, parent, promote=True)
        require(saved and all(saved[key] == value for key, value in info.items()) and saved["seal"] == seal,
                f"Publikasi Drive belum terverifikasi ({phase}).")
        return saved

    def transfer_progress(self, fraction):
        self.heartbeat(percent=round(fraction * 100, 1))

    def register_operations(self, rescue_id, size, sha, *, local_tar=None, recover=False):
        phase = "operations"
        require(checked_id(rescue_id) not in self.slots.values() and size > 0 and re.fullmatch(r"[0-9a-f]{64}", sha),
                "ID, ukuran, atau SHA-256 arsip rescue tidak valid.")
        expected = {"bytes": size, "sha256": sha}
        with self.lock(recover):
            self.begin_phase(phase)
            require(blob_matches(self.drive.get(rescue_id), size, sha),
                    "Ukuran atau SHA-256 arsip rescue Drive berbeda dari nilai yang diberikan.")
            official = self.artifact(phase, None)
            if official is not None:
                require(all(official[key] == value for key, value in expected.items()),
                        "Checkpoint operasi resmi sudah ada dengan isi berbeda. Publikasi dihentikan.")
            else:
                require(all(self.drive.get(self.slots[key]) is None for key in ("finance", "dataset")),
                        "Ada arsip turunan sebelum checkpoint operasi terverifikasi. Periksa Status.")
                self.status("registering", rescue_file_id=rescue_id)
                try:
                    official = self._register_operations(rescue_id, expected, local_tar)
                except BaseException as error:
                    outcome = "interrupted" if isinstance(error, KeyboardInterrupt) else "save_failed"
                    self.status(outcome, rescue_file_id=rescue_id, error=f"{type(error).__name__}: {error}"[:4000])
                    raise
                self.saved[phase] = official
                self.status("checkpoint_verified", rescue_file_id=rescue_id)
            print(f"OPERATIONS RESMI TERVERIFIKASI | {official['id']} | {size} byte | SHA-256 {sha}", flush=True)
            return official

    def _register_operations(self, rescue_id, expected, local_tar):
        phase = "operations"
        size = expected["bytes"]
        self.checkpoints.root.mkdir(exist_ok=True)
        existing = self.checkpoints.verify(phase, None)
        # A fresh runtime needs space for the TAR plus an extracted native checkpoint.
        self.resources.staging(self.work, size * (int(local_tar is None) + 1))
        with TemporaryDirectory(prefix=".rescue-register-", dir=self.work) as temporary:
            staging = Path(temporary)
            if local_tar is None:
                archive = staging / "rescue.tar"
                print(f"Mengunduh arsip rescue Drive ({size} byte).", flush=True)
                with archive.open("xb") as stream:
                    self.drive.download(rescue_id, stream, self.transfer_progress)
            else:
                archive = Path(local_tar)
            require(file_info(archive) == expected, "Ukuran atau SHA-256 TAR rescue lokal berbeda.")
            print("Memeriksa identitas, segel, dan isi checkpoint rescue.", flush=True)
            unpack(archive, staging, phase, self.heartbeat)
            verified = Checkpoints(staging, self.checkpoints.identity, retain=True).verify(phase, None)
            require(verified is not None, "Checkpoint rescue operations tidak ditemukan.")
            restored = staging / phase
            seal = digest(restored / "checkpoint.json")
            local = self.checkpoints.root / phase
            if existing is not None:
                require(digest(local / "checkpoint.json") == seal,
                        "Segel checkpoint lokal asli berbeda dari arsip rescue. Tidak ada berkas yang diganti.")
            else:
                # Keep proven local state available even if publishing to Drive fails.
                require(publish_directory(restored, local), "Checkpoint lokal sudah terisi saat registrasi.")
            print("Menerbitkan byte TAR rescue ke slot operations resmi.", flush=True)
            return self.publish_archive(phase, None, archive, expected, seal)

    def restore(self, phase, parent, info):
        local = self.checkpoints.root / phase
        if local.exists():
            meta = self.checkpoints.verify(phase, parent)
            require(digest(local / "checkpoint.json") == info["seal"], f"Checkpoint lokal berbeda dari Drive ({phase}).")
            discard_checkpoint_cache(local)
            return meta
        print(f"Memulihkan checkpoint {phase} dari Drive.", flush=True)
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
            unpack(archive, temporary, phase, self.heartbeat)
            archive.unlink()
            meta = Checkpoints(temporary, self.checkpoints.identity, retain=True).verify(phase, parent)
            require(meta and digest(temporary / phase / "checkpoint.json") == info["seal"],
                    f"Marker checkpoint hasil unduhan berbeda ({phase}).")
            discard_checkpoint_cache(temporary / phase, flush=True)
            require(publish_directory(temporary / phase, local), f"Workspace checkpoint sudah terisi ({phase}).")
            return meta

    def discard_saved_checkpoint_cache(self):
        for phase in PHASES:
            if phase in self.saved:
                discard_checkpoint_cache(self.checkpoints.root / phase)

    def check_resources(self, *, staging=0):
        return self.resources.check(self.work, self.drive, local_credit=size_of(self.checkpoints.root) + size_of(self.dataset),
                                    drive_credit=sum(item["bytes"] for item in self.saved.values()), staging=staging,
                                    reclaim=self.discard_saved_checkpoint_cache if self.saved else None)

    def worker(self, phase, config_path, lock_fd, staging=0):
        print(f"Memeriksa sumber daya fase {phase}.", flush=True)
        resources = self.check_resources(staging=staging)
        available = resources["available_ram_bytes"]
        raw = resources.get("cgroup_headroom_bytes")
        details = f" (headroom cgroup mentah {raw / GIB:.2f} GiB)" if raw is not None else ""
        print(f"RAM efektif untuk {phase}: {available / GIB:.2f} GiB{details}.", flush=True)
        self.still_owner()
        command = [sys.executable, "-u", "-m", "simulator_v2.stage6", "--config", str(config_path),
                   "--output", str(self.dataset), "--checkpoint-dir", str(self.checkpoints.root)]
        if phase in PHASES:
            command.extend(("--stop-after", phase))
        log = self.work / f"{phase}.log"
        with log.open("wb") as stream:
            # Retain the local lock if the notebook process dies before the worker exits.
            with subprocess.Popen(command, cwd=self.simulator_source, stdout=stream, stderr=subprocess.STDOUT,
                                  pass_fds=(lock_fd,)) as process:
                try:
                    started = time.monotonic()
                    print(f"Fase {phase} dimulai.", flush=True)
                    self.status("running")
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

    def run(self, config, config_path, *, recover=False, require_operations=False):
        self.execution_started = self.phase_started = time.monotonic()
        self.last_heartbeat = None
        print("Memeriksa klaim Drive dan checkpoint yang sudah ada.", flush=True)
        with self.lock(recover) as lock_fd:
            try:
                self._run(config, config_path, lock_fd, require_operations=require_operations)
            except BaseException as error:
                failed = ("interrupted" if isinstance(error, KeyboardInterrupt)
                          else "save_failed" if self.state == "uploading" else "failed")
                self.status(failed, error=f"{type(error).__name__}: {error}"[:4000],
                            retry="Perbaiki penyebab dan jalankan RESUME dengan ID folder yang sama. "
                                  "Jika terkunci, putuskan runtime lama, lalu jalankan STOP/RECOVER.")
                print(f"Tertahan pada {self.phase}. Perbaiki penyebab, lalu gunakan RESUME dengan ID folder "
                      f"{self.folder}. Jika terkunci, putuskan runtime lama dan gunakan STOP/RECOVER.", flush=True)
                raise

    def _run(self, config, config_path, lock_fd, *, require_operations=False):
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
            self.begin_phase(phase)
            self.state = "checking"
            must_be_published = phase == "operations" and require_operations
            info = self.artifact(phase, parent, promote=not must_be_published)
            if info is None:
                require(not must_be_published,
                        "Checkpoint operations resmi belum terverifikasi. Jalankan Registrasi Rescue dahulu.")
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
            self.begin_phase(phase)
            self.status("checking")
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

        self.begin_phase("audit")
        if not self.dataset.exists():
            self.resources.upload(self.drive, parquet + tar_overhead)
            self.worker("audit", config_path, lock_fd, 2 * parquet + tar_overhead + LIVE_DISK_RESERVE)
        print("Memverifikasi inventaris hasil audit dan SHA-256 partisi.", flush=True)
        self.status("validating")
        receipt = verify_release(self.dataset, config, self.checkpoints.identity, self.heartbeat)
        release = {"version": VERSION, "folder_id": self.folder, **POLICY, **receipt,
                   "identity": self.checkpoints.identity, "checkpoints": self.saved}
        # Keep the audit receipt inside the reproducible archive without modifying the audited local dataset.
        self.begin_phase("dataset")
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
        self.begin_phase("dataset")
        self.status("completed", validation_status="passed", complete_independent_audit=True, **{
            key: value for key, value in receipt.items() if key not in {"validation_status", "complete_independent_audit"}})
        print(f"Dataset integritas terverifikasi di Drive (SHA-256 {self.saved['dataset']['sha256']}).", flush=True)

    def inspect(self):
        return inspect_drive(self.drive, self.folder, self.manifest)


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
    parser.add_argument("action", choices=("preflight", "probe-drive", "status", "register-operations", *CONFIRMATIONS))
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="full reviewed monitoring Git commit")
    parser.add_argument("--simulator-source", required=True, type=Path, help="checkout of the original simulator commit")
    parser.add_argument("--folder", help="Google Drive attempt folder ID")
    parser.add_argument("--accept-integrity-only", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--rescue-id", help="independent rescue archive Drive file ID")
    parser.add_argument("--rescue-bytes", type=int)
    parser.add_argument("--rescue-sha256")
    parser.add_argument("--local-rescue-tar", type=Path, help="skip Drive download using a byte-identical local TAR")
    parser.add_argument("--recover-claim", action="store_true", help="take over a stale claim for registration")
    parser.add_argument("--require-operations", action="store_true", help="allow resume only from published operations")
    args = parser.parse_args()
    try:
        if args.action in CONFIRMATIONS:
            require(args.accept_integrity_only and args.confirm == CONFIRMATIONS[args.action],
                    "Diperlukan persetujuan rilis integritas dan otorisasi tindakan eksplisit.")
        if args.action == "register-operations":
            require(args.confirm == REGISTER_CONFIRMATION, "Registrasi memerlukan otorisasi eksplisit.")
            require(args.rescue_bytes and args.rescue_bytes > 0 and args.rescue_sha256
                    and re.fullmatch(r"[0-9a-f]{64}", args.rescue_sha256), "Berikan ukuran dan SHA-256 rescue.")
            checked_id(args.rescue_id)
        if args.action in {"status", "resume", "recover", "register-operations"}:
            checked_id(args.folder)
        if args.action in {"resume", "recover", "register-operations"}:
            print(f"Folder Drive {folder_url(args.folder)}", flush=True)
        print(f"{args.action.upper()} · memeriksa sumber dan koneksi Drive.", flush=True)
        config = production_config()
        require(re.fullmatch(r"[0-9a-f]{40}", args.commit), "Pin commit monitoring tidak valid.")
        verify_checkout(SOURCE, args.commit)
        simulator_source = args.simulator_source.resolve()
        config_path = simulator_source / CONFIG.relative_to(SOURCE)
        require(digest(config_path) == CONFIG_SHA256, "SHA-256 konfigurasi simulator berbeda.")
        identity = simulator_identity(simulator_source, config_path)
        drive = connect(read_only=args.action in {"preflight", "status"})
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
            Attempt.create(drive, args.local, identity, resources, simulator_source).run(config, config_path)
        else:
            attempt = Attempt.open(drive, args.folder, args.local, identity, resources,
                                   check_runtime=args.action in {"resume", "recover"}, simulator_source=simulator_source)
            if args.action == "status":
                print(json.dumps(attempt.inspect(), indent=2))
            elif args.action == "register-operations":
                attempt.register_operations(args.rescue_id, args.rescue_bytes, args.rescue_sha256,
                                            local_tar=args.local_rescue_tar, recover=args.recover_claim)
            else:
                attempt.run(config, config_path, recover=args.action == "recover",
                            require_operations=args.require_operations)
    except (ValueError, KeyError, OSError, RuntimeError, HttpError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
