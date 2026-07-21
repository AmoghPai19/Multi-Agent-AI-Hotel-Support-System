Security Specification
Multi-Agent AI Hotel Support System
	
Companion Docs	`project_vision.md` v2.0 · `technology_decisions.md` v2.0 · `architecture.md` v2.0 · `workflow.md` v2.0 · `api_design.md` v2.0 · `database_design.md` v2.0 · `reservation_agent.md` v2.0 · `compliance_agent.md` v2.0
Component Type	Security Specification (layered / defense-in-depth)
Version	2.0
---
## 1. Introduction

This document specifies the security posture of the system: authentication, authorization, database access, prompt-injection resistance, data protection, secrets, and the compliance gate as a safety control. It consolidates the security requirements scattered across `project_vision.md` (Non-Functional Goals), `architecture.md` §11, and `workflow.md` §10 into one reference.

---

## 2. Security Principles

Defense in depth (auth + app-layer scoping + database RLS) · least privilege (narrow DB roles; role-scoped API) · fail closed (no response without compliance grounding) · untrusted-by-default (all guest and retrieved content is data, not instructions) · encryption in transit (HTTPS/TLS on every hop) · auditability (every decision logged and traceable).

---

## 3. Authentication

Identity is owned by **Supabase Auth**: registration, password hashing, **email verification**, OAuth, password reset, and JWT issuance. FastAPI **verifies** tokens; it never stores credentials.

- **Asymmetric verification via JWKS.** Tokens are signed with ES256; FastAPI verifies against Supabase's public keys at `/auth/v1/.well-known/jwks.json`, cached (~10 min) with rotation respected. This lets any API replica verify independently, and keys rotate without redeploying the backend.
- **No legacy shared secret.** Verifying against the legacy symmetric secret is deprecated and the usual source of "Invalid JWT" failures.
- **Short-lived tokens + refresh.** Limits exposure if a token leaks.

> Supersedes `workflow.md` §3 (FastAPI-issued JWT). Supabase Auth issues; FastAPI verifies.

---

## 4. Authorization

- **Roles from claims.** `app_metadata.role` (`guest` | `admin`) is read from the verified JWT — no per-request DB lookup. Admin routes (`/admin/policies`) require `admin`.
- **Guest scoping (primary control).** Reservation reads/writes are filtered by the FastAPI-injected `guest_id`; a guest can only ever touch their own bookings, regardless of what confirmation code they supply (`reservation_agent.md` §7).
- **Email-verified gate.** Booking requires `email_verified`; unverified accounts can browse/ask but not book (`api_design.md` §7).
- **RLS (defense in depth).** With a genuine per-user identity, Row Level Security on `reservations` and `policy_chunks` provides a second, database-enforced layer so a bug or leaked connection string cannot expose all rows (`database_design.md` §9).

---

## 5. Database Access

| Control | Implementation |
|---|---|
| No free-form SQL | Reservation Agent exposes five typed tools only (`reservation_agent.md` §4) |
| Parameterized queries | Every value bound, never concatenated — primary SQL-injection defense |
| Least privilege | `app_readonly` / `app_writer`; no DDL; `app_writer` has **no DELETE**; app never uses the Supabase `service_role` key |
| Transactions | Availability re-check + write in one transaction (no double-book, no partial write) |
| Statement timeout | ~3s per connection |

---

## 6. Prompt Injection & Tool Abuse

- **Instructions come only from the system prompt and the guest's direct turn.** Tool results and retrieved policy chunks are treated as data (`conversation_agent.md` §9).
- **Bounded by permissions, not prose.** Even a "delete everything" instruction has no delete tool and no DELETE grant; blast radius is capped by grants.
- **No bulk export.** There is no tool/endpoint that returns all guests or all reservations, so injection cannot exfiltrate the dataset.
- **Structural compliance gate.** Retrieval-grounded validation runs on every response regardless of how the guest phrased the input, and retrieval queries originate from the Compliance Agent's own reasoning, not raw guest text (`compliance_agent.md` §9, `rag_design.md` §9).

---

## 7. Data Protection (PII)

Guest name/email/phone live in `guests`; treat as sensitive. Minimize PII in LLM context (pass only what a tool needs) · **no PII in the vector store** — only administrator-curated policy text is embedded (`rag_design.md` §9) · redact email/phone in logs and LangSmith traces · never place PII in URLs/query strings · define a retention window for `conversations`/`messages` · never surface raw exceptions or SQL to the guest (schema leak).

---

## 8. Secrets Management

Supabase keys (publishable/secret), the `service_role` key (server-side only, never in client code), DB role passwords, LLM/embedding API keys, and JWT config live in **environment variables / Azure Key Vault** (`technology_decisions.md` §12) — never in the repo. `.env` is git-ignored with a blank `.env.example`; separate secrets per environment.

---

## 9. Compliance Gate as a Security Control

The golden rule — no response reaches the guest without passing the Compliance Agent — is a security control, enforced at the transport layer: the WS `final` event is emitted only after approval (`api_design.md` §5). It structurally blocks policy-violating, hallucinated, or unauthorized-commitment output, and defaults to rejection when grounding cannot be established (`compliance_agent.md` §8). Compliance failures are written to `audit_logs` with the retrieved policy reference.

---

## 10. Input/Output Hygiene & Rate Limiting

Schema-validate and bound all inputs (message length, date ranges, occupancy) at the FastAPI boundary before any agent or query · return controlled, user-safe error messages · rate-limit per session and per IP to blunt abuse and protect the cost-sensitive Claude Sonnet API (`workflow.md` §10).

---

## 11. Dependency & Supply-Chain

Pin dependency versions · run a vulnerability scan (`pip-audit`, `npm audit`) in CI · prefer actively maintained, widely adopted libraries · OWASP API Security Top 10 as a release-gate checklist (`technology_decisions.md` §12).

---

## 12. Security Checklist (Definition of Done)

- [ ] JWTs verified via Supabase JWKS (ES256); legacy secret not used.
- [ ] Booking requires authenticated **and** email-verified guest.
- [ ] Admin routes require `admin` role claim.
- [ ] Reservation reads/writes guest-scoped server-side; RLS enabled as defense in depth.
- [ ] No code path lets the LLM run raw SQL; all queries parameterized; `app_writer` has no DELETE; `service_role` key never in app code.
- [ ] No PII embedded in the vector store; PII redacted from logs/traces.
- [ ] Secrets in env / Key Vault, not in repo.
- [ ] Compliance gate enforced at transport layer; failures logged with policy reference.
- [ ] Rate limits + input bounds in place; errors are user-safe.

End of Document — Security Specification v2.0
