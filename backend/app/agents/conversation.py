"""
conversation.py
----------------
Implementation of the Conversation Agent (the Supervisor Agent) for the
Multi-Agent AI Hotel Support System.

ROLE OF THIS FILE
------------------
Per docs/agents/conversation_agent.md, the Conversation Agent is the ONLY
component that receives the guest's raw message. Its job is to:
  - understand the guest's request,
  - maintain conversation context,
  - classify intent,
  - produce a draft response,
  - and return structured information back to LangGraph (graph.py) so the
    orchestration layer can decide what happens next.

This file must NEVER:
  - query PostgreSQL,
  - access pgvector,
  - validate hotel policies,
  - perform reservation operations,
  - or return the final response to the guest.

Those responsibilities belong to the Reservation Agent
(app/agents/reservation.py, not yet implemented) and the Compliance Agent
(app/agents/compliance.py, not yet implemented) respectively. This
Conversation Agent's draft response is only ever a *candidate* - it is not
approved for delivery until the Compliance Agent signs off on it
(see docs/agents/compliance_agent.md).

WHAT THIS FILE CURRENTLY IS
-----------------------------
Everything below is a placeholder implementation. Intent classification is
a simple keyword check (not a real language model), draft responses are
fixed template strings, and conversation context is an empty, in-memory
object that is rebuilt from scratch on every call - nothing is persisted
between requests yet. Every placeholder is marked with a TODO comment
describing exactly what will replace it later (see the "FUTURE TODOs"
section at the bottom of this file for a consolidated list).
"""

# --- Standard library imports -----------------------------------------------
import logging
from dataclasses import dataclass, field
from enum import Enum

# --- Internal imports ---------------------------------------------------------
# We import Intent (and the shared state/result types) directly from
# graph.py rather than redefining them here. This guarantees the value this
# module puts into `state["intent"]` is always something graph.py's routing
# function already knows how to handle - there is only one definition of
# "what routing-relevant intents exist", owned by the orchestration layer.
from app.agents.graph import HotelSupportState, Intent, NodeResult

# Module-level logger, following the same pattern as graph.py: no handlers
# or `basicConfig()` are configured here. This module simply emits log
# records; the application's entry point (and, later, LangSmith) decides
# whether/where those records are shown.
logger = logging.getLogger(__name__)


# =============================================================================
# 1. DETECTED INTENT (the Conversation Agent's own classification taxonomy)
# =============================================================================
# graph.py's `Intent` enum only distinguishes what the ORCHESTRATION layer
# needs to know: "does this message require the Reservation Agent, or not?"
# That is a narrower question than "what does the Conversation Agent
# actually think the guest wants?" - the Conversation Agent is explicitly
# asked to support a 4th bucket, UNKNOWN (for messages it cannot classify
# with confidence), which has no equivalent in graph.py's routing-focused
# enum.
#
# Rather than widen graph.py's `Intent` (which would mean touching the
# orchestration layer to accommodate a concern that belongs to this agent),
# this module defines its own, richer `DetectedIntent` enum, and maps it
# down to graph.py's `Intent` before returning state (see
# `_to_graph_intent` below). This keeps orchestration and conversation
# concerns cleanly separated, per Clean Architecture: the outer layer
# (graph.py) is not modified just because an inner layer (this module)
# wants a more expressive internal vocabulary.
class DetectedIntent(str, Enum):
    """The Conversation Agent's own intent classification buckets.

    GREETING, RESERVATION, and GENERAL_QUESTION correspond directly to
    graph.py's `Intent` values. UNKNOWN is specific to this module: it
    represents "the classifier could not confidently determine what the
    guest wants", and is always treated as a general question for routing
    purposes (an unclear request should never be sent to the Reservation
    Agent).
    """

    GREETING = "greeting"
    RESERVATION = "reservation"
    GENERAL_QUESTION = "general_question"
    UNKNOWN = "unknown"


# Explicit mapping from this module's richer taxonomy to graph.py's
# routing-relevant `Intent`. Writing this out as a dictionary (rather than,
# say, relying on matching string values) makes the relationship between
# the two enums visible in one place and easy to audit.
_INTENT_TO_GRAPH_INTENT: dict[DetectedIntent, Intent] = {
    DetectedIntent.GREETING: Intent.GREETING,
    DetectedIntent.RESERVATION: Intent.RESERVATION,
    DetectedIntent.GENERAL_QUESTION: Intent.GENERAL_QUESTION,
    # An unknown intent is routed exactly like a general question: it must
    # never trigger the Reservation Agent, since we have no confidence a
    # booking operation was actually requested.
    DetectedIntent.UNKNOWN: Intent.GENERAL_QUESTION,
}


