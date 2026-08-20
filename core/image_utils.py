"""Utilità indipendenti da Qt per immagini e PDF."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from core.exceptions import ImageLoadError


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def load_image(image_path: Path) -> Any:
    if not image_path.exists():
        raise ImageLoadError(str(image_path), "File non trovato")
    if is_pdf(image_path):
        return pdf_page_to_image(image_path, 1)
    try:
        from PIL import Image
        with Image.open(image_path) as source:
            img = source.copy()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img
    except Exception as exc:
        raise ImageLoadError(str(image_path), str(exc)) from exc


def pdf_page_count(pdf_path: Path) -> int:
    try:
        import fitz
        with fitz.open(str(pdf_path)) as doc:
            return len(doc)
    except Exception:
        return 0


def pdf_to_images(pdf_path: Path, dpi: int = 300, max_pages: int | None = None) -> list[Any]:
    if not pdf_path.exists():
        raise ImageLoadError(str(pdf_path), "File PDF non trovato")
    try:
        import fitz
        from PIL import Image
    except ImportError:
        raise ImageLoadError(str(pdf_path), "Supporto PDF non disponibile. Installare PyMuPDF.") from None
    try:
        images = []
        with fitz.open(str(pdf_path)) as doc:
            count = len(doc) if max_pages is None else min(len(doc), max_pages)
            mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            for idx in range(count):
                pix = doc.load_page(idx).get_pixmap(matrix=mat, alpha=False)
                images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return images
    except Exception as exc:
        raise ImageLoadError(str(pdf_path), f"Errore conversione PDF: {exc}") from exc


def pdf_page_to_image(pdf_path: Path, page_num: int, dpi: int = 300) -> Any:
    try:
        import fitz
        from PIL import Image
    except ImportError:
        raise ImageLoadError(str(pdf_path), "Supporto PDF non disponibile. Installare PyMuPDF.") from None
    try:
        with fitz.open(str(pdf_path)) as doc:
            page_count = len(doc)
            page_idx = page_num - 1
            if page_idx < 0 or page_idx >= page_count:
                raise ImageLoadError(str(pdf_path), f"Pagina {page_num} non valida (PDF ha {page_count} pagine)")
            pix = doc.load_page(page_idx).get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except ImageLoadError:
        raise
    except Exception as exc:
        raise ImageLoadError(str(pdf_path), f"Errore conversione pagina {page_num}: {exc}") from exc


def array_to_pil(array: Any) -> Any:
    from PIL import Image
    return Image.fromarray(array, mode="L") if array.ndim == 2 else Image.fromarray(array)
