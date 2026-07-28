# Hotel Support System — Compliance Policy Corpus

**Purpose:** This is the source document set for the RAG-based Compliance Agent
described in the project's `architecture.md` / `reservation_agent.md` specs. Each
file below is a self-contained policy, written the way a real hotel operations/legal
team would publish it, so it chunks and embeds cleanly for retrieval.

## Suggested chunking approach
- Chunk by `##` section headers (each section is a coherent retrieval unit), not by
  fixed token windows — table rows and numbered steps should stay intact.
- Store `policy_id`, `version`, and `section_title` as metadata alongside each chunk
  in `policy_chunks` so the Compliance Agent can cite which policy + section it used.
- Keep the "Compliance Notes for Automated Agents" section of each file — these are
  written specifically to give your Compliance Agent clear allow/deny/escalate rules,
  which should make your compliance-gate evals (pass^k, fail-closed tests) much easier
  to write, since each file already states explicit dos and don'ts.

## File index

| File | Policy ID | Covers |
|---|---|---|
| 01_booking_reservation_policy.md | POL-BOOK-001 | Reservation creation, guarantees, rate plans, OTA bookings |
| 02_cancellation_policy.md | POL-CXL-002 | Cancellation windows, penalties, exceptions |
| 03_refund_policy.md | POL-REFUND-003 | Refund eligibility, timelines, approval thresholds |
| 04_no_show_policy.md | POL-NOSHOW-004 | No-show charges, late arrivals, disputes |
| 05_checkin_checkout_policy.md | POL-CICO-005 | Check-in/out times, early/late fees, delayed rooms |
| 06_payment_billing_policy.md | POL-PAY-006 | Payment methods, PCI-DSS, folios, deposits, taxes |
| 07_group_event_booking_policy.md | POL-GRP-007 | Group blocks, attrition, master billing |
| 08_overbooking_walked_guest_policy.md | POL-OVBK-008 | Walked-guest mandatory remedies |
| 09_guest_conduct_policy.md | POL-COND-009 | Conduct rules, escalation ladder, fraud indicators |
| 10_damage_incidentals_policy.md | POL-DMG-010 | Damage assessment, charging process, disputes |
| 11_pet_policy.md | POL-PET-011 | Service animals vs. pets, fees, restrictions |
| 12_children_occupancy_policy.md | POL-OCC-012 | Max occupancy, kids-stay-free, unaccompanied minors |
| 13_privacy_data_protection_policy.md | POL-PRIV-013 | GDPR/CCPA-style data handling, guest rights |
| 14_accessibility_policy.md | POL-ADA-014 | ADA-style accessible rooms, accommodations |
| 15_loyalty_program_policy.md | POL-LOY-015 | Earning, tiers, redemption, status match |
| 16_complaint_dispute_resolution_policy.md | POL-CDR-016 | Service recovery, resolution authority thresholds |
| 17_force_majeure_policy.md | POL-FM-017 | Natural disasters, government advisories, waivers |
| 18_smoking_policy.md | POL-SMOKE-018 | Smoke-free rules, violation fees, cannabis |
| 19_security_deposit_policy.md | POL-SEC-019 | Incidental holds, release timing |
| 20_booking_disputes_chargeback_policy.md | POL-DISP-020 | Informal disputes, formal chargebacks, reason codes |

## Notes on realism
These policies mirror common structure and figures found across major hotel brand
terms & conditions, ADA/DOT service-animal guidance, PCI-DSS scope rules, and
GDPR/CCPA lodging-industry practice. Dollar amounts, percentages, and time windows
are realistic industry defaults — **replace them with your actual property's real
figures** before using this as a genuine production policy set; treat the numbers
here as reasonable placeholders for building and testing your RAG + compliance-gate
pipeline (chunking, retrieval, and pass/fail eval logic), not as legal advice.

## Cross-references between policies
Several files reference each other (e.g., cancellation → refund → disputes;
overbooking → complaint resolution; damage → disputes). This is intentional and
realistic — it's a good stress test for your retriever's top-k and multi-hop
retrieval quality, since some guest questions will require pulling chunks from
more than one policy file.
