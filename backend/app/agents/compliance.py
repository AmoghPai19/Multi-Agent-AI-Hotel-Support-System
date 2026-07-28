"""
compliance.py
--------------
Implementation of the Compliance Agent for the Multi-Agent AI Hotel
Support System.

ROLE OF THIS FILE
------------------
Per docs/agents/compliance_agent.md and the Compliance Verdict Contract,
the Compliance Agent validates every candidate response before it is
allowed to reach a guest. It:
  - retrieves relevant hotel policies for the guest's query,
  - checks whether the Conversation Agent's draft response actually
    CONTRADICTS any of those retrieved policies,
  - and returns a verdict: APPROVED, REJECTED (with the real policy text
    as a guest-safe correction), or SYSTEM_ERROR (if validation itself
    could not complete).

This file must NEVER:
  - talk to the guest directly (only graph.py's compliance_node calls it,
    and only the Conversation Agent ever faces the guest),
  - touch PostgreSQL or reservation data,
  - perform reservation logic,
  - or silently approve a response that contradicts a policy it actually
    found.

WHAT THIS FILE CURRENTLY IS
-----------------------------
Per the Plan of Action (Phase 2, Mithun #3: "Compliance agent - in-memory
fake retriever first; get approve / reject / fail-closed right"), this is
a REAL implementation of the approve/reject/fail-closed control flow,
using a small, hardcoded, in-memory "fake" policy knowledge base instead
of real pgvector similarity search, and simple keyword/phrase matching
instead of a real embedding model and LLM reasoning. Every placeholder is
marked with a TODO describing exactly what replaces it later (see "FUTURE
TODOs" at the bottom of this file). Despite using fake retrieval and
fake contradiction-detection, the CONTROL FLOW here is real and fully
tested - see tests/test_compliance_agent.py.
"""

# --- Standard library imports -----------------------------------------------
import logging
from dataclasses import dataclass, field

# --- Internal imports ---------------------------------------------------------
# Every shared/frozen type is imported from graph.py rather than
# redeclared here - graph.py is the canonical source of truth for
# HotelSupportState, ComplianceVerdict, ComplianceStatus,
# FAIL_CLOSED_MESSAGE, and NodeResult. Importing FAIL_CLOSED_MESSAGE here
# also makes it accessible as `app.agents.compliance.FAIL_CLOSED_MESSAGE`,
# which is how this module's own tests reference it - there is still only
# one definition of this string anywhere in the codebase (in graph.py).
from app.agents.graph import (
    ComplianceStatus,
    ComplianceVerdict,
    FAIL_CLOSED_MESSAGE,
    HotelSupportState,
    NodeResult,
)

# Module-level logger, following the same pattern as conversation.py: no
# handlers or `basicConfig()` are configured here.
logger = logging.getLogger(__name__)


# =============================================================================
# 1. FAKE POLICY KNOWLEDGE BASE (in-memory stand-in for pgvector)
# =============================================================================
@dataclass(frozen=True)
class Policy(object):
    """A single retrievable hotel policy.

    TODO (future task): once Amogh's `policy_chunks` table exists (see
    docs/rag/rag_design.md), this shape will be populated from real
    ingested documents and retrieved via a pgvector similarity search
    instead of this hardcoded list.

    Fields:
        policy_id: stable identifier (e.g. "POL-001").
        category: short machine-readable category, used to build
            `reason_code` values like "policy_violation:pets".
        keywords: words/phrases used by the placeholder retriever to
            decide this policy is relevant to a guest's query - a stand-in
            for what a real embedding model would infer semantically.
        correct_statement: the actual, correct policy text. Used as the
            guest-facing message when a draft response is rejected for
            contradicting this policy - the guest always gets the RIGHT
            answer, not just a rejection notice.
        contradiction_phrases: phrases that, if found in a draft response,
            indicate that response contradicts this policy. A stand-in
            for what a real LLM would determine by actually reasoning
            about consistency, rather than fixed phrase matching.
    """

    policy_id: str
    category: str
    keywords: list[str] = field(default_factory=list)
    correct_statement: str = ""
    contradiction_phrases: list[str] = field(default_factory=list)


