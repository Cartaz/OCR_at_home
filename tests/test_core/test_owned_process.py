"""Linux integration tests for owned subprocess lifetime."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _process_is_running(pid: int) -> bool:
    status = Path(f"/proc/{pid}/stat")
    try:
        fields = status.read_text(encoding="utf-8").split()
    except OSError:
        return False
    return len(fields) > 2 and fields[2] != "Z"


@pytest.mark.skipif(
    os.name != "posix" or not sys.platform.startswith("linux"),
    reason="PR_SET_PDEATHSIG is Linux-specific",
)
def test_owned_child_dies_when_owner_is_sigkilled(tmp_path: Path) -> None:
    pid_file = tmp_path / "owned-child.pid"
    child_code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8'); "
        "time.sleep(30)"
    )
    owner_code = f"""
import os
import sys
import time
from core.owned_process import spawn_owned_process

with open(os.devnull, "w", encoding="utf-8") as log:
    spawn_owned_process(
        [sys.executable, "-c", {child_code!r}],
        stdout=log,
        env=os.environ,
    )
    time.sleep(30)
"""
    owner = subprocess.Popen([sys.executable, "-c", owner_code])
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if pid_file.exists():
                child_pid = int(pid_file.read_text(encoding="utf-8"))
                break
            if owner.poll() is not None:
                pytest.fail(f"owner exited before child startup: {owner.returncode}")
            time.sleep(0.05)
        assert child_pid is not None, "owned child did not start"
        assert _process_is_running(child_pid)

        owner.send_signal(signal.SIGKILL)
        owner.wait(timeout=3)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _process_is_running(child_pid):
            time.sleep(0.05)
        assert not _process_is_running(child_pid), (
            "owned child survived an unexpected owner SIGKILL"
        )
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=3)
        if child_pid is not None and _process_is_running(child_pid):
            os.kill(child_pid, signal.SIGKILL)


@pytest.mark.skipif(
    os.name != "posix" or not sys.platform.startswith("linux"),
    reason="PR_SET_PDEATHSIG is Linux-specific",
)
def test_owned_child_survives_the_exit_of_the_spawning_thread() -> None:
    """PR_SET_PDEATHSIG fires when the *thread* that forked the child exits.

    llama-server is started from short-lived worker threads (model load, OCR
    restart); it must live until the owning process exits, not until the
    worker thread returns.
    """
    import threading

    from core.owned_process import spawn_owned_process

    handles = []

    def spawn_then_finish() -> None:
        handles.append(
            spawn_owned_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.DEVNULL,  # type: ignore[arg-type]
                env=dict(os.environ),
            )
        )
        # Like the model-load worker, outlive the child's prctl() call.
        time.sleep(1.0)

    thread = threading.Thread(target=spawn_then_finish)
    thread.start()
    thread.join()
    process = handles[0].process
    try:
        time.sleep(0.8)
        assert process.poll() is None, "owned child was killed when its spawning thread exited"
    finally:
        process.kill()
        process.wait(timeout=5)
