# Automatic Lite acquisition for the fair

Lite is selected by `PERSONMAP_ENV=lite` and must use `personmap_lite`.
No migration is added by this integration. Legacy databases are not accessed.

## Entry point and form

Internal investigation creation normalizes acquisition to `fair`, strategy to
`rule_based`, pivots to `standard` and removes interactive Maigret plans. This
also covers older clients submitting `normal` or fast/deep/all plans. Normal
workspaces and explicitly external MCP investigations retain their semantics.
`/health` reports the effective environment and Lite plan; the form waits for
that configuration. Lite never asks for scan modes or starts the AI acquisition
planner. The existing infostealer authorization remains visible and optional.

## Budget and priority

The global limit is 225 seconds, or a smaller operator configured limit. The
current default reserves 20 seconds for finalization and 6 for cancellation,
leaving 199 seconds for acquisition. The limit is a scheduling deadline, not a
promise that unavailable providers return data or a real time process guarantee.
Review time, Exposure analysis and reconstruction are separate operations.

The ordered list in `engine/lite_policy.py` contains 39 platforms: main social
networks first, then student/technical communities and portfolios. Up to 100
complementary native recipes are selected, with the same ordering applied before
the cap. Platform counts and recipe counts are different. Native profile checks
retain negative controls; a username match is not ownership.

All compatible sources start independently with parallelism bounded by Fair and
shared HTTP budgets. Breaches, GHunt, email enumeration, academic discovery,
SearchDorker and authorized infostealer checks are eligible in the first round.
Infostealers use one email/alias per task, up to six invocations, so a late lookup
cannot erase earlier completed records or replay all previous identifiers.
An omitted permission is recorded as `subject_consent_required`.

Frontier admits bounded strong discoveries into up to three rounds (default
six pivots per admission round, twelve total). New aliases/emails/profile links
can trigger tools again, using input fingerprints, per-source invocation caps,
provider quotas and the global deadline. The local/example preset allows up to
six aliases and six native username/GitHub invocations so typical one-to-three
seed inputs do not consume the entire expansion quota. Unchanged inputs are not replayed.
Optional work stops at 75% of acquisition time; new pivots stop at 90%.

## Direct and discovered Apify profiles

A declared `username + platform` is ready for Apify from the first scheduling
pass. It does not wait for UsernameFinder, search, academia or the checklist.
These independent sources run concurrently. Apify obtains public data; it does
not analyze exposure or assert ownership of other matching accounts.

A bare username first goes through native discovery. Native profile observations
admitted by Frontier may then be enriched with Apify, while quota/time remain.
The adapters currently implemented are Instagram, TikTok, Threads and YouTube.
Other platforms remain native; an unsupported Actor is never launched silently.

The local/example preset allows four Actor runs/four Actor types, two concurrently,
with a maximum reservation of $0.025/run and $0.10/investigation. These are caps,
not measured costs or promises of free execution. Provider minimum charges,
account credits and Actor availability can reduce coverage. Starts are never
retried after ambiguous errors. Actual tokens remain in ignored local env files.

## Exposure records and downstream safety

`ReviewedFootprintDataset.infostealers` projects only the record ID, queried
identifier kind/value, provenance, public source link and exposure semantics.
It requires exact association with a declared or confirmed email/alias. Queries
against unconfirmed discoveries do not enter the subject's reviewed snapshot.
Machine names, IPs, malware paths, credentials and sessions are excluded.

Exposure adds a deterministic `infostealer_exposure` finding, locally capped at
medium, with remediation advice and no assertion of a current infection.
Reconstruction renders a distinct `infostealer` artifact through
`Email/Alias → EXPOSED_IN_INFOSTEALER → record`, plus a separate exposure overlay.
Ordinary breach records retain `Email → EXPOSED_IN_BREACH → record`.
Neither relationship establishes ownership. Changed reviewed data invalidates
old Exposure/reconstruction inputs through the existing hash policy; the
reconstruction evidence policy is also versioned for this projection.

The review checklist remains limited to discoveries; declared platform accounts
are already subject declared. Exposure runs only after final review. Reconstruction
remains deterministic and uses reviewed data plus the current safe Exposure
report. Exposure AI is enabled in the ignored local env files using the existing
configured model; application defaults remain opt-in/off. It receives only the
existing sanitized, reviewed input and retains deterministic fallback on failure.
No new narrative AI, raw-post preprocessing or Phase 7 redesign is added.

## Observability and validation

The investigation displays Fair source states and counts, including breach,
infostealer, Google and email enumeration coverage. Timeout, unavailable provider,
missing compatible inputs and empty results have different explanations.

Tests cover old-client normalization, ordered catalog coverage, parallel execution,
direct declared Apify, new-input pivots, deadline cancellation, infostealer input
isolation and review → Exposure → graph projection without machine data.
DB integration tests use disposable schemas exclusively inside `personmap_lite`.
`backend/scripts/smoke_reconstruction.py` additionally checks infostealer edges
and safety, then cleans up its fixtures. These checks are synthetic; they do not
prove current live provider quality, latency or costs.

### Public provider probe (2026-10-16)

A bounded live AcademicFinder lookup for the public fixture Alan Turing made
three requests: Crossref works, OpenAlex authors and OpenAlex works all returned
HTTP 200; six findings were normalized. This validates connectivity and the
current adapter path, not coverage for any particular student or author. GHunt
runtime/session files report `configured`; no Google subject query was run.
Apify and Exposure AI were validated synthetically without spending live credits.

### Regression results

378 targeted offline backend tests and 35 Lite DB integration tests passed.
All five frontend test files, TypeScript, ESLint and the webpack production build
passed; both Lite smoke scripts passed with cleanup. The general offline suite
was timeboxed to 120 seconds and blocked at the existing
`test_ghunt.py::test_http_capabilities_and_mcp_contract_do_not_expose_session`
(after 613 passing tests).
GHunt's worker module was not changed to bypass this failure.
