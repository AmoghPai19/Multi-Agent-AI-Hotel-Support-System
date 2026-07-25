"""
graph.py
--------
LangGraph orchestration layer for the Multi-Agent AI Hotel Support System.

This module is also the CANONICAL SOURCE OF TRUTH for the four frozen
integration contracts that govern this system (see docs/contracts/):

  1. Graph Entrypoint Contract v1.0
  2. HotelSupportState & Intent Enum Contract v1.0
  3. Compliance Verdict Contract v1.0
  4. Reservation Dispatch Contract v1.1

Every type in this file (Intent, ReservationTool, the per-tool argument
TypedDicts, ReservationData, ComplianceVerdict, ComplianceStatus,
HotelSupportState) exists because one of those four documents froze it.
Where this file's comments explain a design decision, they point back to
the specific contract and section that requires it.

WHAT THIS FILE IS (AND IS NOT)
------------------------------
This file's ONLY job is to coordinate execution order between agents and
define the shared data shapes agents communicate through. It must never
answer questions like "what does the guest want?", "is this booking
allowed?", or "does this response comply with policy?" - those questions
belong to the Conversation, Reservation, and Compliance Agents
respectively (see docs/agents/*.md).

Concretely, this file must NEVER:
  - classify intent
  - select a reservation tool or extract its arguments
  - perform reservation logic
  - validate policies
  - call Claude Sonnet
  - query PostgreSQL
  - access pgvector

The Conversation Agent is fully implemented in app.agents.conversation and
wired in below. The Reservation and Compliance Agents are still
placeholders: each node's body will be replaced with a call into its own
module (app.agents.reservation, app.agents.compliance) the same way
conversation.py was integrated, without changing the graph's shape or the
contract types defined here.

WHY THE COMPLIANCE GATE IS MANDATORY
-------------------------------------
Per docs/architecture/architecture.md, docs/architecture/workflow.md, and
the Compliance Verdict Contract, every response - regardless of intent -
must pass through the Compliance Agent before reaching a guest, and the
system must FAIL CLOSED (return status=ERROR with a safe fallback
message) if compliance processing cannot complete. This file enforces the
"always runs" half of that rule structurally: "compliance_node" is the
*only* node with an edge into END. The "fails closed" half is enforced
inside compliance_node itself (see its docstring below).
"""

# --- Standard library imports -----------------------------------------------
import logging
from datetime import date
from enum import Enum
from typing import Any, NotRequired, Optional, TypedDict

# --- LangGraph imports --------------------------------------------------------
# StateGraph is the core class used to build a graph of nodes (functions)
# connected by edges (the allowed transitions between nodes). START and END
# are built-in markers: every graph begins at START and every path through
# the graph must eventually reach END.
from langgraph.graph import END, START, StateGraph

# Module-level logger. We deliberately do NOT call `logging.basicConfig()`
# or attach handlers here - that is an application-wide concern that
# belongs in the app's entry point / future LangSmith integration, not in
# an individual module.
logger = logging.getLogger(__name__)


# =============================================================================
# 1. INTENT DEFINITION
# (HotelSupportState & Intent Enum Contract v1.0 - "Intent Enum (Frozen)")
# =============================================================================
class Intent(str, Enum):
    """The set of guest-message intents this graph knows how to route on.

    Frozen by the HotelSupportState & Intent Enum Contract: these three
    values and their meanings must not change without a contract version
    update. Inheriting from both `str` and `Enum` means these values
    behave like plain strings at runtime (so they serialize cleanly into
    the state dict LangGraph passes between nodes) while still giving us
    type safety and editor autocompletion everywhere else in this file.
    """

    GREETING = "greeting"                  # Greeting or welcome message.
    RESERVATION = "reservation"            # Reservation-related request.
    GENERAL_QUESTION = "general_question"  # General hotel information or FAQ.


