"""Test della pipeline NumPy di pre-elaborazione."""

import numpy as np

from core.image_preprocessor import ImagePreprocessor


def test_enhance_preserves_shape_and_dtype_when_no_resize() -> None:
    preprocessor = ImagePreprocessor()
    image = np.random.default_rng(1).integers(
        0, 255, (100, 100, 3), dtype=np.uint8
    )
    result = preprocessor.enhance(image)
    assert result.shape == image.shape
    assert result.dtype == np.uint8


def test_enhance_grayscale_input() -> None:
    preprocessor = ImagePreprocessor()
    image = np.random.default_rng(2).integers(
        0, 255, (50, 50), dtype=np.uint8
    )
    result = preprocessor.enhance(image)
    assert result.shape == image.shape
    assert result.dtype == np.uint8


def test_binarize_returns_only_zero_and_255() -> None:
    preprocessor = ImagePreprocessor()
    gray = np.random.default_rng(3).integers(
        0, 255, (50, 50), dtype=np.uint8
    )
    binary = preprocessor.binarize(gray)
    assert set(np.unique(binary).tolist()).issubset({0, 255})


def test_normalize_histogram_constant_image_unchanged() -> None:
    preprocessor = ImagePreprocessor()
    image = np.full((10, 10), 128, dtype=np.uint8)
    assert np.array_equal(preprocessor._normalize_histogram(image), image)


def test_to_grayscale_preserves_2d_input() -> None:
    preprocessor = ImagePreprocessor()
    gray = np.arange(100, dtype=np.uint8).reshape(10, 10)
    assert np.array_equal(preprocessor._to_grayscale(gray), gray)


def test_to_grayscale_uses_rgb_bt601_channel_order() -> None:
    preprocessor = ImagePreprocessor()
    # Pillow -> np.array produce RGB, non BGR.
    pixels = np.array([[[255, 0, 0], [0, 0, 255]]], dtype=np.uint8)
    gray = preprocessor._to_grayscale(pixels)
    assert 75 <= int(gray[0, 0]) <= 77   # 0.299 * 255
    assert 28 <= int(gray[0, 1]) <= 30   # 0.114 * 255
