# Contract #5 – WebSocket Event Schema Contract

## Purpose

This document defines the communication contract between the **React Frontend** and the **FastAPI Backend** over a WebSocket connection. It freezes the event names, payload structures, message flow, ownership, and connection rules for **Version 1.1**.

---

# Version 1.1 Decision

The AI workflow returns **one final `HotelSupportState`** after the graph finishes execution.

For Version 1.1:

- The graph is invoked using `await hotel_support_graph.ainvoke(...)`.
- The system **does not support streaming**.
- Each guest request produces **one final response**.
- All communication happens through the WebSocket events defined in this contract.

**Change from v1.0:** the `final_response` payload previously carried `draft_response` (the Conversation Agent's *unvalidated* candidate text) directly to the guest. This has been corrected to carry `guest_message` instead - the field the Compliance Verdict Contract already guarantees is always present and guest-safe, regardless of whether the verdict was `APPROVED` or `REJECTED`. `compliance_status` is also corrected from a bare string to the full object it actually is in `HotelSupportState`, matching the HotelSupportState & Intent Enum Contract and the Compliance Verdict Contract exactly - no new shape is introduced here, this version simply stops contradicting the two contracts that came before it.

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
final_response  (compliance_status.status == APPROVED or REJECTED)
        -- OR --
error           (compliance_status.status == SYSTEM_ERROR, or any
                 unhandled backend failure before a verdict is reached)
```

**Rule:** `REJECTED` is a completed workflow outcome, not a system failure - a guest who is told "no" still receives a `final_response`, with `compliance_status.status == "REJECTED"` and a guest-safe `guest_message` explaining why. The separate `error` event is reserved for `SYSTEM_ERROR` (compliance validation itself could not complete) and for backend-level failures that occur before any `HotelSupportState` is produced at all (e.g. the graph invocation itself throwing).

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
| `final_response` | `guest_message`, `reservation_data`, `compliance_status` | Final response returned after the AI workflow completes - covers both `APPROVED` and `REJECTED` verdicts. |
| `error` | `code`, `guest_message` | Returns a guest-safe error message when compliance validation itself fails (`SYSTEM_ERROR`) or the backend fails before producing a verdict. |
| `pong` | `timestamp` | Heartbeat response from the server. |

**Field notes for `final_response`:**
- `guest_message` (string, always present, always guest-safe) - taken directly from `compliance_status.guest_message`. This is the ONLY text FastAPI/React are permitted to render as "what the AI said" - never `draft_response`, which is an internal, unvalidated intermediate value and must never be sent to the client.
- `reservation_data` (object or `null`) - present only when the turn involved the Reservation Agent; passed through from `HotelSupportState["reservation_data"]` unchanged.
- `compliance_status` (object, not a string) - passed through from `HotelSupportState["compliance_status"]` in full: `{status, guest_message, reason_code, internal_reason, metadata}`. The frontend may use `status` (`"APPROVED"` / `"REJECTED"`) for UI treatment (e.g. a subtle "unable to confirm" badge on rejection), but must render `guest_message` as the actual response text in both cases. `internal_reason` must never be displayed - it exists for logs only.

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

## Successful Response (APPROVED)

```json
{
  "event": "final_response",
  "guest_message": "Your reservation has been created successfully.",
  "reservation_data": {
    "status": "SUCCESS",
    "booking_id": "3F9A2B7C",
    "data": {
      "room_type": "Deluxe",
      "check_in": "2026-07-25",
      "check_out": "2026-07-26"
    },
    "message": "Reservation confirmed."
  },
  "compliance_status": {
    "status": "APPROVED",
    "guest_message": "Your reservation has been created successfully.",
    "reason_code": null,
    "internal_reason": null,
    "metadata": null
  }
}
```

*(Note: `booking_id` above uses the real 8-character confirmation code format generated by `db/schema.sql` - not a "BK12345"-style placeholder.)*

---

## Rejected Response (REJECTED - still a `final_response`, not an `error`)

```json
{
  "event": "final_response",
  "guest_message": "Unfortunately, pets are not permitted at this hotel.",
  "reservation_data": null,
  "compliance_status": {
    "status": "REJECTED",
    "guest_message": "Unfortunately, pets are not permitted at this hotel.",
    "reason_code": "policy_violation:pets",
    "internal_reason": "Draft response matched contradiction phrase 'pets are welcome' for policy POL-002.",
    "metadata": {"violated_policy_id": "POL-002", "matched_phrase": "pets are welcome"}
  }
}
```

*(Note: `internal_reason` and `metadata` are included here for completeness/logging on the backend, but the frontend must only ever render `guest_message`.)*

---

## Error Response (SYSTEM_ERROR - compliance validation itself failed)

```json
{
  "event": "error",
  "code": "SYSTEM_ERROR",
  "guest_message": "Sorry, I couldn't process your request safely at the moment. Please try again later."
}
```

---

# Event Ownership

## React Frontend

Responsible for:

- Opening the WebSocket connection.
- Sending `chat_message`.
- Receiving server events.
- Rendering `guest_message` from either `final_response` or `error` - never any other field - as the guest-visible text.

---

## FastAPI Backend

Responsible for:

- Accepting WebSocket connections.
- Sending `connection_ack`.
- Invoking `hotel_support_graph`.
- Mapping `HotelSupportState["compliance_status"]["status"]` to the correct outgoing event (`final_response` for `APPROVED`/`REJECTED`, `error` for `SYSTEM_ERROR`).
- Never forwarding `draft_response` to the client under any circumstance.
- Returning guest-safe `error` events for any failure that occurs before a `HotelSupportState` is produced at all.

---

## LangGraph

Responsible for:

- Executing the AI workflow.
- Returning one final `HotelSupportState`.
- Never communicating directly with the frontend.

---

# Connection Rules

- A client must receive `connection_ack` before sending `chat_message`.
- Each `chat_message` maps to exactly **one** terminal event: either `final_response` or `error`.
- Version 1.1 does **not** support streaming responses.
- Heartbeats use the `ping` and `pong` events.
- If the connection is lost, the client must reconnect before sending another request.
- All `error` and `final_response` events must contain only guest-safe messages - `internal_reason` is never sent to, or rendered by, the frontend.

---

# Rules

- Event names are frozen.
- Payload field names are frozen.
- One guest request maps to one terminal event (`final_response` or `error`).
- No streaming events are supported in Version 1.1.
- Internal errors and internal reasoning must never be exposed to the guest.
- `compliance_status` is always the full object defined by the Compliance Verdict Contract - never a bare string.
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

This document serves as the **single source of truth** for WebSocket communication between the React frontend and the FastAPI backend, and is consistent with the HotelSupportState & Intent Enum Contract and the Compliance Verdict Contract that govern the data it carries.

---

# Version

**Version:** 1.1

**Status:** Frozen

**Changelog:** v1.1 corrects `final_response` to carry `guest_message` (not `draft_response`) and restores `compliance_status` to its full, already-frozen object shape (not a bare string). No event names changed; only the `final_response` payload fields and the SYSTEM_ERROR/REJECTED routing rule were clarified.