_FAKE_POLICY_KNOWLEDGE_BASE: list[Policy] = [
    Policy(
        policy_id="POL-001",
        category="cancellation",
        keywords=["cancel", "cancellation", "reservation"],
        correct_statement=(
            "Reservations may be cancelled free of charge up to 48 hours before "
            "check-in. Cancellations made within 48 hours of check-in are subject "
            "to a one-night charge, and a full refund is not guaranteed."
        ),
        contradiction_phrases=["cancel anytime", "full refund", "for a full refund"],
    ),
    Policy(
        policy_id="POL-002",
        category="pets",
        keywords=["dog", "pet", "cat", "animal"],
        correct_statement="Unfortunately, pets are not permitted at this hotel.",
        contradiction_phrases=["pets are welcome", "pets allowed", "bring your pet"],
    ),
    Policy(
        policy_id="POL-003",
        category="age_requirement",
        keywords=["age", "requirement", "guest", "old", "minor"],
        correct_statement=(
            "Guests must be at least 18 years old to check in without a parent "
            "or legal guardian present."
        ),
        contradiction_phrases=["no age requirement", "any age", "no minimum age"],
    ),
    Policy(
        policy_id="POL-004",
        category="check_in_time",
        keywords=["check-in", "check in", "time", "arrival"],
        correct_statement="Standard check-in time is 3:00 PM and check-out is 11:00 AM.",
        contradiction_phrases=["check in anytime", "no set check-in time", "24 hour check-in"],
    ),
]


