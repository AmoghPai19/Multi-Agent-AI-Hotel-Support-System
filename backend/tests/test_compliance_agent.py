"""
test_compliance_agent.py
--------------------------
Tests for app.agents.compliance.run_compliance_agent_offline_fake_kb -
proving the approve/reject/fail-closed logic is genuinely implemented,
not just an unconditional "approved" stub.

NAMING NOTE: this file tests the OFFLINE fake-KB implementation
specifically (no database, no API key, no network - fast and free).
graph.py's compliance_node now calls `run_compliance_agent` (no
"_offline_fake_kb" suffix), which is the REAL production implementation
using retriever.py + llm_validator.py - see
tests/test_compliance_agent_real.py for that function's tests. Both
implementations are exercised directly here (no graph involved).

Run with:
    cd backend && pytest tests/test_compliance_agent.py -v
"""

from __future__ import annotations

import pytest

from app.agents.compliance import (
    FAIL_CLOSED_MESSAGE,
    check_for_policy_violation,
    retrieve_relevant_policies,
    run_compliance_agent_offline_fake_kb,
)
from app.agents.graph import ComplianceVerdict


# =============================================================================
# 1. RETRIEVAL (placeholder keyword-overlap retriever)
# =============================================================================
@pytest.mark.parametrize(
    "query,expected_top_policy_id",
    [
        ("Can I bring my dog to the hotel?", "POL-002"),
        ("I need to cancel my reservation", "POL-001"),
        ("What time is check-in?", "POL-004"),
        ("Is there an age requirement for guests?", "POL-003"),
    ],
)
def test_retrieval_finds_the_expected_policy(query: str, expected_top_policy_id: str):
    results = retrieve_relevant_policies(query)
    assert results, f"No policies retrieved for query: {query!r}"
    assert results[0].policy_id == expected_top_policy_id


def test_retrieval_returns_empty_for_unrelated_query():
    results = retrieve_relevant_policies("What's the wifi password?")
    assert results == []


# =============================================================================
# 2. GENUINE APPROVED VERDICTS
# =============================================================================
def test_approves_a_consistent_response():
    state = {
        "guest_id": "g1",
        "user_message": "What time is check-in?",
        "draft_response": "Standard check-in time is 3:00 PM.",
    }
    result = run_compliance_agent_offline_fake_kb(state)
    compliance_status = result["compliance_status"]

    assert compliance_status["status"] == ComplianceVerdict.APPROVED
    assert compliance_status["guest_message"] == state["draft_response"]
    assert compliance_status["reason_code"] is None
    assert compliance_status["internal_reason"] is None


def test_approves_when_no_policy_is_relevant():
    state = {
        "guest_id": "g1",
        "user_message": "What's the wifi password?",
        "draft_response": "I'll help answer your hotel-related question.",
    }
    result = run_compliance_agent_offline_fake_kb(state)
    assert result["compliance_status"]["status"] == ComplianceVerdict.APPROVED


# =============================================================================
# 3. GENUINE REJECTED VERDICTS - the core behavior this task is proving
# =============================================================================
def test_rejects_a_response_that_contradicts_the_pet_policy():
    state = {
        "guest_id": "g2",
        "user_message": "Can I bring my dog?",
        "draft_response": "Yes, pets are welcome at our hotel!",
    }
    result = run_compliance_agent_offline_fake_kb(state)
    compliance_status = result["compliance_status"]

    assert compliance_status["status"] == ComplianceVerdict.REJECTED
    # The guest-safe message must contain the REAL policy text, not a
    # vague error - and must NOT be the original (incorrect) draft.
    assert "not permitted" in compliance_status["guest_message"]
    assert compliance_status["guest_message"] != state["draft_response"]
    assert compliance_status["reason_code"] == "policy_violation:pets"
    assert "POL-002" in compliance_status["metadata"]["violated_policy_id"]


def test_rejects_a_response_that_contradicts_the_cancellation_policy():
    state = {
        "guest_id": "g3",
        "user_message": "Can I cancel my reservation?",
        "draft_response": "You can cancel anytime for a full refund.",
    }
    result = run_compliance_agent_offline_fake_kb(state)
    compliance_status = result["compliance_status"]

    assert compliance_status["status"] == ComplianceVerdict.REJECTED
    assert compliance_status["reason_code"] == "policy_violation:cancellation"