# =============================================================================
# 2. RESERVATION TOOL VOCABULARY
# (Reservation Dispatch Contract v1.1 - "Supported Reservation Tools")
# =============================================================================
class ReservationTool(str, Enum):
    """The five reservation operations the Conversation Agent may dispatch to.

    Frozen by the Reservation Dispatch Contract: exactly one of these is
    selected per reservation request. The contract specifies `tool_name`
    as type `str`; using a `str`-backed Enum here satisfies that literally
    (these values serialize as plain strings) while giving every module
    that imports this Enum a typo-proof, autocompletable vocabulary
    instead of loose string literals.
    """

    CREATE_RESERVATION = "create_reservation"
    MODIFY_RESERVATION = "modify_reservation"
    CANCEL_RESERVATION = "cancel_reservation"
    CHECK_AVAILABILITY = "check_availability"
    GET_RESERVATION_DETAILS = "get_reservation_details"


# =============================================================================
# 3. TYPED TOOL ARGUMENT CONTRACTS
# (Reservation Dispatch Contract v1.1 - "Typed Tool Argument Contracts (Frozen)")
# =============================================================================
# Each TypedDict below matches, field-for-field, the argument table the
# Reservation Dispatch Contract freezes for that tool. Fields marked
# "(optional)" in the contract use `NotRequired[...]` (Python 3.11+);
# every other field is required. The Conversation Agent is responsible for
# populating one of these (see app.agents.conversation); the Reservation
# Agent (not yet implemented) will be the one consuming and validating
# them at execution time.
class CreateReservationArgs(TypedDict):
    guest_id: str
    room_type: str
    check_in: date
    check_out: date
    guests: int


class ModifyReservationArgs(TypedDict):
    booking_id: str
    check_in: NotRequired[date]
    check_out: NotRequired[date]
    room_type: NotRequired[str]
    guests: NotRequired[int]


class CancelReservationArgs(TypedDict):
    booking_id: str


class CheckAvailabilityArgs(TypedDict):
    room_type: str
    check_in: date
    check_out: date
    guests: int


class GetReservationDetailsArgs(TypedDict):
    booking_id: str


# A convenience alias covering "any one of the five typed argument shapes
# above". `tool_arguments` in HotelSupportState is typed against this
# union so that whichever tool the Conversation Agent selects, its
# arguments are still type-checked against *some* known shape, without
# forcing every caller to import all five names individually.
ReservationToolArguments = (
    CreateReservationArgs
    | ModifyReservationArgs
    | CancelReservationArgs
    | CheckAvailabilityArgs
    | GetReservationDetailsArgs
)


# =============================================================================
# 4. RESERVATION AGENT OUTPUT SHAPE
# (Reservation Dispatch Contract v1.1 - "Reservation Agent Output")
# =============================================================================
class ReservationData(TypedDict):
    """The complete 'ToolResult envelope' the Reservation Agent returns.

    Frozen by the Reservation Dispatch Contract. Note `status` here is a
    free-form string describing the tool execution outcome (e.g.
    "success", "not_found") - the contract does not freeze a fixed set of
    values for it the way the Compliance Verdict Contract freezes
    APPROVED/REJECTED/ERROR, so it is intentionally left as `str` rather
    than an Enum, pending the Reservation Agent's own specification.
    """

    status: str
    booking_id: Optional[str]
    data: Optional[dict[str, Any]]
    message: Optional[str]


