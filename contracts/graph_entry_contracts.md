# Graph Entrypoint Contract

## Purpose

This document freezes the public execution contract exposed by the LangGraph workflow. It defines the graph name, invocation method, input schema, execution model, and return type. This is the integration contract consumed by FastAPI and the WebSocket layer.

---

# Source of Truth

The exported graph object shall be named:

```python
hotel_support_graph
```

This name is frozen and must not change without a contract version update.

---

# Entrypoint

## Public Graph

```python
hotel_support_graph
```

## Invocation

```python
state = await hotel_support_graph.ainvoke(
    {
        "user_message": "...",
        "guest_id": "..."
    }
)
```

---

# Invocation Model (Frozen)

| Property | Value |
|----------|-------|
| Graph Name | hotel_support_graph |
| Execution Method | ainvoke() |
| Execution Model | Asynchronous |
| Streaming | No |
| Return Type | Single final HotelSupportState |

---

# Input Contract

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| user_message | str | Yes | Original guest request. |
| guest_id | str | Yes | Unique guest identifier. |

---

# Output Contract

The graph returns exactly one final `HotelSupportState` after all nodes complete execution.

```python
final_state = {
    "user_message": "...",
    "guest_id": "...",
    "intent": "...",
    "draft_response": "...",
    "reservation_data": "...",
    "compliance_status": "..."
}
```

The returned `HotelSupportState` becomes the shared state consumed by FastAPI and the WebSocket layer.

---

# Streaming Decision (Frozen)

Streaming is disabled for Version 1.0.

The graph does not emit intermediate node events or token streams.

The WebSocket receives one final response after graph execution completes.

Future streaming support requires a new contract version and a dedicated WebSocket event schema.

---

# FastAPI / WebSocket Integration

```python
state = await hotel_support_graph.ainvoke(
    {
        "user_message": user_message,
        "guest_id": guest_id
    }
)
```

FastAPI / WebSocket returns values from the final `HotelSupportState`.

---

# Ownership

## LangGraph

Responsible for:

- Expose the public graph object (`hotel_support_graph`)
- Execute workflow orchestration
- Route execution between all agents
- Return the final `HotelSupportState`

---

## FastAPI / WebSocket

Responsible for:

- Initialize the input state
- Invoke `hotel_support_graph.ainvoke()`
- Read the final `HotelSupportState`
- Return the final response to the client

---

# Error Handling

If graph execution fails before completion:

- No partial `HotelSupportState` should be returned.
- FastAPI / WebSocket must return a safe system error response.
- Internal exceptions must be logged but never exposed to the guest.
- The graph contract remains unchanged regardless of internal execution failures.

---

# Rules

- The exported graph name is frozen as `hotel_support_graph`.
- The public execution method is `ainvoke()`.
- Input keys are frozen as `user_message` and `guest_id`.
- The graph returns one final `HotelSupportState`.
- No streaming or token events are emitted in Version 1.0.
- Any change to the invocation method, graph name, input schema, output schema, or streaming behavior requires a new contract version.

---

# Version

**Version:** 1.1

**Status:** Frozen

---

# Design Summary

This contract freezes:

- Graph object name
- Public invocation method
- Execution model
- Input schema
- Output schema
- Streaming behavior
- FastAPI/WebSocket integration
- Ownership and responsibilities
- Error handling

This document serves as the single source of truth for invoking the LangGraph workflow within the Multi-Agent AI Hotel Support System.