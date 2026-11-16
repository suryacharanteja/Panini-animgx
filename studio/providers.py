# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Keep session credentials and call storyboard planning providers safely."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import ssl
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPResponse, HTTPSConnection
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

_MAX_RESPONSE = 2 * 1024 * 1024
_PROVIDER_NAMES = {
    "ollama": "Ollama",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "compatible": "OpenAI-compatible API",
}
_ENVIRONMENT_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "compatible": "COMPATIBLE_API_KEY",
}
_FIXED_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
_DEFAULTS = {
    "ollama": {"model": "qwen2.5:3b-instruct", "base_url": "http://127.0.0.1:11434"},
    "openai": {"model": "gpt-4.1-mini", "base_url": _FIXED_URLS["openai"]},
    "gemini": {"model": "gemini-3.8-flash", "base_url": _FIXED_URLS["gemini"]},
    "compatible": {"model": "", "base_url": ""},
}


def _provider_name(value: object) -> str:
    if not isinstance(value, str) or value not in _PROVIDER_NAMES:
        raise ValueError("Choose Ollama, OpenAI, Google Gemini, or a compatible API.")
    return value


def _bounded_text(
    value: object, maximum: int, name: str, *, empty: bool = False
) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{name} must be text, up to {maximum} characters.")
    text = value.strip()
    if (not text and not empty) or any(
        ord(char) < 32 or ord(char) == 127 for char in text
    ):
        raise ValueError(f"{name} must be nonempty text without control characters.")
    return text


def _literal_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _allowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_loopback or (
        address.is_global and not address.is_multicast and not address.is_reserved
    )


def _local_provider(provider: str, base_url: str) -> bool:
    if provider == "ollama":
        return True
    if provider != "compatible" or not base_url:
        return False
    host = urlsplit(base_url).hostname
    if not host:
        return False
    address = _literal_address(host)
    return host.lower() == "localhost" or (address is not None and address.is_loopback)


