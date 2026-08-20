"""Test cancellazione cooperativa del download modelli."""

from pathlib import Path

import pytest

from core.cancellation import CancellationToken
from core.exceptions import OperationCancelledError
import core.llama_models as llama_models


def test_cancel_before_download_propagates_cancellation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(llama_models, "GGUF_CACHE_DIR", tmp_path)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        llama_models.ensure_gguf_models(cancel_token=token)
