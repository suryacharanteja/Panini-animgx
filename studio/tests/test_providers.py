# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Provider settings and mocked network contracts keep credentials out of drafts."""

from __future__ import annotations

import io
import json
import socket
from email.message import Message
from pathlib import Path
from typing import cast
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from studio import providers

SECRET = "test-session-secret-do-not-persist"
ENVIRONMENT_SECRET = "test-environment-secret-do-not-echo"


@pytest.fixture
def settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> providers.ProviderSettings:
    """Start every provider test without credentials inherited from the machine."""
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "COMPATIBLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return providers.ProviderSettings(tmp_path)


def _entry(snapshot: dict[str, object], provider: str) -> dict[str, object]:
    rows = cast(list[dict[str, object]], snapshot["providers"])
    return next(row for row in rows if row["id"] == provider)


def _configure(settings: providers.ProviderSettings, provider: str) -> None:
    data: dict[str, object] = {"provider": provider, "api_key": SECRET}
    if provider == "compatible":
        data["base_url"] = "https://models.example/v1"
        data["model"] = "example-model"
    settings.update(data)


def _public_dns(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


class JsonResponse(io.BytesIO):
    """Behave like the bounded response reader without opening a network socket."""

    def __init__(self, value: object) -> None:
        super().__init__(json.dumps(value).encode())

    def __enter__(self) -> JsonResponse:
        return self


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Replace only the outbound socket transport; inspect real provider requests."""
    opener = Mock()
    monkeypatch.setattr(providers, "build_opener", Mock(return_value=opener))
    monkeypatch.setattr(providers.socket, "getaddrinfo", _public_dns)
    return opener


def _request(opener: Mock) -> Request:
    return cast(Request, opener.open.call_args.args[0])


def _payload(request: Request) -> dict[str, object]:
    assert isinstance(request.data, bytes)
    return cast(dict[str, object], json.loads(request.data))


def _headers(request: Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.header_items()}


def _error_headers(location: str | None = None) -> Message:
    headers = Message()
    if location is not None:
        headers["Location"] = location
    return headers


def _generate(
    planner: providers.Planner, provider: str, model: str = "example-model"
) -> str:
    return planner.generate(
        provider,
        model,
        "Produce a mathematical storyboard with matching equations.",
        "Explain the derivative of x squared.",
        {"type": "object", "properties": {"title": {"type": "string"}}},
    )


def test_default_provider_is_local_and_cloud_keys_are_optional(
    settings: providers.ProviderSettings,
) -> None:
    snapshot = settings.snapshot()
    assert snapshot["active_provider"] == "ollama"
    assert {
        row["id"] for row in cast(list[dict[str, object]], snapshot["providers"])
    } == {
        "ollama",
        "openai",
        "gemini",
        "compatible",
    }
    assert _entry(snapshot, "ollama")["configured"] is True
    for provider in ("openai", "gemini", "compatible"):
        assert _entry(snapshot, provider)["key_set"] is False
        assert settings.configured(provider) is False


def test_session_keys_never_enter_snapshots_or_preferences(
    settings: providers.ProviderSettings,
    tmp_path: Path,
) -> None:
    snapshot = settings.update(
        {
            "provider": "openai",
            "model": "test-reasoner",
            "api_key": SECRET,
            "active_provider": "openai",
        }
    )
    assert snapshot["active_provider"] == "openai"
    assert _entry(snapshot, "openai")["key_source"] == "session"
    assert SECRET not in json.dumps(snapshot)
    assert settings.configured("openai") is True
    preferences = list(tmp_path.rglob("*.json"))
    assert preferences
    for path in preferences:
        text = path.read_text(encoding="utf-8")
        assert SECRET not in text
        assert "test-reasoner" in text
    restarted = providers.ProviderSettings(tmp_path)
    assert restarted.model("openai") == "test-reasoner"
    assert restarted.snapshot()["active_provider"] == "openai"
    assert restarted.configured("openai") is False
    assert _entry(restarted.snapshot(), "openai")["key_source"] == "none"


def test_empty_password_preserves_session_key_and_explicit_clear_removes_it(
    settings: providers.ProviderSettings,
) -> None:
    _configure(settings, "gemini")
    settings.update({"provider": "gemini", "model": "new-model", "api_key": ""})
    assert settings.configured("gemini") is True
    cleared = settings.update({"provider": "gemini", "clear_key": True})
    assert settings.configured("gemini") is False
    assert _entry(cleared, "gemini")["key_source"] == "none"
    assert SECRET not in json.dumps(cleared)


@pytest.mark.parametrize(
    ("provider", "variable"),
    [
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
        ("compatible", "COMPATIBLE_API_KEY"),
    ],
)
def test_clear_environment_key_suppresses_it_for_this_session(
    settings: providers.ProviderSettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider: str,
    variable: str,
) -> None:
    monkeypatch.setenv(variable, ENVIRONMENT_SECRET)
    if provider == "compatible":
        settings.update(
            {
                "provider": provider,
                "model": "example-model",
                "base_url": "https://models.example/v1",
            }
        )
    snapshot = settings.snapshot()
    assert _entry(snapshot, provider)["key_source"] == "environment"
    assert ENVIRONMENT_SECRET not in json.dumps(snapshot)
    settings.update({"provider": provider, "clear_key": True})
    assert settings.configured(provider) is False
    assert _entry(settings.snapshot(), provider)["key_source"] == "none"
    assert providers.ProviderSettings(tmp_path).configured(provider) is True


@pytest.mark.parametrize(
    "data",
    [
        {"provider": "unknown"},
        {"provider": []},
        {"provider": "openai", "model": ""},
        {"provider": "openai", "model": "x" * 201},
        {"provider": "openai", "model": "model\nheader"},
        {"provider": "openai", "api_key": "key\nheader"},
        {"provider": "openai", "api_key": 123},
        {"provider": "openai", "api_key": "clé-é"},
        {"provider": "openai", "api_key": "secret🔑"},
        {"provider": "openai", "api_key": "x" * 4097},
        {"provider": "openai", "clear_key": "yes"},
        {"provider": "openai", "active_provider": "unknown"},
    ],
)
def test_invalid_preferences_fail_atomically_without_disclosing_credentials(
    settings: providers.ProviderSettings,
    data: dict[str, object],
) -> None:
    _configure(settings, "openai")
    original = settings.snapshot()
    with pytest.raises(ValueError, match=r"Choose|Model|API key|clear_key") as error:
        settings.update(data)
    assert SECRET not in str(error.value)
    assert settings.snapshot() == original


@pytest.mark.parametrize(
    "url",
    [
        "https://models.example/v1?api_key=secret",
        "https://models.example/v1#fragment",
        "https://user:password@models.example/v1",
        "ftp://models.example/v1",
        "http://models.example/v1",
        "http://192.168.1.2/v1",
        "http://10.0.0.1/v1",
        "https://models.example/\nheader",
        "https:///v1",
        "https://models.example:0/v1",
    ],
)
def test_custom_endpoints_reject_credentials_and_unsafe_syntax(
    settings: providers.ProviderSettings,
    url: str,
) -> None:
    with pytest.raises(ValueError, match=r"URL|HTTPS|loopback"):
        settings.update({"provider": "compatible", "base_url": url})


@pytest.mark.parametrize(
    "url",
    [
        "https://models.example/v1",
        "http://127.0.0.1:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_custom_endpoints_accept_https_or_explicit_loopback_http(
    settings: providers.ProviderSettings,
    url: str,
) -> None:
    snapshot = settings.update({"provider": "compatible", "base_url": url})
    assert _entry(snapshot, "compatible")["base_url"] == url


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_official_provider_origin_cannot_be_replaced(
    settings: providers.ProviderSettings,
    provider: str,
) -> None:
    original = _entry(settings.snapshot(), provider)["base_url"]
    with pytest.raises(ValueError, match="official API endpoint"):
        settings.update(
            {"provider": provider, "base_url": "https://attacker.example/v1"}
        )
    assert _entry(settings.snapshot(), provider)["base_url"] == original


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "192.168.1.2",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "::",
        "fc00::1",
        "fe80::1",
        "ff00::1",
    ],
)
def test_nonpublic_dns_destination_is_rejected_before_sending_key(
    settings: providers.ProviderSettings,
    transport: Mock,
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    _configure(settings, "compatible")
    monkeypatch.setattr(
        providers.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, 443),
            ),
        ],
    )
    with pytest.raises(ValueError, match=r"private|public|endpoint"):
        _generate(providers.Planner(settings), "compatible")
    transport.open.assert_not_called()


def test_dns_with_public_and_private_answers_is_rejected(
    settings: providers.ProviderSettings,
    transport: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(settings, "compatible")
    monkeypatch.setattr(
        providers.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443)),
        ],
    )
    with pytest.raises(ValueError, match="private network"):
        _generate(providers.Planner(settings), "compatible")
    transport.open.assert_not_called()


def test_openai_uses_responses_json_mode_and_server_authorization(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "openai")
    transport.open.return_value = JsonResponse(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '{"title":"A parabola"}'},
                    ],
                }
            ],
        }
    )
    output = _generate(providers.Planner(settings), "openai", "test-model")
    request = _request(transport)
    payload = _payload(request)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert _headers(request)["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in request.full_url
    assert payload["model"] == "test-model"
    assert cast(dict[str, object], payload["text"])["format"] == {"type": "json_object"}
    assert "JSON" in str(payload["input"])
    assert json.loads(output) == {"title": "A parabola"}


def test_openai_json_mode_accepts_brief_without_json_in_input(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    """Model OpenAI's input requirement, independently of system instructions."""
    _configure(settings, "openai")
    brief = "Mode: math\nTarget: 30 seconds\nBrief: pythogreas theorem"

    def json_mode_api(request: Request, *, timeout: float) -> JsonResponse:
        assert timeout == 180
        body = _payload(request)
        text = cast(dict[str, object], body["text"])
        assert text["format"] == {"type": "json_object"}
        incoming = body["input"]
        if not isinstance(incoming, str) or "json" not in incoming.lower():
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                _error_headers(),
                JsonResponse(
                    {
                        "error": {
                            "message": "Response input messages must mention JSON.",
                            "type": "invalid_request_error",
                            "param": "input",
                            "code": None,
                        }
                    }
                ),
            )
        assert incoming.startswith(brief)
        return JsonResponse(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"title":"Pythagoras"}'},
                        ],
                    }
                ],
            }
        )

    transport.open.side_effect = json_mode_api
    result = providers.Planner(settings).generate(
        "openai",
        "gpt-4.1-mini",
        "Plan a visual proof for a beginner.",
        brief,
        {"type": "object", "properties": {"title": {"type": "string"}}},
    )
    assert json.loads(result) == {"title": "Pythagoras"}
    assert transport.open.call_count == 1


