"""
test_llm_validator.py
------------------------
Tests for app.agents.rag.llm_validator - uses a FAKE Anthropic client
(matching the real anthropic.Anthropic client's .messages.create()
interface) rather than calling the real API, same pattern as
test_embedder.py's fake Voyage client.

scripts/verify_anthropic_key.py remains the one place that calls the
REAL API - these tests deliberately do not duplicate that.

Run with:
    cd backend && pytest tests/test_llm_validator.py -v
"""

from __future__ import annotations

import anthropic
import pytest

from app.agents.graph import ComplianceVerdict
from app.agents.rag.llm_validator import (
    LLMValidationError,
    _parse_claude_response,
    validate_with_claude,
)
from app.agents.rag.retriever import RetrievedChunk


def _make_chunk(policy_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        policy_id=policy_id, document_title=f"Test {policy_id}",
        category="test", content=content, similarity=0.9,
    )


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeUsage:
    def __init__(self):
        self.input_tokens = 100
        self.output_tokens = 20


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]
        self.usage = _FakeUsage()


class _FakeAnthropicClient:
    """A fake client matching anthropic.Anthropic's .messages.create() -
    always returns the given JSON text (or raises the given exception)."""

    def __init__(self, response_json: str | None = None, raise_on_call: Exception | None = None):
        self.response_json = response_json
        self.raise_on_call = raise_on_call
        self.calls: list[dict] = []

        class _Messages:
            def __init__(self, outer):
                self.outer = outer

            def create(self, model=None, max_tokens=None, system=None, messages=None, **kwargs):
                self.outer.calls.append(
                    {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
                )
                if self.outer.raise_on_call is not None:
                    raise self.outer.raise_on_call
                return _FakeResponse(self.outer.response_json)

        self.messages = _Messages(self)


# =============================================================================
# 1. _parse_claude_response - JSON parsing, including markdown-fence tolerance
# =============================================================================
def test_parses_clean_json_approved():
    result = _parse_claude_response('{"verdict": "APPROVED", "guest_message": "All good.", "reason": null}')
    assert result.verdict == ComplianceVerdict.APPROVED
    assert result.guest_message == "All good."


def test_parses_clean_json_rejected():
    result = _parse_claude_response(
        '{"verdict": "REJECTED", "guest_message": "Corrected text.", "reason": "contradicts policy"}'
    )
    assert result.verdict == ComplianceVerdict.REJECTED
    assert result.guest_message == "Corrected text."
    assert result.reason == "contradicts policy"


def test_tolerates_markdown_code_fence_wrapping():
    wrapped = '```json\n{"verdict": "APPROVED", "guest_message": "Fine.", "reason": null}\n```'
    result = _parse_claude_response(wrapped)
    assert result.verdict == ComplianceVerdict.APPROVED


def test_invalid_json_raises_llm_validation_error():
    with pytest.raises(LLMValidationError, match="not valid JSON"):
        _parse_claude_response("This is not JSON at all.")


def test_invalid_verdict_value_raises_error():
    with pytest.raises(LLMValidationError, match="invalid verdict"):
        _parse_claude_response('{"verdict": "MAYBE", "guest_message": "x", "reason": null}')


def test_missing_guest_message_raises_error():
    with pytest.raises(LLMValidationError, match="guest_message"):
        _parse_claude_response('{"verdict": "APPROVED", "guest_message": "", "reason": null}')


# =============================================================================
# 2. validate_with_claude - end-to-end with a fake client
# =============================================================================
def test_validate_with_claude_approved_path():
    fake_client = _FakeAnthropicClient(
        response_json='{"verdict": "APPROVED", "guest_message": "Check-in is at 3pm.", "reason": null}'
    )
    chunks = [_make_chunk("POL-CICO-005", "Standard check-in time is 3:00 PM.")]

    result = validate_with_claude("What time is check-in?", "Check-in is at 3pm.", chunks, client=fake_client)

    assert result.verdict == ComplianceVerdict.APPROVED
    assert result.guest_message == "Check-in is at 3pm."


def test_validate_with_claude_rejected_path_returns_corrected_message():
    fake_client = _FakeAnthropicClient(
        response_json=(
            '{"verdict": "REJECTED", '
            '"guest_message": "Unfortunately, pets are not permitted at this hotel.", '
            '"reason": "Draft claimed pets are welcome, contradicting POL-PET-011."}'
        )
    )
    chunks = [_make_chunk("POL-PET-011", "Pets are not permitted at this hotel.")]

    result = validate_with_claude(
        "Can I bring my dog?", "Yes, pets are welcome!", chunks, client=fake_client
    )

    assert result.verdict == ComplianceVerdict.REJECTED
    assert "not permitted" in result.guest_message
    assert result.reason is not None


def test_validate_with_claude_sends_correct_model_and_system_prompt():
    fake_client = _FakeAnthropicClient(
        response_json='{"verdict": "APPROVED", "guest_message": "x", "reason": null}'
    )
    validate_with_claude("q", "r", [], client=fake_client)

    assert fake_client.calls[0]["model"] == "claude-sonnet-5"
    assert "Compliance Agent" in fake_client.calls[0]["system"]


def test_validate_with_claude_handles_empty_retrieved_chunks():
    """No relevant policy was found - the prompt should say so explicitly
    rather than sending an empty/confusing excerpts section."""
    fake_client = _FakeAnthropicClient(
        response_json='{"verdict": "APPROVED", "guest_message": "Hello!", "reason": null}'
    )
    validate_with_claude("Hi", "Hello!", [], client=fake_client)

    sent_content = fake_client.calls[0]["messages"][0]["content"]
    assert "No relevant policy excerpts" in sent_content


# =============================================================================
# 3. Error handling - each real Anthropic error type covered
# =============================================================================
def _fake_httpx_response(status_code: int) -> "httpx.Response":
    """anthropic's real exception classes require a genuine httpx.Response
    (they read `.request` off it internally) - passing None crashes the
    exception's own __init__, which is exactly what happened the first
    time this test was written and run for real. This constructs a
    minimal, valid one instead."""
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code, request=request, json={"error": {"message": "test error"}})


def test_wraps_authentication_error():
    fake_client = _FakeAnthropicClient(
        raise_on_call=anthropic.AuthenticationError(
            message="bad key", response=_fake_httpx_response(401), body=None
        )
    )
    with pytest.raises(LLMValidationError, match="rejected the API key"):
        validate_with_claude("q", "r", [], client=fake_client)


def test_wraps_rate_limit_error():
    fake_client = _FakeAnthropicClient(
        raise_on_call=anthropic.RateLimitError(
            message="slow down", response=_fake_httpx_response(429), body=None
        )
    )
    with pytest.raises(LLMValidationError, match="rate limit"):
        validate_with_claude("q", "r", [], client=fake_client)


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMValidationError, match="ANTHROPIC_API_KEY is not set"):
        validate_with_claude("q", "r", [], client=None)


def test_empty_response_content_raises_error():
    class _EmptyResponse:
        content = []
        usage = _FakeUsage()

    class _EmptyMessages:
        def create(self, **kwargs):
            return _EmptyResponse()

    class _EmptyClient:
        messages = _EmptyMessages()

    with pytest.raises(LLMValidationError, match="empty response"):
        validate_with_claude("q", "r", [], client=_EmptyClient())