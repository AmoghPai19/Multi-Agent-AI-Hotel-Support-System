"""
llm_validator.py
------------------
Real Claude Sonnet-based validation of a draft response against retrieved
real policy content - replaces compliance.py's fixed
`check_for_policy_violation` phrase-matching with genuine reasoning,
which is required once real policy_chunks (via retriever.py) replace the
fake, hand-written 4-policy knowledge base.

This is a NEW capability, not yet wired into `compliance.py`'s
`run_compliance_agent` (see graph.py's compliance_node and
docs/agents/compliance_agent.md for the current, still-active fake-KB
path). Cutting compliance.py over to call this module instead is a
deliberate, separate integration step - see "INTEGRATION STATUS" below.

WHY A SEPARATE MODULE, NOT A COMPLIANCE.PY REWRITE
----------------------------------------------------
compliance.py's existing fake-KB-based `run_compliance_agent` is fully
tested (19 tests) and requires zero external dependencies (no network,
no API key) - it remains valuable as a fast, free, offline-testable
baseline. This module adds the REAL capability alongside it, so the
cutover to real retrieval + real reasoning can happen as one explicit,
reviewable step, rather than silently replacing a well-tested path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import anthropic
from langsmith import traceable

from app.agents.graph import ComplianceVerdict
from app.agents.rag.prompts.compliance_system_prompt import COMPLIANCE_SYSTEM_PROMPT
from app.agents.rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

# Must match the model specified in technology_decisions.md and
# graph_entry_contracts.md's "Claude Sonnet" requirement, and the exact
# model verified live by scripts/verify_anthropic_key.py.
CLAUDE_MODEL = "claude-sonnet-5"

# Keep responses cheap, but generous enough for a real, detailed
# correction (e.g. a cancellation policy with multiple rate-type
# exceptions). A previous value of 300 was found, via a real live eval
# run, to be too small: several genuine corrected guest_message strings
# were cut off mid-sentence, producing truncated/invalid JSON that looked
# like a parsing bug but was actually a token-limit bug.
_MAX_TOKENS = 1024


class LLMValidationError(Exception):
    """Raised when Claude validation cannot complete for any reason (auth,
    rate limit, connectivity, or a response that isn't valid, parseable
    JSON) - the caller (compliance.py) is expected to treat this as a
    SYSTEM_ERROR / fail-closed condition, exactly like EmbeddingError and
    RetrievalError are treated elsewhere in the RAG pipeline."""


@dataclass(frozen=True)
class LLMValidationResult:
    """The Claude-judged outcome of validating a draft response."""

    verdict: ComplianceVerdict     # APPROVED or REJECTED (never SYSTEM_ERROR - that's raised as LLMValidationError instead)
    guest_message: str             # what to actually tell the guest (corrected if REJECTED)
    reason: str | None             # human-readable reason, for reason_code/internal_reason - never shown to the guest


# The system prompt is defined in prompts/compliance_system_prompt.py, not
# inline here - see that module's docstring for why (its own real,
# eval-driven revision history, including a reverted mistake).


def _build_user_message(user_message: str, draft_response: str, retrieved_chunks: list[RetrievedChunk]) -> str:
    if retrieved_chunks:
        excerpts = "\n\n".join(
            f"[{chunk.policy_id} - {chunk.document_title}]\n{chunk.content}"
            for chunk in retrieved_chunks
        )
    else:
        excerpts = "(No relevant policy excerpts were retrieved for this query.)"

    return (
        f"GUEST QUESTION:\n{user_message}\n\n"
        f"DRAFT RESPONSE TO VALIDATE:\n{draft_response}\n\n"
        f"RETRIEVED POLICY EXCERPTS:\n{excerpts}"
    )


def _parse_claude_response(raw_text: str) -> LLMValidationResult:
    """Parse Claude's JSON response, tolerating markdown code fences in
    case the model wraps its output despite instructions not to."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Strip a leading ```json / ``` and a trailing ``` if present.
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMValidationError(f"Claude's response was not valid JSON: {raw_text!r}") from exc

    verdict_str = parsed.get("verdict")
    guest_message = parsed.get("guest_message")
    reason = parsed.get("reason")

    if verdict_str not in ("APPROVED", "REJECTED"):
        raise LLMValidationError(f"Claude returned an invalid verdict value: {verdict_str!r}")
    if not guest_message:
        raise LLMValidationError("Claude's response did not include a guest_message")

    return LLMValidationResult(
        verdict=ComplianceVerdict(verdict_str),
        guest_message=guest_message,
        reason=reason,
    )


