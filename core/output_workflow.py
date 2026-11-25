"""Canonical OCR-result ownership and durable output workflow.

This module owns the completed single-OCR result and batch output policy. It
listens to core events directly, so durable output does not depend on the
presentation layer being present. Filesystem publication is delegated to
``output_writer``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config.settings import Settings
from core.event_bus import EventBus
from core.output_writer import normalize_format, write_ocr_pages, write_ocr_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompletedSingleResult:
    source: str
    text: str
    pdf_pages: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchOutputOptions:
    enabled: bool
    file_format: str
    save_pdf_pages: bool
    output_dir: str


class OutputWorkflow:
    """Own canonical completed results and output persistence policy."""

    _EVENTS = (
        "ocr_started",
        "ocr_completed",
        "ocr_cancelled",
        "ocr_failed",
        "batch_started",
        "batch_task_completed",
        "batch_completed",
        "batch_cancelled",
        "batch_failed",
    )

    def __init__(self, settings_provider: Callable[[], Settings]) -> None:
        self._settings_provider = settings_provider
        self._lock = threading.RLock()
        self._completed_single: CompletedSingleResult | None = None
        self._batch_options: BatchOutputOptions | None = None
        self._batch_saved_count = 0
        self._batch_save_failures = 0
        self._subscriptions: list[tuple[str, Callable[[dict], None]]] = []
        self._manual_thread: threading.Thread | None = None
        self._shutdown = False
        for event_name in self._EVENTS:
            def handler(payload: dict, *, _event_name: str = event_name) -> None:
                self._handle_event(_event_name, dict(payload))

            EventBus.subscribe(event_name, handler)
            self._subscriptions.append((event_name, handler))

    @staticmethod
    def _canonical_source(source_path: str) -> str:
        return str(Path(source_path).expanduser().resolve()) if source_path else ""

    def _handle_event(self, event_name: str, data: dict) -> None:
        if self._shutdown:
            return
        single = data.get("mode") == "single"
        if event_name in {"ocr_started", "ocr_cancelled", "ocr_failed"} and single:
            with self._lock:
                self._completed_single = None
        elif event_name == "ocr_completed" and single:
            self._record_completed_single(data)
        elif event_name == "batch_started":
            self._start_batch()
        elif event_name == "batch_task_completed":
            self._auto_save_batch_result(data)
        elif event_name == "batch_completed":
            self._finish_batch(completed=True)
        elif event_name in {"batch_cancelled", "batch_failed"}:
            self._finish_batch(completed=False)

    def _record_completed_single(self, data: dict) -> None:
        source = self._canonical_source(str(data.get("image_path") or ""))
        result = None
        if source:
            result = CompletedSingleResult(
                source=source,
                text=str(data.get("text") or ""),
                pdf_pages=tuple(str(page) for page in data.get("pages") or ()),
            )
        with self._lock:
            self._completed_single = result

    def _require_single(self, source_path: str) -> CompletedSingleResult:
        source = self._canonical_source(source_path)
        with self._lock:
            result = self._completed_single
        if result is None or not source or result.source != source:
            raise RuntimeError(
                "Il risultato selezionato non corrisponde a un OCR completato."
            )
        return result

    def _start_manual_save(
        self,
        kind: str,
        write: Callable[[], dict[str, object]],
    ) -> str:
        request_id = uuid.uuid4().hex

        def run() -> None:
            try:
                payload = write()
                event, data = "single_output_saved", payload
            except Exception as exc:
                logger.warning("Salvataggio manuale OCR fallito (%s): %s", kind, exc)
                event, data = "single_output_save_failed", {"error": str(exc)}
            finally:
                with self._lock:
                    publish = not self._shutdown
                    if self._manual_thread is threading.current_thread():
                        self._manual_thread = None
            if publish:
                EventBus.emit(event, {"request_id": request_id, "kind": kind, **data})

        thread = threading.Thread(
            target=run,
            name=f"manual-output-{request_id[:8]}",
            daemon=True,
        )
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Output workflow in arresto")
            if self._manual_thread is not None and self._manual_thread.is_alive():
                raise RuntimeError("Un salvataggio manuale è già in corso")
            self._manual_thread = thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                if self._manual_thread is thread:
                    self._manual_thread = None
            raise
        return request_id

    def request_save_single_result(self, source_path: str, file_format: str) -> str:
        """Snapshot canonical state and persist combined output off the caller thread."""
        result = self._require_single(source_path)
        fmt = normalize_format(file_format)
        output_dir = str(self._settings_provider().output_dir)

        def write() -> dict[str, object]:
            destination = write_ocr_text(output_dir, result.source, result.text, fmt)
            logger.info("Risultato OCR salvato in %s", destination)
            return {"path": str(destination), "name": destination.name}

        return self._start_manual_save("combined", write)

    def request_save_single_pdf_pages(self, source_path: str, file_format: str) -> str:
        """Snapshot canonical PDF pages and persist them off the caller thread."""
        result = self._require_single(source_path)
        if not result.pdf_pages:
            raise RuntimeError("Nessuna pagina PDF completata da salvare")
        fmt = normalize_format(file_format)
        output_dir = str(self._settings_provider().output_dir)

        def write() -> dict[str, object]:
            outputs = write_ocr_pages(output_dir, result.source, result.pdf_pages, fmt)
            logger.info("Salvate %d pagine OCR separate per %s", len(outputs), result.source)
            return {"paths": [str(path) for path in outputs], "count": len(outputs)}

        return self._start_manual_save("pages", write)

    def _start_batch(self) -> None:
        settings = self._settings_provider()
        options = BatchOutputOptions(
            enabled=bool(settings.batch_auto_save),
            file_format=str(settings.batch_output_format),
            save_pdf_pages=bool(settings.batch_save_pdf_pages),
            output_dir=str(settings.output_dir),
        )
        with self._lock:
            self._batch_options = options
            self._batch_saved_count = 0
            self._batch_save_failures = 0

    def _auto_save_batch_result(self, data: dict) -> None:
        with self._lock:
            options = self._batch_options
        if options is None or not options.enabled:
            return

        source = str(data.get("image_path") or "")
        text = str(data.get("text") or "")
        pages = [str(page) for page in data.get("pages") or ()]
        if not source:
            with self._lock:
                self._batch_save_failures += 1
            EventBus.emit(
                "batch_output_save_failed",
                {"error": "Percorso sorgente batch mancante"},
            )
            return

        combined_path: Path | None = None
        page_paths: list[Path] = []
        try:
            combined_path = write_ocr_text(
                options.output_dir,
                source,
                text,
                options.file_format,
            )
            if options.save_pdf_pages and pages:
                page_paths = write_ocr_pages(
                    options.output_dir,
                    source,
                    pages,
                    options.file_format,
                )
            with self._lock:
                self._batch_saved_count += 1
            EventBus.emit(
                "batch_output_saved",
                {
                    "image_path": source,
                    "path": str(combined_path),
                    "page_paths": [str(path) for path in page_paths],
                },
            )
        except Exception as exc:
            with self._lock:
                self._batch_save_failures += 1
            logger.warning("Salvataggio automatico batch fallito per %s: %s", source, exc)
            EventBus.emit(
                "batch_output_save_failed",
                {
                    "image_path": source,
                    "error": str(exc),
                    "combined_path": str(combined_path) if combined_path else "",
                },
            )

    def _finish_batch(self, *, completed: bool) -> None:
        with self._lock:
            options = self._batch_options
            saved = self._batch_saved_count
            failed = self._batch_save_failures
            self._batch_options = None
        if completed and options is not None and options.enabled:
            EventBus.emit(
                "batch_output_summary",
                {
                    "saved": saved,
                    "failed": failed,
                    "output_dir": options.output_dir,
                },
            )

    def shutdown(self, wait_seconds: float = 5.0) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            manual_thread = self._manual_thread
            self._completed_single = None

        for event_name, handler in self._subscriptions:
            EventBus.unsubscribe(event_name, handler)
        self._subscriptions.clear()

        if manual_thread is not None and manual_thread.is_alive():
            manual_thread.join(timeout=max(0.0, wait_seconds))
            if manual_thread.is_alive():
                logger.warning(
                    "Worker output manuale non terminato entro il timeout: %s",
                    manual_thread.name,
                )
