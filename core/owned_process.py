"""Owned subprocess lifecycle primitives.

On Linux a tiny exec shim installs ``PR_SET_PDEATHSIG`` before replacing itself
with the requested executable. This preserves the child PID/process group while
ensuring an app or benchmark killed with SIGKILL cannot orphan ``llama-server``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO


@dataclass(frozen=True)
class OwnedProcessHandle:
    process: subprocess.Popen[Any]
    process_group_id: int | None


def owned_process_argv(
    command: Sequence[str],
    *,
    owner_pid: int | None = None,
) -> list[str]:
    argv = [str(item) for item in command]
    if not argv:
        raise ValueError("owned process command must not be empty")
    if os.name != "posix" or not sys.platform.startswith("linux"):
        return argv
    wrapper = Path(__file__).with_name("owned_process_exec.py")
    return [
        sys.executable,
        str(wrapper),
        str(os.getpid() if owner_pid is None else int(owner_pid)),
        "--",
        *argv,
    ]


def spawn_owned_process(
    command: Sequence[str],
    *,
    stdout: TextIO,
    env: Mapping[str, str],
) -> OwnedProcessHandle:
    process = subprocess.Popen(
        owned_process_argv(command),
        stdout=stdout,
        stderr=subprocess.STDOUT,
        env=dict(env),
        start_new_session=(os.name == "posix"),
    )
    process_group_id: int | None = None
    if os.name == "posix":
        try:
            process_group_id = os.getpgid(process.pid)
        except ProcessLookupError:
            process_group_id = None
    return OwnedProcessHandle(process=process, process_group_id=process_group_id)