# =============================================================================
# 5. COMPLIANCE VERDICT SHAPE
# (Compliance Verdict Contract v1.0)
# =============================================================================
class ComplianceVerdict(str, Enum):
    """The three frozen compliance outcome values.

    Frozen by the Compliance Verdict Contract - these exact (uppercase)
    values, and no others, are valid. ERROR is not "something went wrong
    with the guest's request"; it specifically means compliance
    *validation itself* could not complete, and the system must fail
    closed (see `compliance_node` below).
    """

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class ComplianceStatus(TypedDict):
    """The complete compliance verdict envelope.

    NAMING NOTE - resolving an ambiguity between the two contracts: the
    HotelSupportState & Intent Enum Contract freezes a state field named
    `compliance_status` with type `ComplianceStatus`, while the Compliance
    Verdict Contract's own pseudocode calls the equivalent object
    `compliance_result`. This class is the reconciliation of those two
    documents: it is named `ComplianceStatus` (matching the state
    contract's type reference) and holds exactly the fields the Compliance
    Verdict Contract specifies for `compliance_result`. The state field
    itself keeps its frozen name, `compliance_status`, and holds a value
    of this type - it is NOT reduced to a bare enum string, since the
    frontend needs `guest_message` to render a rejection (per that
    contract's "Rejection Contract" section).

    Field-level rules from the contract:
      - `guest_message` MUST always be present and guest-safe when
        `status` is REJECTED or ERROR - it is the only field the
        WebSocket/FastAPI layer is permitted to render to the guest.
      - `internal_reason` is diagnostic-only and must NEVER be exposed to
        the guest.
    """

    status: ComplianceVerdict
    guest_message: str
    reason_code: Optional[str]
    internal_reason: Optional[str]
    metadata: Optional[dict[str, Any]]


# =============================================================================
# 6. SHARED APPLICATION STATE
# (HotelSupportState & Intent Enum Contract v1.0 - "HotelSupportState (Frozen)")
# =============================================================================
class HotelSupportState(TypedDict, total=False):
    """Shared state passed between all nodes in the hotel support graph.

    This is the canonical definition referenced by the HotelSupportState
    & Intent Enum Contract; every other module (app.agents.conversation,
    and later app.agents.reservation / app.agents.compliance) imports
    these fields from here rather than redeclaring them, so there is
    exactly one definition anywhere in the codebase. Field names, types,
    and optionality are frozen - see the contract's "Integration Rules"
    before renaming or retyping anything below.

    `total=False` means none of these keys are required to be present at
    every point in the graph's execution - immediately after START, only
    `user_message` and `guest_id` exist.
    """

    # --- Seeded by FastAPI before the graph starts running (required) ---
    user_message: str          # Original user request received by FastAPI.
    guest_id: str               # Unique guest identifier.

    # --- Written by the Conversation Agent (conversation_node) ---
    intent: Intent               # Detected conversation intent.
    draft_response: str          # Draft response generated by the Conversation Agent.

    # --- Written by the Conversation Agent, ONLY when intent == RESERVATION ---
    # (Reservation Dispatch Contract - "Conversation Agent Output")
    tool_name: ReservationTool                      # Which reservation operation to execute.
    tool_arguments: ReservationToolArguments        # Typed arguments for that operation.

    # --- Written by the Reservation Agent (reservation_node), only when invoked ---
    reservation_data: ReservationData   # Output returned by the Reservation Agent.

    # --- Written by the Compliance Agent (compliance_node) ---
    compliance_status: ComplianceStatus  # Final compliance verdict (see naming note above).


# A small alias to make node function signatures read cleanly: every node
# returns a *partial* update to the shared state, never the full state.
NodeResult = dict[str, Any]


# =============================================================================
# 7. CONVERSATION NODE
# =============================================================================
def conversation_node(state: HotelSupportState) -> NodeResult:
    """Orchestration wrapper around the Conversation Agent (the Supervisor).

    This node's only responsibilities are: (1) log that the Conversation
    Agent ran, (2) call it, and (3) hand its result back to the graph so
    that `route_after_conversation` can decide what happens next. It never
    itself decides the guest's intent, selects a reservation tool, or
    extracts arguments - all of that happens entirely inside
    `run_conversation_agent` (see docs/agents/conversation_agent.md and
    the Reservation Dispatch Contract).

    The import below is deliberately placed INSIDE this function rather
    than at the top of the file: app.agents.conversation imports
    `HotelSupportState`, `Intent`, `ReservationTool`, and `NodeResult`
    from this module, so a top-level import here would create a circular
    import (confirmed by testing both import orders during development).
    Deferring this import until the function actually runs avoids that
    entirely.
    """
    from app.agents.conversation import run_conversation_agent

    logger.info("conversation_node started", extra={"guest_id": state.get("guest_id")})

    result = run_conversation_agent(state)

    logger.info(
        "conversation_node finished",
        extra={"intent": result.get("intent"), "tool_name": result.get("tool_name")},
    )
    return result


