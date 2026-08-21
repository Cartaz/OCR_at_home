"""End-to-end process lifecycle tests using a lightweight fake llama-server.

These tests exercise the real subprocess/process-group management in
``LlamaServerBackend`` without requiring SYCL hardware or GGUF inference.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

import pytest

from core.cancellation import CancellationToken
from core.exceptions import OperationCancelledError
from core.llama_backend import LlamaServerBackend
from core.llama_gpu_detect import GPU_OFFLOAD_ALL_LAYERS

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="The app-owned process-group lifecycle is POSIX-specific.",
)


_FAKE_SERVER = r'''#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def arg(name, default=None):
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


host = arg("--host", "127.0.0.1")
port = int(arg("--port", "0"))
started = time.monotonic()
health_delay = float(os.environ.get("FAKE_LLAMA_HEALTH_DELAY", "0"))

pid_file = os.environ.get("FAKE_LLAMA_PID_FILE")
if pid_file:
    with open(pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

child_pid_file = os.environ.get("FAKE_LLAMA_CHILD_PID_FILE")
if child_pid_file:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
    )
    with open(child_pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(child.pid))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        ready = (time.monotonic() - started) >= health_delay
        self.send_response(200 if ready else 503)
        self.end_headers()
        self.wfile.write(b"ok" if ready else b"loading")

    def log_message(self, _format, *_args):
        pass


HTTPServer((host, port), Handler).serve_forever()
'''


def _wait_until(predicate, timeout: float = 4.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _prepare_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    health_delay: float = 0.0,
    spawn_child: bool = True,
) -> tuple[Path, Path]:
    fake_server = tmp_path / "llama-server"
    fake_server.write_text(_FAKE_SERVER, encoding="utf-8")
    fake_server.chmod(0o755)

    main_model = tmp_path / "model.gguf"
    mmproj_model = tmp_path / "mmproj.gguf"
    main_model.write_bytes(b"fake-main")
    mmproj_model.write_bytes(b"fake-mmproj")

    pid_file = tmp_path / "server.pid"
    child_pid_file = tmp_path / "child.pid"
    env = dict(os.environ)
    env["FAKE_LLAMA_PID_FILE"] = str(pid_file)
    env["FAKE_LLAMA_HEALTH_DELAY"] = str(health_delay)
    if spawn_child:
        env["FAKE_LLAMA_CHILD_PID_FILE"] = str(child_pid_file)

    monkeypatch.setattr("core.llama_backend.find_llama_server", lambda: str(fake_server))
    monkeypatch.setattr(
        "core.llama_backend.ensure_gguf_models",
        lambda **_kwargs: {"main": main_model, "mmproj": mmproj_model},
    )
    monkeypatch.setattr(
        "core.llama_backend.detect_gpu_backend",
        lambda _device: (GPU_OFFLOAD_ALL_LAYERS, "sycl"),
    )
    monkeypatch.setattr("core.llama_backend.venv_lib_env", lambda: dict(env))
    return pid_file, child_pid_file


def test_fake_server_startup_ready_shutdown_leaves_no_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pid_file, child_pid_file = _prepare_runtime(monkeypatch, tmp_path)
    backend = LlamaServerBackend()

    backend.initialize()
    assert backend.is_initialized is True
    assert backend.is_server_running is True
    assert _wait_until(pid_file.exists)
    assert _wait_until(child_pid_file.exists)

    process = backend._process  # type: ignore[attr-defined]
    assert process is not None
    server_pid = int(pid_file.read_text(encoding="utf-8"))
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    pgid = os.getpgid(server_pid)

    assert server_pid == process.pid
    assert os.getpgid(child_pid) == pgid

    backend.shutdown()

    assert backend.is_initialized is False
    assert backend.server_url == ""
    assert _wait_until(lambda: not _pid_exists(server_pid))
    assert _wait_until(lambda: not _pid_exists(child_pid))
    assert _wait_until(lambda: not _group_exists(pgid))


def test_cancel_during_model_startup_terminates_owned_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pid_file, _ = _prepare_runtime(
        monkeypatch,
        tmp_path,
        health_delay=30.0,
        spawn_child=False,
    )
    backend = LlamaServerBackend()
    token = CancellationToken()
    errors: list[BaseException] = []

    def initialize() -> None:
        try:
            backend.initialize(cancel_token=token)
        except BaseException as exc:  # captured for assertion in test thread
            errors.append(exc)

    thread = threading.Thread(target=initialize, daemon=True)
    thread.start()
    assert _wait_until(pid_file.exists)
    server_pid = int(pid_file.read_text(encoding="utf-8"))

    token.cancel()
    thread.join(timeout=6)

    assert not thread.is_alive()
    assert errors and isinstance(errors[0], OperationCancelledError)
    assert backend.is_initialized is False
    assert _wait_until(lambda: not _pid_exists(server_pid))


def test_server_crash_during_image_ocr_restarts_and_retries_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _prepare_runtime(monkeypatch, tmp_path, spawn_child=False)
    backend = LlamaServerBackend()
    backend.initialize()

    first_process = backend._process  # type: ignore[attr-defined]
    assert first_process is not None
    first_pid = first_process.pid
    calls = 0

    def flaky_ocr(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            process = backend._process  # type: ignore[attr-defined]
            assert process is not None
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            raise ConnectionResetError("connection reset by peer")
        return "retry-ok", None

    monkeypatch.setattr("core.llama_backend.ocr_single_image", flaky_ocr)
    image = tmp_path / "page.png"
    image.write_bytes(b"not-decoded-by-test")

    try:
        result = backend.process_image(image)
        second_process = backend._process  # type: ignore[attr-defined]
        assert result.text == "retry-ok"
        assert calls == 2
        assert second_process is not None
        assert second_process.pid != first_pid
        assert second_process.poll() is None
        assert _wait_until(lambda: not _pid_exists(first_pid))
    finally:
        backend.shutdown()


def test_shutdown_is_idempotent_after_server_has_already_crashed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _prepare_runtime(monkeypatch, tmp_path, spawn_child=False)
    backend = LlamaServerBackend()
    backend.initialize()
    process = backend._process  # type: ignore[attr-defined]
    assert process is not None

    os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=3)

    backend.shutdown()
    backend.shutdown()

    assert backend.is_initialized is False
    assert backend.server_url == ""
    assert backend._process is None  # type: ignore[attr-defined]
