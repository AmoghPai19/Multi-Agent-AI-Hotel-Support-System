"""
eval_cases.py
--------------
The evaluation dataset for the Compliance Agent - real guest scenarios
grounded in the actual 20-policy corpus (data/policies/), used by
run_compliance_evals.py to measure the REAL production
`run_compliance_agent` (real pgvector retrieval + real Claude Sonnet
reasoning), not the offline fake-KB implementation.

Each case is either:
  - CONSISTENT: the draft response accurately reflects the real policy -
    expected verdict is APPROVED.
  - CONTRADICTORY: the draft response states something that directly
    contradicts the real policy - expected verdict is REJECTED, and the
    corrected guest_message should reflect the REAL policy fact listed
    in `must_mention` (a substring the corrected message should contain,
    used as a coarse but meaningful correctness check without requiring
    an exact string match).

WHY THIS FILE IS SEPARATE FROM tests/test_compliance_agent_real.py
---------------------------------------------------------------------
Those tests mock retrieve_top_k/validate_with_claude entirely - they
prove run_compliance_agent's own ORCHESTRATION logic is correct, cheaply
and deterministically, on every CI run. This file's cases are meant to be
run for REAL (real database, real Claude Sonnet, real cost) by
run_compliance_evals.py - a slower, non-free evaluation, run manually or
on a schedule, not on every commit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    user_message: str
    draft_response: str
    expected_verdict: str  # "APPROVED" or "REJECTED"
    must_mention: str | None = None  # required substring in a REJECTED case's corrected guest_message
    notes: str = ""


EVAL_CASES: list[EvalCase] = [
    # --- Consistent responses: should be APPROVED ---
    EvalCase(
        case_id="checkin-correct",
        user_message="What time is check-in?",
        draft_response="Standard check-in time is 3:00 PM, and check-out is by 11:00 AM.",
        expected_verdict="APPROVED",
        notes="Matches POL-CICO-005 exactly.",
    ),
    EvalCase(
        case_id="cancellation-correct",
        user_message="Can I cancel my reservation for free?",
        draft_response=(
            "It depends on your rate type. For Flexible/BAR bookings, cancellation is free up to "
            "48 hours before arrival. Advance Purchase and Non-Refundable rates cannot be cancelled "
            "for a refund at any time."
        ),
        expected_verdict="APPROVED",
        notes=(
            "CORRECTED after a real finding: the original version of this case used a blanket "
            "'free up to 48 hours' draft response and expected APPROVED. A live eval run showed "
            "Claude correctly REJECTING that blanket claim every time, and checking the real "
            "02_cancellation_policy.md confirmed why - the actual policy has a rate-type-dependent "
            "table (Flexible/BAR vs. Advance Purchase/Non-Refundable vs. Corporate/Negotiated), each "
            "with different terms. The original draft response was genuinely incomplete/misleading, "
            "not a case of Claude hallucinating. This corrected draft response reflects the real "
            "rate-type distinction and should be approved as-is."
        ),
    ),
    EvalCase(
        case_id="service-animal-correct",
        user_message="I have a service dog, is that allowed and is there a fee?",
        draft_response="Service animals are always welcome at no charge, and we won't ask for documentation.",
        expected_verdict="APPROVED",
        notes="Matches POL-PET-011 section 1 (service animals, distinct from the standard pet policy).",
    ),
    EvalCase(
        case_id="smoking-fee-correct",
        user_message="What happens if someone smokes in a non-smoking room?",
        draft_response="Smoking in a non-designated room results in a cleaning/remediation fee, typically $150-$500.",
        expected_verdict="APPROVED",
        notes="Matches POL-SMOKE-018 section 3.",
    ),

    # --- Contradictory responses: should be REJECTED, with a real correction ---
    EvalCase(
        case_id="pet-policy-contradiction",
        user_message="Can I bring my dog?",
        draft_response="Yes, pets are welcome everywhere in the hotel with no restrictions or fees.",
        expected_verdict="REJECTED",
        must_mention="fee",
        notes="Real policy (POL-PET-011) requires designated rooms + a fee; this draft falsely claims no restrictions/fees.",
    ),
    EvalCase(
        case_id="no-show-contradiction",
        user_message="What happens if I don't show up for my reservation?",
        draft_response="No-shows are not charged anything at all - the reservation is simply cancelled for free.",
        expected_verdict="REJECTED",
        must_mention="charge",
        notes="Real policy (POL-NOSHOW-004) charges the full first night for a no-show; draft falsely claims no charge.",
    ),
    EvalCase(
        case_id="deposit-timing-contradiction",
        user_message="When will my security deposit hold be released?",
        draft_response="Your deposit hold will be released and back in your account within 24 hours, guaranteed.",
        expected_verdict="REJECTED",
        must_mention="business days",
        notes="Real policy (POL-SEC-019) says typically 3-10 business days, bank-dependent - draft overpromises a guaranteed 24-hour timeline.",
    ),
    EvalCase(
        case_id="age-requirement-contradiction",
        user_message="Can my 16-year-old book and check in alone for a solo trip?",
        draft_response="Sure, anyone of any age can book and check in as the main guest, no problem.",
        expected_verdict="REJECTED",
        must_mention="18",
        notes="Real policy (POL-OCC-012) requires guests to be 18+ to be the sole registered guest - draft falsely says any age is fine.",
    ),

    # --- Ambiguous / out-of-scope: sanity check for graceful handling ---
    EvalCase(
        case_id="unrelated-question",
        user_message="What's the wifi password?",
        draft_response="I don't have that information, but the front desk can help you with wifi access.",
        expected_verdict="APPROVED",
        notes="No policy-sensitive claim made; nothing to contradict, so this should be approved as a safe, honest answer.",
    ),
]