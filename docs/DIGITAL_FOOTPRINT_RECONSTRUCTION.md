# Digital Footprint Reconstruction + Graph V2

Phase 6 organizes the public footprint that can be reconstructed from the
subject's declared or confirmed data. It does not claim completeness of a
person's digital identity. Its fact registry and graph are deterministic. An optional, bounded AI presentation layer can select highlights from existing facts.

## Sources of truth and preconditions

The semantic builder accepts exactly `ReviewedFootprintDataset` and
`ExposureReport`. It has no database/session parameter. It never fetches new
content or consults Entity candidates, raw Frontier, review decisions, coauthor
text, bios, post bodies, captions or document title text to add facts.

The persistence service reuses Exposure Lens's finalization gate. That gate can
inspect candidates to check that review remains finalized; candidate objects
never enter the fact registry. Both endpoints require completed Fair acquisition,
a complete Verification Gate and a current reviewed dataset. Exposure is never
started automatically.

| Condition | Response |
| --- | --- |
| Review not finalized or invalidated | 409 `review_not_finalized` |
| No Exposure run for this investigation | 409 `exposure_analysis_required` |
| Exposure exists for a different dataset/version/config only | 409 `exposure_report_stale` |
| Matching Exposure running/failed | 409 `exposure_analysis_required` |
| Matching Exposure completed/partial | Reconstruction permitted |

A matching cached Exposure run can be reused after reverting a configuration.
It must match dataset hash, current Exposure analysis version and config hash,
including the hardened evidence policy. A newer unrelated run does not make a
matching valid cached report unusable.

## Epistemic labels

Every fact/node and relation has one uppercase `basis`:

| Basis | Meaning |
| --- | --- |
| DECLARED | Identifier or account explicitly supplied by the subject |
| OBSERVED | Explicit observation in an attributed source, or a human-confirmed account |
| CORRELATED | Relation between independently observed facts (same alias/email) |
| INFERRED | Reserved for explicitly marked inference; not emitted in this version |

No confidence percentages, identity probabilities, personalities, interests or
sensitive attributes are generated. Correlations never confer ownership.
Ownership comes only from `subject_declared` or `subject_confirmed` in the
reviewed footprint. Rejected, uncertain and pending accounts are excluded,
even if a malformed upstream projection accidentally includes them. Seed-only
accounts remain declarations; without an observed entity they do not generate
SAME_ALIAS public correlations or observed public alias memberships.

## Contract and fact registry

`ReconstructionReport` wraps a versioned `DigitalFootprintReconstruction`:

```text
version, investigation_id, status, stale, cache_hit,
input_hash, current_input_hash, snapshot | null

snapshot:
  version=1, reconstruction_version=reconstruction-v1,
  investigation_id, dataset_hash, exposure_dataset_hash, exposure_hash, input_hash,
  coverage, coverage_reasons, identity, facts, evidence, correlations,
  summary, counts, content_by_platform, exposure_summary, timeline,
  graph(version=graph-v2), generated_at
```

`FactRegistry` is the sole registry for identity projections, counts, narrative,
timeline and graph. Facts carry `id`, `kind`, `label`, `basis`, `group`, `ring`,
platform, safe summary, ownership basis, source tools, evidence references,
evidence count/types and source entity/content IDs. Evidence bodies are stored
once in the `evidence` map. Nodes and edges reference it by stable ID; there are
no duplicated raw evidence paragraphs.

`identity` contains fact IDs for declared identifiers, accounts, public
identifiers, academic/professional presence, documents, public content and breach
exposure. A declared email and its public observation share one canonical fact;
it remains DECLARED and its public appearances are explicit edges/evidence.
Public identifiers include observed aliases, profile URLs and contacts from
Exposure's exact contact findings. Personal domains require explicit linked-domain
evidence from Exposure. A URL does not become proof of ownership of another site.

Counts describe the whole safe registry, while the graph can be a capped subset.
The original Exposure severity counts remain separate as `exposure_summary`.
Only Exposure findings with observed basis and a resolvable reviewed source are
represented as exposure facts. Narrative calls these signals “represented”;
unresolvable/inferred findings are not silently converted into observed facts.

## Node and edge schema

