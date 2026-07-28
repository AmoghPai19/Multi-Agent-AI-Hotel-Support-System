"""
test_eval_harness.py
-----------------------
Tests for evals/run_compliance_evals.py's SCORING LOGIC - proving
pass^k is computed correctly - using a mocked `run_compliance_agent` so
these tests are free, fast, and run in normal CI, unlike the real evals
themselves (evals/run_compliance_evals.py), which make real, costly API
calls and are run manually/on a schedule instead.

The key thing these tests must prove: the harness genuinely detects
INCONSISTENCY across k attempts (a flaky agent that's right 2/3 times
must be scored as FAILED, not as a pass), not just "did it work at least
once" - that distinction is the entire point of pass^k over pass@k.
"""

from __future__ import annotations

from unittest.mock import patch

from evals.eval_cases import EvalCase
from evals.run_compliance_evals import run_case


def _make_agent_result(verdict: str, guest_message: str) -> dict:
    class _FakeVerdict:
        def __init__(self, value):
            self.value = value

    return {
        "compliance_status": {
            "status": _FakeVerdict(verdict),
            "guest_message": guest_message,
            "reason_code": None,
            "internal_reason": None,
            "metadata": None,
        }
    }


def test_case_passes_when_every_attempt_matches_expected_verdict():
    case = EvalCase(
        case_id="test-approve", user_message="q", draft_response="r", expected_verdict="APPROVED"
    )
    with patch("evals.run_compliance_evals.run_compliance_agent") as mock_agent:
        mock_agent.return_value = _make_agent_result("APPROVED", "All good.")

        result = run_case(case, k=3)

        assert result.passed_all
        assert result.attempts_passed == 3
        assert mock_agent.call_count == 3


def test_case_fails_when_verdict_is_wrong_even_once():
    """The core pass^k guarantee: a case that's right on 2 of 3 attempts
    must be reported as FAILED, not as a partial pass."""
    case = EvalCase(
        case_id="test-flaky", user_message="q", draft_response="r", expected_verdict="REJECTED"
    )
    responses = [
        _make_agent_result("REJECTED", "Corrected text."),
        _make_agent_result("APPROVED", "Wrong! Should have been rejected."),  # the flake
        _make_agent_result("REJECTED", "Corrected text."),
    ]
    with patch("evals.run_compliance_evals.run_compliance_agent") as mock_agent:
        mock_agent.side_effect = responses

        result = run_case(case, k=3)

        assert not result.passed_all
        assert result.attempts_passed == 2
        assert "FAIL" in result.attempt_details[1]


def test_case_checks_must_mention_substring_for_rejected_cases():
    case = EvalCase(
        case_id="test-mention", user_message="q", draft_response="r",
        expected_verdict="REJECTED", must_mention="48 hours",
    )
    with patch("evals.run_compliance_evals.run_compliance_agent") as mock_agent:
        # Correct verdict, but the correction doesn't actually mention the
        # required real-policy fact - this must still count as a failure.
        mock_agent.return_value = _make_agent_result("REJECTED", "Some generic rejection with no specifics.")

        result = run_case(case, k=2)

        assert not result.passed_all
        assert result.attempts_passed == 0
        assert "did not mention required fact" in result.attempt_details[0]


def test_must_mention_check_is_case_insensitive():
    case = EvalCase(
        case_id="test-case-insensitive", user_message="q", draft_response="r",
        expected_verdict="REJECTED", must_mention="Business Days",
    )
    with patch("evals.run_compliance_evals.run_compliance_agent") as mock_agent:
        mock_agent.return_value = _make_agent_result(
            "REJECTED", "It typically takes 3-10 business days for funds to appear."
        )

        result = run_case(case, k=1)

        assert result.passed_all


def test_approved_cases_do_not_require_must_mention_check():
    case = EvalCase(
        case_id="test-approved-no-mention", user_message="q", draft_response="r",
        expected_verdict="APPROVED",
    )
    with patch("evals.run_compliance_evals.run_compliance_agent") as mock_agent:
        mock_agent.return_value = _make_agent_result("APPROVED", "Anything at all.")

        result = run_case(case, k=1)

        assert result.passed_all


def test_completely_unreliable_agent_scores_zero():
    case = EvalCase(
        case_id="test-always-wrong", user_message="q", draft_response="r", expected_verdict="APPROVED"
    )
    with patch("evals.run_compliance_evals.run_compliance_agent") as mock_agent:
        mock_agent.return_value = _make_agent_result("REJECTED", "Always wrong.")

        result = run_case(case, k=5)

        assert not result.passed_all
        assert result.attempts_passed == 0