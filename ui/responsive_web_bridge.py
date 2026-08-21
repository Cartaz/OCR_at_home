"""Non-blocking startup bridge for the Qt WebEngine frontend.

The normal WebBridge owns the application API.  This subclass only changes
startup semantics so that no hardware probe or controller initialization can
block the Qt GUI thread before WebEngine has presented its first frame.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from typing import Any

from PySide6.QtCore import Slot

from config.constants import AppMeta
from ui.web_bridge import WebBridge

logger = logging.getLogger(__name__)


class ResponsiveWebBridge(WebBridge):
    """WebBridge variant whose initial bootstrap is intentionally non-blocking."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._init_thread: threading.Thread | None = None
        self._init_thread_lock = threading.Lock()
        self._devices_snapshot: list[dict[str, Any]] = []

    @Slot(str, object)
    def _on_core_event(self, event_name: str, payload: object) -> None:
        if event_name == "hardware_detected" and isinstance(payload, dict):
            devices = payload.get("devices")
            if isinstance(devices, list):
                self._devices_snapshot = [
                    dict(item) for item in devices if isinstance(item, dict)
                ]
        super()._on_core_event(event_name, payload)

    def _bootstrap_payload(self) -> dict[str, Any]:
        """Return only already-available state; never probe hardware here."""
        settings = asdict(self._controller.settings)
        return {
            "app": {
                "name": AppMeta.NAME,
                "version": AppMeta.VERSION,
                "description": AppMeta.DESCRIPTION,
            },
            "settings": settings,
            "runtime": {
                "operation": self._controller.operation,
                "model_ready": self._controller.engine.is_initialized,
                "device": self._controller.engine.device,
                "backend": self._controller.engine.backend,
                "active_batch_id": self._controller.process_manager.active_job_id,
            },
            "devices": list(self._devices_snapshot),
            "limits": {
                "max_batch_size": AppMeta.MAX_BATCH_SIZE,
                "max_image_size_mb": AppMeta.MAX_IMAGE_SIZE_MB,
                "extensions": sorted(AppMeta.SUPPORTED_IMAGE_EXTENSIONS),
            },
            "paths": {
                "model_cache": str(AppMeta.GGUF_MODEL_DIR),
                "log": str(AppMeta.LOG_PATH),
            },
        }

    @Slot()
    def initializeBackend(self) -> None:
        """Initialize detection/controller on a worker and return to Qt at once."""
        with self._init_thread_lock:
            if self._shutdown:
                return
            if self._init_thread is not None and self._init_thread.is_alive():
                return

            def initialize() -> None:
                try:
                    self._controller.initialize()
                except Exception as exc:
                    logger.exception("Inizializzazione controller fallita")
                    if not self._shutdown:
                        self._error(
                            "Impossibile inizializzare il backend OCR.",
                            details=str(exc),
                        )
                finally:
                    with self._init_thread_lock:
                        if self._init_thread is threading.current_thread():
                            self._init_thread = None

            thread = threading.Thread(
                target=initialize,
                name="backend-init-worker",
                daemon=True,
            )
            self._init_thread = thread
            thread.start()

    def shutdown(self, wait_ms: int = 5000) -> None:
        super().shutdown(wait_ms=wait_ms)
        with self._init_thread_lock:
            thread = self._init_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, wait_ms / 1000.0))
