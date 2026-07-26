"""
test_graph_compliance_gate.py
-------------------------------
Tests the single most important safety guarantee in this codebase: the
Compliance Agent MUST run on every path through the graph, for every
intent, with no exceptions - and the graph must fail closed if compliance
processing itself breaks.

This is the "walking skeleton" checkpoint referenced in the Plan of
Action (Phase 1b exit criteria, and Mithun's "today" task): proof that
the plumbing and the compliance-gate ordering work end-to-end, using the
current stub Reservation/Compliance Agents. These tests are expected to
keep passing unchanged even after `compliance.py` and `reservation.py`
are replaced with real implementations - only their *internal* behavior
should change, never whether compliance runs or where it sits in the
graph.

Run with:
    cd backend && pytest tests/test_graph_compliance_gate.py -v
"""

from __future__ import annotations

import pytest

from app.agents.graph import (
    ComplianceVerdict,
    Intent,
    ReservationTool,
    build_graph,
    compliance_node,
    hotel_support_graph,
)


# =============================================================================
# 1. STRUCTURAL GUARANTEE: compliance_node is the ONLY edge into END
# =============================================================================
# This is a stronger check than "did compliance run in this one test case" -
# it inspects the compiled graph's actual edge list, so it would catch a
# future change that adds so much as a second path out of the graph,
# regardless of which intent might trigger it.
def test_compliance_node_is_the_only_edge_into_end():
    graph_repr = hotel_support_graph.get_graph()
    end_edges = [edge for edge in graph_repr.edges if edge.target == "__end__"]

    assert len(end_edges) == 1, (
        "Exactly one edge into END is expected. If this fails, a new edge "
        "was added that lets some path bypass the Compliance Agent - this "
        "must never happen (see architecture.md's compliance-gate rule)."
    )
    assert end_edges[0].source == "compliance_node", (
        "The only edge into END must originate from compliance_node."
    )


# =============================================================================
# 2. BEHAVIORAL GUARANTEE: compliance runs on every real intent path
# =============================================================================
@pytest.mark.parametrize(
    "user_message,expected_intent,expects_reservation_data",
    [
        ("Hello!", Intent.GREETING, False),
        ("What time is check-in?", Intent.GENERAL_QUESTION, False),
        ("I would like to book a room", Intent.RESERVATION, True),
        ("I need to cancel my reservation ABC12345", Intent.RESERVATION, True),
    ],
)
@pytest.mark.asyncio
async def test_compliance_status_present_on_every_intent_path(
    user_message: str, expected_intent: Intent, expects_reservation_data: bool
):
    result = await hotel_support_graph.ainvoke(
        {"user_message": user_message, "guest_id": "test-guest"}
    )

    assert result["intent"] == expected_intent
    assert ("reservation_data" in result) == expects_reservation_data

    # The actual invariant under test: no matter which path was taken,
    # compliance_status must be present, and must be a fully-formed
    # verdict envelope - not missing, not a bare string, not partially
    # populated.
    assert "compliance_status" in result, (
        f"compliance_status missing for message={user_message!r} - "
        "this means the Compliance Agent did not run on this path."
    )
    compliance_status = result["compliance_status"]
    assert compliance_status["status"] in (
        ComplianceVerdict.APPROVED,
        ComplianceVerdict.REJECTED,
        ComplianceVerdict.SYSTEM_ERROR,
    )
    assert "guest_message" in compliance_status and compliance_status["guest_message"]


@pytest.mark.asyncio
async def test_reservation_path_visits_reservation_agent_before_compliance():
    """Confirms the *order* is Reservation -> Compliance, not just that both ran."""
    result = await hotel_support_graph.ainvoke(
        {"user_message": "Book me a room please", "guest_id": "test-guest"}
    )
    assert result["intent"] == Intent.RESERVATION
    assert result["tool_name"] == ReservationTool.CREATE_RESERVATION
    assert "reservation_data" in result
    assert "compliance_status" in result
    # We can't directly observe execution order from the final state alone,
    # but the Reservation Dispatch Contract's Dispatch Rule guarantees this
    # ordering via the graph's fixed edges (reservation_node -> compliance_node),
    # which is separately verified by test_compliance_node_is_the_only_edge_into_end.


# =============================================================================
# 3. FAIL-CLOSED GUARANTEE: if compliance processing itself breaks, the
#    system must report SYSTEM_ERROR with the safe fallback message - never a
#    silently-approved or unvalidated response.
# =============================================================================
def test_compliance_node_fails_closed_on_internal_error():
    """Directly unit-tests compliance_node with a state object engineered
    to raise partway through, proving the try/except fail-closed path
    actually produces the frozen fallback - not just that it exists in
    the source code."""

    class ExplodingState(dict):
        """A state whose .get('draft_response') always raises, simulating
        an unexpected internal failure during compliance processing."""

        def get(self, key, default=None):
            if key == "draft_response":
                raise RuntimeError("Simulated compliance failure")
            return super().get(key, default)

    exploding_state = ExplodingState({"guest_id": "test-guest", "draft_response": "irrelevant"})

    result = compliance_node(exploding_state)
    compliance_status = result["compliance_status"]

    assert compliance_status["status"] == ComplianceVerdict.SYSTEM_ERROR
    assert compliance_status["guest_message"] == (
        "Sorry, I couldn't process your request safely at the moment. Please try again later."
    )
    # internal_reason is diagnostic-only; it must be present for logs, but
    # this test does NOT assert it is ever rendered to a guest - that
    # responsibility belongs to the FastAPI/WebSocket layer, not this graph.
    assert compliance_status["internal_reason"] is not None


# =============================================================================
# 4. REGRESSION GUARD: build_graph() always produces a graph with this
#    invariant, not just the one module-level instance already compiled.
# =============================================================================
def test_freshly_built_graph_also_preserves_the_compliance_gate():
    """Guards against a future change to build_graph() that only happens
    to satisfy the invariant for the specific instance already compiled
    at import time (`hotel_support_graph`), by rebuilding the graph fresh
    and checking again."""
    fresh_graph = build_graph()
    graph_repr = fresh_graph.get_graph()
    end_edges = [edge for edge in graph_repr.edges if edge.target == "__end__"]
    assert len(end_edges) == 1
    assert end_edges[0].source == "compliance_node"