@pytest.mark.parametrize(
    "response",
    [
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
        },
        {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": SECRET}]}
            ],
        },
        {"status": "completed", "output": []},
        {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": ""}]}
            ],
        },
    ],
)
def test_openai_refusal_or_incomplete_output_gives_safe_actionable_error(
    settings: providers.ProviderSettings,
    transport: Mock,
    response: dict[str, object],
) -> None:
    _configure(settings, "openai")
    transport.open.return_value = JsonResponse(response)
    with pytest.raises(ValueError, match=r"OpenAI|storyboard") as error:
        _generate(providers.Planner(settings), "openai")
    assert SECRET not in str(error.value)


def test_gemini_uses_header_key_and_json_response_configuration(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "gemini")
    transport.open.return_value = JsonResponse(
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Internal planning notes"},
                            {"text": '{"title":"Vectors"}'},
                        ]
                    },
                }
            ]
        }
    )
    output = _generate(providers.Planner(settings), "gemini", "gemini-test")
    request = _request(transport)
    payload = _payload(request)
    assert (
        request.full_url
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    )
    assert _headers(request)["x-goog-api-key"] == SECRET
    assert SECRET not in request.full_url
    assert (
        cast(dict[str, object], payload["generationConfig"])["responseMimeType"]
        == "application/json"
    )
    assert json.loads(output) == {"title": "Vectors"}