# =============================================================================
# 2. FAKE RETRIEVER (in-memory stand-in for a pgvector similarity search)
# =============================================================================
def retrieve_relevant_policies(query: str) -> list[Policy]:
    """Retrieve the policies relevant to a guest's query.

    TODO (future task): replace this entire function with a real
    pgvector similarity search against Amogh's `policy_chunks` table (see
    docs/rag/rag_design.md - Retrieval Workflow). This placeholder scores
    each policy by how many of its hand-picked `keywords` appear as a
    substring of the query - a coarse, keyword-based stand-in for real
    semantic similarity. It reliably finds the right policy for direct
    queries (e.g. "can I bring my dog") but, unlike a real embedding
    model, will miss genuinely paraphrased queries that don't happen to
    share any of the listed keywords.

    Returns:
        Policies with at least one keyword match, sorted by number of
        matching keywords (most relevant first). Returns an empty list
        if nothing matches - this is a valid, expected outcome (e.g. for
        an unrelated question like "what's the wifi password?"), not an
        error.
    """
    normalized_query = query.lower()

    scored: list[tuple[Policy, int]] = []
    for policy in _FAKE_POLICY_KNOWLEDGE_BASE:
        score = sum(1 for keyword in policy.keywords if keyword in normalized_query)
        if score > 0:
            scored.append((policy, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [policy for policy, _score in scored]


# =============================================================================
# 3. CONTRADICTION DETECTION (placeholder for real Claude Sonnet reasoning)
# =============================================================================
def check_for_policy_violation(
    draft_response: str, policies: list[Policy]
) -> tuple[Policy, str] | None:
    """Check whether `draft_response` contradicts any of `policies`.

    TODO (future task): replace this entire function with a real Claude
    Sonnet call that reasons about whether `draft_response` is actually
    consistent with each retrieved policy's real text - this placeholder
    can only catch contradictions that happen to match one of a policy's
    hand-picked `contradiction_phrases` verbatim; a real model would catch
    contradictions phrased in ways this fixed list cannot anticipate.

    Args:
        draft_response: the Conversation Agent's candidate reply.
        policies: the policies retrieved as relevant to this turn (see
            `retrieve_relevant_policies`). Only these are checked - a
            policy that was never retrieved is never checked against,
            since it was judged irrelevant to the guest's query.

    Returns:
        `(violated_policy, matched_phrase)` for the first contradiction
        found, or `None` if `draft_response` does not contradict any of
        the given policies.
    """
    normalized_response = draft_response.lower()

    for policy in policies:
        for phrase in policy.contradiction_phrases:
            if phrase in normalized_response:
                return policy, phrase

    return None


# =============================================================================
# 4. MAIN ENTRY POINT - called by graph.py's compliance_node
# =============================================================================
def run_compliance_agent(state: HotelSupportState) -> NodeResult:
    """Run the Compliance Agent for the current turn.

    Returns a partial state update containing a fully-formed
    `ComplianceStatus` envelope (see graph.py). This function handles its
    own expected failure modes internally and always returns a
    well-formed envelope rather than raising - `compliance_node`'s own
    try/except in graph.py is a backstop for anything unexpected that
    escapes this function entirely, not the primary fail-closed
    mechanism.

    IMPORTANT: every piece of state access (`guest_id`, `user_message`,
    `draft_response`) happens INSIDE the try block below, not before it.
    An earlier version of this function extracted `guest_id` before
    entering the try block so it could be included in the "started" log
    line - that meant a failure reading `guest_id` itself would have
    propagated as an unhandled exception instead of failing closed. Every
    field access is now inside the try specifically to close that gap
    (see tests/test_compliance_agent.py::test_fails_closed_on_state_access_error,
    which is parametrized over all three fields for exactly this reason).
    """
    try:
        guest_id = state.get("guest_id", "")
        user_message = state.get("user_message", "")
        draft_response = state.get("draft_response", "")

        logger.info("Compliance Agent started", extra={"guest_id": guest_id})

        retrieved_policies = retrieve_relevant_policies(f"{user_message} {draft_response}".strip())
        logger.info(
            "Policy retrieval complete",
            extra={
                "guest_id": guest_id,
                "retrieved_policy_ids": [policy.policy_id for policy in retrieved_policies],
            },
        )

        violation = check_for_policy_violation(draft_response, retrieved_policies) if retrieved_policies else None

        if violation is not None:
            violated_policy, matched_phrase = violation
            logger.info(
                "Compliance verdict reached",
                extra={"guest_id": guest_id, "verdict": "REJECTED", "policy_id": violated_policy.policy_id},
            )
            compliance_status: ComplianceStatus = {
                "status": ComplianceVerdict.REJECTED,
                # The guest gets the REAL, correct policy answer - never
                # the (incorrect) original draft, and never a vague
                # "something went wrong" deflection.
                "guest_message": violated_policy.correct_statement,
                "reason_code": f"policy_violation:{violated_policy.category}",
                "internal_reason": (
                    f"Draft response matched contradiction phrase '{matched_phrase}' "
                    f"for policy {violated_policy.policy_id}."
                ),
                "metadata": {
                    "violated_policy_id": violated_policy.policy_id,
                    "matched_phrase": matched_phrase,
                },
            }
        else:
            logger.info(
                "Compliance verdict reached",
                extra={"guest_id": guest_id, "verdict": "APPROVED"},
            )
            compliance_status = {
                "status": ComplianceVerdict.APPROVED,
                "guest_message": draft_response,
                "reason_code": None,
                "internal_reason": None,
                "metadata": (
                    {"matched_policy_ids": [policy.policy_id for policy in retrieved_policies]}
                    if retrieved_policies
                    else None
                ),
            }

        logger.info("Compliance Agent finished", extra={"guest_id": guest_id})

    except Exception:  # noqa: BLE001 - deliberately broad: ANY failure must fail closed.
        logger.exception("Compliance Agent failed - failing closed")
        compliance_status = {
            "status": ComplianceVerdict.SYSTEM_ERROR,
            "guest_message": FAIL_CLOSED_MESSAGE,
            "reason_code": "compliance_processing_failed",
            "internal_reason": "Unhandled exception during compliance processing.",
            "metadata": None,
        }

    return {"compliance_status": compliance_status}


# =============================================================================
# FUTURE TODOs (consolidated)
# =============================================================================
#   - pgvector retriever:      replace `retrieve_relevant_policies` with a
#                              real pgvector similarity search against
#                              Amogh's `policy_chunks` table.
#   - Claude Sonnet reasoning: replace `check_for_policy_violation`'s
#                              fixed contradiction-phrase matching with a
#                              real LLM call that reasons about whether
#                              the draft response is actually consistent
#                              with each retrieved policy's real text.
#   - Document ingestion:      the offline pipeline that turns real hotel
#                              policy documents into rows in
#                              `policy_chunks` (chunking, embedding) -
#                              separate from this module entirely (see
#                              docs/rag/rag_design.md).
#   - Prompt Templates:        introduce a versioned, testable prompt
#                              template for the Claude Sonnet validation
#                              call.
#   - LangSmith:               once Claude Sonnet calls exist here,
#                              ensure they are traced end-to-end alongside
#                              the logging already present in this module.