def test_rejection_never_exposes_internal_reason_in_guest_message():
    """The `internal_reason` diagnostic text must never leak into the
    guest-facing `guest_message` field - only FastAPI/logs should ever
    see `internal_reason` (see the Compliance Verdict Contract's
    Rejection Contract section)."""
    state = {
        "guest_id": "g4",
        "user_message": "Can I bring my dog?",
        "draft_response": "Yes, pets are welcome at our hotel!",
    }
    result = run_compliance_agent_offline_fake_kb(state)
    compliance_status = result["compliance_status"]

    assert compliance_status["internal_reason"] is not None
    assert compliance_status["internal_reason"] not in compliance_status["guest_message"]
    assert "contradiction phrase" not in compliance_status["guest_message"]


# =============================================================================
# 4. FAIL-CLOSED - every failure point genuinely produces SYSTEM_ERROR
# =============================================================================
def _make_exploding_state(bad_key: str) -> dict:
    """A state whose `.get(bad_key)` always raises, simulating an
    unexpected internal failure at that specific point."""

    class ExplodingState(dict):
        def get(self, key, default=None):
            if key == bad_key:
                raise RuntimeError(f"Simulated failure reading {bad_key}")
            return super().get(key, default)

    return ExplodingState({"guest_id": "g5", "user_message": "x", "draft_response": "y"})


@pytest.mark.parametrize("bad_key", ["guest_id", "user_message", "draft_response"])
def test_fails_closed_on_state_access_error(bad_key: str):
    """Proves fail-closed covers EVERY field access, not just one - this
    test caught a real bug during development where only draft_response
    was protected by the try block, and a failure reading guest_id or
    user_message would have propagated as an unhandled exception instead
    of failing closed."""
    state = _make_exploding_state(bad_key)
    result = run_compliance_agent_offline_fake_kb(state)
    compliance_status = result["compliance_status"]

    assert compliance_status["status"] == ComplianceVerdict.SYSTEM_ERROR
    assert compliance_status["guest_message"] == FAIL_CLOSED_MESSAGE
    assert compliance_status["internal_reason"] is not None


def test_fails_closed_when_retrieval_itself_raises(monkeypatch):
    """Proves fail-closed also covers a failure inside the retrieval step
    itself (e.g. a future real pgvector call timing out), not just bad
    input data."""
    import app.agents.compliance as compliance_module

    def broken_retriever(*_args, **_kwargs):
        raise RuntimeError("Simulated retrieval failure")

    monkeypatch.setattr(compliance_module, "retrieve_relevant_policies", broken_retriever)

    result = run_compliance_agent_offline_fake_kb({"guest_id": "g6", "user_message": "x", "draft_response": "y"})
    compliance_status = result["compliance_status"]

    assert compliance_status["status"] == ComplianceVerdict.SYSTEM_ERROR
    assert compliance_status["guest_message"] == FAIL_CLOSED_MESSAGE


# =============================================================================
# 5. RETURN SHAPE - matches the frozen ComplianceStatus envelope exactly
# =============================================================================
@pytest.mark.parametrize(
    "state",
    [
        {"guest_id": "g7", "user_message": "hi", "draft_response": "hello"},
        {"guest_id": "g8", "user_message": "Can I bring my dog?", "draft_response": "Yes, pets are welcome!"},
        _make_exploding_state("draft_response"),
    ],
)
def test_return_shape_always_matches_frozen_envelope(state):
    """Regardless of approve/reject/fail-closed, the returned
    `compliance_status` must always have exactly these five keys - never
    more, never fewer, never a bare string (per the Compliance Verdict
    Contract)."""
    result = run_compliance_agent_offline_fake_kb(state)
    assert set(result.keys()) == {"compliance_status"}
    compliance_status = result["compliance_status"]
    assert set(compliance_status.keys()) == {
        "status", "guest_message", "reason_code", "internal_reason", "metadata",
    }
    assert compliance_status["status"] in (
        ComplianceVerdict.APPROVED, ComplianceVerdict.REJECTED, ComplianceVerdict.SYSTEM_ERROR,
    )
    assert isinstance(compliance_status["guest_message"], str) and compliance_status["guest_message"]


# =============================================================================
# 6. `check_for_policy_violation` unit tests (isolated from retrieval)
# =============================================================================
def test_check_for_policy_violation_detects_contradiction():
    policies = retrieve_relevant_policies("Can I bring my dog?")
    violation = check_for_policy_violation("Yes, pets are welcome at our hotel!", policies)
    assert violation is not None
    violated_policy, matched_phrase = violation
    assert violated_policy.policy_id == "POL-002"
    assert matched_phrase == "pets are welcome"


def test_check_for_policy_violation_returns_none_when_consistent():
    policies = retrieve_relevant_policies("Can I bring my dog?")
    violation = check_for_policy_violation("Unfortunately, pets are not permitted here.", policies)
    assert violation is None