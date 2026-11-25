"""Pre-elaborazione immagini NumPy per migliorare la qualità OCR."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from config.constants import OCRDefaults

PREPROCESS_MODES: frozenset[str] = frozenset({"none", "contrast", "resize", "full"})


class ImagePreprocessor:
    def enhance(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Production preprocessing: resize-if-needed followed by contrast enhancement."""
        return self.apply_mode(image, "full")

    def apply_mode(
        self,
        image: NDArray[np.uint8],
        mode: str,
    ) -> NDArray[np.uint8]:
        """Apply one explicit preprocessing mode.

        The extra modes are used by the hardware benchmark so resize and
        contrast can be measured independently. ``full`` is the production path.
        """
        normalized = str(mode).strip().lower()
        if normalized not in PREPROCESS_MODES:
            raise ValueError(
                f"Modalità preprocessing non supportata: {mode!r}; "
                f"attese {sorted(PREPROCESS_MODES)}"
            )

        result = image.copy()
        if normalized in {"resize", "full"}:
            result = self._resize_if_needed(result)
        if normalized in {"contrast", "full"}:
            result = self._enhance_contrast(result)
        return result

    def _resize_if_needed(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        h, w = image.shape[:2]
        max_dim = OCRDefaults.PREPROCESS_MAX_DIMENSION
        if max(h, w) <= max_dim:
            return image
        scale = max_dim / max(h, w)
        return self._resize_nearest(image, int(h * scale), int(w * scale))

    @staticmethod
    def _resize_nearest(image: NDArray[np.uint8], new_h: int, new_w: int) -> NDArray[np.uint8]:
        h, w = image.shape[:2]
        rows = np.clip((np.arange(new_h) * h / new_h).astype(int), 0, h - 1)
        cols = np.clip((np.arange(new_w) * w / new_w).astype(int), 0, w - 1)
        return image[np.ix_(rows, cols)]

    def _enhance_contrast(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        if image.ndim == 2:
            return self._normalize_histogram(image)
        gray = self._to_grayscale(image)
        enhanced_gray = self._normalize_histogram(gray)
        luminance = np.maximum(gray.astype(np.float32), 1.0)
        ratio = np.clip(enhanced_gray.astype(np.float32) / luminance, 0.5, 2.0)
        return np.clip(image.astype(np.float32) * ratio[:, :, np.newaxis], 0, 255).astype(np.uint8)

    @staticmethod
    def _normalize_histogram(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        min_val = image.min()
        max_val = image.max()
        if max_val == min_val:
            return image
        return ((image.astype(np.float32) - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)

    @staticmethod
    def _to_grayscale(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        if image.ndim == 2:
            return image
        # Gli array arrivano da Pillow in RGB: BT.601 = R,G,B.
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        gray = np.dot(image.astype(np.float32), weights)
        return np.clip(gray, 0, 255).astype(np.uint8)