def _validated_url(value: object, *, local_only: bool = False) -> str:
    """Validate a configured endpoint without making a network request."""
    text = _bounded_text(value, 2048, "Base URL")
    if any(char.isspace() for char in text) or "\\" in text:
        raise ValueError("Base URL must not contain whitespace or backslashes.")
    try:
        parts = urlsplit(text)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("Enter a valid API base URL.") from None
    if (
        parts.scheme not in ("http", "https")
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or (port is not None and not 1 <= port <= 65535)
        or "%" in host
    ):
        raise ValueError(
            "Use an API URL without credentials, query parameters, or fragments."
        )
    literal = _literal_address(host)
    loopback = host.lower() == "localhost" or (
        literal is not None and literal.is_loopback
    )
    if local_only and not loopback:
        raise ValueError("Ollama must use an explicit loopback URL on this computer.")
    if parts.scheme == "http" and not loopback:
        raise ValueError("Remote APIs require HTTPS. HTTP is allowed only on loopback.")
    if literal is not None and not _allowed_address(literal):
        raise ValueError(
            "API URLs must use a public address or loopback on this computer."
        )
    if parts.path.startswith("//"):
        raise ValueError("Enter a valid API base path.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _validate_destination(url: str) -> tuple[str, ...]:
    """Reject a hostname resolving to private networks before sending credentials."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise ValueError("The API endpoint has no hostname.")
    literal = _literal_address(host)
    if literal is not None:
        addresses = [literal]
    else:
        try:
            records = socket.getaddrinfo(
                host,
                parts.port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = [ipaddress.ip_address(record[4][0]) for record in records]
        except (OSError, ValueError):
            raise ValueError(
                "Cannot resolve the API hostname. Check the URL and connection."
            ) from None
    if not addresses or any(not _allowed_address(address) for address in addresses):
        raise ValueError(
            "The API endpoint resolves to a private network. Use a public API or loopback."
        )
    if parts.scheme == "http" and any(not address.is_loopback for address in addresses):
        raise ValueError("HTTP API connections must stay on loopback on this computer.")
    if (
        literal is None
        and host.lower() != "localhost"
        and any(address.is_loopback for address in addresses)
    ):
        raise ValueError(
            "A remote API hostname cannot resolve to loopback. Use an explicit loopback URL."
        )
    return tuple(dict.fromkeys(str(address) for address in addresses))


class _PinnedHTTPConnection(HTTPConnection):
    _create_connection: Callable[
        [tuple[str, int], float | None, tuple[str, int] | None], socket.socket
    ]


class _PinnedHTTPSConnection(HTTPSConnection):
    _create_connection: Callable[
        [tuple[str, int], float | None, tuple[str, int] | None], socket.socket
    ]


class _PinnedConnections:
    """Connect to already-validated addresses while verifying the TLS hostname."""

    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses

    def _socket(
        self,
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        for host in self.addresses:
            try:
                return socket.create_connection(
                    (host, address[1]), timeout, source_address
                )
            except OSError:
                continue
        raise OSError("Could not connect to the validated API addresses.")

    def http(self, host: str, timeout: float) -> HTTPConnection:
        connection = _PinnedHTTPConnection(host, timeout=timeout)
        connection._create_connection = self._socket
        return connection

    def https(
        self, host: str, timeout: float, context: ssl.SSLContext
    ) -> HTTPSConnection:
        connection = _PinnedHTTPSConnection(host, timeout=timeout, context=context)
        connection._create_connection = self._socket
        return connection


class _PinnedHTTPHandler(HTTPHandler):
    def __init__(self, connections: _PinnedConnections) -> None:
        super().__init__()
        self._connections = connections

    def http_open(self, req: Request) -> HTTPResponse:
        # urllib accepts a factory with the HTTPConnection constructor interface.
        factory = cast(type[HTTPConnection], self._connections.http)
        return self.do_open(factory, req)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, connections: _PinnedConnections) -> None:
        self._tls_context = ssl.create_default_context()
        super().__init__(context=self._tls_context)
        self._connections = connections

    def https_open(self, req: Request) -> HTTPResponse:
        factory = cast(type[HTTPConnection], self._connections.https)
        return self.do_open(factory, req, context=self._tls_context)


@dataclass(frozen=True)
class _Connection:
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)


class ProviderSettings:
    """Persist model preferences while keeping API keys in server memory.

    Args:
        directory: Local Studio data directory containing nonsecret preferences.
    """

    def __init__(self, directory: Path) -> None:
        self._path = directory / "provider-settings.json"
        self._lock = threading.RLock()
        self._preferences = {name: dict(default) for name, default in _DEFAULTS.items()}
        self._active = "ollama"
        self._keys: dict[str, str] = {}
        self._suppressed: set[str] = set()
        self._load()

    def _load(self) -> None:
        try:
            raw: object = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        data = cast(dict[str, object], raw)
        active = data.get("active_provider")
        if isinstance(active, str) and active in _PROVIDER_NAMES:
            self._active = active
        records = data.get("providers")
        if not isinstance(records, dict):
            return
        for provider, value in records.items():
            if provider not in _PROVIDER_NAMES or not isinstance(value, dict):
                continue
            item = cast(dict[str, object], value)
            try:
                model = _bounded_text(
                    item.get("model", ""), 200, "Model", empty=provider == "compatible"
                )
                base_url = self._base_url(
                    provider, item.get("base_url", _DEFAULTS[provider]["base_url"])
                )
            except ValueError:
                continue
            self._preferences[provider] = {"model": model, "base_url": base_url}

    @staticmethod
    def _base_url(provider: str, value: object) -> str:
        if provider in _FIXED_URLS:
            fixed = _FIXED_URLS[provider]
            if not isinstance(value, str) or value.rstrip("/") != fixed:
                raise ValueError(
                    f"{_PROVIDER_NAMES[provider]} uses its official API endpoint."
                )
            return fixed
        if provider == "compatible" and isinstance(value, str) and not value.strip():
            return ""
        return _validated_url(value, local_only=provider == "ollama")

    def _key(self, provider: str) -> tuple[str, str]:
        if provider in self._keys:
            return self._keys[provider], "session"
        if provider not in self._suppressed:
            environment = _ENVIRONMENT_KEYS.get(provider)
            value = os.environ.get(environment, "").strip() if environment else ""
            if value:
                return value, "environment"
        return "", "none"

    def snapshot(self) -> dict[str, object]:
        """Return safe settings for the browser, never an API key."""
        with self._lock:
            providers: list[dict[str, object]] = []
            for provider, name in _PROVIDER_NAMES.items():
                key, source = self._key(provider)
                preferences = self._preferences[provider]
                local = _local_provider(provider, preferences["base_url"])
                requires_key = not local
                providers.append(
                    {
                        "id": provider,
                        "name": name,
                        "model": preferences["model"],
                        "base_url": preferences["base_url"],
                        "configured": bool(
                            preferences["model"]
                            and preferences["base_url"]
                            and (key or not requires_key)
                        ),
                        "key_set": bool(key),
                        "key_source": source,
                        "scope": "local" if local else "cloud",
                        "requires_key": requires_key,
                    }
                )
            return {
                "active_provider": self._active,
                "providers": providers,
                "key_storage": "session",
                "key_notice": "API keys stay in server memory for this session. Set provider environment variables before starting Studio to reuse a key after restart; model preferences are saved without keys.",
            }

    def model(self, provider: str) -> str:
        """Return the saved model name for a known provider."""
        provider = _provider_name(provider)
        with self._lock:
            return self._preferences[provider]["model"]

    def configured(self, provider: str) -> bool:
        """Report whether the provider has a model, endpoint, and required key."""
        provider = _provider_name(provider)
        with self._lock:
            preferences = self._preferences[provider]
            return bool(
                preferences["model"]
                and preferences["base_url"]
                and (
                    self._key(provider)[0]
                    or _local_provider(provider, preferences["base_url"])
                )
            )

    def update(self, data: dict[str, object]) -> dict[str, object]:
        """Save reviewed preferences and replace a key only when one is supplied.

        Args:
            data: Provider, model, optional endpoint, key, and active provider.

        Returns:
            Updated browser-safe settings.

        Raises:
            ValueError: A field or endpoint is invalid, or preferences cannot save.
        """
        provider = _provider_name(data.get("provider"))
        with self._lock:
            current = self._preferences[provider]
            model = _bounded_text(
                data.get("model", current["model"]),
                200,
                "Model",
                empty=provider == "compatible",
            )
            base_url = self._base_url(
                provider, data.get("base_url", current["base_url"])
            )
            active = _provider_name(data.get("active_provider", self._active))
            clear_key = data.get("clear_key", False)
            if not isinstance(clear_key, bool):
                raise ValueError("clear_key must be true or false.")
            key = _bounded_text(data.get("api_key", ""), 4096, "API key", empty=True)
            if any(not 33 <= ord(char) <= 126 for char in key):
                raise ValueError("API key must use printable ASCII without whitespace.")
            if provider == "ollama" and key:
                raise ValueError("Ollama on this computer does not require an API key.")
            if clear_key and key:
                raise ValueError("Enter a new key or clear the saved key, not both.")
            preferences = {
                name: dict(value) for name, value in self._preferences.items()
            }
            preferences[provider] = {"model": model, "base_url": base_url}
            temporary = self._path.with_name(
                f".{self._path.name}.{uuid.uuid4().hex}.tmp"
            )
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(
                    json.dumps(
                        {"active_provider": active, "providers": preferences}, indent=2
                    )
                    + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self._path)
            except OSError:
                raise ValueError(
                    "Could not save provider preferences in the Studio data directory."
                ) from None
            finally:
                temporary.unlink(missing_ok=True)
            self._preferences = preferences
            self._active = active
            if clear_key:
                self._keys.pop(provider, None)
                self._suppressed.add(provider)
            elif key:
                self._keys[provider] = key
                self._suppressed.discard(provider)
            return self.snapshot()

    def _connection(self, provider: str, model: str | None = None) -> _Connection:
        provider = _provider_name(provider)
        with self._lock:
            preferences = self._preferences[provider]
            selected = (
                preferences["model"]
                if model is None
                else _bounded_text(model, 200, "Model")
            )
            key, _ = self._key(provider)
            if provider == "ollama":
                raise ValueError("Use the local Ollama planner for this provider.")
            if not key and not _local_provider(provider, preferences["base_url"]):
                raise ValueError(
                    f"Add your {_PROVIDER_NAMES[provider]} API key in Admin settings or its environment variable."
                )
            if any(not 33 <= ord(char) <= 126 for char in key) or len(key) > 4096:
                raise ValueError(
                    "The provider API key is invalid. Replace it in Admin settings."
                )
            if not preferences["base_url"]:
                raise ValueError("Set the compatible API base URL in Admin settings.")
            if model is not None and not selected:
                raise ValueError("Choose a model in Admin settings.")
            return _Connection(provider, selected, preferences["base_url"], key)


class _NoRedirect(HTTPRedirectHandler):
    """Keep authorization headers away from redirected destinations."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def _http_error_message(error: HTTPError) -> str:
    """Turn known error metadata into guidance without returning response text."""
    details: dict[str, object] = {}
    try:
        raw = error.read(16 * 1024 + 1)
        if len(raw) <= 16 * 1024:
            parsed: object = json.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                details = cast(dict[str, object], parsed["error"])
    except (ValueError, UnicodeError, OSError, AttributeError, TypeError):
        pass
    finally:
        error.close()
    code = details.get("code")
    parameter = details.get("param")
    if 300 <= error.code < 400:
        return "redirected the API request. Use the final trusted API base URL."
    if error.code in (401, 403):
        return "rejected the API key or permissions. Check the key and account access."
    if error.code == 429:
        if code in ("insufficient_quota", "billing_hard_limit_reached"):
            return "has no available API quota. Check the provider account's billing and spending limit before trying again."
        return (
            "reached its rate or account quota limit. Check billing or try again later."
        )
    if error.code == 404:
        return "could not find the API endpoint or model. Check the selected model and base URL."
    if error.code == 400:
        if parameter == "model" or code == "model_not_found":
            return "rejected the selected model. Choose a text planning model in Admin settings and check your account's model access."
        if parameter in (
            "text.format",
            "text.format.type",
            "response_format",
            "response_format.type",
        ):
            return "rejected the JSON response format. Choose a model that supports JSON responses in Admin settings."
        message = details.get("message")
        if (
            parameter == "input"
            and isinstance(message, str)
            and "json" in message.lower()
        ):
            return "requires JSON instructions in the request input. Restart Studio to load the latest version, then try again."
        return "rejected the planning request (HTTP 400). Check the selected model in Admin settings or try another provider."
    return f"returned HTTP {error.code}. Try again or choose another provider."


class Planner:
    """Call cloud providers only for JSON storyboard planning.

    Args:
        settings: Session credentials and reviewed nonsecret preferences.
    """

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings

    def _request_json(
        self, connection: _Connection, path: str, body: dict[str, object] | None = None
    ) -> dict[str, object]:
        url = connection.base_url + path
        connections = _PinnedConnections(_validate_destination(url))
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if connection.provider == "gemini":
            headers["x-goog-api-key"] = connection.api_key
        elif connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(url, data=encoded, headers=headers)
        opener = build_opener(
            ProxyHandler({}),
            _NoRedirect(),
            _PinnedHTTPHandler(connections),
            _PinnedHTTPSHandler(connections),
        )
        name = _PROVIDER_NAMES[connection.provider]
        try:
            with opener.open(request, timeout=15 if body is None else 180) as response:
                raw = response.read(_MAX_RESPONSE + 1)
        except HTTPError as error:
            raise ValueError(f"{name} {_http_error_message(error)}") from None
        except (URLError, TimeoutError, OSError):
            raise ValueError(
                f"Cannot reach {name}. Check your connection and API base URL, then try again."
            ) from None
        if len(raw) > _MAX_RESPONSE:
            raise ValueError(f"{name} response exceeded the size limit.")
        try:
            parsed: object = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError(f"{name} returned an invalid JSON response.") from None
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} returned an invalid JSON response.")
        return cast(dict[str, object], parsed)

    def models(self, provider: str) -> list[str]:
        """Test credentials by listing models without generating billable content."""
        connection = self.settings._connection(provider)
        names: set[str] = set()
        token = ""
        for _ in range(5):
            path = "/models"
            if provider == "gemini":
                query = {"pageSize": "100"}
                if token:
                    query["pageToken"] = token
                path += "?" + urlencode(query)
            result = self._request_json(connection, path)
            raw = result.get("models" if provider == "gemini" else "data")
            if not isinstance(raw, list):
                raise ValueError(
                    f"{_PROVIDER_NAMES[provider]} returned an invalid model list."
                )
            for value in raw:
                if not isinstance(value, dict):
                    continue
                item = cast(dict[str, object], value)
                if provider == "gemini":
                    methods = item.get("supportedGenerationMethods")
                    if isinstance(methods, list) and "generateContent" not in methods:
                        continue
                model = item.get("name" if provider == "gemini" else "id")
                if (
                    isinstance(model, str)
                    and 0 < len(model) <= 200
                    and not any(ord(char) < 32 for char in model)
                ):
                    names.add(
                        model.removeprefix("models/") if provider == "gemini" else model
                    )
            next_token = result.get("nextPageToken") if provider == "gemini" else None
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token == token
                or len(next_token) > 2048
            ):
                break
            token = next_token
        return sorted(names)

    def generate(
        self,
        provider: str,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, object],
    ) -> str:
        """Request a JSON storyboard; local validation and rendering remain separate."""
        connection = self.settings._connection(provider, model)
        instructions = (
            system
            + "\nReturn one JSON object matching this schema:\n"
            + json.dumps(schema, separators=(",", ":"))
        )
        if provider == "openai":
            result = self._request_json(
                connection,
                "/responses",
                {
                    "model": model,
                    "instructions": instructions,
                    "input": prompt + "\nReturn the storyboard as JSON.",
                    "text": {"format": {"type": "json_object"}},
                    "max_output_tokens": 3000,
                    "store": False,
                },
            )
            if result.get("status") == "incomplete":
                raise ValueError(
                    "OpenAI could not finish the storyboard within the response limit. Try a shorter brief or fewer scenes."
                )
            if result.get("status") in ("failed", "cancelled") or result.get("error"):
                raise ValueError(
                    "OpenAI could not complete the storyboard. Try again or choose another model."
                )
            output = result.get("output")
            if not isinstance(output, list):
                raise ValueError(
                    "OpenAI returned no storyboard text. Choose a text model or try again."
                )
            texts: list[str] = []
            for value in output:
                if not isinstance(value, dict) or value.get("type") != "message":
                    continue
                content = value.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "refusal":
                        raise ValueError(
                            "OpenAI declined this storyboard request. Revise the brief and try again."
                        )
                    if part.get("type") == "output_text" and isinstance(
                        part.get("text"), str
                    ):
                        texts.append(part["text"])
            text = "".join(texts)
        elif provider == "gemini":
            normalized_model = model.removeprefix("models/")
            result = self._request_json(
                connection,
                f"/models/{quote(normalized_model, safe='')}:generateContent",
                {
                    "systemInstruction": {"parts": [{"text": instructions}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "maxOutputTokens": 3000,
                    },
                },
            )
            feedback = result.get("promptFeedback")
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                raise ValueError(
                    "Google Gemini blocked this storyboard request. Revise the brief and try again."
                )
            candidates = result.get("candidates")
            if (
                not isinstance(candidates, list)
                or not candidates
                or not isinstance(candidates[0], dict)
            ):
                raise ValueError(
                    "Google Gemini returned no storyboard text. Try again or choose another model."
                )
            candidate = candidates[0]
            if candidate.get("finishReason") == "MAX_TOKENS":
                raise ValueError(
                    "Google Gemini could not finish the storyboard within the response limit. Try a shorter brief or fewer scenes."
                )
            if candidate.get("finishReason") in (
                "SAFETY",
                "RECITATION",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "SPII",
            ):
                raise ValueError(
                    "Google Gemini declined this storyboard request. Revise the brief and try again."
                )
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            text = (
                "".join(
                    part["text"]
                    for part in parts
                    if isinstance(part, dict)
                    and not part.get("thought")
                    and isinstance(part.get("text"), str)
                )
                if isinstance(parts, list)
                else ""
            )
        else:
            result = self._request_json(
                connection,
                "/chat/completions",
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 3000,
                },
            )
            choices = result.get("choices")
            if (
                not isinstance(choices, list)
                or not choices
                or not isinstance(choices[0], dict)
            ):
                raise ValueError(
                    "The compatible API returned no storyboard text. Check its model and endpoint."
                )
            choice = choices[0]
            if choice.get("finish_reason") == "length":
                raise ValueError(
                    "The compatible API could not finish the storyboard within the response limit. Try a shorter brief or fewer scenes."
                )
            message = choice.get("message")
            if isinstance(message, dict) and message.get("refusal"):
                raise ValueError(
                    "The compatible API declined this storyboard request. Revise the brief and try again."
                )
            text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"{_PROVIDER_NAMES[provider]} returned no storyboard text. Try again or choose another model."
            )
        return text
