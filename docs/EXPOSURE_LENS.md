# Exposure Lens

Exposure Lens turns a finalized `ReviewedFootprintDataset` into a traceable
account of public privacy exposure. It answers what can be correlated or
reconstructed from information the subject declared or confirmed. It does not
build the full identity narrative reserved for Phase 6.

## Source and review gate

The input is only
`investigations.metrics.reviewed_footprint_dataset`, written by
`POST /api/v1/investigations/{id}/review/finalize`. Before both analysis and
report reads, the service verifies:

- acquisition mode is Fair and acquisition is complete;
- Verification Gate status is `complete`;
- the saved dataset validates as `ReviewedFootprintDataset`;
- no review candidates appeared after finalization.

Otherwise both endpoints return `409 review_not_finalized`. A rejected or
uncertain account is never consulted from raw `Entity` rows. Declared accounts
and accounts with ownership `subject_confirmed` are the only account sources.
Documents are accepted only when the finalized dataset linked them to a
confirmed academic profile. Breaches come only from `dataset.breaches`, and
their email must match an attributed email in `dataset.emails`.

No content is preprocessed or presented as attributed while Fair is still
running. Incremental content analysis is deferred so the Verification Gate
remains the attribution boundary.

When a review decision changes, the gate removes the saved dataset. After the
subject finalizes again, a different normalized dataset hash makes the prior
report stale. The API marks it `stale: true`; the UI hides its findings until
the current dataset is analyzed.

## Categories

| Category | Observed signals |
| --- | --- |
| Contact | Exact email and phone strings in attributed bios, public content, or document metadata; visible contact links |
| Alias reuse | Same username on two or more declared/confirmed platforms |
| Cross-platform correlation | Exact repeated public email, personal domain, or direct link between attributed accounts |
| Location | Explicit general place references and address-like strings; specific address text is generalized |
| Temporal | Public dates, events, travel references, or repeated temporal language; never a synthesized schedule |
| Education/work | Explicit institution, company, role, or study/work phrase |
| Biographical identifiers | Public display names and explicit professional roles |
| Public documents | Documents already attributed by the finalized academic authorship relationship; visible title, name, institution, contact, and public link signals |
| Breach exposure | Attributed email and breach names supplied by the reviewed dataset |
| Content disclosure | A short finding for each attributed post with one or more of the above signals |

The current dataset does not include a structured location field or extracted
image metadata. Location detection therefore uses bounded text already present
in profile bios, posts, academic profile text, and document metadata. It does
not fetch or forensically inspect new media.

## Severity

Severity describes potential impact of an exposure, not the likelihood of harm.
No probability score or global numeric score is produced.

- **High:** a public phone number; a specific address-like reference (reported
  only as redacted); the exact same attributed email is public and appears in a
  breach record; or multiple explicit correlation signals converge.
- **Medium:** email exposure, repeated alias, direct cross-link, repeated
  personal domain, general location, study/work context, or travel/event
  references. A document with several visible identifiers is also medium.
- **Low:** a generic public contact link, one visible name/role, or a public
  document with limited metadata.
- **Informational:** reserved for public context that has little direct contact
  or correlation impact. The current rules do not assign this level by default.

The decision is deterministic and reviewable. For example, the combined
alias/email/link finding names each exact signal and cites its source; it does
not estimate the probability that two accounts share an owner.

## Evidence and basis

Each finding contains category, severity, title, summary, impact explanation,
evidence references, entity/content IDs, recommendations, basis, and method.
`basis` is `observed` for the current rules and the optional classifier.
`inferred` remains in the contract for future explicit, non-sensitive
correlations, but this phase does not emit inferred personal traits.

Evidence excerpts are capped at 280 characters. Contact findings may show the
exact public email or phone because that exact string is the finding. General
content excerpts redact contact strings. URLs have query and fragment
parameters removed. Post dates are reduced to day precision in the report.

## Safety policy

- No conclusions about danger, personality, intent, ideology, religion, health,
  sexual orientation, ethnicity, or other sensitive traits.
- The optional text classifier rejects unknown and sensitive categories,
  inferred bases, extra fields, excerpts not present in supplied evidence, and
  output containing address or routine patterns.
- Street-address-like text is replaced with a generic redacted explanation
  before it can be an excerpt, cache result, or model input.
- Repeated schedules are generalized. The report never synthesizes a timetable,
  route, residence, or actionable time to locate a person.
