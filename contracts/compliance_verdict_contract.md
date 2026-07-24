# Compliance Verdict Contract

## Purpose

This document defines the communication contract between the Compliance Agent, LangGraph, and the WebSocket/FastAPI response layer. It freezes the compliance status values, rejection behavior, and fail-closed handling so every component knows exactly what to return and render.

---

# Workflow

```text
FastAPI / WebSocket
        ↓
LangGraph
        ↓
Conversation Agent
        ↓
Reservation Agent (Optional)
        ↓
Compliance Agent
        ↓
FastAPI / WebSocket Response
```

---

# Compliance Status Values (Frozen)

| Status | Meaning |
|--------|---------|
| APPROVED | Response passed compliance checks and may be returned to the guest. |
| REJECTED | Response violates one or more compliance rules and must not be returned unchanged. |
| SYSTEM_ERROR | Compliance validation could not complete. The system must fail closed. |

---

# Compliance Agent Output

```python
compliance_result = {
    "status": "APPROVED | REJECTED | SYSTEM_ERROR",
    "guest_message": "...",
    "reason_code": "...",
    "internal_reason": "...",
    "metadata": {...}
}
```

The `compliance_result` object is written into `HotelSupportState` and becomes the final compliance output consumed by the FastAPI/WebSocket layer.

---

# Field Definitions

| Field | Description |
|--------|-------------|
| status | Frozen compliance verdict. |
| guest_message | Safe message that may be shown to the guest. |
| reason_code | Stable machine-readable rejection or system error code. |
| internal_reason | Diagnostic information for logs only; never exposed to guests. |
| metadata | Optional audit information. |

---

# Rejection Contract

When `status` is `REJECTED`, the Compliance Agent must always provide a guest-safe `guest_message`.

The frontend/WebSocket must render this message and must never display `internal_reason`.

---

# Fail-Closed Behavior

If compliance processing fails for any reason:

```text
status = SYSTEM_ERROR
```

The system must not return the original draft response.

Instead it returns a safe fallback message such as:

> "Sorry, I couldn't process your request safely at the moment. Please try again later."

This behavior is mandatory (**Fail Closed**).

---

# WebSocket / FastAPI Rendering Rules

| Status | Frontend Behavior |
|--------|-------------------|
| APPROVED | Render final validated response. |
| REJECTED | Render `guest_message`. |
| SYSTEM_ERROR | Render fallback `guest_message`. |

The frontend must never expose:

- internal_reason
- raw compliance exceptions
- stack traces
- diagnostic information

---

# Ownership

## Compliance Agent

Responsible for:

- Validate final response
- Produce `compliance_result`

---

## LangGraph

Responsible for:

- Route `HotelSupportState`
- Pass state between agents

---

## WebSocket / FastAPI

Responsible for:

- Read `compliance_result`
- Render only `guest_message`
- Never expose internal compliance information

---

# Rules

- Compliance status values are frozen.
- Every response must pass through the Compliance Agent before reaching the guest.
- `REJECTED` must include a guest-safe `guest_message`.
- `SYSTEM_ERROR` must always fail closed.
- The frontend renders only `guest_message`.
- `internal_reason` is never exposed externally.
- `compliance_result` is the final compliance payload stored in `HotelSupportState`.

---

# Version

**Version:** 1.1

**Status:** Frozen

---

# Design Summary

This contract freezes:

- Compliance status values
- Compliance response payload
- Guest-safe rejection behavior
- Fail-closed system behavior
- FastAPI/WebSocket rendering rules
- Ownership and responsibilities
- Final compliance payload written to `HotelSupportState`

This document serves as the single source of truth for Compliance Agent integration.