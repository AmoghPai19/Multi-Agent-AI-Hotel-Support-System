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
        user_message="I booked a Flexible/BAR rate - can I cancel for free?",
        draft_response=(
            "Yes, for a Flexible/BAR rate, cancellation is free if done at least 48 hours "
            "(by 6:00 PM property local time) before your arrival date. After that cutoff, "
            "or in the case of a no-show, a charge of one night's room plus tax applies."
        ),
        expected_verdict="APPROVED",
        notes=(
            "CORRECTED for a third time, this time verified against every single column of the "
            "exact real table row before finalizing (not an approximation): the real "
            "02_cancellation_policy.md Flexible/BAR row is "
            "'48 hours (6:00 PM property local time) before arrival date | 1 night's room + tax | "
            "1 night's room + tax' (cutoff / after-cutoff penalty / no-show penalty). Earlier "
            "versions of this case omitted the '6:00 PM property local time' qualifier and the "
            "no-show penalty column, which is very likely why the second correction was still "
            "rejected 3/3 (Claude flagging incompleteness relative to the SPECIFIC row asked "
            "about, not just the category). This version covers all 4 columns of that one row "
            "exactly, since the question now names a single specific rate type."
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