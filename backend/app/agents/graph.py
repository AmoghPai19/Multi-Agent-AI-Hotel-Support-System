"""
graph.py
--------
LangGraph orchestration layer for the Multi-Agent AI Hotel Support System.

WHAT THIS FILE IS (AND IS NOT)
------------------------------
This file's ONLY job is to coordinate execution order between agents. It
answers exactly one question, over and over: "given the current state,
which node runs next?" It must never answer questions like "what does the
guest want?", "is this booking allowed?", or "does this response comply
with policy?" - those questions belong to the Conversation, Reservation,
and Compliance Agents respectively (see docs/agents/*.md).

Concretely, this file must NEVER:
  - classify intent
  - perform reservation logic
  - validate policies
  - call Claude Sonnet
  - query PostgreSQL
  - access pgvector

The Conversation Agent is now fully implemented in app.agents.conversation
and wired in below - `conversation_node` calls it directly. The
Reservation and Compliance Agents are still placeholders: each node's body
will be replaced with a call into its own module
(app.agents.reservation, app.agents.compliance) exactly the same way
conversation.py was just integrated, without changing the graph's shape.

WHY THE COMPLIANCE GATE IS MANDATORY
-------------------------------------
Per docs/architecture/architecture.md and docs/architecture/workflow.md,
every response - regardless of intent - must pass through the Compliance
Agent before reaching a guest. This file enforces that rule structurally:
"compliance_node" is the *only* node with an edge into END. There is no
other path out of this graph, so no future change to this file can
accidentally introduce a shortcut that skips compliance - doing so would
require deliberately adding a second edge into END, which is easy to spot
in review.

HOW AGENTS PLUG IN
-------------------
Each node function below either calls its real agent module directly
(conversation_node) or documents, in a TODO comment, exactly what will
replace it once that agent module exists (reservation_node,
compliance_node):
  - conversation_node -> app.agents.conversation.run_conversation_agent (DONE)
  - reservation_node  -> PostgreSQL-backed reservation logic (pending)
  - compliance_node   -> pgvector retrieval + Claude Sonnet validation (pending)
Because every node receives and returns the same shared state shape, an
agent module only needs to accept a HotelSupportState and return a
partial update dict - it does not need to know anything about how the
graph itself is wired.
"""

# --- Standard library imports -----------------------------------------------
import logging
from enum import Enum
from typing import Any, Optional, TypedDict

# --- LangGraph imports --------------------------------------------------------
# StateGraph is the core class used to build a graph of nodes (functions)
# connected by edges (the allowed transitions between nodes). START and END
# are built-in markers: every graph begins at START and every path through
# the graph must eventually reach END.
from langgraph.graph import END, START, StateGraph

# Module-level logger. We deliberately do NOT call `logging.basicConfig()`
# or attach handlers here - that is an application-wide concern that
# belongs in the app's entry point / future LangSmith integration, not in
# an individual module. Using `getLogger(__name__)` means these log calls
# will simply be inert (no output) until the application configures
# logging, and will "light up" automatically once it does.
logger = logging.getLogger(__name__)


# =============================================================================
# 1. INTENT DEFINITION
# =============================================================================
# The Conversation Agent is responsible for figuring out what the guest
# wants. Orchestration only needs to know which of these buckets a message
# falls into, because that is what decides which path through the graph is
# taken (see docs/architecture/workflow.md Section 6, "AI Decision
# Workflow"). This Enum is the single source of truth for those buckets,
# owned by this module - app.agents.conversation imports it from here
# rather than defining its own, so there is exactly one definition of
# "what routing-relevant intents exist" anywhere in the codebase.
class Intent(str, Enum):
    """The set of guest-message intents this graph knows how to route on.

    Inheriting from both `str` and `Enum` means these values behave like
    plain strings at runtime (so they serialize cleanly into the state
    dict LangGraph passes between nodes) while still giving us type
    safety and editor autocompletion everywhere else in this file.
    """

    GREETING = "greeting"                  # e.g. "Hi", "Hello" - no booking or policy content
    RESERVATION = "reservation"            # e.g. "Book me a room", "Cancel my reservation"
    GENERAL_QUESTION = "general_question"  # e.g. "What time is check-in?", policy FAQs


