"""Resource floors and Linux cgroup headroom for Stage 7 Colab production."""

from pathlib import Path
import re
import shutil

from .drive_storage import require
from .production_plan import FLOORS_GIB, GIB

TRANSFER_RESERVE = GIB // 2
LIVE_DISK_RESERVE = 2 * GIB
LIVE_RAM_RESERVE = 2 * GIB


def cgroup_headroom(groups, mounts):
    """Take the tightest finite limit over the visible v1/v2 memory hierarchies."""
    limits = []
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
                        limits.append(max(0, int(value) - int(usage.read_text())))
                if current == point:
                    break
    return min(limits, default=None)


def memory():
    lines = Path("/proc/meminfo").read_text().splitlines()
    host = int(next(row.split()[1] for row in lines if row.startswith("MemAvailable:"))) * 1024
    limited = cgroup_headroom(Path("/proc/self/cgroup").read_text(), Path("/proc/self/mountinfo").read_text())
    return {"host_available_bytes": host, "cgroup_headroom_bytes": limited,
            "available_ram_bytes": host if limited is None else min(host, limited)}


class Resources:
    def __init__(self, floors=None):
        self.floors = floors if floors is not None else {name: value * GIB for name, value in FLOORS_GIB.items()}

    def check(self, root, drive, *, local_credit=0, drive_credit=0, staging=0):
        info = {**memory(), "local_free_bytes": shutil.disk_usage(root).free,
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
