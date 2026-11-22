"""Relay live subprocess output through the notebook kernel's Python stdout."""

from codecs import getincrementaldecoder
import os
from selectors import EVENT_READ, DefaultSelector
import signal
import subprocess
import sys
from time import monotonic


def stream_command(command, *, cwd=None, env=None, interrupt_grace=45):
    with subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process, DefaultSelector() as reader:
        reader.register(process.stdout, EVENT_READ)
        decoder = getincrementaldecoder("utf-8")(errors="replace")

        def drain(deadline=None):
            while reader.get_map():
                remaining = None if deadline is None else max(0, deadline - monotonic())
                if not reader.select(remaining):
                    raise subprocess.TimeoutExpired(command, interrupt_grace)
                data = os.read(process.stdout.fileno(), 8192)
                sys.stdout.write(decoder.decode(data, final=not data))
                sys.stdout.flush()
                if not data:
                    reader.unregister(process.stdout)

        try:
            drain()
            return process.wait()
        except KeyboardInterrupt:
            print("Interupsi dikirim. Menunggu worker berhenti dan status Drive diperbarui.", flush=True)
            try:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                deadline = monotonic() + interrupt_grace
                drain(deadline)
                process.wait(timeout=max(0, deadline - monotonic()))
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                print("Proses dihentikan paksa. Periksa klaim dan checkpoint dengan Monitor Drive.", flush=True)
            raise
