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
  - for reservation requests: select a reservation tool and extract its
    typed arguments (Reservation Dispatch Contract v1.1),
  - produce a draft response,
  - and return structured information back to LangGraph (graph.py) so the
    orchestration layer can decide what happens next.

This file must NEVER:
  - query PostgreSQL,
  - access pgvector,
  - validate hotel policies,
  - actually EXECUTE a reservation operation (only select which one and
    prepare its arguments - execution belongs to the Reservation Agent),
  - or return the final response to the guest.

WHAT THIS FILE CURRENTLY IS
-----------------------------
Everything below is a placeholder implementation. Intent classification,
reservation-tool selection, and argument extraction are all simple
keyword/heuristic checks (not a real language model), draft responses are
fixed template strings, and conversation context is an empty, in-memory
object rebuilt from scratch on every call. Every placeholder is marked
with a TODO describing exactly what will replace it later (see "FUTURE
TODOs" at the bottom of this file).
"""

# --- Standard library imports -----------------------------------------------
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

# --- Internal imports ---------------------------------------------------------
# Every shared/frozen type is imported from graph.py rather than
# redeclared here - graph.py is the canonical source of truth for
# HotelSupportState, Intent, ReservationTool, the typed tool-argument
# contracts, and NodeResult (see graph.py's module docstring). This
# guarantees there is exactly one definition of each anywhere in the
# codebase.
from app.agents.graph import (
    CancelReservationArgs,
    CheckAvailabilityArgs,
    CreateReservationArgs,
    GetReservationDetailsArgs,
    HotelSupportState,
    Intent,
    ModifyReservationArgs,
    NodeResult,
    ReservationTool,
    ReservationToolArguments,
)

# Module-level logger, following the same pattern as graph.py: no handlers
# or `basicConfig()` are configured here.
logger = logging.getLogger(__name__)


# =============================================================================
# 1. DETECTED INTENT (the Conversation Agent's own classification taxonomy)
# =============================================================================
# graph.py's `Intent` enum only distinguishes what the ORCHESTRATION layer
# needs to know: "does this message require the Reservation Agent, or
# not?" This module defines its own, richer `DetectedIntent` enum (adding
# an UNKNOWN bucket the orchestration layer has no use for), and maps it
# down to graph.py's `Intent` before returning state. This keeps
# orchestration and conversation concerns cleanly separated: the outer
# layer (graph.py) is not modified just because this inner layer wants a
# more expressive internal vocabulary.
class DetectedIntent(str, Enum):
    """The Conversation Agent's own intent classification buckets."""

    GREETING = "greeting"
    RESERVATION = "reservation"
    GENERAL_QUESTION = "general_question"
    UNKNOWN = "unknown"


# Explicit mapping from this module's richer taxonomy to graph.py's
# routing-relevant `Intent`.
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
    """Translate this module's `DetectedIntent` into graph.py's `Intent`."""
    return _INTENT_TO_GRAPH_INTENT[detected_intent]


# =============================================================================
# 2. CONVERSATION CONTEXT (in-memory placeholder)
# =============================================================================
@dataclass
class ConversationContext:
    """Placeholder container for everything the Conversation Agent will
    eventually need to remember about an ongoing conversation.

    TODO (future task): none of these fields are persisted or loaded from
    anywhere yet - see "FUTURE TODOs" at the bottom of this file.
    """

    conversation_history: list[str] = field(default_factory=list)
    session_context: dict[str, str] = field(default_factory=dict)
    guest_preferences: dict[str, str] = field(default_factory=dict)


def build_conversation_context(state: HotelSupportState) -> ConversationContext:
    """Construct the conversation context for the current turn.

    TODO (future task): look up `state["guest_id"]` in a session store
    (Redis) and/or a conversation-history table instead of returning an
    empty placeholder.
    """
    return ConversationContext()


# =============================================================================
# 3. INTENT CLASSIFICATION (placeholder)
# =============================================================================
def classify_intent(user_message: str) -> DetectedIntent:
    """Classify the guest's message into one of the `DetectedIntent` buckets.

    TODO (future task): replace this entire function body with a call to
    Claude Sonnet, using a prompt template that considers the full
    conversation context, not just the current message in isolation.
    """
    normalized_message = user_message.strip().lower()

    if not normalized_message:
        return DetectedIntent.UNKNOWN

    if any(word in normalized_message for word in ("hi", "hello", "hey", "good morning", "good evening")):
        return DetectedIntent.GREETING

    if any(
        word in normalized_message
        for word in ("book", "reservation", "reserve", "cancel", "modify", "availability", "available")
    ):
        return DetectedIntent.RESERVATION

    if len(normalized_message.split()) >= 2:
        return DetectedIntent.GENERAL_QUESTION

    return DetectedIntent.UNKNOWN


# =============================================================================
# 4. RESERVATION TOOL SELECTION
# (Reservation Dispatch Contract v1.1 - "Supported Reservation Tools")
# =============================================================================
def select_reservation_tool(user_message: str) -> ReservationTool:
    """Choose exactly one of the five reservation tools for this message.

    TODO (future task): replace this keyword-based placeholder with a
    real Claude Sonnet tool-selection call. A real implementation must
    also handle ambiguous cases (e.g. "change my booking and check if a
    bigger room is free") that this simple keyword check cannot.

    Placeholder heuristic (checked in order, first match wins):
      - "cancel"                         -> CANCEL_RESERVATION
      - "modify" / "change"              -> MODIFY_RESERVATION
      - "availability" / "available"     -> CHECK_AVAILABILITY
      - "details" / "status" / "lookup"  -> GET_RESERVATION_DETAILS
      - anything else reservation-shaped -> CREATE_RESERVATION (default)
    """
    normalized_message = user_message.strip().lower()

    if "cancel" in normalized_message:
        return ReservationTool.CANCEL_RESERVATION
    if "modify" in normalized_message or "change" in normalized_message:
        return ReservationTool.MODIFY_RESERVATION
    if "availability" in normalized_message or "available" in normalized_message:
        return ReservationTool.CHECK_AVAILABILITY
    if "details" in normalized_message or "status" in normalized_message or "lookup" in normalized_message:
        return ReservationTool.GET_RESERVATION_DETAILS

    # Default: a reservation-intent message with none of the above
    # keywords is treated as a new booking request.
    return ReservationTool.CREATE_RESERVATION


# =============================================================================
# 5. TYPED ARGUMENT EXTRACTION (placeholder)
# (Reservation Dispatch Contract v1.1 - "Typed Tool Argument Contracts (Frozen)")
# =============================================================================
# A simple pattern used only to demonstrate where a booking reference
# WOULD be pulled from the message. This is not a real ID validator - see
# the TODO in `extract_tool_arguments` below.
#
# NOTE: this must match the REAL confirmation_code format Amogh's
# db/schema.sql actually generates -
# `upper(substr(md5(random()::text), 1, 8))` - an 8-character uppercase
# hexadecimal string (digits 0-9 and letters A-F only, e.g. "3F9A2B7C").
# An earlier version of this pattern assumed a "letters-then-digits"
# format (e.g. "ABC123"), which does not match real confirmation codes at
# all - verified by generating 10 real codes with Postgres's actual
# algorithm and confirming 0/10 matched the old pattern. `booking_id`
# here refers to `confirmation_code`, NOT the reservation's raw UUID
# `id` - guests are given the short code, never the UUID.
_BOOKING_ID_PATTERN = re.compile(r"\b[0-9A-F]{8}\b")


def extract_tool_arguments(
    tool: ReservationTool, user_message: str, guest_id: str
) -> ReservationToolArguments:
    """Build the typed argument dict required by the selected tool.

    TODO (future task): replace this entire function with a real Claude
    Sonnet extraction call that reads the full conversation context (not
    just the current message) and reliably parses dates, room types, and
    guest counts. Every field below that cannot be reliably extracted by
    a keyword/regex placeholder is deliberately left as `None` rather than
    guessed - a real extraction step, and/or a clarifying question back to
    the guest, must fill these in before the Reservation Agent can safely
    execute the tool. Downstream validation of "are all required fields
    present" belongs to the Reservation Agent, per the Reservation
    Dispatch Contract ("The Reservation Agent is responsible for
    extracting and validating the required arguments" is qualified there
    by the Conversation Agent being responsible for the extraction step
    itself; the Reservation Agent is expected to validate what it
    receives before executing).

    Args:
        tool: which reservation tool was selected by `select_reservation_tool`.
        user_message: the guest's raw message (placeholder source for extraction).
        guest_id: the authenticated guest's id (the one field this placeholder
            CAN reliably fill in, since it comes from `state`, not free text).

    Returns:
        One of the five typed argument TypedDicts defined in graph.py,
        matching `tool`.
    """
    booking_id_match = _BOOKING_ID_PATTERN.search(user_message.upper())
    placeholder_booking_id = booking_id_match.group(0) if booking_id_match else "UNKNOWN"

    if tool == ReservationTool.CREATE_RESERVATION:
        create_args: CreateReservationArgs = {
            "guest_id": guest_id,
            # TODO: extract real room_type/check_in/check_out/guests via Claude Sonnet.
            "room_type": "UNSPECIFIED",
            "check_in": None,   # type: ignore[typeddict-item]  # TODO: real date extraction
            "check_out": None,  # type: ignore[typeddict-item]  # TODO: real date extraction
            "guests": 1,
        }
        return create_args

    if tool == ReservationTool.MODIFY_RESERVATION:
        modify_args: ModifyReservationArgs = {
            "booking_id": placeholder_booking_id,
            # No other fields are populated yet - all are optional per the
            # contract, and a real implementation would only include the
            # ones the guest actually asked to change.
        }
        return modify_args

    if tool == ReservationTool.CANCEL_RESERVATION:
        cancel_args: CancelReservationArgs = {"booking_id": placeholder_booking_id}
        return cancel_args

    if tool == ReservationTool.CHECK_AVAILABILITY:
        availability_args: CheckAvailabilityArgs = {
            "room_type": "UNSPECIFIED",
            "check_in": None,   # type: ignore[typeddict-item]  # TODO: real date extraction
            "check_out": None,  # type: ignore[typeddict-item]  # TODO: real date extraction
            "guests": 1,
        }
        return availability_args

    # tool == ReservationTool.GET_RESERVATION_DETAILS
    details_args: GetReservationDetailsArgs = {"booking_id": placeholder_booking_id}
    return details_args


# =============================================================================
# 6. DRAFT RESPONSE GENERATION (placeholder)
# =============================================================================
_PLACEHOLDER_RESPONSES: dict[DetectedIntent, str] = {
    DetectedIntent.GREETING: "Hello! Welcome to our hotel. How may I assist you today?",
    DetectedIntent.RESERVATION: "I can help you with your reservation.",
    DetectedIntent.GENERAL_QUESTION: "I'll help answer your hotel-related question.",
    DetectedIntent.UNKNOWN: "Could you please clarify your request?",
}


def generate_draft_response(detected_intent: DetectedIntent, context: ConversationContext) -> str:
    """Produce a draft (not yet approved) response for the given intent.

    TODO (future task): replace this fixed lookup with a real call to
    Claude Sonnet, incorporating `context` so the response is tailored to
    the guest's actual situation rather than a generic template string.
    """
    return _PLACEHOLDER_RESPONSES[detected_intent]


# =============================================================================
# 7. MAIN ENTRY POINT - called by graph.py's conversation_node
# =============================================================================
def run_conversation_agent(state: HotelSupportState) -> NodeResult:
    """Run the Conversation Agent for the current turn.

    Returns a partial state update. Per the Reservation Dispatch
    Contract's "Conversation Agent Output" table, `tool_name` and
    `tool_arguments` are included ONLY when the detected intent is
    RESERVATION - for every other intent, this function returns just
    `intent` and `draft_response`, exactly as before.
    """
    guest_id = state.get("guest_id", "")
    user_message = state.get("user_message", "")

    logger.info("Conversation Agent started", extra={"guest_id": guest_id})

    context = build_conversation_context(state)

    detected_intent = classify_intent(user_message)
    logger.info(
        "Intent detected",
        extra={"guest_id": guest_id, "detected_intent": detected_intent.value},
    )

    draft_response = generate_draft_response(detected_intent, context)
    logger.info(
        "Draft response generated",
        extra={"guest_id": guest_id, "detected_intent": detected_intent.value},
    )

    result: NodeResult = {
        "intent": _to_graph_intent(detected_intent),
        "draft_response": draft_response,
    }

    # Reservation Dispatch Contract: tool_name/tool_arguments are only
    # produced for a genuine reservation intent - graph.py's routing
    # function only checks `intent`, but populating these unconditionally
    # for non-reservation turns would be meaningless data with nothing to
    # consume it.
    if result["intent"] == Intent.RESERVATION:
        tool = select_reservation_tool(user_message)
        tool_arguments = extract_tool_arguments(tool, user_message, guest_id)
        logger.info(
            "Reservation tool selected",
            extra={"guest_id": guest_id, "tool_name": tool.value},
        )
        result["tool_name"] = tool
        result["tool_arguments"] = tool_arguments

    logger.info("Conversation Agent finished", extra={"guest_id": guest_id})
    return result


# =============================================================================
# FUTURE TODOs (consolidated)
# =============================================================================
#   - Claude Sonnet:            replace `classify_intent`,
#                                `select_reservation_tool`,
#                                `extract_tool_arguments`, and
#                                `generate_draft_response` with real LLM
#                                calls.
#   - Conversation Memory:      persist and retrieve real conversation
#                                history instead of the empty placeholder
#                                in `ConversationContext`.
#   - Redis:                    back `session_context` and
#                                `guest_preferences` with a real, fast
#                                session store keyed by `guest_id`.
#   - Prompt Templates:         introduce versioned, testable prompt
#                                templates for classification, tool
#                                selection, argument extraction, and
#                                response generation.
#   - LangSmith:                once Claude Sonnet calls exist, ensure
#                                they are traced end-to-end alongside the
#                                logging already present in this module.