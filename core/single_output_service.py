"""Canonical ownership of completed single-OCR output.

This service keeps the persistable OCR result in Python instead of trusting text
round-tripped through the Web UI.  It listens to the existing core OCR events,
keeps only the currently completed single-document result, and delegates durable
filesystem publication to ``core.output_writer``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from core.event_bus import EventBus
from core.output_writer import write_ocr_pages, write_ocr_text


@dataclass(frozen=True)
class CompletedSingleOutput:
    source: Path
    text: str
    page_texts: tuple[str, ...]


class SingleOutputService:
    """Own the one completed single-OCR result that may be persisted."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_source: Path | None = None
        self._page_texts: dict[int, str] = {}
        self._expected_pages = 0
        self._completed: CompletedSingleOutput | None = None
        self._closed = False

        self._subscriptions = {
            "ocr_started": self._on_ocr_started,
            "pdf_page_completed": self._on_pdf_page_completed,
            "ocr_completed": self._on_ocr_completed,
            "ocr_cancelled": self._on_ocr_invalidated,
            "ocr_failed": self._on_ocr_invalidated,
        }
        for event_name, handler in self._subscriptions.items():
            EventBus.subscribe(event_name, handler)

    @staticmethod
    def _canonical_source(value: object) -> Path | None:
        text = str(value or "").strip()
        if not text:
            return None
        return Path(text).expanduser().resolve()

    def _reset_locked(self, active_source: Path | None = None) -> None:
        self._active_source = active_source
        self._page_texts = {}
        self._expected_pages = 0
        self._completed = None

    def _on_ocr_started(self, data: dict[str, object]) -> None:
        if data.get("mode") != "single":
            return
        source = self._canonical_source(data.get("image_path"))
        with self._lock:
            self._reset_locked(source)

    def _on_pdf_page_completed(self, data: dict[str, object]) -> None:
        if data.get("mode") != "single":
            return
        source = self._canonical_source(data.get("pdf_path"))
        page_num = int(data.get("page_num") or 0)
        total_pages = int(data.get("total_pages") or 0)
        if source is None or page_num <= 0:
            return
        with self._lock:
            if source != self._active_source:
                return
            self._page_texts[page_num] = str(data.get("text") or "")
            if total_pages > 0:
                self._expected_pages = total_pages

    def _on_ocr_completed(self, data: dict[str, object]) -> None:
        if data.get("mode") != "single":
            return
        source = self._canonical_source(data.get("image_path"))
        if source is None:
            return

        with self._lock:
            if source != self._active_source:
                return

            if bool(data.get("is_pdf")):
                page_numbers = sorted(self._page_texts)
                expected_count = self._expected_pages or len(page_numbers)
                expected_numbers = list(range(1, expected_count + 1))
                if not page_numbers or page_numbers != expected_numbers:
                    self._completed = None
                    return
                pages = tuple(self._page_texts[number] for number in page_numbers)
                if len(pages) == 1:
                    text = pages[0]
                else:
                    text = "\n\n".join(
                        f"--- Pagina {index} ---\n{page_text}"
                        for index, page_text in enumerate(pages, start=1)
                    )
            else:
                text = str(data.get("text") or "")
                pages = ()

            self._completed = CompletedSingleOutput(
                source=source,
                text=text,
                page_texts=pages,
            )

    def _on_ocr_invalidated(self, data: dict[str, object]) -> None:
        if data.get("mode") not in (None, "single"):
            return
        with self._lock:
            self._reset_locked()

    def _require_completed(self, source_path: str | Path) -> CompletedSingleOutput:
        source = self._canonical_source(source_path)
        with self._lock:
            completed = self._completed
            if source is None or completed is None or completed.source != source:
                raise RuntimeError(
                    "Il risultato selezionato non corrisponde a un OCR completato."
                )
            return completed

    def save_result(
        self,
        output_dir: str | Path,
        source_path: str | Path,
        file_format: str,
    ) -> Path:
        completed = self._require_completed(source_path)
        return write_ocr_text(
            output_dir,
            completed.source,
            completed.text,
            file_format,
        )

    def save_pdf_pages(
        self,
        output_dir: str | Path,
        source_path: str | Path,
        file_format: str,
    ) -> list[Path]:
        completed = self._require_completed(source_path)
        if completed.source.suffix.lower() != ".pdf":
            raise RuntimeError("Il risultato completato non appartiene a un PDF")
        if not completed.page_texts:
            raise RuntimeError("Nessuna pagina PDF completata da salvare")
        return write_ocr_pages(
            output_dir,
            completed.source,
            completed.page_texts,
            file_format,
        )

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for event_name, handler in self._subscriptions.items():
            EventBus.unsubscribe(event_name, handler)
