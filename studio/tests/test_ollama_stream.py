# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
"""Exercise streamed storyboard boundaries without calling or loading Ollama."""

import io
import json
from collections.abc import Sequence

import pytest
from studio import ollama_stream, server


def _event(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n"


def _stream(fragments: Sequence[str], *, done: bool = False) -> io.BytesIO:
    lines = [_event({"response": fragment, "done": False}) for fragment in fragments]
    if done:
        lines.append(_event({"done": True}))
    return io.BytesIO(b"".join(lines))


class _ChunkedStream(io.BytesIO):
    def readline(self, size: int | None = -1, /) -> bytes:
        return super().readline(min(1, size) if size is not None and size >= 0 else 1)


class _StopAfterObject(io.BytesIO):
    def readline(self, size: int | None = -1, /) -> bytes:
        result = super().readline(size)
        if not result:
            raise AssertionError(
                "The parser should not read after a complete storyboard."
            )
        return result


def test_joins_split_object_fragments_without_changing_model_text() -> None:
    text = ' \n{"title":"Original plot", "scenes":[{"text":"A \\"quoted\\" } { bracket"}]} \t'
    fragments = [text[:1], text[1:18], text[18:42], text[42:51], text[51:]]
    result = ollama_stream.read_generation(_stream(fragments))
    assert result == {"response": text}


def test_ollama_request_uses_stream_reader_for_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = '{"title":"Authored content","scenes":[]}'
    stream = _StopAfterObject(_event({"response": text, "done": False}))
    monkeypatch.setattr(server, "urlopen", lambda *args, **kwargs: stream)
    assert server.Ollama().request("/api/generate", {"stream": True}) == {
        "response": text
    }


def test_model_list_still_reads_a_single_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = {"models": [{"name": "installed-model"}]}
    stream = io.BytesIO(json.dumps(data).encode())
    monkeypatch.setattr(server, "urlopen", lambda *args, **kwargs: stream)
    assert server.Ollama().models() == ["installed-model"]


def test_streamed_escape_and_backslash_boundaries_are_parsed_as_json() -> None:
    text = json.dumps(
        {"title": 'A } quote " and backslash \\', "scenes": [{"path": "\\"}]}
    )
    result = ollama_stream.read_generation(_stream(list(text)))
    assert result == {"response": text}


def test_partial_byte_lines_can_split_multibyte_utf8_characters() -> None:
    text = json.dumps({"title": "प्रमाण · 東京 · ∑"}, ensure_ascii=False)
    stream = _ChunkedStream(_event({"response": text, "done": False}))
    assert ollama_stream.read_generation(stream) == {"response": text}


def test_complete_root_object_returns_before_trailing_whitespace_can_hang() -> None:
    text = '{"title":"Done","scenes":[]}\n \t'
    stream = _StopAfterObject(_event({"response": text, "done": False}))
    assert ollama_stream.read_generation(stream) == {"response": text}


def test_ignores_thinking_and_metrics_instead_of_adding_them_to_storyboard() -> None:
    stream = io.BytesIO(
        _event({"thinking": "This is private reasoning, not JSON.", "done": False})
        + _event({"response": '{"title":', "total_duration": 999, "done": False})
        + _event({"response": '"A draft"}', "done": True})
    )
    assert ollama_stream.read_generation(stream) == {"response": '{"title":"A draft"}'}


def test_complete_final_event_without_line_ending_is_accepted() -> None:
    text = '{"title":"Final event"}'
    stream = io.BytesIO(_event({"response": text, "done": True}).rstrip(b"\n"))
    assert ollama_stream.read_generation(stream) == {"response": text}


@pytest.mark.parametrize("value", [[], None, 3, "event"])
def test_rejects_nonobject_generation_events(value: object) -> None:
    with pytest.raises(ValueError, match="generation event must be a JSON object"):
        ollama_stream.read_generation(io.BytesIO(_event(value)))


@pytest.mark.parametrize("value", [None, [], 42, True, {"text": "wrong shape"}])
def test_rejects_nonstring_response_fragments(value: object) -> None:
    with pytest.raises(ValueError, match="fragment must be text"):
        ollama_stream.read_generation(io.BytesIO(_event({"response": value})))


@pytest.mark.parametrize("value", [1, "false", None])
def test_rejects_invalid_done_flags(value: object) -> None:
    with pytest.raises(ValueError, match="done flag"):
        ollama_stream.read_generation(
            io.BytesIO(_event({"response": "{", "done": value}))
        )


def test_provider_error_is_rejected_without_copying_untrusted_error_details() -> None:
    with pytest.raises(ValueError, match="generation error") as raised:
        ollama_stream.read_generation(
            io.BytesIO(_event({"error": "secret-private-brief"}))
        )
    assert "secret-private-brief" not in str(raised.value)


@pytest.mark.parametrize("text", ["[]", "null", "42", '"story"'])
def test_rejects_nonobject_storyboards(text: str) -> None:
    with pytest.raises(ValueError, match="storyboard must be a JSON object"):
        ollama_stream.read_generation(_stream([text]))


@pytest.mark.parametrize("text", ['{"title":', '{"title":"unfinished', "   ", ""])
def test_done_rejects_incomplete_storyboards_without_repair(text: str) -> None:
    with pytest.raises(ValueError, match="incomplete or invalid storyboard"):
        ollama_stream.read_generation(_stream([text], done=True))


@pytest.mark.parametrize("text", ['{"title":', '{"title":"unfinished', "   ", ""])
def test_premature_eof_rejects_incomplete_storyboards(text: str) -> None:
    with pytest.raises(ValueError, match="ended before a complete storyboard"):
        ollama_stream.read_generation(_stream([text]))


@pytest.mark.parametrize(
    "text",
    ['{"bad":}', '{"bad":NaN}', '{"bad":Infinity}', '{"bad":[1,2}', '{"bad":1,}'],
)
def test_balanced_but_invalid_json_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="storyboard is not valid JSON"):
        ollama_stream.read_generation(_stream([text]))


