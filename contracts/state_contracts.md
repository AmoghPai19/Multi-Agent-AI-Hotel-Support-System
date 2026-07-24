# HotelSupportState Contract

## Purpose

This document defines the shared state contract used by the Multi-Agent AI Hotel Support System. Every agent communicates through this shared state. The field names, types, ownership, and lifecycle defined here are considered the official contract and should not be changed without team agreement.

---

# HotelSupportState

| Field | Type | Required | Set By | Used By | Description |
|--------|------|----------|--------|---------|-------------|
| user_message | str | Yes | FastAPI | Conversation Agent | Raw message sent by the guest |
| guest_id | str | Yes | FastAPI | All Agents | Authenticated guest identifier |
| intent | Intent | No | Conversation Agent | LangGraph | Guest intent used for routing |
| draft_response | str | No | Conversation Agent | Compliance Agent | Draft response generated before validation |
| reservation_data | Optional[dict] | No | Reservation Agent | Compliance Agent | Reservation details returned by the Reservation Agent |
| compliance_status | str | No | Compliance Agent | FastAPI | Final compliance validation status |

---

# Intent Enum

The routing layer supports only the following intents.

```python
GREETING
RESERVATION
GENERAL_QUESTION
```

These values are owned by LangGraph and must remain unchanged unless the orchestration logic is updated.

---

# State Lifecycle

```
FastAPI
    │
    ▼
user_message
guest_id
    │
    ▼
Conversation Agent
    │
    ├── intent
    └── draft_response
    │
    ▼
Reservation Agent (Only for Reservation Intent)
    │
    └── reservation_data
    │
    ▼
Compliance Agent
    │
    └── compliance_status
    │
    ▼
FastAPI Response
```

---

# Ownership Rules

- FastAPI creates the initial HotelSupportState.
- Conversation Agent updates only `intent` and `draft_response`.
- Reservation Agent updates only `reservation_data`.
- Compliance Agent updates only `compliance_status`.
- Agents must not modify fields owned by other agents.
- The field names and types defined in this document are considered frozen for the current implementation.

---

# Version

Version: 1.0

Status: Frozen