# =============================================================================
# 8. RESERVATION NODE (stub)
# =============================================================================
def reservation_node(state: HotelSupportState) -> NodeResult:
    """Orchestration wrapper around the Reservation Agent.

    TODO(future task): replace this stub's body with a call into
    `app.agents.reservation` (per docs/agents/reservation_agent.md and the
    Reservation Dispatch Contract), which will read `state["tool_name"]`
    and `state["tool_arguments"]`, execute the corresponding PostgreSQL
    operation, and return a real `ReservationData` envelope.

    This stub performs no database access and no booking logic; it only
    echoes back the tool the Conversation Agent selected, so the wiring
    between the two can be verified even before real reservation logic
    exists.
    """
    guest_id = state.get("guest_id")
    tool_name = state.get("tool_name")
    logger.info("reservation_node started", extra={"guest_id": guest_id, "tool_name": tool_name})

    # TODO: Replace with a real call into app.agents.reservation once that
    # module implements PostgreSQL-backed execution of `tool_name` with
    # `tool_arguments` (docs/agents/reservation_agent.md).
    reservation_data: ReservationData = {
        "status": "placeholder",
        "booking_id": None,
        "data": None,
        "message": f"Reservation Agent logic not yet implemented for tool '{tool_name}'.",
    }
    result: NodeResult = {"reservation_data": reservation_data}

    logger.info("reservation_node finished")
    return result


# =============================================================================
# 9. COMPLIANCE NODE (stub)
# =============================================================================
# Fallback message returned whenever compliance validation cannot complete.
# Frozen text example from the Compliance Verdict Contract's "Fail-Closed
# Behavior" section; kept as a module-level constant so both the stub and
# the future real implementation use the exact same wording.
_FAIL_CLOSED_MESSAGE = "Sorry, I couldn't process your request safely at the moment. Please try again later."


def compliance_node(state: HotelSupportState) -> NodeResult:
    """Orchestration wrapper around the Compliance Agent.

    TODO(future task): replace the body of the `try` block below with a
    real call into `app.agents.compliance` (per docs/agents/compliance_agent.md
    and docs/rag/rag_design.md), which will retrieve relevant policy
    passages from pgvector and use Claude Sonnet to validate
    `state["draft_response"]`, returning APPROVED, REJECTED (with a
    guest-safe reason), or raising if validation itself fails.

    FAIL-CLOSED BEHAVIOR (mandatory per the Compliance Verdict Contract):
    this function wraps its logic in a try/except specifically so that
    ANY unexpected failure - now, or once real Claude/pgvector calls
    replace the stub - results in `status=ERROR` and the frozen safe
    fallback message, never a silently-passed-through, unvalidated draft
    response. This structural guarantee is put in place now, while the
    body is trivial, so it cannot be accidentally omitted later when real
    (fallible) logic is added.
    """
    guest_id = state.get("guest_id")
    logger.info("compliance_node started", extra={"guest_id": guest_id})

    try:
        # TODO: Replace this stub with real pgvector retrieval + Claude
        # Sonnet validation. For now, every draft response is approved
        # unconditionally, and the guest-facing message is simply the
        # Conversation Agent's draft response.
        compliance_status: ComplianceStatus = {
            "status": ComplianceVerdict.APPROVED,
            "guest_message": state.get("draft_response", ""),
            "reason_code": None,
            "internal_reason": None,
            "metadata": None,
        }
    except Exception:  # noqa: BLE001 - deliberately broad: ANY failure must fail closed.
        logger.exception("compliance_node failed - failing closed", extra={"guest_id": guest_id})
        compliance_status = {
            "status": ComplianceVerdict.ERROR,
            "guest_message": _FAIL_CLOSED_MESSAGE,
            "reason_code": "compliance_processing_failed",
            "internal_reason": "Unhandled exception in compliance_node.",
            "metadata": None,
        }

    result: NodeResult = {"compliance_status": compliance_status}
    logger.info("compliance_node finished", extra={"status": compliance_status["status"]})
    return result


