"""
test_compliance_agent_real.py
--------------------------------
Tests for app.agents.compliance.run_compliance_agent - the REAL
production Compliance Agent (real pgvector retrieval + real Claude Sonnet
reasoning), as opposed to the offline fake-KB implementation tested in
tests/test_compliance_agent.py.

This file mocks `retrieve_top_k` and `validate_with_claude` at the
module level (they already have their own dedicated, thorough test
files - tests/test_retriever.py against a real database, and
tests/test_llm_validator.py against a fake Anthropic client) - these
tests exist ONLY to prove `run_compliance_agent`'s own orchestration
logic is correct: does it call retrieval, pass the right things to
validation, map the result into the correct ComplianceStatus envelope,
and fail closed if either step raises.

Run with:
    cd backend && pytest tests/test_compliance_agent_real.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.compliance import run_compliance_agent
from app.agents.graph import ComplianceVerdict
from app.agents.rag.llm_validator import LLMValidationError, LLMValidationResult
from app.agents.rag.retriever import RetrievalError, RetrievedChunk


def _make_chunk(policy_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        policy_id=policy_id, document_title=f"Test {policy_id}",
        category="test", content="Some real policy text.", similarity=0.9,
    )


# =============================================================================
# 1. Happy path - approved
# =============================================================================
def test_approved_path_maps_correctly_into_compliance_status():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = [_make_chunk("POL-CICO-005")]
        mock_validate.return_value = LLMValidationResult(
            verdict=ComplianceVerdict.APPROVED,
            guest_message="Check-in is at 3pm.",
            reason=None,
        )

        state = {"guest_id": "g1", "user_message": "What time is check-in?", "draft_response": "Check-in is at 3pm."}
        result = run_compliance_agent(state)

        cs = result["compliance_status"]
        assert cs["status"] == ComplianceVerdict.APPROVED
        assert cs["guest_message"] == "Check-in is at 3pm."
        assert cs["metadata"]["retrieved_policy_ids"] == ["POL-CICO-005"]


# =============================================================================
# 2. Happy path - rejected, with corrected guest_message
# =============================================================================
def test_rejected_path_carries_corrected_guest_message_and_reason():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = [_make_chunk("POL-PET-011")]
        mock_validate.return_value = LLMValidationResult(
            verdict=ComplianceVerdict.REJECTED,
            guest_message="Unfortunately, pets are not permitted at this hotel.",
            reason="Draft claimed pets are welcome, contradicting POL-PET-011.",
        )

        state = {"guest_id": "g1", "user_message": "Can I bring my dog?", "draft_response": "Yes, pets are welcome!"}
        result = run_compliance_agent(state)

        cs = result["compliance_status"]
        assert cs["status"] == ComplianceVerdict.REJECTED
        assert "not permitted" in cs["guest_message"]
        assert cs["internal_reason"] is not None
        assert "contradicting" in cs["internal_reason"]


# =============================================================================
# 3. Orchestration correctness - right arguments passed through
# =============================================================================
def test_passes_combined_query_to_retriever():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = []
        mock_validate.return_value = LLMValidationResult(
            verdict=ComplianceVerdict.APPROVED, guest_message="Hi!", reason=None
        )

        run_compliance_agent({"guest_id": "g1", "user_message": "Hello", "draft_response": "Hi there!"})

        query_arg = mock_retrieve.call_args[0][0]
        assert "Hello" in query_arg
        assert "Hi there!" in query_arg


def test_passes_retrieved_chunks_to_validator():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        chunk = _make_chunk("POL-TEST-001")
        mock_retrieve.return_value = [chunk]
        mock_validate.return_value = LLMValidationResult(
            verdict=ComplianceVerdict.APPROVED, guest_message="x", reason=None
        )

        run_compliance_agent({"guest_id": "g1", "user_message": "q", "draft_response": "r"})

        passed_chunks = mock_validate.call_args[0][2]
        assert passed_chunks == [chunk]


def test_no_metadata_when_nothing_retrieved():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = []
        mock_validate.return_value = LLMValidationResult(
            verdict=ComplianceVerdict.APPROVED, guest_message="Hi!", reason=None
        )

        result = run_compliance_agent({"guest_id": "g1", "user_message": "Hi", "draft_response": "Hi!"})
        assert result["compliance_status"]["metadata"] is None


# =============================================================================
# 4. Fail-closed: NO silent fallback to the offline fake-KB path
# =============================================================================
def test_fails_closed_when_retrieval_raises():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve:
        mock_retrieve.side_effect = RetrievalError("DATABASE_URL_RO is not set")

        result = run_compliance_agent({"guest_id": "g1", "user_message": "q", "draft_response": "r"})

        cs = result["compliance_status"]
        assert cs["status"] == ComplianceVerdict.SYSTEM_ERROR
        assert "Sorry" in cs["guest_message"]


def test_fails_closed_when_llm_validation_raises():
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = []
        mock_validate.side_effect = LLMValidationError("ANTHROPIC_API_KEY is not set")

        result = run_compliance_agent({"guest_id": "g1", "user_message": "q", "draft_response": "r"})

        cs = result["compliance_status"]
        assert cs["status"] == ComplianceVerdict.SYSTEM_ERROR
        assert "Sorry" in cs["guest_message"]


@pytest.mark.parametrize("bad_key", ["guest_id", "user_message", "draft_response"])
def test_fails_closed_on_state_access_error(bad_key):
    """Same defense-in-depth check as the offline implementation - every
    field access must be inside the try block, not before it."""

    class ExplodingState(dict):
        def get(self, key, default=None):
            if key == bad_key:
                raise RuntimeError(f"Simulated failure reading {key}")
            return super().get(key, default)

    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = []
        mock_validate.return_value = LLMValidationResult(
            verdict=ComplianceVerdict.APPROVED, guest_message="x", reason=None
        )

        state = ExplodingState({"guest_id": "g1", "user_message": "q", "draft_response": "r"})
        result = run_compliance_agent(state)

        assert result["compliance_status"]["status"] == ComplianceVerdict.SYSTEM_ERROR


# =============================================================================
# 5. Return shape always matches the frozen envelope
# =============================================================================
@pytest.mark.parametrize(
    "verdict",
    [ComplianceVerdict.APPROVED, ComplianceVerdict.REJECTED],
)
def test_return_shape_always_matches_frozen_envelope(verdict):
    with patch("app.agents.compliance.retrieve_top_k") as mock_retrieve, \
         patch("app.agents.compliance.validate_with_claude") as mock_validate:
        mock_retrieve.return_value = []
        mock_validate.return_value = LLMValidationResult(
            verdict=verdict, guest_message="Some message.", reason="Some reason."
        )

        result = run_compliance_agent({"guest_id": "g1", "user_message": "q", "draft_response": "r"})
        cs = result["compliance_status"]

        assert set(cs.keys()) == {"status", "guest_message", "reason_code", "internal_reason", "metadata"}
        assert isinstance(cs["guest_message"], str) and cs["guest_message"]