@pytest.mark.parametrize(
    "response",
    [
        {"promptFeedback": {"blockReason": "SAFETY", "blockReasonMessage": SECRET}},
        {"candidates": []},
        {
            "candidates": [
                {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}
            ]
        },
        {
            "candidates": [
                {"finishReason": "SAFETY", "content": {"parts": [{"text": SECRET}]}}
            ]
        },
        {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]},
    ],
)
def test_gemini_blocked_truncated_or_empty_output_is_safe(
    settings: providers.ProviderSettings,
    transport: Mock,
    response: dict[str, object],
) -> None:
    _configure(settings, "gemini")
    transport.open.return_value = JsonResponse(response)
    with pytest.raises(ValueError, match=r"Gemini|storyboard") as error:
        _generate(providers.Planner(settings), "gemini")
    assert SECRET not in str(error.value)


def test_compatible_provider_uses_chat_completions_contract(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "compatible")
    transport.open.return_value = JsonResponse(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"title":"Geometry"}'},
                }
            ]
        }
    )
    output = _generate(providers.Planner(settings), "compatible")
    request = _request(transport)
    payload = _payload(request)
    assert request.full_url == "https://models.example/v1/chat/completions"
    assert _headers(request)["authorization"] == f"Bearer {SECRET}"
    assert payload["response_format"] == {"type": "json_object"}
    messages = cast(list[dict[str, object]], payload["messages"])
    assert [message["role"] for message in messages] == ["system", "user"]
    assert json.loads(output) == {"title": "Geometry"}