# =============================================================================
# 10. ROUTING LOGIC
# =============================================================================
# LangGraph supports "conditional edges": after a node runs, a routing
# function inspects the state and returns the *name* of the next node to
# run. This is how the three flows from docs/architecture/workflow.md
# Section 6 (and the Reservation Dispatch Contract's "Dispatch Rule") are
# implemented:
#
#   Greeting           -> Conversation -> Compliance -> END
#   Reservation intent -> Conversation -> Reservation -> Compliance -> END
#   General question   -> Conversation -> Compliance -> END
#
# This function - not app.agents.conversation - is the ONLY place in the
# codebase that decides which node runs next.
def route_after_conversation(state: HotelSupportState) -> str:
    """Decide what happens immediately after the Conversation Agent runs.

    Only a RESERVATION intent needs the Reservation Agent ("The
    Reservation Agent is executed only when intent == RESERVATION" - the
    Reservation Dispatch Contract's Dispatch Rule). Every other intent
    proceeds straight to the Compliance Agent - it is never skipped, only
    the Reservation step is conditional.
    """
    if state.get("intent") == Intent.RESERVATION:
        return "reservation_node"
    return "compliance_node"


# Note: no routing function is needed after `reservation_node` or
# `compliance_node`, because those transitions are unconditional (a single,
# fixed next step) rather than a decision - see the fixed edges added in
# `build_graph()` below.


# =============================================================================
# 11. GRAPH CONSTRUCTION
# =============================================================================
def build_graph() -> StateGraph:
    """Construct and compile the LangGraph StateGraph for the hotel support system.

    The shape built here - three nodes, one conditional edge, two fixed
    edges - is unchanged by the contract-alignment work in this revision;
    only the state shape and node bodies changed to match the frozen
    contracts.
    """
    workflow = StateGraph(HotelSupportState)

    workflow.add_node("conversation_node", conversation_node)
    workflow.add_node("reservation_node", reservation_node)
    workflow.add_node("compliance_node", compliance_node)

    # Entry point: every request starts at the Conversation Agent.
    workflow.add_edge(START, "conversation_node")

    # Conditional routing after the Conversation Agent.
    workflow.add_conditional_edges(
        "conversation_node",
        route_after_conversation,
        {
            "reservation_node": "reservation_node",
            "compliance_node": "compliance_node",
        },
    )

    # Reservation always flows into Compliance next (unconditional edge).
    workflow.add_edge("reservation_node", "compliance_node")

    # Compliance always flows to END - the ONLY edge into END anywhere in
    # this file. Do not add a second edge into END without updating
    # docs/architecture/architecture.md and the Compliance Verdict
    # Contract, since doing so would break this project's core safety
    # guarantee.
    workflow.add_edge("compliance_node", END)

    return workflow.compile()


# =============================================================================
# 12. MODULE-LEVEL COMPILED GRAPH
# =============================================================================
# Building the compiled graph once at import time (rather than on every
# request) lets the FastAPI layer import `hotel_support_graph` directly.
#
# PUBLIC ENTRYPOINT (Graph Entrypoint Contract v1.0 - frozen):
#     state = await hotel_support_graph.ainvoke({
#         "user_message": user_message,
#         "guest_id": guest_id,
#     })
#
# `ainvoke()` is the frozen, official invocation method (async, no
# streaming, returns exactly one final HotelSupportState). The compiled
# graph also exposes a synchronous `.invoke()` (provided automatically by
# LangGraph, useful for quick scripts/tests), but FastAPI/WebSocket code
# must use `ainvoke()` per the contract, since the request-handling layer
# runs on an async event loop and a blocking call there would stall other
# connected clients.
hotel_support_graph = build_graph()