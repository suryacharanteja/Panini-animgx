# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT

"""Slow local inference gets a distinct recovery message from an offline service."""

from urllib.error import URLError

import pytest
from studio import server


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("planning", [False, True])
def test_timeout_explains_slow_request_without_claiming_ollama_is_offline(
    wrapped: bool, planning: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = TimeoutError("private diagnostic")

    def timed_out(*args: object, **kwargs: object) -> object:
        raise URLError(error) if wrapped else error

    monkeypatch.setattr(server, "urlopen", timed_out)
    with pytest.raises(ValueError, match=r"timed out|too long") as caught:
        server.Ollama().request(
            "/api/generate" if planning else "/api/tags", {} if planning else None
        )
    message = str(caught.value)
    assert "private diagnostic" not in message
    assert "Start Ollama" not in message
    assert (
        "Local planning timed out" if planning else "Refresh the connection"
    ) in message