@pytest.mark.parametrize("suffix", ["unexpected", "{}", "]"])
def test_nonwhitespace_after_complete_object_is_rejected(suffix: str) -> None:
    with pytest.raises(ValueError, match="content after"):
        ollama_stream.read_generation(_stream(['{"title":"Draft"}' + suffix]))


def test_invalid_utf8_or_malformed_ndjson_events_are_rejected() -> None:
    for body in (b'{"response":"\xff"}\n', b"not-json\n", b'{"response":\n'):
        with pytest.raises(
            ValueError, match=r"UTF-8|generation event is not valid JSON"
        ):
            ollama_stream.read_generation(io.BytesIO(body))


def test_one_event_over_wire_limit_is_rejected() -> None:
    body = _event({"response": "x" * ollama_stream.MAX_STREAM_BYTES})
    with pytest.raises(ValueError, match="size limit"):
        ollama_stream.read_generation(io.BytesIO(body))


def test_many_individually_small_events_cannot_exceed_total_wire_limit() -> None:
    start = _event({"response": '{"title":"'})
    fragment = _event({"response": "x" * 1024, "done": False})
    repetitions = ollama_stream.MAX_STREAM_BYTES // len(fragment) + 1
    stream = io.BytesIO(start + fragment * repetitions)
    with pytest.raises(ValueError, match="size limit"):
        ollama_stream.read_generation(stream)


def test_partial_readline_calls_cannot_bypass_the_line_limit() -> None:
    class PartialLine(io.BytesIO):
        def readline(self, size: int | None = -1, /) -> bytes:
            return super().readline(
                min(8192, size) if size is not None and size >= 0 else 8192
            )

    with pytest.raises(ValueError, match="size limit"):
        ollama_stream.read_generation(
            PartialLine(b" " * (ollama_stream.MAX_STREAM_BYTES + 1))
        )


def test_readline_requests_are_bounded() -> None:
    requests: list[int] = []

    class Observed(io.BytesIO):
        def readline(self, size: int | None = -1, /) -> bytes:
            requests.append(-1 if size is None else size)
            return super().readline(size)

    stream = Observed(_event({"response": "{}"}))
    assert ollama_stream.read_generation(stream) == {"response": "{}"}
    assert requests == [ollama_stream.MAX_STREAM_BYTES + 1]


def test_nested_json_data_is_preserved_without_flattening_or_repair() -> None:
    text = '{"array":' + "[" * 100 + "0" + "]" * 100 + "}"
    assert ollama_stream.read_generation(_stream([text])) == {"response": text}
