"""Regressioni per install.sh e build SYCL riproducibile."""

from pathlib import Path
import re


def test_installer_pins_llama_cpp_and_uses_current_sycl_option() -> None:
    text = (Path(__file__).parents[2] / "install.sh").read_text(encoding="utf-8")
    assert 'LLAMA_CPP_COMMIT="07822bddf80d73f1168e592c52e69caaff820f9c"' in text
    # Verifica l'assenza di un comando `git pull`, senza farsi ingannare da
    # commenti/documentazione che possono citarne letteralmente il nome.
    assert re.search(
        r"(?m)^\s*git(?:\s+-C\s+\S+)?\s+pull(?:\s|$)",
        text,
    ) is None
    assert "-DGGML_SYCL=ON" in text


def test_installer_sources_oneapi_without_nounset() -> None:
    text = (Path(__file__).parents[2] / "install.sh").read_text(encoding="utf-8")
    # oneAPI setvars.sh usa variabili opzionali non necessariamente definite;
    # il sottoprocesso di build non deve quindi abilitare `set -u`.
    build_block = text.split('if ! bash -c "', 1)[1].split('"; then', 1)[0]
    assert "set -eo pipefail" in build_block
    assert "set -euo pipefail" not in build_block
    assert "OCL_ICD_FILENAMES" in build_block


def test_installer_fails_when_no_llama_server_exists() -> None:
    text = (Path(__file__).parents[2] / "install.sh").read_text(encoding="utf-8")
    assert "Installazione incompleta: nessun llama-server eseguibile disponibile." in text
    assert re.search(
        r"Installazione incompleta: nessun llama-server eseguibile disponibile\.[\s\S]{0,300}?exit 1",
        text,
    ) is not None
