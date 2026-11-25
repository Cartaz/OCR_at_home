"""Session-owned staging for transient local OCR inputs."""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "session-"
_LOCK_NAME = ".owner.lock"


class InputStaging:
    """Own temporary OCR input files (clipboard images) for one session.

    Each session directory holds an ``flock`` for the life of the process.
    Directories left behind by a crashed session are therefore recognisable
    (their lock can be taken) and are purged, while directories of another
    running instance are left alone.
    """

    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self._root = Path(root)
        self._max_bytes = int(max_bytes)
        self._session_dir: Path | None = None
        self._lock_fd: int | None = None
        self._shutdown = False

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    def stage_png(self, data: bytes) -> Path:
        """Persist one PNG payload inside the current session directory."""
        if self._shutdown:
            raise RuntimeError("Input staging già arrestato")
        if not data:
            raise ValueError("Immagine clipboard vuota")
        if len(data) > self._max_bytes:
            raise ValueError(
                f"Immagine clipboard oltre il limite di {self._max_bytes // (1024 * 1024)} MB"
            )

        session_dir = self._ensure_session_dir()
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="clipboard-",
            suffix=".png",
            dir=session_dir,
            delete=False,
        )
        path = Path(handle.name)
        try:
            with handle:
                handle.write(data)
                handle.flush()
            return path.resolve()
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def purge_orphaned_sessions(self) -> int:
        """Remove session directories whose owning process no longer exists."""
        if not self._root.is_dir():
            return 0
        removed = 0
        for candidate in self._root.glob(f"{_SESSION_PREFIX}*"):
            if not candidate.is_dir() or candidate == self._session_dir:
                continue
            lock_path = candidate / _LOCK_NAME
            try:
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            except OSError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                continue  # owned by a running instance
            try:
                shutil.rmtree(candidate, ignore_errors=True)
                removed += 1
            finally:
                os.close(fd)
        if removed:
            logger.info("Rimosse %d sessioni di input orfane", removed)
        return removed

    def _ensure_session_dir(self) -> Path:
        if self._session_dir is None:
            self._root.mkdir(parents=True, exist_ok=True)
            session_dir = Path(tempfile.mkdtemp(prefix=_SESSION_PREFIX, dir=self._root))
            fd = os.open(session_dir / _LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
            self._session_dir = session_dir
        return self._session_dir

    def shutdown(self) -> None:
        """Remove every transient input owned by this application session."""
        if self._shutdown:
            return
        self._shutdown = True
        session_dir = self._session_dir
        self._session_dir = None
        if session_dir is not None:
            shutil.rmtree(session_dir, ignore_errors=True)
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
