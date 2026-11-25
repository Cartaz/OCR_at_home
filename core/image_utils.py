"""Utilità indipendenti da Qt per immagini e PDF."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.exceptions import ImageLoadError


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def load_image(image_path: Path) -> Any:
    if not image_path.exists():
        raise ImageLoadError(str(image_path), "File non trovato")
    try:
        from PIL import Image

        with Image.open(image_path) as source:
            img = source.copy()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img
    except Exception as exc:
        raise ImageLoadError(str(image_path), str(exc)) from exc


class PdfDocument:
    """One open PDF whose pages are rendered on demand."""

    def __init__(self, path: Path, document: Any) -> None:
        self._path = path
        self._document = document

    @property
    def page_count(self) -> int:
        return len(self._document)

    def render_page(self, page_num: int, dpi: int) -> Any:
        from PIL import Image

        import fitz

        page_idx = page_num - 1
        if page_idx < 0 or page_idx >= self.page_count:
            raise ImageLoadError(
                str(self._path),
                f"Pagina {page_num} non valida (PDF ha {self.page_count} pagine)",
            )
        try:
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = self._document.load_page(page_idx).get_pixmap(matrix=matrix, alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception as exc:
            raise ImageLoadError(
                str(self._path), f"Errore conversione pagina {page_num}: {exc}"
            ) from exc


@contextmanager
def open_pdf(pdf_path: Path) -> Iterator[PdfDocument]:
    """Open a PDF once; unreadable, encrypted or empty files raise ``ImageLoadError``."""
    try:
        import fitz
    except ImportError:
        raise ImageLoadError(
            str(pdf_path), "Supporto PDF non disponibile. Installare PyMuPDF."
        ) from None
    try:
        document = fitz.open(str(pdf_path))
    except Exception as exc:
        raise ImageLoadError(str(pdf_path), f"PDF non leggibile: {exc}") from exc
    try:
        if document.needs_pass:
            raise ImageLoadError(str(pdf_path), "Il PDF è protetto da password")
        if len(document) == 0:
            raise ImageLoadError(str(pdf_path), "Il PDF non contiene pagine")
        yield PdfDocument(pdf_path, document)
    finally:
        document.close()


def array_to_pil(array: Any) -> Any:
    from PIL import Image

    # A 2-D uint8 array is inferred as mode "L"; the explicit ``mode``
    # argument was deprecated in Pillow 11.3 and removed afterwards.
    return Image.fromarray(array)
