# Payment & Billing Policy

**Policy ID:** POL-PAY-006 | **Effective Date:** 2026-01-01 | **Version:** 2.2
**Owner:** Finance

## 1. Accepted Payment Methods
- Major credit/debit cards (Visa, Mastercard, Amex, Discover), and where applicable, digital wallets (Apple Pay, Google Pay) and cash (subject to property-specific cash deposit rules).
- Virtual/prepaid cards are accepted for the initial charge but may be declined for incidental holds due to card issuer restrictions; guests should be informed a secondary card may be required at check-in in that case.
- The property never accepts payment instructions received via unverified email or chat message claiming to be from the guest without authentication through the booking system.

## 2. PCI-DSS Compliance
- No agent, human or automated, may store, log, print, or transmit full card numbers (PAN), CVV, or magnetic-stripe/chip track data in plaintext anywhere outside the certified PCI-compliant payment processor.
- Only the last 4 digits of a card may appear in guest-facing confirmations, folios, or agent conversation transcripts.
- Any system component that touches cardholder data must be scoped and audited per PCI-DSS v4.0 requirements annually.

## 3. Folio & Itemized Billing
- Every guest is entitled to an itemized folio on request or at check-out, showing: room charge per night, taxes (occupancy/room tax, sales tax, etc.), resort/facility fees, incidentals, and any credits/discounts applied.
- Disputed line items must be resolved before the final charge posts where possible; if already posted, follow the Booking Disputes & Chargeback Policy (POL-DISP-020).

## 4. Deposits & Pre-Authorization Holds
- Incidental holds (typically $50-$150/night or a flat per-stay amount) are pre-authorizations, not charges, and are released automatically by the bank within 3-10 business days after check-out, timing controlled by the guest's card issuer, not the property.
- The property must never double-collect: if a hold is later converted into an actual charge, the original hold must be voided, not left to expire separately (to avoid the appearance of duplicate charges on the guest's statement).

## 5. Currency & Taxes
- Guests are charged in the property's local currency by default; dynamic currency conversion (DCC) at the guest's request must clearly disclose the conversion rate and any markup before the guest confirms.
- All applicable government taxes and mandatory resort/facility fees must be disclosed in the total price shown at booking (in line with all-in pricing / "junk fee" transparency requirements such as the US FTC rule and EU Consumer Rights Directive).

## 6. Compliance Notes for Automated Agents
- Never quote a "final price" without including known mandatory taxes and fees.
- Never request, display, or repeat a guest's full card number in a chat transcript — mask to last 4 digits only.
- Escalate any billing dispute involving a suspected duplicate charge or fraud to a human agent and the Booking Disputes policy immediately rather than issuing an ad hoc refund.