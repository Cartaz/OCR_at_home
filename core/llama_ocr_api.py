"""Elaborazione OCR tramite API REST locale di llama-server."""

from __future__ import annotations

import base64
import gc
import http.client
import io
import json
import logging
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config.constants import AppConstants
from core.cancellation import CancellationToken
from core.event_bus import EventBus
from core.exceptions import ImageLoadError, OperationCancelledError
from core.image_preprocessor import ImagePreprocessor
from core.image_utils import array_to_pil, load_image, pdf_page_count, pdf_page_to_image

logger = logging.getLogger(__name__)

# Keep the existing production default unchanged until the prompt benchmark has
# been run on the target SYCL hardware. The task-specific values below are the
# prompts defined by the official zai-org/GLM-OCR pipeline/training examples.
PROMPT_LEGACY_OCR = "OCR"
PROMPT_TEXT_RECOGNITION = "Text Recognition:"
PROMPT_TABLE_RECOGNITION = "Table Recognition:"
PROMPT_FORMULA_RECOGNITION = "Formula Recognition:"
OCR_PROMPT = PROMPT_LEGACY_OCR

MAX_IMAGE_DIM = AppConstants.LLAMA_MAX_IMAGE_DIM
JPEG_QUALITY = AppConstants.LLAMA_JPEG_QUALITY
MAX_TOKENS = AppConstants.LLAMA_MAX_TOKENS
HTTP_TIMEOUT_S = AppConstants.LLAMA_HTTP_TIMEOUT_S
_preprocessor = ImagePreprocessor()


def _check_cancel(token: CancellationToken | None) -> None:
    if token is not None:
        token.raise_if_cancelled()


def ocr_single_image(
    image_path: Path,
    server_url: str,
    *,
    preprocessing_enabled: bool = True,
    cancel_token: CancellationToken | None = None,
    prompt: str = OCR_PROMPT,
) -> tuple[str, float | None]:
    import numpy as np

    _check_cancel(cancel_token)
    image = load_image(image_path)
    if preprocessing_enabled:
        image = array_to_pil(_preprocessor.enhance(np.array(image)))
    _check_cancel(cancel_token)
    return ocr_image_api(
        image,
        server_url,
        cancel_token=cancel_token,
        prompt=prompt,
    )


def ocr_pdf(
    pdf_path: Path,
    server_url: str,
    *,
    preprocessing_enabled: bool = True,
    cancel_token: CancellationToken | None = None,
    emit_events: bool = True,
    event_mode: str = "single",
    prompt: str = OCR_PROMPT,
) -> tuple[str, float | None]:
    import numpy as np

    total_pages = pdf_page_count(pdf_path)
    if total_pages == 0:
        raise ImageLoadError(str(pdf_path), "Il PDF non contiene pagine")

    all_text_parts: list[str] = []
    for page_num in range(1, total_pages + 1):
        _check_cancel(cancel_token)
        if emit_events:
            EventBus.emit(
                "pdf_progress",
                {
                    "mode": event_mode,
                    "page_num": page_num,
                    "total_pages": total_pages,
                    "pdf_path": str(pdf_path),
                },
            )

        page_image = pdf_page_to_image(pdf_path, page_num, dpi=150)
        _check_cancel(cancel_token)
        if preprocessing_enabled:
            image = array_to_pil(_preprocessor.enhance(np.array(page_image)))
            del page_image
        else:
            image = page_image
        gc.collect()

        text, _confidence = ocr_image_api(
            image,
            server_url,
            cancel_token=cancel_token,
            prompt=prompt,
        )
        del image
        gc.collect()
        _check_cancel(cancel_token)

        all_text_parts.append(
            f"--- Pagina {page_num} ---\n{text}" if total_pages > 1 else text
        )
        if emit_events:
            EventBus.emit(
                "pdf_page_completed",
                {
                    "mode": event_mode,
                    "page_num": page_num,
                    "total_pages": total_pages,
                    "text": text,
                    "pdf_path": str(pdf_path),
                },
            )

    # llama-server/GLM-OCR does not expose a calibrated OCR confidence score.
    return "\n\n".join(all_text_parts), None


