"""Test che install.sh usi un pin riproducibile di llama.cpp."""

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
