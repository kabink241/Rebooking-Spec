# Evidence

Sources: 60 call logs (CL-001 to CL-060), interview INT-ROSALIND-01, and the Storm Travel Waiver Fare Rules Bulletin (Denver, November 2026). Averages use 55 clean calls (CL-022, 029, 038, 041, 055 excluded). Interview minute figures are Rosalind's own estimates from memory.

## Baseline (minutes, 55 clean calls)

| | All calls | Above-average-handle calls (22) | Gap |
|---|---|---|---|
| Find Open Flights | 5.41 | 6.47 | +1.07 |
| Check Waiver Rules | 3.03 | 3.28 | +0.24 |
| Reseat Party | 2.18 | 4.38 | +2.20 |
| Confirm And Notify | 1.97 | 2.28 | +0.31 |
| Document Booking | 1.80 | 2.44 | +0.63 |
| Total Handle Time | 14.40 | 18.85 | +4.45 |
| Hold Time | 3.52 | 5.89 | +2.37 |
| Screens Switched | 11.13 | 15.59 | +4.46 |

Hold overlaps the steps. The five steps sum to Total Handle Time on every complete call.

## By party size

| Party | Calls | Handle | Hold | Screens | Find | Reseat |
|---|---|---|---|---|---|---|
| 1 | 26 | 11.38 | 1.92 | 7.42 | 4.62 | 0.05 |
| 2 | 18 | 14.38 | 2.96 | 11.17 | 5.41 | 2.27 |
| 3+ | 11 | 21.56 | 8.22 | 19.82 | 7.26 | 7.05 |

Parties of 3+ are 20% of calls, 30% of handle minutes, 47% of hold minutes, and 80% of the minutes the long calls ran over average. All 11 were above the average handle time.

## By outcome

| Outcome | Calls | Handle | Hold |
|---|---|---|---|
| rebooked | 46 | 12.97 | 2.59 |
| rebooked_split_party | 6 | 22.40 | 8.83 |
| escalated_to_supervisor | 3 | 20.27 | 7.13 |

## Requirement traceability

| Requirement (REBOOKING_SPEC.md) | Evidence |
|---|---|
| 7.1 Single-query search over qualifying flights | Seat screen shows one flight at a time; six flights paged for a party of two (INT-ROSALIND-01 [00:01:09]). Find is the largest step, 37.5% of handle time |
| 7.2 Side-by-side pair for 3+ | Rosalind asked for three together plus the next flight with a seat for the fourth, side by side (INT-ROSALIND-01 [00:16:36]). Customers differ on tolerance: a mother refused next-morning (INT-ROSALIND-01 [00:12:52]), a party of five refused any split (CL-052) |
| 7.4, 9.3 Escalation packets | Agent cannot hold a seat or move others; waits on lead and gate (INT-ROSALIND-01 [00:13:43]). Split-party hold averages 8.8 min vs 2.6 for plain rebookings |
| 8 G7 freshness | Seats disappeared or refreshed mid-reseat: CL-024, 028, 032, 034 |
| 9.1 Flag-only fare outcome | Check Waiver averages 4.58 min on the 12 non-covered calls vs 2.60 on covered. Agents reopen the waiver page every time for Anytime and Business Select (INT-ROSALIND-01 [00:06:42]); six calls note re-checking (CL-003, 030, 048, 050, 051, 059). Bulletin 1.4 and 3.3 remove the need |
| 9.1 BLOCKED on flag conflict | Eligibility lives on the fare screen, a separate switch from booking (INT-ROSALIND-01 [00:07:05]); fare class displayed differently on two screens (CL-051) |
| 12 Auto-drafted note | Document Booking averages 1.80 min (median 1.4). Three solo calls took 4.9 to 5.9 min after notes-tool failures (CL-008, 020, 037). Two agents average 3.43 and 2.87 min vs 1.28 to 1.41 for the other four. Split notes carry reciprocal booking numbers read back twice (INT-ROSALIND-01 [00:14:34]) |
| 6 Single workspace | Screens average 11.1 and correlate 0.96 with handle time (about 0.85 min per switch; correlation, not proof). Rosalind counted 11 on a simple two-person call; logs show 11.2 for pairs. "Nothing carries over between screens" (INT-ROSALIND-01 [00:02:35]) |
| 7.5 Event-based timing | Missing or inconsistent timing in CL-022 (waiver timer not started), CL-038 (3.0 min untracked), CL-041 (documentation timer not stopped) |
| 13 Draft save and resume | Callers abandoned while the agent paged seats (CL-029 at 12.9 min) or moved a second passenger (CL-055 at 10.3 min) |