# =============================================================================
# 2. SHARED APPLICATION STATE
# =============================================================================
# LangGraph passes ONE shared state object between every node in the graph.
# Each node reads the fields it needs and returns a partial dictionary of
# updates, which LangGraph merges back into the overall state before
# handing it to the next node.
#
# Only fields required for ORCHESTRATION (routing decisions and passing
# data between nodes) belong here - each agent's own internal data model
# lives inside that agent's module, not in this shared shape. This is the
# single definition of the shared state; app.agents.conversation imports
# it from here rather than declaring its own.
class HotelSupportState(TypedDict, total=False):
    """Shared state passed between all nodes in the hotel support graph.

    `total=False` means none of these keys are required to be present at
    every point in the graph's execution - immediately after START, fields
    like `intent` or `compliance_status` simply don't exist yet.
    """

    # --- Input, set before the graph starts running (by the FastAPI layer) ---
    user_message: str          # The raw text message the guest typed
    guest_id: str              # Identifier for the authenticated guest

    # --- Set by the Conversation Agent (conversation_node) ---
    intent: Intent             # Which routing bucket this message falls into
    draft_response: str        # The Conversation Agent's proposed reply (not yet approved)

    # --- Set by the Reservation Agent (reservation_node), only when invoked ---
    reservation_data: Optional[dict[str, Any]]

    # --- Set by the Compliance Agent (compliance_node) ---
    compliance_status: str     # "approved" or "rejected" - the final gate result


# A small alias to make node function signatures read cleanly: every node
# returns a *partial* update to the shared state, never the full state.
NodeResult = dict[str, Any]


# =============================================================================
# 3. CONVERSATION NODE
# =============================================================================
def conversation_node(state: HotelSupportState) -> NodeResult:
    """Orchestration wrapper around the Conversation Agent (the Supervisor).

    This node's only responsibilities are: (1) log that the Conversation
    Agent ran, (2) call it, and (3) hand its result back to the graph so
    that `route_after_conversation` can decide what happens next. It never
    itself decides the guest's intent - that classification happens
    entirely inside `run_conversation_agent`
    (see docs/agents/conversation_agent.md).

    The import below is deliberately placed INSIDE this function rather
    than at the top of the file. app.agents.conversation imports
    `HotelSupportState`, `Intent`, and `NodeResult` from this module (to
    guarantee there is only one definition of each, per Requirement 4) -
    if this module also imported from app.agents.conversation at the top
    level, the two modules would try to fully load each other before
    either finished loading, causing a circular-import error (confirmed by
    testing both import orders during development). Deferring this import
    until the function actually runs avoids that entirely, since by the
    time `conversation_node` is called, both modules have already finished
    loading.
    """
    from app.agents.conversation import run_conversation_agent

    logger.info("conversation_node started", extra={"guest_id": state.get("guest_id")})

    result = run_conversation_agent(state)

    logger.info("conversation_node finished", extra={"intent": result.get("intent")})
    return result


# =============================================================================
# 4. RESERVATION NODE (stub)
# =============================================================================
def reservation_node(state: HotelSupportState) -> NodeResult:
    """Orchestration wrapper around the Reservation Agent.

    TODO(future task): replace this stub's body with a call into
    `app.agents.reservation` (per docs/agents/reservation_agent.md), which
    will query/write PostgreSQL directly - availability lookups, booking
    creation, modification, and cancellation - and return real structured
    booking data in `reservation_data`. This will follow the same
    integration pattern already used for `conversation_node` above.

    This stub performs no database access and no booking logic; it only
    returns placeholder data so downstream nodes have a value to work
    with.
    """
    logger.info("reservation_node started", extra={"guest_id": state.get("guest_id")})

    # TODO: Replace with a real call into app.agents.reservation once that
    # module implements PostgreSQL-backed availability/booking/modification/
    # cancellation logic (docs/agents/reservation_agent.md).
    result: NodeResult = {
        "reservation_data": {
            "status": "placeholder",
            "note": "Reservation Agent logic not yet implemented.",
        }
    }

    logger.info("reservation_node finished")
    return result


# =============================================================================
# 5. COMPLIANCE NODE (stub)
# =============================================================================
def compliance_node(state: HotelSupportState) -> NodeResult:
    """Orchestration wrapper around the Compliance Agent.

    TODO(future task): replace this stub's body with a call into
    `app.agents.compliance` (per docs/agents/compliance_agent.md and
    docs/rag/rag_design.md), which will retrieve relevant policy passages
    from pgvector and use Claude Sonnet to validate the draft response
    before it can be approved. This will follow the same integration
    pattern already used for `conversation_node` above.

    This stub performs no retrieval and no validation; it always reports
    "approved". Even as a stub, this node's *position* in the graph -
    always immediately before END, on every path - is what enforces the
    mandatory compliance-gate architecture rule. That guarantee comes from
    the edges wired in `build_graph()` below, not from this function's
    logic, so it holds true even while this stub exists.
    """
    logger.info("compliance_node started", extra={"guest_id": state.get("guest_id")})

    # TODO: Replace with a real call into app.agents.compliance once that
    # module implements pgvector retrieval + Claude Sonnet validation
    # (docs/agents/compliance_agent.md, docs/rag/rag_design.md).
    result: NodeResult = {"compliance_status": "approved"}

    logger.info("compliance_node finished", extra={"compliance_status": result["compliance_status"]})
    return result


