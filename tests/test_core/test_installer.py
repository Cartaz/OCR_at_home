"""Regressioni per install.sh e build SYCL riproducibile."""

from pathlib import Path
import re


def _installer_text() -> str:
    return (Path(__file__).parents[2] / "install.sh").read_text(encoding="utf-8")


def test_installer_pins_llama_cpp_and_uses_sycl() -> None:
    text = _installer_text()
    assert 'LLAMA_CPP_COMMIT="07822bddf80d73f1168e592c52e69caaff820f9c"' in text
    assert re.search(
        r"(?m)^\s*git(?:\s+-C\s+\S+)?\s+pull(?:\s|$)",
        text,
    ) is None
    assert "-DGGML_SYCL=ON" in text


def test_installer_sources_oneapi_without_nounset() -> None:
    text = _installer_text()
    build_block = text.split('if ! bash -c "', 1)[1].split('"; then', 1)[0]
    assert "set -eo pipefail" in build_block
    assert "set -euo pipefail" not in build_block
    assert "OCL_ICD_FILENAMES" in build_block


def test_installer_requires_verified_sycl_device() -> None:
    text = _installer_text()
    assert "venv_llama_sycl_works" in text
    assert "--list-devices" in text
    assert "SYCL[0-9]+" in text
    assert "CPU e Vulkan non sono fallback consentiti" in text
    assert "command -v llama-server" not in text
    assert re.search(
        r"nessun llama-server SYCL funzionante disponibile\.[\s\S]{0,250}?exit 1",
        text,
        flags=re.IGNORECASE,
    ) is not None