def _to_graph_intent(detected_intent: DetectedIntent) -> Intent:
    """Translate this module's `DetectedIntent` into graph.py's `Intent`.

    This is the single point where the two taxonomies meet. Keeping the
    translation in one small function (rather than scattering `if`
    statements around the file) means updating the mapping later - for
    example, if graph.py ever grows its own `Intent.UNKNOWN` - only
    requires a change here.
    """
    return _INTENT_TO_GRAPH_INTENT[detected_intent]


# =============================================================================
# 2. CONVERSATION CONTEXT (in-memory placeholder)
# =============================================================================
@dataclass
class ConversationContext:
    """Placeholder container for everything the Conversation Agent will
    eventually need to remember about an ongoing conversation.

    TODO (future task): this dataclass currently exists only to give the
    rest of this module something concrete to pass around. None of its
    fields are persisted or loaded from anywhere yet:
      - `conversation_history` will eventually be populated from a
        conversation-history store (see docs/architecture/architecture.md
        Section 9, "Conversation History" table) so prior turns are
        available to the classifier and response generator.
      - `session_context` and `guest_preferences` will eventually be
        loaded from a fast session store (e.g. Redis) keyed by
        `guest_id`, rather than starting empty on every call.
    """

    # Each entry will eventually be a structured record (e.g. role + text +
    # timestamp) rather than a plain string; a plain list of strings is
    # sufficient for a placeholder that is never actually populated yet.
    conversation_history: list[str] = field(default_factory=list)

    # Arbitrary short-lived session data (e.g. "guest is mid-booking flow").
    session_context: dict[str, str] = field(default_factory=dict)

    # Longer-lived guest preferences (e.g. preferred room type), expected to
    # eventually be sourced from a guest profile rather than invented here.
    guest_preferences: dict[str, str] = field(default_factory=dict)


def build_conversation_context(state: HotelSupportState) -> ConversationContext:
    """Construct the conversation context for the current turn.

    TODO (future task): look up `state["guest_id"]` in a session store
    (Redis - see docs/architecture/technology_decisions.md) and/or a
    conversation-history table, and populate `ConversationContext` with
    real prior-turn data instead of returning an empty placeholder.

    For now, this always returns a fresh, empty context: no memory is
    retained between calls to `run_conversation_agent`.
    """
    return ConversationContext()


# =============================================================================
# 3. INTENT CLASSIFICATION (placeholder)
# =============================================================================
def classify_intent(user_message: str) -> DetectedIntent:
    """Classify the guest's message into one of the `DetectedIntent` buckets.

    TODO (future task): replace this entire function body with a call to
    Claude Sonnet (see docs/technology_decisions.md and
    docs/agents/conversation_agent.md), using a prompt template (see
    "FUTURE TODOs" below) that considers the full conversation context,
    not just the current message in isolation.

    The placeholder logic below is intentionally simple keyword matching.
    Unlike graph.py (which must never contain any classification logic),
    this IS the correct place for a temporary intent-classification
    placeholder to live, since intent classification is explicitly this
    agent's responsibility.
    """
    normalized_message = user_message.strip().lower()

    if not normalized_message:
        # An empty or whitespace-only message gives the classifier nothing
        # to work with - treat it as unknown rather than guessing.
        return DetectedIntent.UNKNOWN

    if any(word in normalized_message for word in ("hi", "hello", "hey", "good morning", "good evening")):
        return DetectedIntent.GREETING

    if any(word in normalized_message for word in ("book", "reservation", "reserve", "cancel", "modify", "availability")):
        return DetectedIntent.RESERVATION

    # TODO: a real classifier would distinguish "general hotel question" from
    # "truly unrecognizable input" far more reliably than a keyword list can.
    # For this placeholder, any non-empty message that doesn't match the
    # greeting/reservation keywords above is treated as a general question,
    # which is the safer default (it still goes through Compliance
    # validation before any response is released).
    if len(normalized_message.split()) >= 2:
        return DetectedIntent.GENERAL_QUESTION

    return DetectedIntent.UNKNOWN


