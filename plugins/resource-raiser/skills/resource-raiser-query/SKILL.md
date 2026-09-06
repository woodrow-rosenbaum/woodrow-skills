---
name: "resource-raiser-query"
description: "Answer natural-language questions from connected US government/nonprofit public datasets using a local TechSoup/resource-raiser deployment instead of internet research or training-data recall. Triggers on: nonprofit/501(c)(3) status or EIN questions ('is X a 501(c)(3)', 'what is X's EIN', 'is X in good standing'), IRS Form 990 financials or grants received/made for a named nonprofit, US Census demographics for a named place (poverty rate, median rent, population), CDC PLACES health statistics by place (diabetes rate, obesity rate), US Treasury data (national debt, exchange rates), USASpending federal award/funding questions, NIH RePORTER grant funding, College Scorecard tuition/completion data, FEMA disaster declarations. Only applies if a resource-raiser deployment can actually be found (see step 1) -- otherwise fall back to normal research."
---

# Resource Raiser — local dataset Q&A

[TechSoup/resource-raiser](https://github.com/TechSoup/resource-raiser) is a natural-language
query engine over ~20 authoritative US public datasets (ARD discovery + OKF source descriptions,
a `discover → plan → fetch → check → synthesize` pipeline). When a project has a local deployment
of it and the question fits one of its connected datasets, **prefer it over web search or
training-data recall** — it fetches the live source and cites it, typically at $0 on local
models.

This skill is methodology for using such a deployment, not a scaffold for building one. It
assumes the deployment already exists somewhere findable; see **reference/deployment.md** for a
concrete worked example (paths, ports, model identifiers) from one real installation — copy the
shape, not the specifics, since those are configuration, not constants.

## 1. Find the deployment — don't assume a fixed path

Look for, in order: a project `CLAUDE.md` (or `README`) describing a resource-raiser deployment
and naming its local paths/ports; a `resource-raiser/` (or similarly named) checkout containing
`harness.py`, `app.py`, `planner.py`; a `local/` (or equivalent) directory with launcher scripts
(commonly `Ask.ps1`/`Start-Stack.ps1` or shell equivalents) and an `env.local.ps1`/`set_keys.sh`.

If none of this exists in the current project or a documented sibling location, **this skill
doesn't apply** — answer the question normally instead of trying to improvise a deployment.

Once found, treat the web app's `/health` and `/ask` endpoints (default port `8099` unless the
project's docs say otherwise) as the actual interface — everything below talks to those.

## 2. Recognize the fit

Typical connected source families (a given deployment may have more, fewer, or a trimmed index —
check the project's own docs, e.g. `GET /sources`):

| Domain | Ask about |
|---|---|
| nonprofit BMF (IRS Business Master File, ProPublica- or GivingTuesday-backed) | 501(c) subsection, tax-exempt status, deductibility, foundation type, EIN — for a named org |
| nonprofit 990 | A named nonprofit's Form 990 financials — revenue, expenses, assets, compensation |
| IRS grant graph | Who funds/is funded by whom, biggest grantmakers/recipients (often needs a large one-time download — check it's actually built before relying on it) |
| Census | Poverty rate, median rent, population, etc. for a named US place |
| CDC PLACES | Disease/health-behavior rates (diabetes, obesity, etc.) for a named US place |
| Treasury | National debt, exchange rates |
| USASpending | Federal award/funding data |
| NIH RePORTER | NIH grant funding |
| College Scorecard | Tuition, completion rates for a named institution |
| FEMA | Disaster declarations |

If the question doesn't fit a connected family, don't force it — answer normally.

## 3. Check if the stack is already up, bring it up if not

```bash
curl -s http://127.0.0.1:8099/health   # adjust host/port per the project's own docs
```

If it's down, the project's own launcher scripts are the source of truth for bringing it up —
don't reinvent the startup sequence. It's typically: start/confirm the local model server(s),
load the chat + embedding models, then start the discovery service and the web app, health-
polling both before querying. **Do this autonomously** if the project's own docs say it's safe to
(a standing local dev deployment, no cloud credentials involved) — don't ask first just to start
a local process. See `reference/deployment.md` for one concrete example end to end, including a
PowerShell/LM-Studio-specific gotcha worth knowing about generally: piping a CLI tool's success
message through `2>&1` under `$ErrorActionPreference = "Stop"` can turn stderr-printed success
text into a terminating error and abort a launch script before it does anything. If a launcher
script fails immediately on an ostensibly-successful step, suspect this before assuming the
underlying command actually failed.

## 4. Ask

Use the project's own ask launcher if one exists (fastest path to a readable answer + saved
JSON for later inspection). Otherwise POST directly:

```bash
curl -s -X POST http://127.0.0.1:8099/ask -H "Content-Type: application/json" \
  -d '{"query":"<the question, verbatim>","streaming":false}'
```

The response is a JSON document of NLWeb-style messages; the one with `message_type: "nlws"`
carries `content.answer`, `content.shape`, `content.status`, `content.data`, and (if you passed
`"debug": true`) `content.attempts` / `content.evidence` with the underlying validation detail.

## 5. Report back, with trust calibration by shape

Quote the synthesized answer and name the cited source — don't paraphrase away a caveat the
synthesis stage included. Then look at `shape` before presenting it as settled fact:

- **`status` / `point`** — these typically carry the resolved entity's name/EIN/identifier
  in the returned data, so an acceptance/validation layer can actually check it against the
  question. If `attempts[].validation.checks` (or equivalent) show real `"pass"` verdicts for
  entity and measure, not just `"inconclusive"`, this is well-verified — report with confidence.
- **`timeseries` / multi-period fan-out results** — worth extra scrutiny in general: fan-out
  code paths that assemble several fetches into a series often carry less per-point metadata than
  a single-fetch answer, which can leave the same acceptance checks with nothing to verify (silent
  `"inconclusive"` rather than a real pass or fail). See `reference/known-issues.md` for one
  documented, reproducible case of this producing a confidently wrong "trend" from IRS Form 990
  data — the specific field families to distrust are named there, and the general lesson (don't
  trust a multi-period answer just because a single-period one from the same source was fine)
  applies to other sources with a similar rolling/cumulative-total field.
- **`comparison` / `ranking`** — check the validation reasons for anything other than a clean
  pass before presenting confidently, same principle as above.

## 6. When to skip this and answer normally instead

- The question isn't about a connected dataset family.
- No deployment can be found (step 1), or it fails to come up — report the failure, don't loop
  on retries or improvise a fetch some other way.
- The response's `status` is a refusal or asks for clarification. **A refusal is often correct
  behavior** — the design point of this kind of engine is refusing an unanswerable question
  rather than guessing at one. Relay the refusal/clarification to the user; only fall back to
  general knowledge or web search after saying explicitly that the local engine couldn't answer
  it and why.
