---
name: "flight-ops"
description: "Answer live flight and airport questions for a frequent flyer: is my flight OK, where is the inbound aircraft, what's the weather or ATC picture at an airport, what are my fallback flights, what does a delay collide with. Uses FlightAware AeroAPI, aviation weather (TAF/METAR), FAA NAS status, flight search, the traveller's own booking feeds and calendars, and optional ACARS/ADS-B sources. Read-only by default; never books."
---

# Flight ops — operating methodology

How to answer "is my flight OK?" well. This is methodology: which source to trust for what, the arithmetic that turns raw ops data into a decision, and the traps that make a confident answer wrong. Every account, address, ID and preference lives in a private config file the user keeps outside any shared repo — see `reference/config.example.md`.

Answer short. Lead with the fact or the decision. Work in UTC; convert to local only for display.

## 0. Load the user's config first

Look for the user's private flight-ops config (the location is theirs to choose — a note in their own memory, a project CLAUDE.md, an untracked local file). It supplies: where their booking feed and calendars are, where credentials are stored, any monitoring state they keep, who may be messaged and how, and their travel preferences. If there is no config, ask for the one or two things the question actually needs rather than guessing.

## Ground rules

- **Read-only by default.** Send nothing unless the user asks in this conversation. Never edit or delete calendar events or booking records. Never change a scheduled automation.
- **Credentials stay where they are.** Read a key at the moment of use, put it in a request header, discard it. Never echo it into chat, a file, a log, a note or a commit.
- **Search, never book.** Flight-search tools show schedule and market shape. Booking happens with the airline, by the user. Search-engine fares are usually basic non-changeable fares — present them as indicative.
- **Never invent a flight number, tail or cause.** If no source said it, don't say it. "No reason was given" is a complete answer.
- **No flight number or tail is a verdict.** Operational state belongs to one flight on one date. Vet live, every time.

## 1. What they're booked on

Bookings come from the user's itinerary feed (e.g. a TripIt calendar import) and **airline mail**. Not from work calendars, and not from auto-generated "flight from email" calendar events, which go stale silently.

- Sweep airline mail **by sender**, then read each message for meaning. A keyword list misses the wording nobody anticipated ("we've made a change to your trip"). Include ancillary transport (helicopter transfers, rail) that a flight depends on.
- Itinerary feeds duplicate segments on delay emails: two segments with the **same** flight number on the same day are one flight. **Different** numbers on the same route and day usually mean a change the traveller made.
- Cabin class is often only in airline mail, not the feed.
- The traveller's **own sent mail** to the airline settles whether a change was voluntary.
- When sources disagree: airline's own mail for that booking > itinerary feed > anything else.

## 2. Live flight state — FlightAware AeroAPI

Per-query billing with no built-in cap on personal tiers. If the user keeps a monthly query counter, read it before querying and update it after; stop at their ceiling.

```
curl -sS --max-time 25 -H "x-apikey: $KEY" -H "Accept: application/json; charset=UTF-8" \
  "https://aeroapi.flightaware.com/aeroapi/flights/UAL1234"
```

