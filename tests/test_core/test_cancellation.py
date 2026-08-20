"""Test delle primitive di cancellazione cooperative."""

import pytest

from core.cancellation import CancellationToken
from core.exceptions import OperationCancelledError


def test_cancel_is_idempotent_and_calls_closer_once() -> None:
    token = CancellationToken()
    calls: list[int] = []
    token.register_closer(lambda: calls.append(1))
    token.cancel()
    token.cancel()
    assert calls == [1]
    with pytest.raises(OperationCancelledError):
        token.raise_if_cancelled()