@pytest.mark.parametrize("provider", ["openai", "gemini", "compatible"])
def test_unconfigured_provider_fails_before_network(
    settings: providers.ProviderSettings,
    transport: Mock,
    provider: str,
) -> None:
    with pytest.raises(ValueError, match=r"key|configure|settings|Settings"):
        _generate(providers.Planner(settings), provider)
    transport.open.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        URLError(SECRET),
        TimeoutError(SECRET),
        HTTPError(
            "https://models.example/v1?secret=" + SECRET,
            401,
            SECRET,
            _error_headers(),
            io.BytesIO(SECRET.encode()),
        ),
        HTTPError(
            "https://models.example/v1",
            429,
            SECRET,
            _error_headers(),
            io.BytesIO(SECRET.encode()),
        ),
        HTTPError(
            "https://models.example/v1",
            302,
            SECRET,
            _error_headers("https://attacker.example/"),
            None,
        ),
    ],
)
def test_transport_failures_and_redirects_never_reveal_keys(
    settings: providers.ProviderSettings,
    transport: Mock,
    failure: Exception,
) -> None:
    _configure(settings, "compatible")
    transport.open.side_effect = failure
    with pytest.raises(ValueError, match=r"API|connect|response|request") as error:
        _generate(providers.Planner(settings), "compatible")
    assert SECRET not in str(error.value)
    assert transport.open.call_count == 1


@pytest.mark.parametrize(
    ("status", "details", "guidance"),
    [
        (400, {"param": "model"}, r"model|access"),
        (400, {"code": "model_not_found"}, r"model|access"),
        (400, {"param": "text.format"}, r"JSON"),
        (400, {"param": "text.format.type"}, r"JSON"),
        (400, {"param": "response_format"}, r"JSON"),
        (400, {"param": "response_format.type"}, r"JSON"),
        (
            400,
            {"param": "input", "message": "Input messages must contain JSON."},
            r"restart|Restart|latest|JSON",
        ),
        (429, {"code": "insufficient_quota"}, r"billing|Billing|quota"),
        (429, {"code": "billing_hard_limit_reached"}, r"billing|Billing|quota"),
        (429, {"code": "rate_limit_exceeded"}, r"rate|quota"),
    ],
)
def test_http_error_metadata_gives_specific_guidance_without_echoing_provider_body(
    settings: providers.ProviderSettings,
    transport: Mock,
    status: int,
    details: dict[str, object],
    guidance: str,
) -> None:
    _configure(settings, "openai")
    response = JsonResponse(
        {
            "error": {
                "type": "invalid_request_error",
                "message": SECRET + " private user brief",
                **details,
                "debug": SECRET,
            }
        }
    )
    transport.open.side_effect = HTTPError(
        "https://api.openai.com/v1/responses",
        status,
        SECRET,
        _error_headers(),
        response,
    )
    with pytest.raises(ValueError, match=guidance) as error:
        _generate(providers.Planner(settings), "openai")
    assert SECRET not in str(error.value)
    assert "private user brief" not in str(error.value)
    assert response.closed
    assert transport.open.call_count == 1


