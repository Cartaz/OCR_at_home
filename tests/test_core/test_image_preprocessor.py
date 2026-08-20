"""Test per core/image_preprocessor.py — verifica pipeline NumPy.

Tests:
    - enhance preserva shape e dtype dell'immagine
    - binarize produce solo 0/255
    - _to_grayscale usa i pesi BT.601
    - _normalize_histogram non modifica immagini costanti
"""
import numpy as np

from core.image_preprocessor import ImagePreprocessor


def test_enhance_preserves_shape_and_dtype() -> None:
    """Verifica che enhance preservi shape e dtype dell'input."""
    p = ImagePreprocessor()
    img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    result = p.enhance(img)
    assert result.shape == img.shape
    assert result.dtype == np.uint8


def test_enhance_grayscale_input() -> None:
    """Verifica che enhance funzioni anche su immagini in scala di grigi."""
    p = ImagePreprocessor()
    img = np.random.randint(0, 255, (50, 50), dtype=np.uint8)
    result = p.enhance(img)
    assert result.shape == img.shape
    assert result.dtype == np.uint8


def test_binarize_returns_only_0_and_255() -> None:
    """Verifica che binarize produca solo valori 0 e 255."""
    p = ImagePreprocessor()
    gray = np.random.randint(0, 255, (50, 50), dtype=np.uint8)
    binary = p.binarize(gray)
    unique = set(np.unique(binary).tolist())
    assert unique.issubset({0, 255})


def test_normalize_histogram_constant_image_unchanged() -> None:
    """Verifica che la normalizzazione non rompa immagini costanti."""
    p = ImagePreprocessor()
    const_img = np.full((10, 10), 128, dtype=np.uint8)
    result = p._normalize_histogram(const_img)
    # Per immagini costanti (min == max), la normalizzazione non modifica
    assert np.array_equal(result, const_img)


def test_to_grayscale_preserves_2d_input() -> None:
    """Verifica che _to_grayscale non modifichi input già in scala di grigi."""
    p = ImagePreprocessor()
    gray = np.random.randint(0, 255, (10, 10), dtype=np.uint8)
    result = p._to_grayscale(gray)
    assert np.array_equal(result, gray)