@traceable(name="validate_with_claude", run_type="llm")
def validate_with_claude(
    user_message: str,
    draft_response: str,
    retrieved_chunks: list[RetrievedChunk],
    client: anthropic.Anthropic | None = None,
) -> LLMValidationResult:
    """Ask Claude Sonnet to judge whether `draft_response` is consistent
    with `retrieved_chunks`, returning a structured verdict.

    Args:
        user_message: the guest's original question.
        draft_response: the Conversation Agent's candidate reply.
        retrieved_chunks: real policy sections from retriever.py's
            retrieve_top_k() - may be empty (see rule 4 in the system
            prompt: an empty list means "nothing relevant was found").
        client: an existing anthropic.Anthropic client, or None to create
            one from ANTHROPIC_API_KEY. Accepting an injected client is
            what makes this testable without a real API key - see
            tests/test_llm_validator.py.

    Raises:
        LLMValidationError: on any failure - missing key, API error, or
            a response that isn't valid/parseable JSON. The caller must
            treat this as a fail-closed (SYSTEM_ERROR) condition, exactly
            like every other RAG-pipeline error type in this codebase.
    """
    import os

    anthropic_client = client
    if anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMValidationError(
                "ANTHROPIC_API_KEY is not set. Check your .env file - see "
                "scripts/verify_anthropic_key.py."
            )
        anthropic_client = anthropic.Anthropic(api_key=api_key)

    try:
        response = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=COMPLIANCE_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _build_user_message(user_message, draft_response, retrieved_chunks)}
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMValidationError(f"Anthropic rejected the API key: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMValidationError(f"Anthropic rate limit hit: {exc}") from exc
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
        raise LLMValidationError(f"Anthropic was unreachable: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMValidationError(f"Anthropic API returned an error: {exc}") from exc

    if not response.content:
        raise LLMValidationError("Claude returned an empty response")

    # Detect truncation EXPLICITLY, before attempting to parse - a
    # truncated response is not "invalid JSON" (a parsing problem), it's
    # "the response was cut off" (a token-limit problem), and conflating
    # the two makes this exact bug look like a JSON-parsing issue rather
    # than what it actually is. Found via a real live eval run: a detailed
    # policy correction genuinely exceeded the previous, too-small
    # _MAX_TOKENS value and got cut off mid-sentence.
    if response.stop_reason == "max_tokens":
        raise LLMValidationError(
            f"Claude's response was truncated (hit max_tokens={_MAX_TOKENS}) before "
            f"completing valid JSON. Increase _MAX_TOKENS in llm_validator.py."
        )

    # BUG FIX (found via a real live eval run): Claude Sonnet can return a
    # `ThinkingBlock` (its internal reasoning trace) as an EARLIER content
    # block before the actual `TextBlock` answer - content[0] is not
    # reliably the text block. Find the first block that actually has
    # type "text" instead of assuming position 0.
    text_blocks = [block for block in response.content if getattr(block, "type", None) == "text"]
    if not text_blocks:
        raise LLMValidationError(
            f"Claude's response contained no text block (got block types: "
            f"{[getattr(b, 'type', type(b).__name__) for b in response.content]})"
        )
    raw_text = text_blocks[0].text

    logger.info("Claude validation call complete", extra={"input_tokens": response.usage.input_tokens})

    return _parse_claude_response(raw_text)