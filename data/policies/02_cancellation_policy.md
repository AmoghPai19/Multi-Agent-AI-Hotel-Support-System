# Cancellation Policy

**Policy ID:** POL-CXL-002 | **Effective Date:** 2026-01-01 | **Version:** 2.3
**Owner:** Revenue Management | **Review Cycle:** Semi-Annual

## 1. Purpose
Defines the standard cancellation windows, penalties, and exceptions across rate types. This is the policy the Compliance Agent must check against before confirming or denying a guest's cancellation request.

## 2. Standard Cancellation Windows
| Rate Type | Free Cancellation Cutoff | Penalty if Cancelled After Cutoff | Penalty if No-Show |
|---|---|---|---|
| Flexible / BAR | 48 hours (6:00 PM property local time) before arrival date | 1 night's room + tax | 1 night's room + tax |
| Advance Purchase / Non-Refundable | None — non-refundable from time of booking | 100% of total stay | 100% of total stay |
| Corporate/Negotiated | Per contract (commonly 24-72 hrs) | Per contract, default 1 night | Per contract, default 1 night |
| Group Block (10+ rooms) | Per group contract attrition clause, typically 30 days | Per attrition schedule | Per attrition schedule |

Peak/holiday periods and special events may carry an extended cutoff (e.g., 7-14 days) and this must be disclosed at time of booking, not applied retroactively.

## 3. How Cancellations Are Processed
1. Guest requests cancellation via the original booking channel where possible (OTA bookings should be cancelled through the OTA).
2. System verifies the reservation status, current time against the property's local cutoff time zone, and rate-plan terms.
3. If within the free window: full cancellation, no charge, cancellation confirmation number issued.
4. If after cutoff: penalty per table above is charged to the card on file; guest receives an itemized cancellation confirmation.
5. All cancellations must generate an audit log entry: reservation ID, timestamp, channel, cancelling party, and resulting charge (if any).

## 4. Exceptions Requiring Human Escalation
Automated agents must **not** unilaterally waive a cancellation penalty. Escalate to a human agent for:
- Documented medical emergencies or bereavement (with reasonable supporting evidence).
- Government-declared natural disasters, mandatory evacuations, or travel bans affecting the guest's origin or destination.
- Airline cancellations/strikes stranding the guest (subject to proof).
- Verified property-caused issues (e.g., the property cancelled first due to overbooking or maintenance closure).

## 5. Same-Day Cancellations & Early Departure
- Cancelling on the arrival date is treated as a no-show under the applicable rate's no-show terms unless the guest has not yet checked in and cancels before the property's cancellation cutoff (rare, property-specific).
- Early departure after check-in is governed by the property's early-departure fee schedule (typically the remaining nights are not charged unless the rate was non-refundable/prepaid, in which case no refund is issued for unused nights).

## 6. Group & Event Cancellations
Group bookings follow the signed group contract's attrition and cancellation clause, not the standard individual policy. Attrition penalties are calculated against the contracted room-night block, not individual reservations.

## 7. Compliance Notes for Automated Agents
- Always calculate the cutoff using the **property's local time zone**, not the guest's or server's time zone.
- Never process a refund for a non-refundable rate without a documented, approved exception on file.
- Always disclose the exact penalty amount and refund timeline (see POL-REFUND-003) before finalizing a cancellation, and require explicit guest confirmation for any cancellation that incurs a charge.
