# flight-ops private config — TEMPLATE

Copy this somewhere **private** (your own Claude memory, a project CLAUDE.md, or an untracked file) and fill it in. Never commit the filled-in copy to a shared or public repo. It describes your accounts, contacts and travel habits, and that's exactly what someone would need to target you.

Keep credential *locations* here, never credential values.

## Booking sources
- Itinerary feed calendar: `<calendar id>`
- Airline mail senders to sweep: `<sender domains>`
- Ancillary transport senders (helicopter, rail, car service): `<sender domains>`

## Calendars to check for collisions
- Primary work calendar (in-person anchors): `<calendar id>`
- Busy-only calendars: `<calendar id>`
- Family / kids' activity feeds (and their time zone): `<calendar id>`
- Personal: `<calendar id>`

## Credentials (locations only)
- AeroAPI key: `<where it's stored>`
- Monthly query counter + ceiling: `<where, and the number>`

## Monitoring state (if you run an automation)
- State page / file: `<location>` — what an on-demand session may read, and the **only** line(s) it may write
- Automations to leave alone: `<names / ids>`

## Messaging
- Channels and senders: `<email account, SMS route>`
- Recipients and their thresholds: `<who hears about what>`
- Quiet hours: `<window>`

## Traveller preferences
- Home airports and how long each takes door to gate: `<…>`
- Airline order by market (domestic / transborder / international): `<…>`
- Cabin rules: `<…>`
- Checked bags: `<yes / no>`
- City-specific airport choices: `<…>`