A graph node is the same typed fact used elsewhere, including stable ID, basis,
group and ring. `severity` is populated only on exposure nodes. Accounts are
never labeled as high-risk accounts.

| Ring | Kinds |
| --- | --- |
| 0 | subject |
| 1 | name, email, phone, alias, domain, url |
| 2 | account, academic_profile |
| 3 | post, repository, document, publication, breach, context |
| 4 | exposure |

Edges contain `id`, `source`, `target`, `type`, `basis`, `why`,
`source_entity_ids`, `source_content_ids`, `evidence_refs`, `evidence_count` and
`evidence_types`. Every edge has evidence and endpoints in the registry.
The bounded graph excludes edges whose endpoints are not drawn.

| Relation | Direction and meaning |
| --- | --- |
| DECLARES | Subject → declared identifier |
| ATTRIBUTED_ACCOUNT / ATTRIBUTED_PROFILE | Subject → reviewed account/academic profile |
| USES_ALIAS / USES_EMAIL / USES_PHONE | Account/subject → explicit identifier |
| PUBLIC_EMAIL_ON / PUBLIC_PHONE_ON | Public source → exact contact identifier |
| SAME_ALIAS / SAME_EMAIL | Canonically ordered sources sharing the explicit identifier; CORRELATED |
| LINKS_TO | Source → explicit URL/domain/profile link |
| AUTHORED | Attributed academic profile → publication with recorded authored_work relation |
| ASSOCIATED_WITH | Profile → other document with explicit association, without inventing authorship |
| PUBLISHED | Account → its public post/repository |
| MENTIONED_IN | Minimized institutional context → source mentioning it |
| EXPOSED_IN_BREACH | Attributed email → breach record; never subject → breach |
| HAS_EXPOSURE_SIGNAL | Source artifact/account/identifier → independent Exposure finding |

For shared identifiers involving many sources, a deterministic representative
source connects to the others rather than generating every possible pair.
Email correlation prefers an account/profile as the representative. This keeps
relationships explainable without quadratic edge growth. Alias membership is
also visible through each account → USES_ALIAS → shared alias node.

IDs use `subject:{investigation_id}`, `entity:{uuid}`, fingerprinted normalized
identifiers and `content:{fingerprint(account, external_id_or_url)}`. Evidence
and edge IDs are content fingerprints. External content IDs are used only in
local lookup; persisted source_content_ids reference canonical content fact IDs
to avoid reproducing text hidden in provider IDs. Input ordering cannot change
IDs or graph ordering. Deduplication respects canonical Entity IDs.

## Safety and minimization

- No raw bios, titles or post text are reused as display excerpts. Account names
  are displayed verbatim only when matching a safe declared name; otherwise
  platform/username and a generic observation are shown.
- Institution/context evidence is rebuilt with Exposure's category minimizer.
  Location and temporal evidence remain generalized; lost precision is never
  recovered. Unknown/ambiguous context uses fixed generic text.
- Exact public contacts are extracted only from contact evidence, not from raw
  posts. Breach membership requires an already attributed structured email.
- Street addresses, routines, family references and known sensitive markers are
  rejected in identifiers and URLs. Reconstruction also rejects URL paths with
  exact hours, including percent encoding. Queries/fragments are removed.
- Sensitive-account records are omitted. No sensitive-trait, relative, precise
  location, routine or psychology node types exist.
- Academic profiles must be attributed; documents must point to an included
  profile. Only an explicit authored_work marker produces AUTHORED. Coauthors
  and authorship free text are not projected.
- A typed repository artifact is represented only for a GitHub account with a
  repository URL under that exact attributed username. Otherwise the artifact
  remains generic public content. No repository or project is fetched.
- Timeline uses validated ISO dates reduced to day precision from typed post
  date fields. No timestamps, habitual weekdays or inferred patterns are shown.
- No raw posts/prompts are logged. All persisted snapshot/graph JSON is already
  minimized; UI hiding is not the privacy boundary.

This is conservative extraction, not universal semantic recognition. Arbitrary
names/URLs still require the upstream review and source policies. Missing or
omitted data is not proof that no other public information exists.

## Narrative and coverage

Templates reference fact IDs from the same registry used by the graph. They
report account/document counts, representative shared aliases/emails, observed
Exposure signals and breach records, with no global risk score or identity
claims. The factual paragraphs include observed activity counts. By default no AI is called;
The default reconstruction remains available without model credentials; the optional presentation setting is documented below.

