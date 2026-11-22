"""Focused notebook stream and Drive monitoring regressions."""

from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import subprocess
import sys
from types import SimpleNamespace

import pytest

from simulator_v2.stage6.colab import notebook_stream, production as prod
from simulator_v2.stage6.tests.test_production_colab import attempt_setup, reopen  # noqa: F401


def test_inherited_fds_bypass_kernel_stdout_but_bridge_renders_before_exit(tmp_path, capfd):
    gate = tmp_path / "heartbeat-rendered"
    snippet = """
from pathlib import Path
import sys
import time
print("Folder Drive https://drive.google.com/drive/folders/example", flush=True)
print("Fase operations dimulai.", flush=True)
print("Heartbeat · operations · 15 detik", file=sys.stderr, flush=True)
gate = Path(sys.argv[1])
deadline = time.monotonic() + 2
while not gate.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
sys.exit(0 if gate.exists() else 4)
"""
    command = [sys.executable, "-u", "-c", snippet, str(gate)]

    # An output hook on Python stdout receives nothing from the old inherited
    # FDs, even though the child's unbuffered stdout and stderr contain data.
    captured = StringIO()
    with redirect_stdout(captured), subprocess.Popen(command, start_new_session=True) as old:
        assert old.wait(timeout=5) == 4
    inherited = capfd.readouterr()
    assert captured.getvalue() == ""
    assert "Fase operations dimulai" in inherited.out
    assert "Heartbeat" in inherited.err

    class CellOutput(StringIO):
        def write(self, value):
            written = super().write(value)
            if "Heartbeat · operations" in self.getvalue():
                gate.touch()
            return written

    rendered = CellOutput()
    with redirect_stdout(rendered):
        assert notebook_stream.stream_command(command) == 0
    assert "Folder Drive" in rendered.getvalue()
    assert "Fase operations dimulai" in rendered.getvalue()
    assert "Heartbeat · operations · 15 detik" in rendered.getvalue()


def test_cell_interrupt_relays_shutdown_output(monkeypatch):
    selector = notebook_stream.DefaultSelector

    class InterruptAfterFirstRead(selector):
        polls = 0

        def select(self, timeout=None):
            self.polls += 1
            if self.polls == 2:
                raise KeyboardInterrupt
            return super().select(timeout)

    monkeypatch.setattr(notebook_stream, "DefaultSelector", InterruptAfterFirstRead)
    snippet = """
import signal
import sys
import time
def stop(*_):
    print("status interrupted; claim released", flush=True)
    sys.exit(130)
signal.signal(signal.SIGINT, stop)
print("ready", flush=True)
time.sleep(5)
"""
    captured = StringIO()
    with redirect_stdout(captured), pytest.raises(KeyboardInterrupt):
        notebook_stream.stream_command([sys.executable, "-u", "-c", snippet], interrupt_grace=3)
    assert "ready" in captured.getvalue()
    assert "status interrupted; claim released" in captured.getvalue()


def test_two_manual_interruptions_leave_visible_heartbeat_and_released_claim(
    attempt_setup, tmp_path, monkeypatch, capsys,
):
    attempt, config_path, config, drive = attempt_setup
    moment = 0

    class LongWorker:
        pid = 123

        def __init__(self, command, **kwargs):
            self.command = command
            self.calls = 0
            self.active = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            assert not self.active

        def wait(self, timeout):
            nonlocal moment
            if not self.active:
                return -15
            self.calls += 1
            if self.calls <= 27:
                moment += timeout
                raise subprocess.TimeoutExpired(self.command, timeout)
            raise KeyboardInterrupt

        def poll(self):
            return None if self.active else -15

        def terminate(self):
            self.active = False

    monkeypatch.setattr(prod, "time", SimpleNamespace(monotonic=lambda: moment))
    monkeypatch.setattr(prod.subprocess, "Popen", LongWorker)
    monkeypatch.setattr(prod.psutil, "Process", lambda _: SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=1)))
    monkeypatch.setattr(attempt.resources, "active", lambda *args: None)
    for count, run in enumerate((attempt, reopen(attempt, tmp_path / "new-runtime")), 1):
        with pytest.raises(KeyboardInterrupt):
            run.run(config, config_path)
        shown = run.inspect()
        assert shown["recorded_status"] == "interrupted"
        assert shown["phase"] == "operations"
        assert shown["error"].startswith("KeyboardInterrupt")
        assert shown["claim_lock"]["state"] == "released"
        assert shown["claim_lock"]["count"] == count
        assert shown["last_heartbeat"]["phase_elapsed_seconds"] == 135
        assert shown["status_json_verified"] is True
        assert shown["last_verified_checkpoint"] is None
        assert shown["archives"]["operations"]["state"] == "absent"
        rendered = capsys.readouterr().out
        assert "Fase operations dimulai." in rendered
        assert rendered.count("Heartbeat ") == 2
        assert "checkpoint Drive terakhir belum ada" in rendered
    assert drive.events == ["operations", "operations"]


def test_inspector_reports_unreleased_claim_and_staged_checkpoint_without_writing(attempt_setup):
    attempt, _, _, drive = attempt_setup
    file_id = attempt.slots["operations"]
    raw = b"uploaded test content"
    checksum = sha256(raw).hexdigest()
    drive.files[file_id] = ({"name": ".checkpoint-operations.tar.partial", "parents": [attempt.folder],
                            "size": str(len(raw)), "sha256Checksum": checksum,
                            "appProperties": {"phase": "operations", "parent": "none", "sha256": checksum,
                                              "seal": "1" * 64, "bytes": str(len(raw))}}, raw)
    with attempt.lock(recover=False):
        shown = attempt.inspect()
        assert shown["claim_lock"]["state"] == "unreleased"
        assert shown["claim_lock"]["count"] == 1
        assert shown["archives"]["operations"]["state"] == "staged_verified"
        assert shown["last_verified_checkpoint"] is None
        assert drive.events == []
        assert drive.get(file_id)["name"] == ".checkpoint-operations.tar.partial"

        drive.files[file_id][0].update(name="checkpoint-operations.tar", sha256Checksum="0" * 64)
        shown = attempt.inspect()
        assert shown["archives"]["operations"]["state"] == "inconsistent"
        assert shown["issues"]
        assert shown["last_verified_checkpoint"] is None


def test_start_prints_folder_before_manifest_write(attempt_setup, monkeypatch, capsys):
    original, _, _, drive = attempt_setup
    capsys.readouterr()

    def fail(*args, **kwargs):
        assert "Folder Drive https://drive.google.com/drive/folders/" in capsys.readouterr().out
        raise OSError("manifest write failed")

    monkeypatch.setattr(drive, "ids", lambda count: [f"DriveSlot00010{index}" for index in range(count)])
    monkeypatch.setattr(drive, "write_json", fail)
    with pytest.raises(OSError, match="manifest write failed"):
        prod.Attempt.create(drive, original.work.parent, original.checkpoints.identity, original.resources)
