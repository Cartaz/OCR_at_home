# core/llama_ocr_api.py
"""Metodi di elaborazione OCR tramite l'API REST di llama-server.

Contiene la logica per elaborare singole immagini, PDF multi-pagina
e la comunicazione HTTP con llama-server per l'inferenza OCR.

La comunicazione usa la modalita' non-streaming con timeout ampio
(600s) per garantire che il modello vision completi l'inferenza
anche su pagine dense. Il prompt "OCR" e' quello per cui il modello
GLM-OCR e' stato addestrato.

Functions:
    ocr_single_image: Elabora una singola immagine via API.
    ocr_pdf: Elabora un PDF pagina per pagina via API.
    ocr_image_api: Esegue la chiamata HTTP a llama-server.
"""

from __future__ import annotations

import base64
import gc
import io
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from config.constants import AppConstants
from core.event_bus import EventBus
from core.exceptions import ImageLoadError
from core.image_preprocessor import ImagePreprocessor
from core.image_utils import (
    load_image,
    array_to_pil,
    pdf_page_count,
    pdf_page_to_image,
)

logger = logging.getLogger(__name__)

# Parametri letti dalle costanti centralizzate
OCR_PROMPT: str = "OCR"  # Prompt nativo GLM-OCR — non modificare
MAX_IMAGE_DIM: int = AppConstants.LLAMA_MAX_IMAGE_DIM
JPEG_QUALITY: int = AppConstants.LLAMA_JPEG_QUALITY
MAX_TOKENS: int = AppConstants.LLAMA_MAX_TOKENS
HTTP_TIMEOUT_S: int = AppConstants.LLAMA_HTTP_TIMEOUT_S

# Istanza condivisa del preprocessor (è stateless, quindi thread-safe).
_preprocessor = ImagePreprocessor()


def ocr_single_image(
    image_path: Path, server_url: str,
) -> tuple[str, float]:
    """Elabora una singola immagine tramite l'API di llama-server.

    Applica la stessa pipeline di pre-elaborazione usata per i PDF
    (ridimensionamento + miglioramento contrasto) prima di inviare
    l'immagine al modello, garantendo un comportamento coerente.

    Args:
        image_path: Percorso del file immagine.
        server_url: URL base del server llama.cpp.

    Returns:
        Tupla (testo estratto, confidenza).
    """
    import numpy as np

    image = load_image(image_path)
    img_array = np.array(image)
    enhanced = _preprocessor.enhance(img_array)
    image = array_to_pil(enhanced)
    return ocr_image_api(image, server_url)


