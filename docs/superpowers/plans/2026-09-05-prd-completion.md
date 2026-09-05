# Ripple PRD Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining PRD workflows so a user can ingest a corpus, discover and review regulatory changes, inspect evidence-backed impacts, run scans and simulations, make recorded decisions, and understand the result through the dashboard and dependency graph.

**Architecture:** Preserve the current FastAPI + SQLite/FTS5/sqlite-vec backend and Next.js App Router frontend. Consolidate change, impact, scan, simulation, and recommendation logic into domain services; run expensive work through the existing jobs mechanism; give every authenticated account organization-wide administrator access. Preserve the user-approved React Flow graph and selectable blocking sample environments.

**Tech Stack:** Python 3.12, FastAPI, SQLite/FTS5/sqlite-vec, official OpenAI Python SDK, Next.js 15, React 19, TypeScript, Tailwind CSS, shadcn/ui, React Flow.

**Spec:** `PRD.md` sections 6–14, with the user decisions recorded under “Resolved product decisions” below.

## Global Constraints

- Implement production code first. Add and run the consolidated automated test suite only in Task 12, per the user's requested workflow. Earlier tasks use syntax, type, build, and focused manual smoke checks only.
- Before editing files under `web/`, read the relevant local Next.js documentation under `web/node_modules/next/dist/docs/` as required by `web/AGENTS.md`.
- Keep the system local-first. The only permitted external service is OpenAI.
- Never modify an uploaded source document. Recommendations create proposed replacement text and an audit decision only.
- Treat every authenticated account as an administrator with organization-wide read, write, review, reset, simulation, scan, and user-management capabilities. Authentication is still required.
- Preserve document owner and collaborator fields as workflow metadata only; they must not restrict access or change aggregate counts.
- Keep source evidence adjacent to impact classifications and recommendations. Every review surface must expose the regulation, requirement version, document, affected section, and evidence span.
- Do not render the strings “AI”, “AI-powered”, or provider/model names in user-facing copy.
- Use existing API error envelopes: `{ "error": { "code", "message", "details" } }`.
- All list endpoints use deterministic ordering and `{ items, total, limit, offset }` when pagination is relevant.
- Any long-running operation returns `202` with `{ job_id, resource_id? }`; the resulting job exposes named stages, counters, failure details, usage, estimated cost, and retry eligibility.
- Keep the persistent legal footer and the three default demo accounts.

## Resolved Product Decisions

- Keep React Flow. The PRD's Cytoscape/fcose choice was a default, and the user explicitly chose and approved the existing React Flow implementation.
- Keep Settings, Requirements, and Scans in navigation. They are user-requested additions to the PRD navigation.
- Keep selectable PDPF/PDPA, merger and acquisition, capital markets, energy market, and carbon-credit sample environments. Loading a scenario atomically replaces the current environment and blocks browsing until embeddings, mappings, and impacts are ready.
- Keep the expanded PDPF sample visible to all three sample accounts. This intentionally supersedes the older reference-demo expectation that Sam sees zero impact.
- Make all three default accounts administrators regardless of their historical role labels. Normalize persisted and newly created users to `role="admin"`, and make authorization depend only on successful authentication.
- Preserve boot without `OPENAI_API_KEY`: `/health` reports `openai_configured: false`, and retrieval/generation endpoints return `503`. This follows PRD sections 5.2 and 9.8; update the contradictory acceptance-criterion sentence instead of making boot fail.
- Keep the graph's current “all open impacts” mode in addition to the PRD's selected-change mode.

## Gap Summary

| Priority | Missing or incomplete capability | Completion task |
|---|---|---|
| Critical | Impact router has an accidental decorated model route and duplicate recommendation route | Task 3 |
| Critical | Change/impact detail contracts, administrator access, and affected-document drill-down are incomplete | Tasks 1, 3, and 6 |
| Critical | Scans, change analysis, and simulations still run synchronously | Tasks 4 and 5 |
| Critical | Simulation UI and change/impact detail pages do not exist | Tasks 6 and 7 |
| High | Impact classification and recommendations are deterministic rather than structured OpenAI workflows | Tasks 2 and 3 |
| High | Scan gaps G1–G4, automatic triggers, and retry/progress behavior are partial | Task 4 |
| High | Simulation add/promote/cache/export flows are partial | Tasks 5 and 7 |
| High | Document, regulation, and requirement review surfaces omit PRD metadata and actions | Task 8 |
| High | Graph lacks selected-change mode, filters, expansion, table parity, cap, and export | Task 9 |
| Medium | Dashboard, scan staleness, global job state, and account-switch refresh are incomplete | Tasks 8 and 10 |
| Medium | Official SDK retries, concurrency, usage/cost accounting, and embedding invariants are missing | Task 2 |
| Medium | `seed` and `reindex` scripts are absent; README and stale comments are inaccurate | Task 11 |
| Final gate | API, UI, acceptance, and reference-demo coverage is incomplete | Task 12 |

