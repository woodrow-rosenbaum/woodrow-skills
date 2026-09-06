# Known issues affecting trust calibration (dated — check upstream before trusting)

Last verified: 2026-09-06, against a specific local deployment (see `deployment.md`) of
TechSoup/resource-raiser. These are upstream/data issues, not deployment-specific — worth
checking whether they're still live against whatever deployment you're using, since upstream may
have fixed them since this was written.

## IRS Form 990 Schedule A "170"/"509" fields mislabeled as annual, not caught by validation

**Symptom:** a `timeseries`-shaped question about a nonprofit's "grants received by year" (or
similar) returns a smooth, plausible-looking multi-year trend that is actually wrong — the
underlying field is a 5-year rolling cumulative total (Schedule A, Part II, Line 1, column (f) —
the `170(b)(1)(A)(vi)`/`509(a)(2)` public-support-percentage-test total), not a single year's
figure. Three consecutive filings' overlapping 5-year windows get presented as three independent
annual data points, with a computed "change"/"change %" that is an artifact of the rolling window
shifting, not a real change in anything the organization received.

**How to recognize it live:** compare the reported figure to the same organization's total
revenue for the same year (from the same source) — if the "grants received" figure exceeds total
revenue, that's the tell. IRS Form 990 fields with this shape are typically named or tagged with
`170`/`509`/"support test" (e.g. `gftgrntsrcvd170`, `totgftgrntrcvd509`, `grsrcptsrelated170`).
The field you actually want for a genuine single-year contributions/grants figure is usually
labeled plainly, e.g. "Total Contributions and Grants" (`totcntrbgfts` on the ProPublica-backed
source used in the deployment this was found on).

**Why validation doesn't catch it:** on the deployment where this was found, the acceptance
checker's entity/measure checks only fire when the fetched data carries fields like
`organization`/`measure`; the timeseries fan-out code path assembling the multi-year series didn't
thread those through per data point, so the checks silently returned `"inconclusive"` rather than
failing — a structural gap in that fan-out path, not something the field-level description alone
could fix. If your deployment's timeseries path does carry that metadata through, this specific
failure mode may already be closed; verify against a real answer before assuming either way.

**General lesson, not specific to this one field:** any government/nonprofit financial dataset
that reports both a single-period figure and a rolling/cumulative multi-period aggregate under
similarly-worded field names is a candidate for the same mistake — a natural-language description
generated without the underlying accounting instructions in view will often describe a cumulative
field as if it were per-period. Cross-check a timeseries answer's magnitude against a known
independent figure (like total revenue) before trusting a "trend."
