# core/image_preprocessor.py
"""Pre-elaborazione immagini per migliorare la qualità OCR.

Questo modulo fornisce operazioni di pre-elaborazione sulle immagini
prima dell'invio al motore OCR. Le operazioni includono ridimensionamento,
binarizzazione, correzione della rotazione e miglioramento del contrasto.
Tutte le operazioni usano NumPy vettorizzato per prestazioni ottimali.
"""

from __future__ import annotations

import logging

import numpy as np
from numpy.typing import NDArray

from config.constants import AppConstants

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """Pre-elaboratore di immagini per l'OCR con operazioni NumPy vettorizzate.

    Fornisce metodi per migliorare la qualità delle immagini prima
    dell'elaborazione OCR. Tutte le operazioni usano NumPy puro
    senza dipendenze da OpenCV, OpenVINO o altri framework esterni.

    Attributi:
        _enabled: Flag che indica se la pre-elaborazione è attiva.
    """

    def __init__(self) -> None:
        """Inizializza il pre-elaboratore."""
        self._enabled: bool = True
        logger.info("Pre-elaboratore immagini inizializzato (NumPy puro)")

    def enhance(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Applica il pipeline completo di miglioramento dell'immagine.

        Il pipeline include: ridimensionamento se necessario, miglioramento
        del contrasto tramite equalizzazione dell'istogramma (canale
        luminanza), e conversione in scala di grigi se opportuno.

        Args:
            image: Array NumPy dell'immagine (H, W, C) in formato BGR/RGB.

        Returns:
            Array NumPy dell'immagine migliorata.
        """
        result = image.copy()
        result = self._resize_if_needed(result)
        result = self._enhance_contrast(result)
        logger.debug(
            "Immagine migliorata: shape=%s, dtype=%s",
            result.shape, result.dtype,
        )
        return result

    def binarize(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Applica la binarizzazione adattiva per testo su sfondo uniforme.

        Utilizza la soglia di Otsu implementata in NumPy per produrre
        un'immagine bianco/nero che massimizza il contrasto del testo.

        Args:
            image: Array NumPy dell'immagine in scala di grigi (H, W).

        Returns:
            Array NumPy binarizzato (0 o 255).
        """
        if image.ndim == 3:
            gray = self._to_grayscale(image)
        else:
            gray = image
        threshold = self._otsu_threshold(gray)
        binary = np.where(gray > threshold, np.uint8(255), np.uint8(0))
        logger.debug("Binarizzazione completata: soglia=%d", int(threshold))
        return binary

    def _resize_if_needed(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Ridimensiona l'immagine se supera la dimensione massima.

        Args:
            image: Array NumPy dell'immagine.

        Returns:
            Array NumPy ridimensionato se necessario, altrimenti invariato.
        """
        h, w = image.shape[:2]
        max_dim = AppConstants.PREPROCESS_MAX_DIMENSION
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            image = self._resize_nearest(image, new_h, new_w)
            logger.debug("Ridimensionamento: %dx%d → %dx%d", w, h, new_w, new_h)
        return image

    @staticmethod
    def _resize_nearest(
        image: NDArray[np.uint8], new_h: int, new_w: int,
    ) -> NDArray[np.uint8]:
        """Ridimensiona l'immagine con interpolazione nearest-neighbor.

        Implementazione pura NumPy senza dipendenze da OpenCV.

        Args:
            image: Array NumPy dell'immagine originale.
            new_h: Nuova altezza.
            new_w: Nuova larghezza.

        Returns:
            Array NumPy dell'immagine ridimensionata.
        """
        h, w = image.shape[:2]
        row_indices = (np.arange(new_h) * h / new_h).astype(int)
        col_indices = (np.arange(new_w) * w / new_w).astype(int)
        row_indices = np.clip(row_indices, 0, h - 1)
        col_indices = np.clip(col_indices, 0, w - 1)
        return image[np.ix_(row_indices, col_indices)]

    def _enhance_contrast(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Migliora il contrasto dell'immagine tramite normalizzazione istogramma.

        Implementazione semplificata che normalizza l'istogramma
        della luminanza per migliorare la leggibilità del testo.
        Per le immagini a colori, applica la normalizzazione sulla
        luminanza e proporzionalmente agli altri canali.

        Args:
            image: Array NumPy dell'immagine (H, W) o (H, W, C).

        Returns:
            Array NumPy con contrasto migliorato, stesso shape dell'input.
        """
        if image.ndim == 2:
            return self._normalize_histogram(image)

        # Calcola la luminanza una sola volta (pesi BT.601).
        gray = self._to_grayscale(image)
        enhanced_gray = self._normalize_histogram(gray)

        # Applica il rapporto enhanced/original ai canali RGB,
        # preservando il bilanciamento cromatico.
        luminance = gray.astype(np.float32)
        luminance = np.maximum(luminance, 1.0)
        ratio = np.clip(enhanced_gray.astype(np.float32) / luminance, 0.5, 2.0)
        result = np.clip(
            image.astype(np.float32) * ratio[:, :, np.newaxis],
            0, 255,
        ).astype(np.uint8)
        return result

    @staticmethod
    def _normalize_histogram(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Normalizza l'istogramma di un'immagine in scala di grigi.

        Args:
            image: Array NumPy 2D in scala di grigi.

        Returns:
            Array NumPy con istogramma normalizzato.
        """
        min_val = image.min()
        max_val = image.max()
        if max_val == min_val:
            return image
        normalized = ((image.astype(np.float32) - min_val) /
                      (max_val - min_val) * 255.0)
        return normalized.astype(np.uint8)

    @staticmethod
    def _to_grayscale(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Converte un'immagine BGR/RGB in scala di grigi.

        Usa i pesi della luminanza ITU-R BT.601.

        Args:
            image: Array NumPy (H, W, 3) in formato BGR o RGB.

        Returns:
            Array NumPy (H, W) in scala di grigi.
        """
        if image.ndim == 2:
            return image
        weights = np.array([0.114, 0.587, 0.299], dtype=np.float32)
        gray = np.dot(image.astype(np.float32), weights)
        return np.clip(gray, 0, 255).astype(np.uint8)

    @staticmethod
    def _otsu_threshold(image: NDArray[np.uint8]) -> float:
        """Calcola la soglia di Otsu per la binarizzazione.

        Implementazione pura NumPy dell'algoritmo di Otsu che massimizza
        la varianza tra classi per trovare la soglia ottimale.

        Args:
            image: Array NumPy 2D in scala di grigi.

        Returns:
            Valore di soglia ottimale.
        """
        histogram = np.bincount(image.ravel(), minlength=256).astype(np.float32)
        total = image.size
        if total == 0:
            return 128.0
        sum_total = np.dot(np.arange(256), histogram)
        sum_bg = 0.0
        weight_bg = 0.0
        max_variance = 0.0
        best_threshold = 0.0
        for t in range(256):
            weight_bg += histogram[t]
            if weight_bg == 0:
                continue
            weight_fg = total - weight_bg
            if weight_fg == 0:
                break
            sum_bg += t * histogram[t]
            mean_bg = sum_bg / weight_bg
            mean_fg = (sum_total - sum_bg) / weight_fg
            variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
            if variance > max_variance:
                max_variance = variance
                best_threshold = float(t)
        return best_threshold
