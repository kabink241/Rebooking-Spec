# 0001: Seating a party when seats are short

Status: Proposed. Date: 26 Nov 2026. Updated for the Denver storm bulletin (v0.2).

## Context

When a party of four finds only three adjacent seats on the best flight, agents currently split the family across flights. In CL-004 and CL-039 the notes say "only three adjacent seats" and a parent moved to a later flight. In the interview example (INT-ROSALIND-01 [00:12:15]) the seat screen showed three together and the fourth open seat "rows away", yet the agent offered three on the evening flight and the father the next morning. The transcript does not say why the fourth seat on the same flight was not offered (OQ-05).

The bulletin makes splitting fare-neutral for covered bookings: a party may use more than one flight, and no fare penalty, change fee, or fare difference applies to any member (3.5). Every flight must still meet Section 2, so a later flight must be inside 18 to 23 Nov and at or after `earliest_acceptable_departure`. Section 3.5 does not protect non-covered bookings (Section 3 does not apply to them), so there each member's flight is priced under the original fare class rules.

Splitting is costly in agent time. Split-party calls average 22.4 min against 13.0 for plain rebookings and pull a lead off the floor. Customers also differ: one mother refused the next-morning option, and a party of five refused any split (CL-052).

## Decision

1. Spec rules apply to every option (not in the bulletin, to be confirmed, OQ-04): every minor shares a flight with an adult from the party, and every flight group with a minor has an adult. No split happens without the customer's explicit agreement.
2. Generate options in this order: (a) same flight, three adjacent plus one apart, when every minor is in the adjacent group with an adult; (b) same flight via a lead-approved seat move; (c) earliest all-together flight; (d) split across flights, with the group of three containing the minors and the remaining adult on the next soonest qualifying flight.
3. Show (c) and (d) side by side with arrival gaps. The assistant does not rank one above the other.
4. Documentation: for covered splits the line `STORM WAIVER DEN NOV26 <original confirmation number>` goes on every rebooked flight (3.6). Reciprocal booking numbers in each note are recommended floor practice, verified by lookup.
5. Lead approval for a split is configurable, default on until confirmed (OQ-06). The bulletin does not require it.

## Why

- (a) keeps the family on one flight and avoids an overnight split. It is the cheapest option for the customer if non-adjacent family seating is allowed.
- Putting minors with an adult in the adjacent group is the safest arrangement that still arrives together.
- Showing (c) and (d) as a pair respects that tolerance varies, and stops the agent negotiating blind.
- The singleton in a split is an adult on the soonest following flight, which matches the interview example.
- If approval proves unnecessary, removing it attacks the largest hold times in the data (8.8 min on split-party calls).

## Consequences

- Option (a) is behind a configuration flag until policy confirms it is allowed (OQ-05).
- Needs a per-passenger adult or minor flag in the data (OQ-04).
- Needs adjacency information for every qualifying flight, not one flight at a time.
- Non-covered splits need per-member pricing, which depends on the price source (OQ-01).

## To validate

- Ask Rosalind why the same-flight option was not used in the Phoenix example.
- Test in the prototype: share of parties of 3+ that accept (a), (c), (d), and time to agreement.

## Update (v0.3): who can fly alone and the consent protocol

Settled in `REBOOKING_SPEC.md` 11.1 and 11.2.

- **Who can fly alone:** adults always; teens 12 to 17 only with the guardian's recorded consent and never proposed first; children under 12, lap infants, and anyone the customer says needs a companion never, so every such person stays with an adult (18+) from the party. The rule for under-12s is deliberately stricter than Southwest's own (an accompanying passenger 12 or older), because a 12-year-old sibling as sole companion is a risk the assistant should not create, and because Unaccompanied Minor service cannot be set up mid-rebooking.
- **Before confirming any split:** show the all-together alternative beside it, state the split plainly, state the fare treatment, get an explicit yes to the exact split from an adult (and confirm the separate traveler agrees), resolve any condition and restate with a second yes, get lead approval if configured, re-verify seats, then close the loop with cross-linked notes and a read-back.
- **Why a second yes:** in the interview example the mother agreed only if the agent would ask about moving seats (INT-ROSALIND-01 [00:12:52]). That is a provisional yes. The lead's answer changed the plan, so the final plan must be restated.
- **Lead approval is not consent.** A lead decides whether the airline can do something; only the customer decides whether to accept it.
