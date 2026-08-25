"""Session-owned staging for transient local OCR inputs."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


class InputStaging:
    """Own temporary OCR input files for one application session."""

    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self._root = Path(root)
        self._max_bytes = int(max_bytes)
        self._session_dir: Path | None = None
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

    def _ensure_session_dir(self) -> Path:
        if self._session_dir is None:
            self._root.mkdir(parents=True, exist_ok=True)
            self._session_dir = Path(
                tempfile.mkdtemp(prefix="session-", dir=self._root)
            )
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