@pytest.mark.parametrize(
    "raw",
    [
        SECRET.encode(),
        b"\xff",
        b"[]",
        b'"not an error object"',
        b'{"error":[]}',
        json.dumps(
            {"error": {"param": SECRET, "code": SECRET, "message": SECRET}}
        ).encode(),
        json.dumps({"error": {"param": {}, "code": [], "message": SECRET}}).encode(),
        json.dumps({"error": {"param": "input", "message": SECRET}}).encode(),
    ],
)
def test_unknown_bad_request_body_has_neutral_diagnosis_without_secret_echo(
    settings: providers.ProviderSettings,
    transport: Mock,
    raw: bytes,
) -> None:
    _configure(settings, "openai")
    response = io.BytesIO(raw)
    transport.open.side_effect = HTTPError(
        "https://api.openai.com/v1/responses",
        400,
        SECRET,
        _error_headers(),
        response,
    )
    with pytest.raises(ValueError, match=r"HTTP 400|request|settings") as error:
        _generate(providers.Planner(settings), "openai")
    assert SECRET not in str(error.value)
    assert "JSON" not in str(error.value)
    assert response.closed


def test_bad_request_without_response_body_uses_safe_generic_error(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "openai")
    transport.open.side_effect = HTTPError(
        "https://api.openai.com/v1/responses",
        400,
        SECRET,
        _error_headers(),
        None,
    )
    with pytest.raises(ValueError, match=r"HTTP 400|request|settings") as error:
        _generate(providers.Planner(settings), "openai")
    assert SECRET not in str(error.value)