---

### Task 1: Add completion schema and shared change accessors

**Files:**
- Create: `api/migrations/002_prd_completion.sql`
- Create: `api/services/changes.py`
- Modify: `api/db.py`
- Modify: `api/models.py`
- Modify: `api/access.py`
- Modify: `api/routers/auth.py`
- Modify: `api/routers/users.py`

- [x] Add an `organizations` table and insert the single local organization. Add `organization_id` foreign keys to users, documents, regulations, scans, and simulations with a migration-safe default for existing rows.
- [x] Update every existing user to `role='admin'`, change account creation to persist `admin`, and return `role: "admin"` for every authenticated session.
- [x] Replace role and document-membership authorization branches in `api/access.py` with authentication-only guards. Keep the existing helper names temporarily so callers remain stable, but make every helper authorize every authenticated account.
- [x] Keep owner, reviewer, and viewer associations for attribution, routing, and display only. They must never hide a document, dependency, impact, change, job, simulation, search result, graph node, or aggregate.
- [x] Add an `impact_cache` table keyed by `(dependency_id, previous_requirement_hash, new_requirement_hash, document_chunk_hash, model)` with JSON result, prompt/completion token counts, estimated cost, and timestamps.
- [x] Add `basis_hash` and `materially_checked_at` to `mapping_passes`. The hash must combine the active requirement content and mapped document-version chunk hashes so scan gap G4 is deterministic.
- [x] Add job columns `initiated_by`, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd`, and `retry_of_job_id`; backfill system-generated jobs with a null initiator.
- [x] Add a simulation requirement snapshot table with `(simulation_id, lineage_id, operation, previous_requirement_json, proposed_requirement_json)`. This becomes the sole source of simulated change content.
- [x] Implement `get_change_requirement_pair(conn, change_row) -> tuple[dict | None, dict | None]` in `api/services/changes.py`. Real changes resolve stored requirement versions; simulated changes resolve snapshots.
- [x] Implement `change_visibility_sql(user, alias="c")` as an organization boundary only. Every authenticated account can see all real and simulated changes.
- [x] Implement `requirement_content_hash(row)` and `document_chunk_hash(row)` with stable SHA-256 canonical JSON/text serialization.
- [x] Update database health diagnostics to verify the new tables/columns without requiring OpenAI configuration.
- [x] Run `python -m compileall api` and boot the API once against a migrated copy of the local database.
- [x] Commit with message `feat: add PRD completion schema foundations`.

### Task 2: Harden the OpenAI boundary, embedding rules, and usage accounting

**Files:**
- Modify: `requirements.txt`
- Rewrite: `api/services/openai.py`
- Create: `api/services/usage.py`
- Modify: `api/services/retrieval.py`
- Modify: `api/services/mapping.py`
- Modify: `api/services/jobs.py`

- [ ] Replace direct `httpx` OpenAI calls with the official `openai` Python package. Keep one lazily constructed client and preserve the current `503 unavailable` response when the key is missing.
- [ ] Define `OpenAIResult[T]` with `value`, `raw_response`, `prompt_tokens`, `completion_tokens`, and `estimated_cost_usd`. Make embedding and structured-completion helpers return this type.
- [ ] Limit concurrent OpenAI calls with a process-wide bounded semaphore configured by `OPENAI_MAX_CONCURRENCY`, default `4`.
- [ ] Retry `429` and `5xx` responses twice with exponential backoff and jitter. Retry a schema-invalid structured response once with the validation errors appended to the repair prompt. Raise an actionable `ApiError` after exhaustion.
- [ ] Record raw failed structured responses in the owning job's `result_json.error_context`; do not store secrets or the API key.
- [ ] Centralize model prices in `api/services/usage.py` and implement `estimate_cost(model, prompt_tokens, completion_tokens)`. Unknown models record tokens and a null cost.
- [ ] Embed only non-heading chunks with normalized content length of at least 60 characters, using `section_path + "\n" + content` as the input. Keep heading rows available for outlines but out of vector search.
- [ ] Assert that every embedding matches the configured sqlite-vec dimension before insertion. On mismatch, fail the job with the detected and expected dimensions and direct the operator to `python run.py reindex --dimensions N`.
- [ ] Refactor document-first mapping to send one chunk with up to eight candidate requirements per structured-completion call. Bound retrieval candidates, isolate failed batches, and increment job usage after every successful call.
- [ ] Reactivate a previously dismissed dependency only when a new mapping pass returns a materially different evidence span or relationship; otherwise preserve the dismissal and audit history.
- [ ] Run `python -m compileall api` and manually perform one search plus one single-document mapping with the configured API key.
- [ ] Commit with message `feat: harden OpenAI retrieval and mapping services`.

### Task 3: Complete change, impact, and recommendation domain behavior

**Files:**
- Rewrite: `api/services/impact.py`
- Create: `api/services/recommendations.py`
- Rewrite: `api/routers/changes.py`
- Rewrite: `api/routers/impacts.py`
- Modify: `api/routers/recommendations.py`
- Modify: `api/access.py`

- [ ] Remove the accidental `@router.get("/{impact_id}")` decoration from `ImpactPatch` and delete the duplicate `POST /impacts/{impact_id}/recommendation` route that references an undefined handler.
- [ ] Normalize literal comparisons before model evaluation: Unicode normalization, whitespace collapse, case folding, number-word conversion for zero through twenty, unit aliases, and punctuation-insensitive equality.
- [ ] Implement a six-dependency structured impact batch returning exactly `{ dependency_id, level, reason, evidence_quote, confidence }`, where level is `none|low|medium|high`. Reject missing/duplicate dependency IDs and invalid evidence quotes.
- [ ] Store one impact row per evaluated dependency, including `none`, and read/write `impact_cache` around model calls. Return aggregate counts, cache hits, usage, and estimated cost without committing inside the service.
- [ ] Generate recommendations through a structured prompt returning `{ replacement_text, rationale, source_citations }`. Require a minimal edit grounded in the affected chunk and changed requirement; preserve the deterministic literal substitution only as an explicitly labeled fallback after model failure.
- [ ] Make `GET /changes` return title, source, effective date, operation, organization-wide affected-document count, impact counts by level, simulation state, and pagination.
- [ ] Make `GET /changes/{id}` return previous/new requirements, regulation metadata, organization-wide aggregate counts, affected documents with owners and impact levels, and analysis job state.
- [ ] Make `GET /changes/{id}/impacts` support `level`, `document_id`, `owner_id`, `status`, `limit`, and `offset`, with organization-wide counts.
- [ ] Make `GET /impacts/{id}` return change, regulation, requirement versions, dependency, document/chunk context, exact evidence offsets, recommendation, decision state, and named decision actor/time.
- [ ] Allow every authenticated account to accept, edit, reject, and resolve. Simulated recommendations still cannot be accepted until promotion.
- [ ] Make decisions idempotent and append-only in audit history while maintaining the current recommendation/impact status projection.
- [ ] Run `python -m compileall api`; inspect the generated OpenAPI document to confirm one route per method/path and manually query a PDPF high-impact detail.
- [ ] Commit with message `feat: complete change impact and recommendation contracts`.

### Task 4: Turn scans and change analysis into complete background workflows

**Files:**
- Create: `api/services/scanning.py`
- Modify: `api/services/jobs.py`
- Rewrite: `api/routers/scans.py`
- Modify: `api/routers/jobs.py`
- Modify: `api/routers/documents.py`
- Modify: `api/routers/regulations.py`
- Modify: `api/routers/requirements.py`
- Modify: `api/routers/changes.py`

- [ ] Add named job stages `queued`, `detecting_gaps`, `mapping`, `evaluating_impacts`, `finalizing`, `completed`, and `failed`; persist stage counters and usage after each batch.
- [ ] Implement exact scan gaps: G1 unmapped document/lineage pairs, G2 newly added documents requiring inheritance checks, G3 dependencies whose evidence chunk/span no longer resolves, and G4 mapping passes whose stored basis hash differs from current source hashes.
- [ ] Ensure only one scan job runs at a time. `POST /scans` accepts `scope=stale|full`; full scans require `confirmed: true`, while stale scans start with one click.
- [ ] Return `202 { scan_id, job_id }` immediately and update documents scanned, mapping pairs checked, dependencies added/reactivated, impacts created, cache hits, tokens, and cost incrementally.
- [ ] Chain a `document_added` stale scan after successful document ingestion and a `policy_change` stale scan after requirement propagation or regulation amendment detection.
- [ ] Change `POST /changes/{id}/analyse` to enqueue impact analysis and return `202 { change_id, job_id }`. Duplicate requests return the active job rather than starting a second analysis.
- [ ] Add `POST /jobs/{id}/retry`. Any authenticated account may retry a failed job; copy the original job input and set `retry_of_job_id`.
- [ ] Make user-initiated and system jobs visible to every authenticated account with complete resource counts.
- [ ] Make all automatic triggers transactional: source persistence commits first, then job creation; a job-creation failure leaves an actionable failed job rather than rolling back the uploaded source.
- [ ] Run `python -m compileall api` and manually verify that uploading one document returns an ingestion job that is followed by a scan job.
- [ ] Commit with message `feat: run scans and impact analysis as background jobs`.

### Task 5: Complete simulations, including add operations and promotion

**Files:**
- Create: `api/services/simulations.py`
- Rewrite: `api/routers/simulations.py`
- Modify: `api/services/mapping.py`
- Modify: `api/services/impact.py`
- Modify: `api/services/retrieval.py`

- [ ] Persist immutable previous/proposed snapshots for every simulation operation: modify, remove, and add. Do not require a real lineage ID for an add operation before promotion.
- [ ] Make `POST /simulations` validate that the selected regulation/requirement exists and return the created draft with estimate inputs.
- [ ] Make `POST /simulations/estimate` return organization-wide document/dependency counts, estimated model batches/tokens/cost, and cache-hit count using actual impact-cache keys.
- [ ] Make `POST /simulations/{id}/run` enqueue a job and return `202 { simulation_id, job_id }`. Use existing dependencies for modify/remove; for add, retrieve candidate chunks and create simulation-scoped ephemeral dependencies without writing real dependency rows.
- [ ] Make simulation list/detail responses include status, operation, creator, requirement snapshots, aggregate impact counts, affected document/owner summaries, usage, and job state.
- [ ] Allow every authenticated account to view, run, discard, and promote any simulation. Preserve creator identity for attribution only.
- [ ] Implement discard as a terminal state that retains the audit record but deletes ephemeral simulation dependencies and impacts.
- [ ] Implement promotion for all operations in one transaction: create the real requirement version/lineage as needed, create a real change, embed new requirement content, convert valid ephemeral dependencies, copy simulation impacts without re-running the model, and mark the simulation promoted.
- [ ] Trigger a policy-change scan after promotion to catch corpus changes made since the simulation run.
- [ ] Run `python -m compileall api` and manually run one modify and one add simulation through promotion.
- [ ] Commit with message `feat: complete simulation lifecycle and promotion`.

### Task 6: Build the change and impact review pages

**Files:**
- Create: `web/src/app/(app)/changes/[id]/page.tsx`
- Create: `web/src/app/(app)/impacts/[id]/page.tsx`
- Create: `web/src/components/change-detail-page.tsx`
- Create: `web/src/components/impact-review-page.tsx`
- Create: `web/src/components/evidence-panel.tsx`
- Create: `web/src/components/job-progress.tsx`
- Modify: `web/src/components/changes-page.tsx`
- Modify: `web/src/components/insights-page.tsx`

- [ ] Define frontend response types matching the completed change, impact, recommendation, and job contracts; do not use untyped record access for domain fields.
- [ ] Link every change-list and dashboard change item to `/changes/[id]`. Show operation, source, effective date, affected-document count, per-level impact badges, and analysis state.
- [ ] Build change detail with previous/new requirement comparison, source metadata, per-level totals, affected-document table, owner names, filters, and links to individual impacts.
- [ ] Build impact detail with regulation and requirement evidence directly above the affected document chunk. Highlight the exact evidence offsets and provide a fallback highlighted quote when offsets are unavailable.
- [ ] Render current text and proposed replacement as an accessible diff. Provide Generate, Accept, Edit and accept, Reject, and Resolve actions according to capability flags returned by the API.
- [ ] Display the recorded decision, named actor, timestamp, rationale, and immutable audit trail. Disable accept for simulations with explanatory copy.
- [ ] Use `job-progress.tsx` for analysis/generation state: named stage, completed/total counters, usage/cost when available, failure message, and retry action. Never use a bare indefinite spinner for a background job.
- [ ] Add empty, loading, not-found, unauthenticated, and failed-job states using the shared page format already used by Documents and Regulations.
- [ ] Run `npm run lint` and `npm run build` from `web/`; manually traverse change → affected document → impact → highlighted evidence.
- [ ] Commit with message `feat: add change and impact review workspace`.

### Task 7: Build the simulation workspace and requirement what-if flow

**Files:**
- Replace: `web/src/app/(app)/simulations/page.tsx`
- Create: `web/src/app/(app)/simulations/[id]/page.tsx`
- Create: `web/src/components/simulations-page.tsx`
- Create: `web/src/components/simulation-workspace.tsx`
- Create: `web/src/components/simulation-dialog.tsx`
- Modify: `web/src/components/requirement-detail.tsx`
- Modify: `web/src/components/app-nav.tsx`

- [ ] Replace `NotBuiltYet` with a list of drafts, running simulations, completed simulations, and promoted/discarded history.
- [ ] Add “What if” to requirement detail and “New hypothetical requirement” to the simulation list. Support modify, remove, and add with an explicit effective-date field.
- [ ] Show the estimate before run: organization-wide documents, dependency candidates, cache hits, model batches, estimated tokens, and estimated cost. Require one confirmation only when estimated cost exceeds the configured threshold.
- [ ] Block result browsing while the simulation job runs and display named progress stages. On completion, open the workspace automatically.
- [ ] Add a persistent amber “Simulation — no files changed” band to every simulation result page.
- [ ] Reuse change/impact review components in read-only simulation mode. Preserve selected impact/document filters in the URL.
- [ ] Add Promote and Discard actions with status-aware capability checks. Promotion requires one explicit confirmation naming the resulting real change; discard requires no second confirmation.
- [ ] Add client-side Markdown export containing scenario metadata, proposed requirement, impact totals, all affected documents and owners, evidence quotes, and recommendation text.
- [ ] Add Simulations as a secondary item under Changes without removing user-requested navigation items.
- [ ] Run `npm run lint` and `npm run build`; manually complete one requirement what-if and export the result.
- [ ] Commit with message `feat: add simulation workspace and what-if flow`.

### Task 8: Complete document, regulation, requirement, search, and session UX

**Files:**
- Modify: `api/routers/documents.py`
- Modify: `api/routers/regulations.py`
- Modify: `api/routers/requirements.py`
- Modify: `api/routers/search.py`
- Modify: `web/src/components/documents-page.tsx`
- Modify: `web/src/components/document-detail.tsx`
- Modify: `web/src/components/regulation-detail.tsx`
- Modify: `web/src/components/requirement-detail.tsx`
- Modify: `web/src/components/search-page.tsx`
- Modify: `web/src/components/session-provider.tsx`
- Create: `web/src/lib/use-session-query.ts`

- [ ] Return complete document-list fields: current version, owner, collaborators, dependency count, open impact count, last checked, ingestion/scan status, and retryable job state.
- [ ] Let uploaders assign owner, reviewers, and viewers per upload batch as workflow metadata. Show one row per file with name, type, progress, failure reason, retry, and resulting scan summary.
- [ ] Add document outline navigation, inline dependency underlines, evidence hover cards, “Only linked” filter, Coverage tab, open-impact badges, and “View in graph.” Preserve PDF rendering and DOCX/TXT text preview.
- [ ] Add regulation Overview, Requirements, and Changes tabs. Link requirements to dependency lists and changes to change detail; keep the source PDF visible.
- [ ] Add requirement version selector/history, correction dialog, mapping coverage, affected-document owner columns, highlighted evidence, dependency dismissal with rationale, and the Task 7 What-if action.
- [ ] Make search results deep-link to regulation requirements and exact document chunks. Pass evidence offsets in the URL and highlight the matching snippet after navigation.
- [ ] Return organization-wide result totals by scope. Owner/collaborator filters may narrow results only when the user explicitly selects them.
- [ ] Add a session revision in `session-provider.tsx`. `use-session-query` must refetch on account switch and abort stale requests so every open page updates without a full browser reload.
- [ ] Verify all modified pages retain the existing max-width, spacing, headings, card/table styles, footer position, and responsive behavior.
- [ ] Run `npm run lint` and `npm run build`; manually switch among all three accounts while document, search, and change pages are open and confirm identical access and administrator controls.
- [ ] Commit with message `feat: complete source review and organization-wide search UX`.

### Task 9: Finish the interactive dependency graph

**Files:**
- Modify: `api/routers/graph.py`
- Modify: `web/src/components/dependency-graph.tsx`
- Create: `web/src/components/graph-filters.tsx`
- Create: `web/src/components/graph-table.tsx`

- [ ] Extend `GET /graph` with `change_id`, `simulation_id`, `owner_id`, `regulation_id`, `impact_level`, `min_confidence`, `my_documents`, `expanded_document_ids`, and `limit` parameters.
- [ ] Return regulation, requirement, document, and optionally section nodes; dependency and impact edges; affected/open state; owner metadata; organization-wide aggregate counts; and truncated count. Remove permission-hidden graph behavior.
- [ ] Support three explicit modes: all dependencies, all open impacts, and one selected change/simulation. Keep every affected node red in impact modes and use accessible shape/icon differences in addition to color.
- [ ] Default documents to collapsed nodes, expand sections on double-click, preserve pan/zoom/selection state, and cap rendered nodes at 400 with a clear refine-filters prompt.
- [ ] Add owner, regulation, impact level, confidence, and My documents filters. Filters must update both graph and table from the same response object.
- [ ] Show node details on click and dependency evidence on edge hover/click. Document details include owner, affected policies, impact levels, and links to exact highlighted portions.
- [ ] Build a table view with exact graph parity and keyboard-accessible selection. Toggling views must preserve filters and selected item.
- [ ] Add PNG export of the current viewport with legend and active-filter summary. Add print styles for the table view.
- [ ] Run `npm run lint` and `npm run build`; manually verify pan, zoom, filters, section expansion, highlighted affected nodes, deep links, table parity, and export.
- [ ] Commit with message `feat: complete dependency graph exploration`.

### Task 10: Complete dashboard, scan UI, and global job visibility

**Files:**
- Modify: `api/routers/dashboard.py`
- Modify: `web/src/components/insights-page.tsx`
- Modify: `web/src/components/scans-page.tsx`
- Modify: `web/src/components/app-header.tsx`
- Create: `web/src/components/global-job-status.tsx`

- [ ] Return organization-wide dashboard totals for documents, active regulations/requirements, dependencies, open impacts by level, recent changes, stale scan gaps, and active/failed jobs.
- [ ] Add attention queues for high impacts, failed ingestion/scan jobs, unresolved mapping gaps, and recent changes, each linked to the exact review surface.
- [ ] Add organization-wide source and impact-level breakdowns.
- [ ] Replace the Scans page's synchronous state with job progress, counters, tokens/cost, named failure, retry, stale/full controls, and full-scan cost confirmation.
- [ ] Add a header Scan indicator that shows Current, Stale, or Running and opens the Scans page. Poll only while a job is active; otherwise refresh on session revision and page focus.
- [ ] Add global job status for ingestion, scans, impact analysis, and simulations. A completed job links to its created resource; a failed job exposes retry when authorized.
- [ ] Preserve the existing Settings reset/sample loader behavior and do not allow navigation until a sample environment's blocking load completes.
- [ ] Run `npm run lint` and `npm run build`; manually validate that all three accounts receive the same administrator dashboard, controls, and totals.
- [ ] Commit with message `feat: complete dashboard scans and job feedback`.

### Task 11: Add runtime recovery commands and accurate operator documentation

**Files:**
- Create: `scripts/seed_demo.py`
- Create: `scripts/reindex.py`
- Modify: `run.py`
- Rewrite: `README.md`
- Modify: `PRD.md`
- Modify: `api/db.py`
- Modify: `api/models.py`
- Modify: `api/errors.py`
- Modify: `api/routers/*.py` where stale wave comments remain
- Modify: `web/src/app/globals.css`

- [ ] Implement `python run.py seed --scenario pdpf|merger-acquisition|capital-markets|energy-market|carbon-credit`. Reuse the same environment service as Settings, require confirmation only when invoked interactively against non-empty data, and report final entity/embedding/dependency/impact counts.
- [ ] Implement `python run.py reindex [--dimensions N]`. Rebuild FTS and vector mirrors transactionally from canonical chunks/requirements, reject dimensions that do not match newly generated vectors, and leave the old mirrors intact on failure.
- [ ] Make `run.py` return non-zero exit codes and actionable messages for configuration, migration, seed, reindex, server, and test failures.
- [ ] Rewrite README with prerequisites, install/run commands, default accounts, sample scenarios, upload/scan/change/review/simulation workflow, reset/recovery commands, OpenAI data-boundary disclosure, scanned-PDF limitation, no-monitoring statement, and legal disclaimer.
- [ ] Document that all accounts are administrators in this local product build and that owner/reviewer/viewer assignments are attribution metadata, not security boundaries.
- [ ] Correct the PRD acceptance-criterion contradiction so missing OpenAI configuration permits boot and produces an unconfigured health state plus endpoint-level `503` errors.
- [ ] Remove obsolete “later wave”, “not built”, and `501` comments/types when the relevant feature now exists.
- [ ] Add print styles for evidence, impact, simulation export preview, and graph table while suppressing navigation and interactive controls.
- [ ] Run `python -m compileall api scripts run.py`, `python run.py --help`, `python run.py seed --help`, `python run.py reindex --help`, `npm run lint`, and `npm run build`.
- [ ] Commit with message `docs: add recovery commands and complete operator guide`.

### Task 12: Add the consolidated tests and run the final acceptance gate

**Files:**
- Create: `tests/test_changes_impacts.py`
- Create: `tests/test_recommendations.py`
- Create: `tests/test_scans.py`
- Create: `tests/test_simulations.py`
- Create: `tests/test_graph.py`
- Create: `tests/test_jobs.py`
- Create: `tests/test_runtime_commands.py`
- Create: `tests/test_reference_demo.py`
- Create: `tests/test_openai_resilience.py`
- Create: `web/playwright.config.ts`
- Create: `web/e2e/review-flow.spec.ts`
- Create: `web/e2e/accounts-and-settings.spec.ts`
- Modify: `web/package.json`
- Modify: existing tests where completed contracts intentionally supersede partial behavior

- [ ] Cover normalized literal comparison, all four impact levels, six-item batches, cache hits, malformed structured-output repair, retry exhaustion, token/cost accounting, and evidence validation.
- [ ] Cover every change/impact/recommendation route, including organization-wide counts, exact evidence detail, decisions by every default account, actor/time audit data, duplicate-route regression, and simulated accept refusal.
- [ ] Cover scan G1–G4 detection, stale/full behavior, single-running-scan enforcement, automatic upload/change triggers, incremental counters, failures, and retry authorization.
- [ ] Cover simulation modify/remove/add, estimate/cache counts, background run, organization-wide access, discard, promotion, copied impacts, and post-promotion scan.
- [ ] Cover graph modes, filters, expansion, 400-node cap, organization-wide data, affected-node state, and table response parity.
- [ ] Cover organization-wide job access, active-job deduplication, stage progress, usage, failure details, retry by every account, and retry lineage.
- [ ] Cover `seed` and `reindex` success plus rollback-on-failure. Confirm the canonical database remains intact after a failed mirror rebuild.
- [ ] Update the reference-demo test to assert the expanded PDPF environment's known requirements, changes, dependencies, impacts, owner names, identical all-three-account outcomes, and full administrator capabilities for each account.
- [ ] Add Playwright flows for upload → job → scan → change → impact → evidence → decision; simulation → estimate → run → export/promote; graph drill-down; account switching; Settings scenario replacement; reset; and footer placement.
- [ ] Run the complete backend suite with `python run.py test`.
- [ ] Run `npm run lint`, `npm run build`, and `npm run test:e2e` from `web/`.
- [ ] Run the live OpenAI integration subset with the configured key and record model names, token use, estimated cost, and any skipped cases in the release notes.
- [ ] Search built UI assets for prohibited user-facing terms and obsolete unavailable/not-built copy.
- [ ] Execute PRD acceptance criteria 1–64 against a clean database, recording pass/fail evidence. All failures must be fixed and the full affected suite rerun before completion.
- [ ] Commit with message `test: cover completed PRD workflows and acceptance demo`.

## Completion Definition

The plan is complete only when every checkbox is satisfied, all corrected PRD acceptance criteria pass, no production route returns placeholder behavior, the UI offers a navigable path to every implemented workflow, every authenticated account has identical administrator access, and a clean scenario load produces searchable sources, mappings, changes, impacts, graph state, and reviewable evidence before browsing is enabled.