If Fair acquisition or Exposure is partial, the snapshot has `coverage=partial`,
partial reasons, and terminal status partial. UI states:

> Esta reconstrucción representa únicamente las fuentes observadas durante esta investigación.

“completed” means snapshot construction succeeded, not that all public identity
has been found. The main scope text is:

> Esta es la huella reconstruible a partir de las fuentes observadas.

## Persistence, hashing and staleness

Migration `c62d914ae306` follows `bf781b42de01` and creates only
`reconstruction_runs`: investigation FK with cascade delete, dataset/exposure/
input hashes, reconstruction version, status, one snapshot JSONB including
graph, config, started_at and completed_at. No graph database is introduced.

Exposure hash covers the report including status, findings, config, version and
generation timestamp; read-time cache_hit/stale/current_dataset_hash are excluded.
Input hash covers dataset hash, Exposure hash, reconstruction version, graph
version and config. Thus a regenerated/changed Exposure report, review change,
version or cap change requires an appropriate current snapshot.

Build holds the existing investigation row lock, builds locally, then inserts
a complete snapshot with ON CONFLICT on UNIQUE(investigation_id, input_hash).
It commits only terminal completed/partial states. A crash or exception before
commit leaves no run; rollback permits a fresh retry. No running lease is needed
for this local, atomic build. Concurrent identical requests reuse one logical
snapshot. The DB CHECK forbids persistent running/pending states.

GET observes and never builds. If prerequisites are stale, it returns the
appropriate 409 without historical content. If Exposure is current but only an
older reconstruction exists, it returns `stale=true, snapshot=null`. If a valid
cached snapshot matches the current input, it is preferred even after reverting
configuration. Historical snapshots are retained until investigation deletion;
a separate retention/GC policy remains future work.

## API and UI

```text
POST /api/v1/investigations/{id}/reconstruction/build
GET  /api/v1/investigations/{id}/reconstruction
```

There is a single synchronized reconstruction contract with embedded Graph V2.
The view is `/investigation/{id}/reconstruction`, linked from a current completed
or partial Exposure Lens report. It includes identity counts, factual narrative,
reviewed identity sections, public content counts by platform, timeline and an
interactive React Flow graph (existing @xyflow/react dependency).

Graph layout places subject at center and identifiers/profiles/artifacts/
exposure in successive rings. Layout is memoized for the full snapshot; filters
hide layers without moving remaining nodes. Pan, zoom, fit controls, keyboard
selection, node/edge detail, source links and a legend are available. Details
show explanations and referenced evidence rather than internal metadata dumps.
Account icons reuse existing platform SVGs. Exposure colors belong only to
exposure nodes. No discovery calls or per-node HTTP requests are made.

This is a functional integrated view; global navigation, branding, final fair
animations, guided storytelling and the Phase 7 redesign are out of scope.

## Limits

```text
RECONSTRUCTION_MAX_TIMELINE_ITEMS=50   # 1–200
GRAPH_MAX_TOTAL_NODES=150             # 10–300
GRAPH_MAX_POST_NODES=30               # 0–100, posts+repositories combined
GRAPH_MAX_DOCUMENT_NODES=30           # 0–100, documents+publications combined
GRAPH_MAX_EXPOSURE_NODES=30           # 0–100
```

Graph prioritizes subject, declared anchors, accounts/profiles, then strong
artifacts and exposure evidence. Parent accounts/profiles/emails remain present
when a dependent artifact is selected. Exposure overlays require a visible source.
Omitted-node totals and kinds are explicit. There is no expansion/group API yet;
full facts and counts remain in the snapshot. Timeline is separately bounded.

## Lite validation and smoke

All DB validation selects personmap_lite or disposable schemas inside it.
The legacy person_map database must never be selected, migrated or modified.
The smoke requires both runtime environment and actual connection to match Lite:

```bash
cd backend
PERSONMAP_ENV=lite \
DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/personmap_lite \
  .venv/bin/python scripts/smoke_reconstruction.py
```