- No relatives are identified. Breach exposure is explicitly
  `exposure_observed_not_identity_proof`; passwords and private dumps are not
  read or shown.
- Recommendations are defensive: reduce public contact details, separate
  aliases where desired, delay travel posts, review documents, use unique
  passwords, change reused credentials, enable MFA, and review recovery methods.

## Deterministic analysis and optional AI

Rules run first for exact emails, phones, links, alias reuse, cross-links,
personal domains, breach email matches, address-like text, dates, travel/event
language, institutions, roles, and document metadata. They run even when AI is
disabled.

The optional classifier is off by default:

```text
EXPOSURE_AI_ENABLED=false
EXPOSURE_AI_MODEL=<optional LiteLLM model; otherwise LLM_MODEL>
```

When enabled, it classifies only bounded text from already attributed bios,
posts, academic profiles, and documents. It never makes ownership decisions.
The response is Pydantic structured output with an allowlisted category enum
and `basis=observed`; free-form model explanations are not used as report truth.
The prompt says:

```text
Only analyze publicly observable privacy exposure.
Do not infer sensitive personal traits.
Do not infer exact home addresses.
Do not produce schedules or actionable routine predictions.
Do not identify relatives.
Do not perform social engineering.
Only use supplied evidence.
```

Before model submission, local rules redact address-like strings, contact
strings, repeated routines, and sensitive-trait terms. Returned excerpts must
be literal substrings of that redacted input. Severity remains capped by local
impact rules. A model failure preserves deterministic findings and produces a
`partial` report.

## Limits, hashes, and cache

Defaults are configurable and bounded:

```text
EXPOSURE_MAX_CONTENT_ITEMS=100
EXPOSURE_BATCH_SIZE=15
EXPOSURE_MAX_TEXT_CHARS=30000
EXPOSURE_MAX_TEXT_EXCERPT=280
EXPOSURE_MAX_FINDINGS=100
```

The local prefilter prioritizes contact, location, time, institution, role,
and URL signals; lower-signal content is still included while budget remains.
Content beyond a cap is counted as skipped and makes the report `partial`.
An incomplete Fair source snapshot also marks the report `partial`; the UI
states that uncovered sources are unknown rather than evidence of absence.

`dataset_hash` is SHA-256 over sorted normalized dataset data. Volatile
`reviewed_at`, `decided_at`, `generated_at`, and `retrieved_at` values are
omitted; decisions and attributed records remain part of the hash. Each content
unit receives its own SHA-256 hash. Content cache keys include the content hash,
analysis version, and configuration hash (including model and limits). The
cache stores only safe structured signals and bounded excerpts, never a
duplicate body.

`exposure_runs` stores report JSON, status, dataset/config hashes, version,
model, timestamps, summary, and top exposures. A unique key reuses one report
for the same investigation, dataset, version, and configuration.
`exposure_content_cache` avoids repeating content analysis across runs.
Statuses are `pending`, `running`, `completed`, `partial`, and `failed`.

## API and UI

- `POST /api/v1/investigations/{id}/exposure/analyze` runs or reuses analysis.
- `GET /api/v1/investigations/{id}/exposure` returns the latest report or a
  pending state and marks an old dataset report stale.

The page is `/investigation/{id}/exposure`, linked after Verification Gate is
finalized. It shows severity counts without an overall score, category counts,
top attributed publications, explainable evidence, method, basis, and
recommendations. Stale findings stay hidden until reanalysis.

## Persistence and Lite

Migration `bf781b42de01` adds only the report and content-cache tables. The
Fase 5 migration was applied with `PERSONMAP_ENV=lite` and
`DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/personmap_lite`.
The legacy `person_map` database was not selected, migrated, queried, or copied.
Database tests create a disposable schema inside `personmap_lite`.

Run the provider-free fixture with:

```bash
PERSONMAP_ENV=lite \
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  backend/.venv/bin/python backend/scripts/smoke_exposure_lens.py
```

The smoke removes its synthetic target, investigation, decisions, report, and
fixture-specific content-cache entries.

## Boundary with Phase 6

This phase does not write a narrative identity, infer interests or personality,
build a full identity graph, or answer “who you are.” It reports only explainable
public exposure in the human-reviewed dataset. Phase 6 can consume these
findings as evidence but must preserve their provenance and safety boundaries.

## Mini Fase 5.1 — Execution lease and recovery

