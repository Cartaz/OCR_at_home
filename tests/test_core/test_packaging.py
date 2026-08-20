"""Test che il packaging punti al repository e runtime corretti."""

from pathlib import Path


def test_pkgbuild_uses_real_repository_and_system_python() -> None:
    text = (Path(__file__).parents[2] / "PKGBUILD").read_text(encoding="utf-8")
    assert "Cartaz/OCR_at_home" in text
    assert "/usr/bin/python /usr/share/glm-ocr/main.py" in text
    assert ".venv/bin/python /opt/glm-ocr/main.py" not in text