def ocr_pdf(
    pdf_path: Path, server_url: str,
) -> tuple[str, float]:
    """Elabora un PDF pagina per pagina tramite llama-server.

    Ogni pagina viene convertita in immagine una alla volta per
    ridurre l'uso di RAM, essenziale su GPU integrate.

    Dopo ogni pagina completata, emette l'evento ``pdf_page_completed``
    sull'EventBus con il testo estratto, in modo che la GUI possa
    mostrare i risultati incrementalmente (checkpoint per PDF lunghi).

    Emette anche ``pdf_progress`` con il numero di pagina corrente
    e il totale, per aggiornare la barra di stato.

    Args:
        pdf_path: Percorso del file PDF.
        server_url: URL base del server llama.cpp.

    Returns:
        Tupla (testo combinato di tutte le pagine, confidenza media).

    Raises:
        ImageLoadError: Se il PDF non contiene pagine.
    """
    import numpy as np

    total_pages = pdf_page_count(pdf_path)
    if total_pages == 0:
        raise ImageLoadError(str(pdf_path), "Il PDF non contiene pagine")

    logger.info("Elaborazione PDF %s: %d pagine (llama.cpp)", pdf_path.name, total_pages)

    all_text_parts: list[str] = []
    total_confidence = 0.0

    for page_num in range(1, total_pages + 1):
        page_start = time.perf_counter()
        logger.info("Elaborazione pagina %d/%d di %s", page_num, total_pages, pdf_path.name)

        # Notifica la GUI dell'avanzamento prima di elaborare la pagina
        EventBus.emit("pdf_progress", {
            "page_num": page_num,
            "total_pages": total_pages,
            "pdf_path": str(pdf_path),
        })

        page_image = pdf_page_to_image(pdf_path, page_num, dpi=150)
        if page_image is None:
            page_text = "[Errore: conversione fallita]"
            all_text_parts.append(f"--- Pagina {page_num} ---\n{page_text}")
            # Emetti anche per le pagine fallite, così la GUI conta i checkpoint
            EventBus.emit("pdf_page_completed", {
                "page_num": page_num,
                "total_pages": total_pages,
                "text": page_text,
                "confidence": 0.0,
                "pdf_path": str(pdf_path),
            })
            continue

        img_array = np.array(page_image)
        enhanced = _preprocessor.enhance(img_array)
        image = array_to_pil(enhanced)
        del img_array, enhanced, page_image
        gc.collect()

        text, confidence = ocr_image_api(image, server_url)
        del image
        gc.collect()

        page_elapsed = time.perf_counter() - page_start
        logger.info("Pagina %d/%d completata in %.1fs", page_num, total_pages, page_elapsed)

        if total_pages > 1:
            all_text_parts.append(f"--- Pagina {page_num} ---\n{text}")
        else:
            all_text_parts.append(text)
        total_confidence += confidence

        # Checkpoint: emetti il testo della pagina appena completata
        # così la GUI può mostrarla subito senza aspettare la fine del PDF
        EventBus.emit("pdf_page_completed", {
            "page_num": page_num,
            "total_pages": total_pages,
            "text": text,
            "confidence": confidence,
            "pdf_path": str(pdf_path),
        })

    combined_text = "\n\n".join(all_text_parts)
    avg_confidence = total_confidence / total_pages if total_pages else 0.0
    return combined_text, avg_confidence


def ocr_image_api(image: Any, server_url: str) -> tuple[str, float]:
    """Esegue OCR su un'immagine PIL tramite l'API REST di llama-server.

    Usa la modalita' non-streaming con timeout ampio (600s).
    Il modello vision deve prima codificare l'immagine e poi generare
    i token, quindi il tempo di risposta puo' variare da 20s a 120s
    per pagina a seconda della densita' del testo.

    Args:
        image: Immagine PIL da elaborare.
        server_url: URL base del server llama.cpp.

    Returns:
        Tupla (testo estratto, confidenza).

    Raises:
        RuntimeError: Se la comunicazione o la risposta falliscono.
    """
    from PIL import Image as PILImage

    if image.mode != "RGB":
        image = image.convert("RGB")

    # Ridimensiona per performance
    w, h = image.size
    if max(w, h) > MAX_IMAGE_DIM:
        scale = MAX_IMAGE_DIM / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        image = image.resize((new_w, new_h), PILImage.LANCZOS)
        logger.info("Ridimensionamento immagine %dx%d → %dx%d", w, h, new_w, new_h)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    img_url = f"data:image/jpeg;base64,{img_b64}"

    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": img_url}},
                {"type": "text", "text": OCR_PROMPT},
            ],
        }],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
    }

    t_start = time.perf_counter()
    try:
        req = Request(
            f"{server_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Errore comunicazione con llama-server: {exc}") from exc

    elapsed = time.perf_counter() - t_start

    text = ""
    try:
        text = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        logger.error("Risposta inattesa da llama-server: %s", json.dumps(result)[:500])
        raise RuntimeError(f"Risposta inattesa da llama-server: {exc}") from exc

    usage = result.get("usage", {})
    n_tokens = usage.get("completion_tokens", 0)
    tokens_per_sec = n_tokens / elapsed if elapsed > 0 else 0
    logger.info("llama.cpp: %d token in %.1fs (%.1f token/s)", n_tokens, elapsed, tokens_per_sec)

    confidence = 0.9 if len(text.strip()) > 0 else 0.1
    return text.strip(), confidence