def test_http_error_reader_is_bounded_and_closes_large_response(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    class TrackedResponse(io.BytesIO):
        def __init__(self) -> None:
            super().__init__(SECRET.encode() * 10000)
            self.read_sizes: list[int | None] = []

        def read(self, size: int | None = -1, /) -> bytes:
            self.read_sizes.append(size)
            return super().read(size)

    _configure(settings, "openai")
    response = TrackedResponse()
    transport.open.side_effect = HTTPError(
        "https://api.openai.com/v1/responses",
        400,
        SECRET,
        _error_headers(),
        response,
    )
    with pytest.raises(ValueError, match=r"HTTP 400|request|settings") as error:
        _generate(providers.Planner(settings), "openai")
    assert SECRET not in str(error.value)
    assert len(response.read_sizes) == 1
    assert isinstance(response.read_sizes[0], int)
    assert 0 < response.read_sizes[0] <= 16 * 1024 + 1
    assert response.closed


def test_no_redirect_handler_never_forwards_authorization() -> None:
    handler = providers._NoRedirect()
    request = Request(
        "https://models.example/v1", headers={"Authorization": f"Bearer {SECRET}"}
    )
    assert (
        handler.redirect_request(
            request, None, 302, "Redirect", {}, "https://attacker.example/"
        )
        is None
    )


@pytest.mark.parametrize(
    ("provider", "response", "expected", "suffix"),
    [
        (
            "openai",
            {"data": [{"id": "model-b"}, {"id": "model-a"}]},
            ["model-a", "model-b"],
            "/v1/models",
        ),
        (
            "compatible",
            {"data": [{"id": "model-b"}, {"id": "model-a"}]},
            ["model-a", "model-b"],
            "/v1/models",
        ),
        (
            "gemini",
            {
                "models": [
                    {
                        "name": "models/gemini-test",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-test",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
            ["gemini-test"],
            "/v1beta/models",
        ),
    ],
)
def test_connection_models_use_read_only_model_list_and_filter_generation_models(
    settings: providers.ProviderSettings,
    transport: Mock,
    provider: str,
    response: dict[str, object],
    expected: list[str],
    suffix: str,
) -> None:
    _configure(settings, provider)
    transport.open.return_value = JsonResponse(response)
    assert providers.Planner(settings).models(provider) == expected
    request = _request(transport)
    assert request.get_method() == "GET"
    assert suffix in request.full_url
    assert request.data is None
    assert SECRET not in request.full_url


def test_gemini_model_pagination_is_bounded_and_uses_encoded_tokens(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "gemini")
    transport.open.side_effect = [
        JsonResponse(
            {
                "models": [
                    {
                        "name": "models/one",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ],
                "nextPageToken": "a token/+",
            }
        ),
        JsonResponse(
            {
                "models": [
                    {
                        "name": "models/two",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ]
            }
        ),
    ]
    assert providers.Planner(settings).models("gemini") == ["one", "two"]
    second = cast(Request, transport.open.call_args_list[1].args[0])
    assert "pageToken=a+token%2F%2B" in second.full_url
    assert SECRET not in second.full_url


def test_provider_response_size_is_bounded(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "compatible")
    transport.open.return_value = io.BytesIO(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match=r"size|limit|large"):
        _generate(providers.Planner(settings), "compatible")


@pytest.mark.parametrize("url", ["https://224.0.0.1/v1", "https://[ff00::1]/v1"])
def test_multicast_literal_endpoints_are_rejected_at_settings_boundary(
    settings: providers.ProviderSettings,
    url: str,
) -> None:
    with pytest.raises(ValueError, match=r"public|loopback|address"):
        settings.update({"provider": "compatible", "base_url": url})


def test_pinned_socket_uses_only_validated_addresses_without_resolving_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[tuple[str, int]] = []
    final_socket = Mock(spec=socket.socket)

    def connect(
        address: tuple[str, int],
        timeout: float | None,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        attempted.append(address)
        assert timeout == 15
        assert source_address is None
        if address[0] == "8.8.8.8":
            raise OSError("First public address was unavailable.")
        return cast(socket.socket, final_socket)

    monkeypatch.setattr(providers.socket, "create_connection", connect)
    connections = providers._PinnedConnections(("8.8.8.8", "1.1.1.1"))
    assert connections._socket(("rebinding.example", 443), 15) is final_socket
    assert attempted == [("8.8.8.8", 443), ("1.1.1.1", 443)]


def test_network_opener_disables_proxies_and_redirects_before_sending_secret(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "compatible")
    transport.open.return_value = JsonResponse(
        {"choices": [{"message": {"content": "{}"}}]}
    )
    _generate(providers.Planner(settings), "compatible")
    opener_factory = cast(Mock, providers.build_opener)
    handlers = opener_factory.call_args.args
    proxy = next(
        handler for handler in handlers if isinstance(handler, providers.ProxyHandler)
    )
    assert proxy.proxies == {}
    assert any(isinstance(handler, providers._NoRedirect) for handler in handlers)
    assert any(
        isinstance(handler, providers._PinnedHTTPHandler) for handler in handlers
    )
    assert any(
        isinstance(handler, providers._PinnedHTTPSHandler) for handler in handlers
    )


@pytest.mark.parametrize("raw", [b"not JSON", b"[]", b'"value"', b"\xff"])
def test_invalid_api_response_errors_never_echo_response_bytes(
    settings: providers.ProviderSettings,
    transport: Mock,
    raw: bytes,
) -> None:
    _configure(settings, "compatible")
    transport.open.return_value = io.BytesIO(raw)
    with pytest.raises(ValueError, match=r"JSON|response"):
        _generate(providers.Planner(settings), "compatible")


@pytest.mark.parametrize(
    "response",
    [
        {"choices": [{"finish_reason": "length", "message": {"content": SECRET}}]},
        {"choices": [{"message": {"refusal": SECRET}}]},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_compatible_refusal_truncation_and_empty_response_errors_are_safe(
    settings: providers.ProviderSettings,
    transport: Mock,
    response: dict[str, object],
) -> None:
    _configure(settings, "compatible")
    transport.open.return_value = JsonResponse(response)
    with pytest.raises(ValueError, match=r"compatible|storyboard") as error:
        _generate(providers.Planner(settings), "compatible")
    assert SECRET not in str(error.value)


def test_gemini_model_pagination_stops_at_five_pages(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    _configure(settings, "gemini")
    transport.open.side_effect = [
        JsonResponse(
            {
                "models": [
                    {
                        "name": f"models/model-{index}",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ],
                "nextPageToken": f"page-{index + 1}",
            }
        )
        for index in range(6)
    ]
    assert providers.Planner(settings).models("gemini") == [
        f"model-{index}" for index in range(5)
    ]
    assert transport.open.call_count == 5


def test_failed_preference_file_write_preserves_saved_settings_and_session_key(
    settings: providers.ProviderSettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(settings, "openai")
    original = settings.snapshot()
    saved = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")

    def fail_replace(*args: object) -> None:
        raise OSError(SECRET)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(ValueError, match="save provider preferences") as error:
        settings.update(
            {"provider": "openai", "model": "new-model", "api_key": "replacement-key"}
        )
    assert SECRET not in str(error.value)
    assert settings.snapshot() == original
    assert next(tmp_path.glob("*.json")).read_text(encoding="utf-8") == saved
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("invalid_suffix", ["\ninvalid", "é", "🔑", "x" * 4097])
def test_invalid_environment_key_is_rejected_before_http_and_never_echoed(
    settings: providers.ProviderSettings,
    monkeypatch: pytest.MonkeyPatch,
    transport: Mock,
    invalid_suffix: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET + invalid_suffix)
    with pytest.raises(ValueError, match="API key is invalid") as error:
        _generate(providers.Planner(settings), "openai")
    assert SECRET not in str(error.value)
    transport.open.assert_not_called()


def test_internal_connection_representation_omits_session_credential(
    settings: providers.ProviderSettings,
) -> None:
    _configure(settings, "openai")
    assert SECRET not in repr(settings._connection("openai"))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_loopback_compatible_provider_is_local_and_works_without_key(
    settings: providers.ProviderSettings,
    transport: Mock,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setattr(
        providers.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000)),
        ],
    )
    snapshot = settings.update(
        {"provider": "compatible", "model": "local-model", "base_url": url}
    )
    local = _entry(snapshot, "compatible")
    assert local["scope"] == "local"
    assert local["requires_key"] is False
    assert local["configured"] is True
    assert local["key_set"] is False
    assert settings.configured("compatible") is True
    transport.open.return_value = JsonResponse(
        {"choices": [{"message": {"content": "{}"}}]}
    )
    assert _generate(providers.Planner(settings), "compatible", "local-model") == "{}"
    assert "authorization" not in _headers(_request(transport))
    transport.open.return_value = JsonResponse({"data": [{"id": "local-model"}]})
    assert providers.Planner(settings).models("compatible") == ["local-model"]
    assert "authorization" not in _headers(_request(transport))


def test_remote_compatible_provider_still_requires_credential(
    settings: providers.ProviderSettings,
    transport: Mock,
) -> None:
    snapshot = settings.update(
        {
            "provider": "compatible",
            "model": "remote-model",
            "base_url": "https://models.example/v1",
        }
    )
    remote = _entry(snapshot, "compatible")
    assert remote["scope"] == "cloud"
    assert remote["requires_key"] is True
    assert remote["configured"] is False
    with pytest.raises(ValueError, match="API key"):
        _generate(providers.Planner(settings), "compatible", "remote-model")
    transport.open.assert_not_called()