# =============================================================================
# 4. DRAFT RESPONSE GENERATION (placeholder)
# =============================================================================
# Fixed placeholder response text per intent, exactly as specified in this
# module's design brief. These are deliberately generic and will be
# replaced by real, context-aware generation once Claude Sonnet is wired
# in (see TODO in `generate_draft_response` below).
_PLACEHOLDER_RESPONSES: dict[DetectedIntent, str] = {
    DetectedIntent.GREETING: "Hello! Welcome to our hotel. How may I assist you today?",
    DetectedIntent.RESERVATION: "I can help you with your reservation.",
    DetectedIntent.GENERAL_QUESTION: "I'll help answer your hotel-related question.",
    DetectedIntent.UNKNOWN: "Could you please clarify your request?",
}


def generate_draft_response(detected_intent: DetectedIntent, context: ConversationContext) -> str:
    """Produce a draft (not yet approved) response for the given intent.

    TODO (future task): replace this fixed lookup with a real call to
    Claude Sonnet, using a prompt template (see "FUTURE TODOs" below) that
    incorporates `context` (conversation history, session context, guest
    preferences) so the response is actually tailored to the guest's
    situation rather than a generic template string.

    The `context` parameter is accepted now (even though it is unused by
    this placeholder) so that the function's signature does not need to
    change when real generation logic is added later.
    """
    return _PLACEHOLDER_RESPONSES[detected_intent]


# =============================================================================
# 5. MAIN ENTRY POINT - called by graph.py's conversation_node
# =============================================================================
def run_conversation_agent(state: HotelSupportState) -> NodeResult:
    """Run the Conversation Agent for the current turn.

    This is the function graph.py's `conversation_node` is expected to call
    (replacing the temporary `_stub_conversation_agent_call` placeholder
    currently in graph.py - see the integration notes accompanying this
    module). It accepts the shared `HotelSupportState` and returns a
    partial state update, exactly like every other node in the graph.

    Steps performed:
      1. Log that the Conversation Agent started.
      2. Build (currently empty/placeholder) conversation context.
      3. Classify the guest's message into a `DetectedIntent`.
      4. Log the detected intent.
      5. Generate a draft response for that intent.
      6. Log that a draft response was generated.
      7. Log that the Conversation Agent finished.
      8. Return the graph-compatible `Intent` and the draft response.

    Returns:
        A dict with keys `"intent"` (a graph.py `Intent` value) and
        `"draft_response"` (a placeholder string) - the two fields
        `route_after_conversation` and downstream nodes in graph.py rely on.
    """
    guest_id = state.get("guest_id")
    user_message = state.get("user_message", "")

    logger.info("Conversation Agent started", extra={"guest_id": guest_id})

    # Step 2: build conversation context (placeholder - see TODO above).
    context = build_conversation_context(state)

    # Step 3: classify intent (placeholder - see TODO above).
    detected_intent = classify_intent(user_message)
    logger.info(
        "Intent detected",
        extra={"guest_id": guest_id, "detected_intent": detected_intent.value},
    )

    # Step 5: generate a draft response for the detected intent.
    draft_response = generate_draft_response(detected_intent, context)
    logger.info(
        "Draft response generated",
        extra={"guest_id": guest_id, "detected_intent": detected_intent.value},
    )

    logger.info("Conversation Agent finished", extra={"guest_id": guest_id})

    # Translate this module's richer taxonomy down to graph.py's routing
    # taxonomy before returning - see `_to_graph_intent` above.
    return {
        "intent": _to_graph_intent(detected_intent),
        "draft_response": draft_response,
    }


# =============================================================================
# FUTURE TODOs (consolidated)
# =============================================================================
# The following integrations are intentionally NOT implemented in this
# file. Each is called out at its relevant location above; this section
# exists as a single, easy-to-scan checklist for future work:
#
#   - Claude Sonnet:            replace `classify_intent` and
#                                `generate_draft_response` with real LLM
#                                calls (docs/technology_decisions.md).
#   - Conversation Memory:      persist and retrieve real conversation
#                                history instead of the empty placeholder
#                                in `ConversationContext`.
#   - Redis:                    back `session_context` and
#                                `guest_preferences` with a real, fast
#                                session store keyed by `guest_id`.
#   - Prompt Templates:         introduce versioned, testable prompt
#                                templates for both intent classification
#                                and response generation, rather than
#                                inline strings.
#   - LangSmith:                once Claude Sonnet calls exist, ensure
#                                they are traced end-to-end alongside the
#                                logging already present in this module.