The provider-free fixture creates Instagram/TikTok with shared alias, public
email, academic profile/paper, breach, two posts, rejected and uncertain accounts.
It finalizes review, runs Exposure, builds/reads/reuses reconstruction, checks
semantic graph edges, exclusion, safe report/persisted JSON, and cleans its
synthetic target/runs/cache. It preserves any preexisting global cache entries.
`--output /tmp/report.json` optionally exports only the safe synthetic report.

Tests cover preconditions, epistemology, correlations, breach/academic/social
hierarchy, safe timeline, deterministic IDs/order, duplication, staleness,
config reversion, limits with 500 posts, explainability, concurrent atomic
builds and rollback. Frontend tests exercise API methods/errors, pending/stale
states, rendered coverage/narrative/timeline, graph filters and node/edge
selection details using the actual presentational components.

### Validation recorded on 2026-10-16

- Reconstruction: **36 passed** (27 pure + 9 REST/PostgreSQL), including refusal
  of non-Lite smoke URLs, repository ownership, seed-only declarations and
  inferred Exposure exclusion. Existing Exposure/Verification/Fair/database
  isolation regression: **77 passed**. Across overlapping runs, 113 distinct
  directed backend tests passed.
- New frontend tests: **7 passed**, using rendered real TSX sections/status/
  detail components; all **4 frontend test files** also passed. TypeScript
  and full ESLint passed. No real-browser E2E was run.
- Production build passed using `next build --webpack`, including the dynamic
  reconstruction route. Default Turbopack failed to bind a local CSS-worker
  port (Operation not permitted), including the escalated attempt. No compiler
  configuration was changed to mask that environment error.
- Lite smoke passed with **30 nodes / 52 explained edges**, persisted JSON
  safety checks, cache reuse and cleanup. Alembic is **c62d914ae306 (head)**.
- General backend suite was bounded by `timeout 180 ... pytest -vv`: exit 124,
  **705 PASSED** lines, no recorded failures, last test in progress
  `test_maigret_capabilities.py::test_all_native_report_formats_work_without_network[graph]`.
  The full suite is not validated. GHunt/Maigret modules were not modified.
- person_map was never selected or modified; main was not changed.

Reproduce directed PostgreSQL tests with both environment and test URL set to
Lite (reconstruction reuses Exposure's guarded disposable fixture):

```bash
cd backend
PERSONMAP_ENV=lite \
DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/personmap_lite \
EXPOSURE_LENS_TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/personmap_lite \
  .venv/bin/python -m pytest tests/test_reconstruction.py tests/test_reconstruction_pure.py -m '' -q
cd ../frontend
node --experimental-strip-types tests/reconstruction.test.mts
```

Remaining work for Phase 7: visual polish, browser interaction/performance QA,
optional collapsed-group expansion, guided demonstration and final branding.
Historical snapshot/cache retention and completion of the general source suite
remain separate technical debt. None is implemented as part of this phase.

## Lite integration: infostealer exposure

The reviewed contract now has a minimal `infostealers` collection. A record can
enter the fact registry only through an attributed email/alias. Graph V2 retains
a distinct `infostealer` artifact under the exposure-record group, connected by
`EXPOSED_IN_INFOSTEALER` from that identifier, never directly from the subject.
The identity snapshot's `breach_exposure` list groups exposure record IDs; node
kinds/edge types distinguish ordinary breaches from malware records. No machine
metadata enters facts, narrative or graph. The evidence policy hash advances to
`reviewed-typed-fields-and-minimized-exposure-v2`. Existing input hashes enforce
reanalysis/rebuild when the reviewed projection or exposure configuration changes.

## Optional AI presentation and observed activity

`RECONSTRUCTION_AI_ENABLED=false` remains the application default. Local demo env
files enable it. The model receives minimized registry facts and can return only
up to eight existing IDs; local safe summaries become `narrative_highlights`.
The snapshot exposes `narrative_method`, `narrative_status` and `narrative_model`.
Failure retains the factual reconstruction, and an explicit build can retry a
fallback. The flag/model/policy enter the input hash. AI cannot create facts or
free prose, reinterpret severity or infer traits. Activity counts and engagement
counters describe public posts, not private activity or habits.

Instagram collaborative posts carry an explicit reviewed `authorship_role`;
`COAUTHORED` links the attributed account to its post and participates in graph
parent/cap handling. Other coauthors never become subject nodes.