`EXPOSURE_RUN_LEASE_SECONDS=120` (30–900 seconds) bounds each analysis attempt
with an async timeout. `started_at` is the lease timestamp; no new columns or
migration are needed. Internally `running_active` means elapsed time <= lease;
`running_abandoned` means elapsed time > lease. There is no scheduler/heartbeat.

POST semantics for the same investigation/dataset/version/config:

| Stored state | Action |
| --- | --- |
| completed / partial | Return saved report |
| running, active | Return running; do not analyze again |
| running, abandoned | Claim the same row, clear old results/counters, restart timestamp |
| failed | Claim the same row and retry |
| absent | Insert one logical run |

Creation uses PostgreSQL `INSERT ON CONFLICT DO NOTHING` against the existing
unique constraint. The investigation and run row locks serialize claims;
locks are released by commit before content analysis. Concurrent identical
POSTs therefore share one run and only the claimant invokes analysis/AI.
Final writes are conditional on status and attempt timestamp, preventing a
late worker from overwriting a replacement. Failure rolls back uncommitted
content cache entries before marking the owned attempt failed with completed_at.
Cancellation follows the same cleanup; a hard process kill is recovered by lease.

GET only observes: an abandoned running row is projected as `status=failed`
so the existing retry action is available. It never updates the row or starts
analysis. This projection does not change dataset staleness semantics.

## Mini Fase 5.1 — Evidence minimization and persistence

Category builders run before content signals enter cache/report JSON. Location
uses a general observation or a redacted specific-location message. Temporal
uses a generic reference without hours or routines. Education/work extracts
only an institution marker and a short capitalized name; ambiguous names fall
back to a generic context message. Biographical evidence extracts only the
explicit professional-role token. Documents and generic content use fixed
messages. No builder falls back to raw sentences or paragraphs.

Examples:

- `Tengo lupus y estudio en Universidad X` → `Contexto educativo observado: Universidad X.`
- `Trabajo en Empresa Y y todos los martes entro a las 08:10` → `Contexto laboral observado: Empresa Y.`
- `Nos vemos en Calle Olivos 123 para el evento de Universidad Z` → education
  retains `Universidad Z`; location uses `[redactada]`.

These exclusions hold even for terms outside the sensitive-word regex. Existing
address/routine/family/sensitive/contact filters remain defense in depth. Exact
contact evidence still contains only the extracted public contact string.
Optional AI excerpts are discarded and reconstructed locally from the original
unit and allowed category. AI severity stays capped by local rules. Top
Exposures uses these same minimized signals, including its nested evidence.
The config hash includes `evidence_policy=category-minimization-v2`, so old
cached classifications and reports are not reused by new POST analyses.
Historical saved reports remain historical; this change does not rewrite them.
URLs reject unsafe decoded paths (including nested percent encoding and common
separators) and remove queries/fragments. Analysis does not log source text or
full model prompts.

`ExposureRun.findings`, `top_exposures`, and `ExposureContentCache.result` receive
already minimized JSON, independent of frontend rendering. An abandoned run
never invalidates safe content cache. AI batch failure leaves misses uncached.

The global content cache has no investigation ownership or full dataset, and
contains only hashes/config/model plus sanitized signals. It can survive deletion
of an investigation. Proposed retention is 30 days by `created_at`, including
obsolete evidence-policy versions, via a future operator-controlled batch delete;
there is currently no automatic GC or retention guarantee. No scheduler or
cleanup route is introduced in this mini phase. Hashes should still be treated
as pseudonymous data. Historical reports need a separate retention policy.

## Hardening validation (2026-10-16)

- Exposure: 37 tests passed (pure helpers plus real PostgreSQL/REST in disposable
  Lite schemas), covering active/abandoned/failed claims, concurrent POSTs,
  expired workers succeeding/failing after replacement, content-cache reuse,
  minimized AI output/local severity, persisted JSON, and encoded URLs.
- Verification Gate: 9 DB tests passed against personmap_lite.
- Fair Orchestrator: 29 tests passed.
- Lite smoke: passed with address, schedule, unknown sensitive terminology and
  institutional context; assertions inspect report and persisted JSON; cleanup
  removes fixture records. Public Alembic revision remains bf781b42de01 (head).
- TypeScript (`tsc --noEmit --incremental false`), full frontend ESLint and
  `git diff --check`: passed.
- General suite is subject to the existing GHunt/Maigret runtime limitations;
  see the Mini Fase 5.1 validation notes in FAIR_V2_PLAN.md for the bounded run.