# =============================================================================
# 6. ROUTING LOGIC
# =============================================================================
# LangGraph supports "conditional edges": after a node runs, a routing
# function inspects the state and returns the *name* of the next node to
# run. This is how the three flows from docs/architecture/workflow.md
# Section 6 are implemented:
#
#   Greeting           -> Conversation -> Compliance -> END
#   Reservation intent -> Conversation -> Reservation -> Compliance -> END
#   General question   -> Conversation -> Compliance -> END
#
# This function - not app.agents.conversation - is the ONLY place in the
# codebase that decides which node runs next. The Conversation Agent only
# reports what it classified; it has no say in what happens as a result.
def route_after_conversation(state: HotelSupportState) -> str:
    """Decide what happens immediately after the Conversation Agent runs.

    Only a RESERVATION intent needs the Reservation Agent. Every other
    intent (greeting, general question) proceeds straight to the
    Compliance Agent - it is never skipped, only the Reservation step is
    conditional.

    Comparing against `Intent.RESERVATION` (an Enum member) rather than a
    raw string keeps this the single place in the file where intent values
    are interpreted, and gives us a typo-proof, autocompletable check.
    """
    if state.get("intent") == Intent.RESERVATION:
        return "reservation_node"
    return "compliance_node"


# Note: no routing function is needed after `reservation_node` or
# `compliance_node`, because those transitions are unconditional (a single,
# fixed next step) rather than a decision - see the fixed edges added in
# `build_graph()` below.


# =============================================================================
# 7. GRAPH CONSTRUCTION
# =============================================================================
def build_graph() -> StateGraph:
    """Construct and compile the LangGraph StateGraph for the hotel support system.

    Returns a compiled graph object that can be invoked with an initial
    state (e.g. `graph.invoke({"user_message": "...", "guest_id": "..."})`).
    The shape built here - three nodes, one conditional edge, two fixed
    edges - is expected to remain stable as each remaining stub node's
    internal body is replaced by a real agent implementation; only the
    *inside* of the node functions should need to change, not this wiring.
    """
    workflow = StateGraph(HotelSupportState)

    # --- Register each node with a name LangGraph will use internally ---
    workflow.add_node("conversation_node", conversation_node)
    workflow.add_node("reservation_node", reservation_node)
    workflow.add_node("compliance_node", compliance_node)

    # --- Entry point: every request starts at the Conversation Agent ---
    # This matches the architecture rule that the Conversation Agent is the
    # only agent that receives the guest's raw message.
    workflow.add_edge(START, "conversation_node")

    # --- Conditional routing after the Conversation Agent ---
    # After "conversation_node" finishes, LangGraph calls
    # `route_after_conversation(state)` and moves to whichever node name it
    # returns. The mapping below is written out explicitly (even though the
    # keys and values match) so the graph's possible destinations are
    # visible at a glance, and so adding a future destination only means
    # adding one more entry here.
    workflow.add_conditional_edges(
        "conversation_node",
        route_after_conversation,
        {
            "reservation_node": "reservation_node",
            "compliance_node": "compliance_node",
        },
    )

    # --- Reservation always flows into Compliance next ---
    # A fixed (unconditional) edge, not a routing decision: any time the
    # Reservation Agent runs, the very next step is always the Compliance
    # Agent. This is what guarantees a reservation response is never
    # released without validation.
    workflow.add_edge("reservation_node", "compliance_node")

    # --- Compliance always flows to END ---
    # The other half of the mandatory compliance-gate rule: once the
    # Compliance Agent has run, the graph is finished. This is the ONLY
    # edge into END anywhere in this file - every path must pass through
    # "compliance_node" first. Do not add a second edge into END without
    # updating docs/architecture/architecture.md, since doing so would
    # break this project's core safety guarantee.
    workflow.add_edge("compliance_node", END)

    # `compile()` validates the graph structure (e.g. checks that every
    # node is reachable and every path terminates) and returns an
    # executable graph object.
    return workflow.compile()


# =============================================================================
# 8. MODULE-LEVEL COMPILED GRAPH
# =============================================================================
# Building the compiled graph once at import time (rather than on every
# request) lets the FastAPI layer import `hotel_support_graph` directly and
# call `.invoke(...)` on it without re-building the graph each time.
hotel_support_graph = build_graph()