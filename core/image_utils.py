# core/image_utils.py
"""Utilità per il caricamento e la conversione di immagini e PDF.

Contiene funzioni per caricare immagini da disco, convertire pagine
PDF in immagini PIL, e convertire array NumPy in immagini PIL.
Questo modulo è indipendente da Qt e da qualsiasi backend di inferenza.

Functions:
    load_image: Carica un'immagine o la prima pagina di un PDF.
    is_pdf: Verifica se un percorso indica un file PDF.
    pdf_to_images: Converte un PDF in lista di immagini PIL.
    pdf_page_count: Restituisce il numero di pagine di un PDF.
    pdf_page_to_image: Converte una singola pagina PDF in immagine PIL.
    array_to_pil: Converte un array NumPy in immagine PIL.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.exceptions import ImageLoadError

logger = logging.getLogger(__name__)


def is_pdf(path: Path) -> bool:
    """Verifica se il percorso indica un file PDF.

    Args:
        path: Percorso del file.

    Returns:
        True se il file ha estensione .pdf.
    """
    return path.suffix.lower() == ".pdf"


def load_image(image_path: Path) -> Any:
    """Carica un'immagine dal percorso specificato.

    Se il file è un PDF, converte la prima pagina in immagine.
    Per elaborare tutte le pagine, usare pdf_to_images().

    Args:
        image_path: Percorso del file immagine o PDF.

    Returns:
        Immagine PIL in modalità RGB.

    Raises:
        ImageLoadError: Se l'immagine non può essere caricata.
    """
    if not image_path.exists():
        raise ImageLoadError(str(image_path), "File non trovato")

    if is_pdf(image_path):
        pages = pdf_to_images(image_path)
        if not pages:
            raise ImageLoadError(
                str(image_path),
                "Il PDF non contiene pagine o la conversione è fallita",
            )
        return pages[0]

    try:
        from PIL import Image
        img = Image.open(image_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img
    except Exception as exc:
        raise ImageLoadError(str(image_path), str(exc)) from exc


def pdf_page_count(pdf_path: Path) -> int:
    """Restituisce il numero di pagine di un file PDF.

    Args:
        pdf_path: Percorso del file PDF.

    Returns:
        Numero di pagine del PDF, 0 se non può essere aperto.
    """
    try:
        import fitz
    except ImportError:
        return 0
    try:
        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


def pdf_to_images(
    pdf_path: Path, dpi: int = 300, max_pages: int | None = None,
) -> list[Any]:
    """Converte un file PDF in una lista di immagini PIL.

    Utilizza PyMuPDF (fitz) per il rendering ad alta risoluzione.

    Args:
        pdf_path: Percorso del file PDF.
        dpi: Risoluzione di rendering (default 300, raccomandato per OCR).
        max_pages: Numero massimo di pagine (None = tutte).

    Returns:
        Lista di immagini PIL (una per pagina, modalità RGB).

    Raises:
        ImageLoadError: Se il PDF non può essere aperto o convertito.
    """
    if not pdf_path.exists():
        raise ImageLoadError(str(pdf_path), "File PDF non trovato")

    try:
        import fitz
    except ImportError:
        raise ImageLoadError(
            str(pdf_path),
            "Supporto PDF non disponibile. "
            "Installare PyMuPDF: pip install PyMuPDF",
        ) from None

    images: list[Any] = []
    try:
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return images

        pages_to_convert = page_count if max_pages is None else min(page_count, max_pages)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        for page_idx in range(pages_to_convert):
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            from PIL import Image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)

        doc.close()
        logger.info("PDF convertito: %d pagine → %d immagini (DPI=%d)",
                     page_count, len(images), dpi)
    except ImageLoadError:
        raise
    except Exception as exc:
        raise ImageLoadError(str(pdf_path), f"Errore conversione PDF: {exc}") from exc

    return images


def pdf_page_to_image(
    pdf_path: Path, page_num: int, dpi: int = 300,
) -> Any:
    """Converte una singola pagina di un PDF in immagine PIL.

    A differenza di pdf_to_images(), converte una sola pagina alla
    volta, riducendo l'uso di RAM.

    Args:
        pdf_path: Percorso del file PDF.
        page_num: Numero di pagina (1-based).
        dpi: Risoluzione di rendering (default 300).

    Returns:
        Immagine PIL (RGB) della pagina, o None se fallisce.

    Raises:
        ImageLoadError: Se la pagina non può essere convertita.
    """
    try:
        import fitz
    except ImportError:
        raise ImageLoadError(
            str(pdf_path),
            "Supporto PDF non disponibile. "
            "Installare PyMuPDF: pip install PyMuPDF",
        ) from None

    try:
        doc = fitz.open(str(pdf_path))
        page_idx = page_num - 1
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            raise ImageLoadError(
                str(pdf_path),
                f"Pagina {page_num} non valida (PDF ha {len(doc)} pagine)",
            )

        page = doc.load_page(page_idx)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        from PIL import Image
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        del pix
        doc.close()
        return img
    except ImageLoadError:
        raise
    except Exception as exc:
        raise ImageLoadError(
            str(pdf_path),
            f"Errore conversione pagina {page_num}: {exc}",
        ) from exc


def array_to_pil(array: Any) -> Any:
    """Converte un array NumPy in immagine PIL.

    Args:
        array: Array NumPy (2D per grayscale, 3D per RGB).

    Returns:
        Immagine PIL corrispondente.
    """
    from PIL import Image
    if array.ndim == 2:
        return Image.fromarray(array, mode="L")
    return Image.fromarray(array)
