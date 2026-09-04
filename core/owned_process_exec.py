"""Linux exec shim that binds an owned process to its Python parent."""

from __future__ import annotations

import ctypes
import os
import signal
import sys

_PR_SET_PDEATHSIG = 1


def _set_parent_death_signal() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    if prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[1] != "--":
        raise SystemExit("usage: owned_process_exec.py <parent-pid> -- <command> [args...]")
    expected_parent = int(args[0])
    command = args[2:]
    if not command:
        raise SystemExit("owned command missing")

    _set_parent_death_signal()
    # Close the race where the owner dies between fork/exec and prctl().
    if os.getppid() != expected_parent:
        return 125
    os.execvpe(command[0], command, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
