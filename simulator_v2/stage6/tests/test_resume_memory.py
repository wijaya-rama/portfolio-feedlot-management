"""Check the Finance RAM gate across mocked cgroups and a tiny sealed checkpoint."""

from pathlib import Path

import pytest

from simulator_v2.stage6.colab import production as prod, production_resources as resources
from simulator_v2.stage6.tests.test_drive_rescue import rescue_setup  # noqa: F401
from simulator_v2.stage6.tests.test_production_colab import attempt_setup, reopen  # noqa: F401

GIB = resources.GIB


def v2_stats(directory, *, used, limit=50 * GIB, **stats):
    (directory / "memory.max").write_text(str(limit))
    (directory / "memory.current").write_text(str(used))
    (directory / "memory.stat").write_text("\n".join(f"{key} {value}" for key, value in stats.items()))


def test_inactive_cache_adjusts_016_gib_raw_but_keeps_ancestor_cap(tmp_path):
    child = tmp_path / "job"
    child.mkdir()
    raw = 16 * GIB // 100
    v2_stats(child, used=50 * GIB - raw, file=38 * GIB, inactive_file=37 * GIB,
             shmem=GIB, file_mapped=GIB, file_dirty=GIB, file_writeback=GIB)
    mounts = f"1 0 0:1 / {tmp_path} ro - cgroup2 cgroup rw"
    assert resources.cgroup_headroom("0::/job", mounts) == (raw, raw + 34 * GIB)
    v2_stats(tmp_path, used=43 * GIB, file=16 * GIB, inactive_file=16 * GIB,
             shmem=0, file_mapped=0, file_dirty=0, file_writeback=0)
    assert resources.cgroup_headroom("0::/job", mounts) == (raw, 23 * GIB)


def test_v1_uses_hierarchical_counters_and_does_not_credit_active_cache(tmp_path):
    (tmp_path / "memory.limit_in_bytes").write_text(str(36 * GIB))
    (tmp_path / "memory.usage_in_bytes").write_text(str(30 * GIB))
    stats = tmp_path / "memory.stat"
    stats.write_text("\n".join(f"{key} {value * GIB}" for key, value in {
        "inactive_file": 99, "total_cache": 27, "total_inactive_file": 24, "total_shmem": 10,
        "total_mapped_file": 4, "total_dirty": 4, "total_writeback": 1, "total_active_file": 20,
    }.items()))
    mounts = f"1 0 0:1 / {tmp_path} ro - cgroup memory rw,memory"
    assert resources.cgroup_headroom("1:memory:/", mounts) == (6 * GIB, 14 * GIB)
    # With missing or malformed counters, keep the raw finite limit.
    stats.write_text("total_inactive_file 99999999999\ntotal_dirty unknown\n")
    assert resources.cgroup_headroom("1:memory:/", mounts) == (6 * GIB, 6 * GIB)


def test_above_hard_limit_does_not_inflate_adjusted_capacity(tmp_path):
    v2_stats(tmp_path, used=52 * GIB, file=25 * GIB, inactive_file=25 * GIB,
             shmem=0, file_mapped=0, file_dirty=0, file_writeback=0)
    mounts = f"1 0 0:1 / {tmp_path} ro - cgroup2 cgroup rw"
    assert resources.cgroup_headroom("0::/", mounts) == (0, 23 * GIB)


def test_rechecks_after_advice_without_waiving_memory_or_worker_rss(tmp_path, monkeypatch):
    guard = resources.Resources({"ram": 24 * GIB, "local_disk": 0, "drive": 0})
    effective = 16 * GIB

    def memory():
        return {"available_ram_bytes": effective}

    def reclaim(remaining):
        nonlocal effective
        effective = remaining

    monkeypatch.setattr(resources, "memory", memory)
    drive = type("Drive", (), {"free_bytes": lambda self: 0})()
    with pytest.raises(ValueError, match="RAM efektif kurang"):
        guard.check(tmp_path, drive, reclaim=lambda: reclaim(23 * GIB))
    info = guard.check(tmp_path, drive, reclaim=lambda: reclaim(36 * GIB))
    assert info["available_ram_bytes"] == 36 * GIB
    with pytest.raises(ValueError, match="mendekati batas runtime"):
        guard.active(tmp_path, 35 * GIB, info["available_ram_bytes"])
    reclaim(GIB)
    with pytest.raises(ValueError, match="mendekati batas runtime"):
        guard.active(tmp_path, GIB, info["available_ram_bytes"])


def test_cache_advice_is_scoped_to_local_checkpoint_files(tmp_path, monkeypatch):
    root = tmp_path / "operations"
    root.mkdir()
    marker = root / "checkpoint.json"
    marker.write_bytes(b"marker")
    other = tmp_path / "rescue.tar"
    other.write_bytes(b"rescue")
    (root / "outside-link").symlink_to(other)
    seen = []

    def advise(fd, offset, length, advice):
        assert offset == length == 0
        assert advice == resources.os.POSIX_FADV_DONTNEED
        seen.append(Path(f"/proc/self/fd/{fd}").resolve())

    monkeypatch.setattr(resources.os, "posix_fadvise", advise)
    resources.discard_checkpoint_cache(root, flush=True)
    assert seen == [marker]
    assert marker.read_bytes() == b"marker" and other.read_bytes() == b"rescue"


def test_fresh_resume_reclaims_cache_after_native_verification_and_starts_finance(rescue_setup, tmp_path,
                                                                                monkeypatch, capsys):
    attempt, path, config, drive, _, _, info, rescue_id = rescue_setup
    attempt.register_operations(rescue_id, info["bytes"], info["sha256"])
    fresh = reopen(attempt, tmp_path / "fresh")
    fresh.resources.floors = {"ram": 24 * GIB, "local_disk": 0, "drive": 0}
    raw = 36 * GIB
    original_verify = prod.Checkpoints.verify
    events = []

    def verify(self, phase, parent):
        nonlocal raw
        checked = original_verify(self, phase, parent)
        if phase == "operations" and self.root.name.startswith(".restore-"):
            assert checked is not None
            events.append("archive-and-native-checkpoint-verified")
            raw = 16 * GIB // 100
        return checked

    def advise(root, *, flush=False):
        nonlocal raw
        if flush and root.name == "operations":
            assert (root / "checkpoint.json").is_file()
            assert not (root.parent / "download.tar").exists()
            assert events == ["archive-and-native-checkpoint-verified"]
            events.append("verified-operations-cache-released")
            raw = 36 * GIB

    def memory():
        return {"host_available_bytes": 49 * GIB, "cgroup_headroom_bytes": raw, "available_ram_bytes": raw}

    monkeypatch.setattr(prod.Checkpoints, "verify", verify)
    monkeypatch.setattr(prod, "discard_checkpoint_cache", advise)
    monkeypatch.setattr(resources, "memory", memory)
    fresh.run(config, path, require_operations=True)
    assert events == ["archive-and-native-checkpoint-verified", "verified-operations-cache-released"]
    assert drive.events == ["checkpoint-operations.tar", "finance", "checkpoint-finance.tar",
                            "audit", "dataset-integrity-only.tar"]
    assert "RAM efektif untuk finance: 36.00 GiB" in capsys.readouterr().out
