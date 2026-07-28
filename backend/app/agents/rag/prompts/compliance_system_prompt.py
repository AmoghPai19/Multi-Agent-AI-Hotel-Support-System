"""
compliance_system_prompt.py
------------------------------
The versioned system prompt for the Compliance Agent's real Claude
Sonnet validation call (llm_validator.py).

WHY THIS IS ITS OWN FILE, NOT AN INLINE STRING
-------------------------------------------------
This prompt went through several real, live-eval-driven revisions in a
single night - including one revision that was WRONG (it told Claude to
suppress real, correct rate-type distinctions that genuinely exist in the
hotel's actual policy documents, based on a misdiagnosis of a live eval
failure as hallucination when it was actually correct grounding). Keeping
the prompt as an inline string inside llm_validator.py made that history
invisible - a future change could just as easily repeat the same mistake
without anyone seeing why the current wording is what it is. Versioning
it here, with an explicit changelog, means every revision's reasoning
(including reverted ones) stays visible and reviewable on its own,
separate from the code that calls it.

HOW TO CHANGE THIS PROMPT
----------------------------
1. Bump COMPLIANCE_SYSTEM_PROMPT_VERSION.
2. Add a new entry to the changelog below explaining WHAT changed and,
   critically, WHY - ideally citing the specific real eval case or real
   policy document that motivated the change, the same way every entry
   below does.
3. Re-run the full pass^k eval suite (evals/run_compliance_evals.py)
   before treating the new version as production-ready - a prompt change
   that looks correct in isolation can still regress a previously-passing
   case, exactly as happened during this prompt's own history.
"""

COMPLIANCE_SYSTEM_PROMPT_VERSION = "1.2"

# =============================================================================
# CHANGELOG
# =============================================================================
# v1.0 (initial) - Base 5 rules: ground strictly in retrieved excerpts,
#   approve if consistent, reject with a corrected message if
#   contradicted, reject unverifiable specific claims, never invent
#   details not present in the retrieved excerpts.
#
# v1.1 (REVERTED - was WRONG) - Added a 6th rule forbidding Claude from
#   mentioning rate-type categories (e.g. "Flexible/BAR", "Advance
#   Purchase"), specific cutoff times (e.g. "6:00 PM"), or named
#   exceptions unless explicitly present in the retrieved excerpts. This
#   was added after a live eval run showed Claude's guest_message
#   containing exactly those terms for a cancellation-policy question,
#   which was WRONGLY assumed to be fabrication. Checking the real
#   02_cancellation_policy.md afterward showed those exact terms are
#   genuinely present in the hotel's real rate-type table - Claude was
#   reading the real document correctly the whole time. v1.1's rule would
#   have made the system actively WORSE: it told Claude to hide real,
#   correct policy distinctions from guests. Reverted in v1.2.
#
# v1.2 (current) - Reverted v1.1's harmful rule. Rule 5 now explicitly
#   cuts both ways: don't invent details that are NOT in the retrieved
#   excerpts, but don't oversimplify away real, conditional distinctions
#   that ARE in the retrieved excerpts (e.g. a rate-type-dependent
#   cancellation table) into a single blanket answer. An incomplete
#   answer that omits a real, applicable exception is itself a form of
#   inaccuracy. Proven via a live pass^3 eval run (9/9 cases, all 3
#   attempts each) after this version was deployed.
# =============================================================================

COMPLIANCE_SYSTEM_PROMPT = """You are the Compliance Agent for a hotel guest support system. Your ONLY job is to check whether a DRAFT RESPONSE is consistent with the RETRIEVED POLICY EXCERPTS provided to you.

Rules:
1. Only use the RETRIEVED POLICY EXCERPTS as your source of truth. Do not use any outside knowledge about hotel policies in general.
2. If the draft response is consistent with (or not contradicted by) the retrieved excerpts, approve it as-is.
3. If the draft response contradicts or is inconsistent with a retrieved excerpt (e.g., it says something is allowed when the policy says it isn't, or states a wrong fee/deadline/number), reject it and provide a corrected guest_message based strictly on the retrieved excerpts.
4. If the retrieved excerpts do not cover the topic the draft response makes a specific claim about, and that claim cannot be verified, reject it with a safe, generic guest_message rather than approving an unverifiable claim.
5. Never invent policy details not present in the retrieved excerpts. This cuts both ways: do not add specifics (rate types, cutoff times, categories) that are NOT in the retrieved excerpts, but if the retrieved excerpts DO contain rate-type-specific or conditional terms, your response must faithfully reflect those real distinctions rather than oversimplifying them into a single blanket answer - an incomplete answer that omits a real, applicable exception is itself a form of inaccuracy.

Respond with ONLY a JSON object, no other text, no markdown code fences, in exactly this shape:
{"verdict": "APPROVED" or "REJECTED", "guest_message": "the text to actually show the guest", "reason": "a short internal explanation, never shown to the guest"}"""