Useful endpoints: `/flights/{ident}`, `/flights/{fa_flight_id}` (one operation), `/flights/{ident}?start=<date>` (history), `/flights/{registration}` (a tail's legs), `/airports/{ICAO}/flights/scheduled_departures`, `/airports/{ICAO}/delays`.

**Idents are ICAO** (AC→ACA, UA→UAL, DL→DAL, AA→AAL; Air Canada Rouge only resolves under ROU). Regional-operated flights sold under a mainline number may need the operator's prefix: on an empty result retry **once** under it, and accept only if origin, destination and UTC date all match. A codeshare returning the operating ident is correct, not a mismatch.

**Pick the operation** whose `scheduled_out` UTC date matches the booked departure — convert local to UTC first; west-coast evening departures are the next UTC day. Forward visibility is roughly two days.

**Read**: `cancelled`, `diverted`, `status`, `departure_delay` / `arrival_delay` (seconds, signed), `scheduled_/estimated_/actual_` × `out/off/on/in` (UTC), `registration` (null = no tail assigned; normal more than ~4 h out, a warning inside it), `inbound_fa_flight_id`, gates, terminals, `origin.timezone`.

- **Departed = `actual_out`. Arrived = `actual_in`.** `actual_on` is wheels down, not arrival. Never infer departure from an email, a gate posting or a moving estimate.

### The inbound aircraft — the earliest signal there is

Query the `inbound_fa_flight_id`. Then:

1. Projected inbound gate arrival = `actual_in`, else `estimated_in`.
2. Minimum turn: ~30 min narrowbody at a carrier hub; ~40 at an outstation or with a crew change (the default when unsure); ~60 widebody or long-haul. These are compressed-recovery figures — don't discount them again.
3. Latest workable inbound arrival = their `scheduled_out` − minimum turn.
4. **Margin remaining** = latest workable − projected inbound arrival. This is the number to report.
5. Projected departure delay = max(0, projected inbound + min turn − `scheduled_out`).

A late inbound is a floor, not an estimate — delays rarely recover. An inbound still on the gate past its own push time is an **open-ended** delay. Report a thin margin even when the projected delay is zero. One leg back only. A tail swap voids the projection; re-read `registration` every check.

For a connection, compare connection slack against the **larger** of departure delay and arrival slippage — a leg that pushes on time and then holds eats the connection just as surely.

### Errors and fallbacks

- `curl: (56) CONNECT tunnel failed` / 403 with no body = the sandbox's egress allowlist, not the key; the call never reached FlightAware (not billed). The domain needs adding to the environment's allowed hosts.
- 401, or 403 with a JSON body = the key is rotated or revoked.
- Fallbacks, saying which you used: an HTTP-request automation that can set headers (paid, still billed by FlightAware); or FlightAware's public flight pages in a browser, where page state (`window.trackpollBootstrap`) carries the activity log, aircraft and inbound flight — useful for bulk tail sweeps without burning API budget.

## 3. Airport conditions

**TAF / METAR** from aviationweather.gov (`/api/data/taf?ids=KORD,KEWR&format=raw&metar=true`, `/api/data/metar?ids=…&format=raw&hours=1`). Valid params are only `ids`, `format`, `hours`, `metar`. Sandboxes often can't reach it from the shell but a web-fetch tool can.

- If a summarising fetch tool sits in between, ask for "the exact header line (station, issuance time, validity period) and every change group in order with its raw codes". Asking for the text "verbatim" tends to be refused.
- **Check issuance time before reading a word.** Fetch tools cache by URL: a TAF more than ~7 h old or a METAR more than ~90 min old is a cache hit — refetch with a different URL shape (reverse station order, one station, `metar=false`, `hours=2`). Byte-identical text across checks is a cache hit, never a "stable forecast".
- **Check the validity window covers the flight.** A TAF is a 24–30 h product; beyond that there is no forecast, only a model.
- Worth flagging: ceiling < 400 ft or visibility < 1 SM; any freezing precipitation (FZRA, FZDZ, PL — the best single predictor of a mass-cancellation day, with de-icing queues hours later); snow within ~4 h of departure; thunderstorms in the window; sustained > 30 kt or gusts > 40 kt; a named system.
- A forecast is a leading indicator, not a disruption. Word it that way.

**FAA NAS status (US airports only)**: `nasstatus.faa.gov/api/airport-status-information`. **Not reliable as a negative** — it has silently omitted active ground stops. Check its update time for cache staleness. The authoritative view is the JavaScript-rendered dashboard at nasstatus.faa.gov (Active Airport Events). A ground stop or GDP's **scope list** names the departure airports swept in, non-US ones included (e.g. Canadian origins under preclearance): a flight in scope is affected even while the airline shows it on time. If scope can't be confirmed, say so; never turn "couldn't see it" into "no impact". Canadian domestic airspace is NAV CANADA — FAA silence means nothing there.

Consumer weather apps are corroboration only; they carry no ceiling, visibility or validity window.

## 4. Fallback flights

- Search with a flight-search tool by origin, destination and date; page through results and filter explicitly for early and late departures, because lists truncate. Codeshares often show only the marketing number — say so.
- **Vet before recommending**: run section 2 on the primary option and a couple of alternatives inside the AeroAPI window. Outside it, label them unvetted.
- Count the same-day outs left behind each option, including the city's other airports. Say plainly when their flight is the last of the day — then holding an earlier seat beats waiting for certainty.
- Include "go later / next morning / don't travel tonight" whenever a delay pushes past midnight. Give each option's cost and what it protects; let the traveller choose.
- In irregular operations, calling the airline's premium desk or concierge **before** the rebooking queue forms is often the whole fix. The useful output is the specific alternative to ask for.
- Apply the traveller's own airline, airport and cabin preferences from their config — never assume them.

## 5. What a delay collides with

- In-person anchors are what constrain travel: a named venue, a "hybrid" meeting, any day inside a conference, a connection, a hotel check-in, a family event with an arrival time.
- A video-call meeting doesn't constrain **where** they are, but it is still a commitment they can't attend from a plane, a taxiway or a gate area.
- Blocks people put on calendars to protect time ("Do Not Book", "Hold", focus time) are **free time**, not commitments.
- Read calendar times in the venue's local time.
- Work out arrival at the commitment as: estimated gate arrival + deplaning + ground transit (+ bag claim only if they check bags). Any delay that pushes past the commitment is a finding, whatever its size.

## 6. Time zones — 2026 changes

Software and memory both lag here; check against the current tz database.

- British Columbia: permanent UTC−7. Alberta and the Northwest Territories: permanent UTC−6. Manitoba: permanent UTC−5. Saskatchewan is unchanged at −6 all year. Ontario, Quebec, Atlantic Canada and the US still observe DST.
- Mexico has no DST outside the US border strip (central Mexico −6, Quintana Roo −5). Morocco moved to permanent UTC in September 2026.
- A disagreement of **exactly one hour** between sources at one of these places is a zone-handling error in the source, not a schedule change.

## 7. Telling people (only when asked)

- Alerts, not briefings: the first sentence carries the fact or the decision; options one line each; under ~120 words.
- SMS: under 160 characters, in the order flight, what changed, consequence.
- Before sending, check the sent folder (and any monitoring state the user keeps) so you don't repeat what an automation already said.
- Message only the recipients and channels the user's config names, at the thresholds it sets.

## 8. Optional sources

- **ACARS / VDL** (e.g. the Airframes.io public API — anonymous, rate-limited): datalink messages from a specific tail, or station traffic near an airport, can show maintenance, diversions or a stopped departure stream before anything is published. Noisy; triage it before acting on it.
- **ADS-B** (e.g. adsb.lol, adsb.fi — keyless): live position of an aircraft, useful for "is the inbound actually moving".
- **Model weather** (e.g. Open-Meteo) for hours no TAF covers yet — a lower-confidence lead, never a TAF substitute.

Say which source each claim rests on whenever it's one of these.
