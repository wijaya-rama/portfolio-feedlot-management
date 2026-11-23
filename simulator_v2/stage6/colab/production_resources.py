"""Resource floors and Linux cgroup headroom for Stage 7 Colab production."""

import os
from pathlib import Path
import re
import shutil

from .drive_storage import require
from .production_plan import FLOORS_GIB, GIB

TRANSFER_RESERVE = GIB // 2
LIVE_DISK_RESERVE = 2 * GIB
LIVE_RAM_RESERVE = 2 * GIB


def reclaimable_file_cache(directory, version):
    """Credit clean, inactive file cache only. Missing counters fall back to zero."""
    try:
        stats = {key: int(value) for key, value in (row.split() for row in
                                                   (directory / "memory.stat").read_text().splitlines())}
        if version == "cgroup2":
            inactive, cached, shared, mapped, dirty, writeback = (stats[key] for key in (
                "inactive_file", "file", "shmem", "file_mapped", "file_dirty", "file_writeback"))
        else:
            inactive, cached, shared, mapped, dirty, writeback = (stats[f"total_{key}"] for key in (
                "inactive_file", "cache", "shmem", "mapped_file", "dirty", "writeback"))
    except (OSError, KeyError, ValueError):
        return 0
    if min(inactive, cached, shared, mapped, dirty, writeback) < 0:
        return 0
    return max(0, min(inactive, cached - shared) - mapped - dirty - writeback)


def cgroup_headroom(groups, mounts):
    """Return raw and cache-adjusted headroom, each bounded by every visible hard limit."""
    raw, effective = [], []
    for row in groups.splitlines():
        _, controllers, group = row.split(":", 2)
        if controllers and "memory" not in controllers.split(","):
            continue
        fs = "cgroup" if controllers else "cgroup2"
        for mount in mounts.splitlines():
            before, after = mount.split(" - ", 1)
            kind, _, options = after.split()
            if kind != fs or (fs == "cgroup" and "memory" not in options.split(",")):
                continue
            root, point = (Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), path))
                           for path in before.split()[3:5])
            group_path = Path(group)
            relative = group_path.relative_to(root) if group_path.is_relative_to(root) else group_path.relative_to("/")
            directory = point / relative
            # In a cgroup namespace the mount point can itself represent the reported root.
            if not directory.is_dir():
                directory = point
            names = ("memory.max", "memory.current") if fs == "cgroup2" else (
                "memory.limit_in_bytes", "memory.usage_in_bytes",
            )
            for current in (directory, *directory.parents):
                maximum, usage = (current / name for name in names)
                if maximum.is_file() and usage.is_file():
                    value = maximum.read_text().strip()
                    if value != "max" and int(value) < 2**60:
                        used = int(usage.read_text())
                        remaining = int(value) - used
                        cache = min(used, reclaimable_file_cache(current, fs))
                        raw.append(max(0, remaining))
                        effective.append(max(0, remaining + cache))
                if current == point:
                    break
    return min(raw, default=None), min(effective, default=None)


def memory():
    lines = Path("/proc/meminfo").read_text().splitlines()
    host = int(next(row.split()[1] for row in lines if row.startswith("MemAvailable:"))) * 1024
    raw, effective = cgroup_headroom(Path("/proc/self/cgroup").read_text(), Path("/proc/self/mountinfo").read_text())
    return {"host_available_bytes": host, "cgroup_headroom_bytes": raw, "cgroup_effective_headroom_bytes": effective,
            "available_ram_bytes": host if effective is None else min(host, effective)}


def discard_checkpoint_cache(root, *, flush=False):
    """Advise on regular files in this local checkpoint only, without changing payloads."""
    if not hasattr(os, "posix_fadvise") or root.is_symlink():
        return
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            if flush:
                os.fdatasync(stream.fileno())
            try:
                os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                # Advice is optional. Resource checks still enforce the actual floor.
                continue


class Resources:
    def __init__(self, floors=None):
        self.floors = floors if floors is not None else {name: value * GIB for name, value in FLOORS_GIB.items()}

    def check(self, root, drive, *, local_credit=0, drive_credit=0, staging=0, reclaim=None):
        ram = memory()
        if ram["available_ram_bytes"] < self.floors["ram"] and reclaim is not None:
            reclaim()
            ram = memory()
        info = {**ram, "local_free_bytes": shutil.disk_usage(root).free,
                "drive_free_bytes": drive.free_bytes()}
        for key, actual, need in (
            ("RAM efektif", info["available_ram_bytes"], self.floors["ram"]),
            ("disk lokal", info["local_free_bytes"], max(staging, self.floors["local_disk"] - local_credit)),
            ("Google Drive", info["drive_free_bytes"], max(0, self.floors["drive"] - drive_credit)),
        ):
            require(actual >= need, f"{key} kurang: tersedia {actual / GIB:.2f} GiB, perlu {need / GIB:.2f} GiB.")
        return info

    def staging(self, root, amount):
        require(shutil.disk_usage(root).free >= amount + LIVE_DISK_RESERVE, "Disk lokal kurang untuk staging arsip.")

    def upload(self, drive, amount):
        require(drive.free_bytes() >= amount + TRANSFER_RESERVE, "Kuota Drive kurang untuk mengunggah arsip.")

    def active(self, root, rss, start_ram):
        available = memory()["available_ram_bytes"]
        require(available >= LIVE_RAM_RESERVE and rss <= start_ram - LIVE_RAM_RESERVE,
                "Fase dihentikan karena RAM mendekati batas runtime.")
        require(shutil.disk_usage(root).free >= LIVE_DISK_RESERVE, "Fase dihentikan karena disk lokal hampir penuh.")
