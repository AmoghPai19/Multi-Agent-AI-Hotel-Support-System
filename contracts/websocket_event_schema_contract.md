# Contract #5 – WebSocket Event Schema Contract

## Purpose

This document defines the communication contract between the **React Frontend** and the **FastAPI Backend** over a WebSocket connection. It freezes the event names, payload structures, message flow, ownership, and connection rules for **Version 1.0**.

---

# Version 1.0 Decision

The AI workflow returns **one final `HotelSupportState`** after the graph finishes execution.

For Version 1.0:

- The graph is invoked using `await hotel_support_graph.ainvoke(...)`.
- The system **does not support streaming**.
- Each guest request produces **one final response**.
- All communication happens through the WebSocket events defined in this contract.

---

# Connection Flow

```text
React
    ↓
WebSocket
    ↓
FastAPI
    ↓
hotel_support_graph.ainvoke()
    ↓
Final HotelSupportState
    ↓
final_response
    ↓
React
```

---

# Event Flow

```text
Client connects
        ↓
connection_ack
        ↓
chat_message
        ↓
hotel_support_graph.ainvoke()
        ↓
Conversation Agent
        ↓
Reservation Agent (if required)
        ↓
Compliance Agent
        ↓
Final HotelSupportState
        ↓
final_response
```

---

# Client → Server Events

| Event | Fields | Description |
|--------|--------|-------------|
| `chat_message` | `guest_id`, `user_message` | Submit a guest request to the AI system. |
| `ping` | `timestamp` | Heartbeat event used to verify that the connection is alive. |

---

# Server → Client Events

| Event | Fields | Description |
|--------|--------|-------------|
| `connection_ack` | `connection_id` | Confirms that the WebSocket connection has been established successfully. |
| `final_response` | `draft_response`, `reservation_data`, `compliance_status` | Final response returned after the AI workflow completes. |
| `error` | `code`, `guest_message` | Returns a guest-safe error message if processing fails. |
| `pong` | `timestamp` | Heartbeat response from the server. |

---

# Payload Examples

## Client Request

```json
{
  "event": "chat_message",
  "guest_id": "guest-123",
  "user_message": "Book a Deluxe room for tomorrow"
}
```

---

## Successful Response

```json
{
  "event": "final_response",
  "draft_response": "Your reservation has been created successfully.",
  "reservation_data": {
    "status": "SUCCESS",
    "booking_id": "BK12345",
    "data": {
      "room_type": "Deluxe",
      "check_in": "2026-07-25",
      "check_out": "2026-07-26"
    },
    "message": "Reservation confirmed."
  },
  "compliance_status": "APPROVED"
}
```

---

## Error Response

```json
{
  "event": "error",
  "code": "SYSTEM_ERROR",
  "guest_message": "Sorry, we couldn't process your request right now. Please try again later."
}
```

---

# Event Ownership

## React Frontend

Responsible for:

- Opening the WebSocket connection.
- Sending `chat_message`.
- Receiving server events.
- Displaying guest-safe messages to the guest.

---

## FastAPI Backend

Responsible for:

- Accepting WebSocket connections.
- Sending `connection_ack`.
- Invoking `hotel_support_graph`.
- Returning `final_response`.
- Returning guest-safe `error` events.

---

## LangGraph

Responsible for:

- Executing the AI workflow.
- Returning one final `HotelSupportState`.
- Never communicating directly with the frontend.

---

# Connection Rules

- A client must receive `connection_ack` before sending `chat_message`.
- Each `chat_message` maps to exactly **one** `final_response`.
- Version 1.0 does **not** support streaming responses.
- Heartbeats use the `ping` and `pong` events.
- If the connection is lost, the client must reconnect before sending another request.
- All error responses must contain only guest-safe messages.

---

# Rules

- Event names are frozen.
- Payload field names are frozen.
- One guest request maps to one `final_response`.
- No streaming events are supported in Version 1.0.
- Internal errors must never be exposed to the guest.
- Any future change to the event names or payload structure requires a new contract version.

---

# Design Summary

This contract freezes:

- WebSocket event names.
- Client → Server payloads.
- Server → Client payloads.
- Event sequence.
- Connection rules.
- Message flow.
- Component ownership.

This document serves as the **single source of truth** for WebSocket communication between the React frontend and the FastAPI backend.

---

# Version

**Version:** 1.0

**Status:** Frozen