## Bulletin cross-check

| Finding | Detail |
|---|---|
| Agents re-assess eligibility; the bulletin forbids it | Notes cite reasons that are not bulletin clauses: purchased after cutoff (CL-003, 019, 046), original flight not on the waiver list (CL-023, 059), dates outside the window (CL-036), with agents checking the fare-rule screen twice (CL-003, 023, 059). Clause 1.4 makes the flag the decision. v0.1 reason codes were dropped for this reason |
| Fare class checks are unnecessary for covered quotes | Rosalind checks that the waiver "covers their fare class" (INT-ROSALIND-01 [00:05:44]). Clause 3.3 says the open fare class need not match, and 3.1 applies whatever the class |
| Window start conflicts with the logs | Clause 2.1 starts rebooked travel on 18 Nov. Notes on 15 to 17 Nov calls describe same-day or next-flight rebookings (CL-001, 010, 025). See OQ-03 |
| Alternate airports go to Revenue Management | CL-012: the passenger wanted HOU not DAL and the agent reran the search. Under 2.2 and 2.5 that request is not an agent task |
| Delayed flights are allowed | Clause 2.3 permits `delayed`. Rosalind avoided one for children (INT-ROSALIND-01 [00:12:52]), which stays an agent and customer choice |
| Documentation line | Clause 3.6 requires `STORM WAIVER DEN NOV26` plus the original confirmation number. The interview describes a free-form note with no template (INT-ROSALIND-01 [00:03:45]) and does not mention the line, so whether agents record it today is unknown (OQ-12) |
| Waiver has ended | Requests are accepted through 23 Nov 2026 (1.5, 2.5); the date today is 26 Nov. Rules must be dated config (OQ-15) |
| Bulletin silent on connections | Rosalind names the onward connection as the most important check (INT-ROSALIND-01 [00:00:20]); the bulletin never mentions it (OQ-07) |

## Queue and seat files (Nov 2026)

Two files loaded into the service: 140 cancelled bookings and 154 seat rows (153 valid).

| Finding | Detail |
|---|---|
| Most large parties cannot sit together anywhere | Only 1 flight in the seat file has four adjacent seats (WN1136, DEN to PHX, 21 Nov). 44 of the 53 bookings of 3 or more have no flight on their route with seats for everyone together. The family of four with three seats together is the normal case, not the edge case |
| Adjacent-seat distribution on usable flights | 0 seats: 14 flights; 1: 33; 2: 76; 3: 20; 4: 1 |
| Party sizes | 1: 46, 2: 41, 3: 18, 4: 21, 5: 8, 6: 6 |
| Covered by the waiver | 134 of 140. 6 non-covered |
| Customer notes that decide the seating | "must sit together" on 20 bookings (parties of 3 and 4); "happy to split if needed" on 9; children noted on 8 |
| Infants and wheelchair users | 27 bookings travel with an infant; 6 need wheelchair assistance |
| Connections | 27 bookings name an onward flight; none can be checked |
| Seat-file defects | 4 cancelled flights show open seats; row WN1154 is truncated |

Service result on this data (rules only, as of 17 Nov): 101 bookings get an offerable plan, 30 need a fact from the agent first (age bands 30, customer note 17, policy OQ-05 14, lap infant 5; counts overlap), 9 have no two-flight plan (7 parties of 5 or 6, 2 wheelchair parties). Four bookings (children noted, no "must sit together") get a split as the lead option.

## Caveats

- The logs have no fare-class or connection fields, so those effects cannot be measured from them.
- One agent was interviewed, and she is the fastest on handle time (13.5 min vs 13.4 to 16.1 across the six agents).
- Rosalind put a split-party call at 35 to 40 minutes. The longest logged call is 25.1. Handle plus hold reaches 35.5, so how lead wait is recorded needs checking (OQ-14).
- Hypothesis tested and rejected: that the longest calls have Find, Reseat, and Check Waiver all above average. Only 2 of the 10 longest did. Find plus Reseat above average predicts long calls (16 of 17).