def ocr_image_api(
    image: Any,
    server_url: str,
    *,
    cancel_token: CancellationToken | None = None,
    prompt: str = OCR_PROMPT,
) -> tuple[str, float | None]:
    from PIL import Image as PILImage

    _check_cancel(cancel_token)
    if image.mode != "RGB":
        image = image.convert("RGB")
    w, h = image.size
    if max(w, h) > MAX_IMAGE_DIM:
        scale = MAX_IMAGE_DIM / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    },
                    {"type": "text", "text": str(prompt)},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
    }

    parsed = urlparse(server_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise RuntimeError(f"URL llama-server non valido: {server_url}")
    conn = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port or 80,
        timeout=HTTP_TIMEOUT_S,
    )

    def abort_connection() -> None:
        try:
            sock = conn.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    if cancel_token is not None:
        cancel_token.register_closer(abort_connection)

    t_start = time.perf_counter()
    try:
        _check_cancel(cancel_token)
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        raw = response.read()
        _check_cancel(cancel_token)
        if not 200 <= response.status < 300:
            raise RuntimeError(
                f"llama-server HTTP {response.status}: "
                f"{raw.decode('utf-8', errors='replace')[:500]}"
            )
        result = json.loads(raw.decode("utf-8"))
    except OperationCancelledError:
        raise
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        if cancel_token is not None and cancel_token.is_cancelled:
            raise OperationCancelledError() from exc
        raise RuntimeError(f"Errore comunicazione con llama-server: {exc}") from exc
    finally:
        if cancel_token is not None:
            cancel_token.unregister_closer(abort_connection)
        abort_connection()

    try:
        text = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Risposta inattesa da llama-server: {exc}") from exc

    elapsed = time.perf_counter() - t_start
    usage = result.get("usage", {})
    timings = result.get("timings", {}) or {}

    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    predicted_n = int(
        timings.get("predicted_n", completion_tokens) or completion_tokens
    )
    prompt_n = int(timings.get("prompt_n", prompt_tokens) or prompt_tokens)
    cache_n = int(timings.get("cache_n", 0) or 0)
    predicted_ms = float(timings.get("predicted_ms", 0.0) or 0.0)
    prompt_ms = float(timings.get("prompt_ms", 0.0) or 0.0)
    predicted_tps = float(timings.get("predicted_per_second", 0.0) or 0.0)
    prompt_tps = float(timings.get("prompt_per_second", 0.0) or 0.0)

    if predicted_tps <= 0.0 and predicted_ms > 0.0:
        predicted_tps = predicted_n / (predicted_ms / 1000.0)
    if prompt_tps <= 0.0 and prompt_ms > 0.0:
        prompt_tps = prompt_n / (prompt_ms / 1000.0)

    accounted = (predicted_ms + prompt_ms) / 1000.0
    other_s = max(0.0, elapsed - accounted)

    if timings:
        logger.info(
            "llama.cpp timings: generation=%d tok %.1fs (%.1f tok/s); "
            "prompt=%d tok + %d cached %.1fs (%.1f tok/s); "
            "vision/overhead≈%.1fs; request=%.1fs",
            predicted_n,
            predicted_ms / 1000.0,
            predicted_tps,
            prompt_n,
            cache_n,
            prompt_ms / 1000.0,
            prompt_tps,
            other_s,
            elapsed,
        )
    else:
        logger.info(
            "llama.cpp: %d completion token in %.1fs total request "
            "(server timings non disponibili)",
            completion_tokens,
            elapsed,
        )

    text = str(text).strip()
    # GLM-OCR through llama.cpp returns generated text, not a calibrated
    # confidence probability. Returning None prevents the UI/integrations from
    # presenting an invented percentage as model output.
    return text, None
