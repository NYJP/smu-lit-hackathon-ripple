# Ripple — four product areas: state of play and remaining phases

Working doc for completing four areas: the dependency graph, a personalized
dashboard, the remediation workflow, and one unified severity/status system.

**Phases 1–6 are done and verified.**

Phase 3's backend and screens are built and exercised end to end against the
real PDPF corpus. Its visual-consistency debt was paid in Phase 4 by migrating
the review queue and detail screen onto the new shared workspace primitives.

---

## 0. Read this first — environment and landmines

These cost real time to rediscover.

| Thing | Detail |
|---|---|
| **Python** | `python` on PATH is **3.10.4**. The venv is 3.12. Always use `py -3.12 run.py …` or `.\.venv\Scripts\python.exe` directly. |
| **OpenAI key** | `.env` holds an **OpenRouter** key (`sk-or-v1-…`). `OPENAI_BASE_URL` is set to `https://openrouter.ai/api/v1`. OpenRouter supports embeddings (1536 dims) and strict `json_schema`, and resolves bare `gpt-5` to `openai/gpt-5`. Do not "fix" the base URL back to api.openai.com. |
| **Cost** | Embeddings are ~$0.0000002/call. One `gpt-5` structured extraction is ~$0.005. `RIPPLE_BULK_MODEL` is the knob if a phase gets expensive. |
| **`run.py`** | Has an uncommitted fix: `find_npm()` prefers `npm.cmd` on Windows. Python 3.12's `shutil.which("npm")` returns the extensionless POSIX script, which `subprocess` can't exec (`WinError 193`). Do not revert. |
| **Seeding** | `run.py seed` is dead (`scripts/seed_demo.py` does not exist). Real path: `POST /api/v1/settings/sample-environment {"scenario_id":"pdpf"}`, or the `/settings` page. It resets the DB **and re-seeds users with new ids**, so any held session cookie dies — re-login after loading. |
| **Access control** | `api/access.py` is entirely permissive by deliberate design (commit `ec59e33`): every account is admin and sees everything. Personalization must be **relevance only** — it ranks and explains, it never gates. Do not reinstate scoping. |
| **Next.js 16** | `web/AGENTS.md` warns the APIs differ from training data. Read `web/node_modules/next/dist/docs/` before writing route/router code. |
| **Uvicorn `--reload` lies** | On this Windows box WatchFiles logs `Reloading...` but the worker frequently does **not** restart, so you test old code and chase a phantom bug. Confirm with `grep -c "Started server process" <devlog>` — the count must increase. Killing it can also strand a **multiprocessing worker holding :8000** whose parent PID no longer exists, so a new server silently fails to bind (`Errno 10048`) and you keep talking to the dead one. Find the real holder with `Get-CimInstance Win32_Process -Filter "Name like '%python%'"` and `Stop-Process` that child. |
| **Never blanket-kill node** | `taskkill //F //IM node.exe //T` also kills the **Playwright MCP server**, which cannot reconnect for the rest of the session. Kill by PID, or accept losing browser verification. |
| **Lint baseline** | `npm run lint` is **not** clean at HEAD: 1 error (`scans-page.tsx`, `react-hooks/set-state-in-effect`) and 1 warning (`settings-page.tsx`). Compare against 1 error + 1 warning, not zero. The house workaround for that rule is `queueMicrotask(() => void load())` inside the effect. |
| **Ordering audit rows** | Order event tables by `rowid`, never by `id`. `id` is a random `uuid4`, and several acts routinely land in one transaction with timestamps identical to the microsecond, so `ORDER BY …, id` shuffles them non-deterministically. This caused a 25%-of-runs flaky test before it was found. |

### Test baseline — memorise this

```
py -3.12 run.py test    ->  95 passed, 17 failed     (91 passed before Phase 4)
```

**The 17 failures are pre-existing and out of scope.** They assert the
pre-`ec59e33` per-user scoping model that was deliberately deleted. Before/after
any change, compare against 17 — do not try to fix them, and do not assume a new
failure is one of them without checking the name.

The 17: 5 in `test_access.py`, 5 in `test_accounts.py`, 1 in `test_ingestion.py`,
3 in `test_mapping.py`, 2 in `test_retrieval.py`, 1 in `test_scoping_discipline.py`.

Frontend now has Playwright and axe coverage: `web/playwright.config.ts`,
`web/e2e/dashboard.spec.ts`, and `npm run test:e2e`. The Phase 4 suite covers
account switching/refetch, relevance reasons, narrow-width overflow, axe, and
the shared review surfaces. Phase 5 must extend this runner for graph click vs
drag, URL restoration, table parity, performance, and reduced motion.

### Decisions already approved by the user — do not relitigate

1. **Graph library: `react-force-graph-2d`.** Canvas + d3-force. This departs
   from PRD §10.5 (Cytoscape+fcose) and from the older plan doc's "user-approved
   React Flow" note; the departure is intentional because fcose is a one-shot
   layout, not live physics. Amend both docs when Phase 5 lands.
2. **`critical` is derived, never stored.** Rule: stored `high` + confidence
   ≥ 0.9 + effective_date within 30 days (or already passed). An earlier draft
   also escalated on `change_type`; that marked **100%** of the corpus critical
   and was removed. `tests/test_severity.py::test_change_type_alone_never_escalates`
   guards against re-adding it.
3. **Personalization is relevance-only.** All-admin access stays.
4. **"Approve" never edits the document.** It writes `document_patches`; the
   reader renders an overlay. `document_chunks.content` and the file on disk are
   untouched. This is the single most important invariant in the project.

---

## 1. What Phases 1 and 2 delivered

*(Phase 3's delivery record is in section 2 below.)*

### Phase 1 — severity + status foundation

- **`api/migrations/008_workflow_and_personalization.sql`**
  - Rebuilt `impacts` to widen the `review_status` CHECK to the 9-value
    workflow, backfilling `open → detected`. SQLite cannot ALTER a CHECK, so
    this is the 12-step rebuild. **`recommendations` and `impact_review_events`
    cascade-delete from `impacts`**, so `PRAGMA foreign_keys=OFF` around the
    DROP is load-bearing — verified empirically that `executescript` commits
    first, so the pragma takes effect. Validated on a copy of the live DB:
    counts preserved, zero FK violations.
  - Added `impacts.due_date`, `impacts.updated_at`.
  - New tables: `teams`, `team_members`, `document_teams`, `follows`,
    `notifications`, `document_patches`, `audit_events`.
  - `UNIQUE INDEX` on `recommendations(impact_id)` (three call sites already
    assumed one-per-impact).
- **`api/services/severity.py`** — `derive_severity()`, `SEVERITY_ORDER`,
  `max_severity()`. The only place severity is ranked. `graph.py`'s inline
  `rank` dict is gone.
- **`api/services/workflow.py`** — `ALLOWED_TRANSITIONS`, `transition()`,
  `supersede_open_impacts()`, `open_status_sql()`. Validates, writes
  `impact_review_events` + `audit_events`, sets `resolved_by`/`resolved_at`,
  notifies stakeholders (owner/assignee/collaborators — **not** all admins).
  Does not commit; the router owns the transaction.
- Routed through it: `PATCH /impacts/{id}`, `PATCH /recommendations/{id}`,
  `POST /impacts/{id}/recommendation` (which advances to `patch_proposed`, and
  this is what makes a later Accept legal — `resolved` is deliberately not
  reachable straight from `detected`).
- `effective_date` now flows into seeded changes via `effective_in_days`
  **offsets** in `scenarios.json` (absolute dates would drift across the 30-day
  window and silently change what the demo shows).
- Tests: `tests/test_severity.py`, `tests/test_workflow.py` (36 tests).

### Phase 2 — design tokens and shared components

- **`web/src/app/globals.css`** — `--impact-critical`, `--status-*`, `--sim`,
  both themes. Darkened `--impact-medium` for AA contrast; `--impact-low` moved
  from grey to slate-blue. Lightness descends critical→high→medium so the scale
  survives greyscale.
- **`web/src/lib/types.ts`** — real domain unions (`Severity`, `ReviewStatus`,
  `Impact`, `GraphNode`, …), replacing ~30 duplicated inline interfaces.
- **`web/src/lib/severity.ts`** — client mirror: ordering, labels, glyphs,
  `confidenceLabel()`, `needsUrgentReview()`. Never derives severity.
- **`web/src/components/ui/severity-badge.tsx`** — `SeverityBadge`,
  `SeverityRail`, `SeverityCounts`. Falls back to `none` rather than rendering
  a blank pill.
- **`web/src/components/ui/status-badge.tsx`** — `StatusBadge`,
  `SimulatedBadge`, `SourceBadge`.
- **`web/src/components/ui/confidence-meter.tsx`** — shows the "Urgent review"
  chip for severe-but-thin findings instead of implying a confirmed breach.
- Backend now returns `severity` + `review_status_label` from `/impacts`,
  `/changes`, `/changes/{id}/impacts`, `/dashboard`, `/documents` (new
  `max_severity` via batched `_max_open_severity`), `/graph`.
- Call sites converted: `change-detail-page`, `document-detail-page`,
  `documents-page`, `insights-page`, `dependency-graph`.

**Bugs fixed in passing:** `document-detail-page.tsx` called
`/impacts?review_status=open` which 422'd after Phase 1 (now `open_only=true`);
the dashboard rendered blank badges because it reads `/dashboard`, not
`/changes`.

### Visual consistency contract for Phases 3–6

The remaining screens must feel like one polished legal-intelligence workspace,
not four independently designed features. Preserve the existing palette,
severity tokens, status tokens, typography choices, theme behavior, component
library, and navigation shell. **Do not introduce a new dashboard palette or
page-specific colour system.** New visual work must consume the existing design
tokens and semantic severity/status components delivered in Phase 2.

The visual code for all remaining work is:

> Professional, clean, calm, intuitive, and visually interesting. Combine
> generous spacing, soft shadows, rounded corners, clean typography, subtle
> icons, and small purposeful animations. Maintain enough information density
> for legal work without making screens feel cramped or spreadsheet-like.

Translate that direction into executable implementation rules:

1. **Create or consolidate shared layout primitives before styling individual
   pages.** In `web/src/components/ui/` or the existing shared-component
   location, provide reusable primitives for `PageHeader`, `SectionHeader`,
   `Surface`/`Card`, `MetricCard`, `EmptyState`, `LoadingSkeleton`, and
   `InlineAction`. Reuse current shadcn/ui foundations rather than creating a
   competing component layer.
2. **Standardize page geometry.** Use the existing application-shell content
   width and spacing scale. Define one responsive page gutter, one section-gap
   rhythm, and a small approved set of card paddings. Dashboard, review, graph,
   simulation, and document pages must align their headers and major content
   edges.
3. **Standardize surfaces.** Cards and panels should use the same existing
   border token, radius family, and restrained shadow levels. Reserve the more
   elevated surface for overlays, inspectors, menus, and active work—not every
   container. Avoid hard-coded `shadow-*`, radius, border, or background values
   repeated across feature components when a shared variant can express them.
4. **Standardize typography.** Define and reuse clear styles for page greeting,
   page title, section title, metric value, supporting copy, metadata, and
   labels. Keep paragraphs short, use tabular numerals for counts/dates, and
   avoid arbitrary font sizes or weights inside feature components.
5. **Use one icon language.** Reuse the installed icon library, with consistent
   sizes and stroke weight. Icons clarify document type, change, review,
   ownership, due date, and action; they are not decoration and never replace a
   text label for an unfamiliar action.
6. **Create shared motion utilities.** Use short, restrained transitions for
   card entry, feed updates, inspector opening, status changes, hover/focus, and
   graph selection. Define common duration/easing classes or variants rather
   than ad hoc animations. No constant card movement, excessive bounce, or
   animation that delays work. Under `prefers-reduced-motion`, remove
   non-essential movement while preserving state changes.
7. **Make interaction states consistent.** Hover, focus, active, selected,
   disabled, loading, error, and success states must behave the same across
   cards, rows, filters, buttons, and inspectors. Preserve visible keyboard
   focus and do not communicate state through animation or colour alone.
8. **Use visual interest through hierarchy, not decoration.** Vary panel size,
   grouping, whitespace, metric emphasis, progress, timelines, and the graph.
   Avoid decorative gradients, oversized illustrations, glass effects, and
   one-off flourishes unless an equivalent pattern already exists in the site.
9. **Propagate, then remove duplication.** When a new dashboard or review
   pattern proves useful, move it into the shared primitive and replace
   equivalent one-off markup in the other Phase 3–6 screens. Do not leave two
   visually different versions of the same card, empty state, heading, status
   row, or action bar.
10. **Perform a visual consistency pass after each phase.** Compare the new
    screen with the application shell and the previously completed screens at
    desktop and narrow widths. Check aligned edges, spacing rhythm, surface
    treatment, type hierarchy, icon sizing, interaction states, overflow, and
    reduced motion before calling the phase complete.

This contract applies to the remediation pages in Phase 3, the dashboard in
Phase 4, graph controls and inspector in Phase 5, and simulation summary and
clause rail in Phase 6. The force graph itself may use its domain-specific node
rendering, but all surrounding controls, panels, filters, legends, dialogs, and
empty/loading/error states must use the same site-wide primitives.

---

## 2. Phase 3 — remediation workflow (Area 3) — **DONE**

The most complete backend surface in the repo was **unreachable** — `GET/PATCH
/api/v1/impacts/{id}` returned a full review payload that nothing rendered.
It now has both screens, and the approve path is proven end to end.

### Backend, as built

- **`api/services/patching.py`** (new) — `apply_patch`, `revert_patch`,
  `patch_for_impact`, `patches_for_document`, `resolve_span`.
  - `apply_patch` issues exactly **two** writes: the `document_patches` row and
    its `audit_events` record. Never `document_chunks`, never the file.
  - Spans are always resolved to concrete `(char_start, char_end)` — a null
    span would leave the reader guessing which words were replaced. Precedence:
    the impact's own conflict span → locate the recommendation's `current_text`
    → the whole chunk.
  - Overlapping applied patches on one chunk are refused (409); two overlays
    over the same words cannot both render. Re-approving the *same* impact
    reverts its own earlier patch instead of stacking.
- **`api/services/clauses.py`** (new) — `clause_label` and `clause_excerpt`.
  Only ~9 of 31 chunks in a real corpus carry a parsed `section_path`, so the
  queue titled every row "Section unavailable". The heading is still present as
  text *inside* the chunk, and a chunk usually spans several numbered sections
  — so the label is the nearest numbered heading **at or above the affected
  span**, not the chunk's first line. Derived labels are verbatim document
  lines (`Ctrl-F`-able); parsed metadata always wins. Returned as
  `clause_label` / `clause_excerpt` by `/impacts`, `/impacts/{id}` (header and
  siblings) and `/documents/{id}` chunks, so no screen can name a passage
  differently. **The UI must never render `section_path` directly.**
- **`api/services/recommendations.decide()`** (new) — the single code path for
  "a person decided about this wording": the append-only decision row, the
  patch an acceptance produces, and the impact's transition. **Both**
  `PATCH /recommendations/{id}` and `POST /impacts/{id}/patch` route through
  it, so neither can reach `resolved` without recording the wording accepted.
  Rejecting after an acceptance withdraws the overlay.
- **`POST /api/v1/impacts/{id}/patch`** — the Approve action. Refuses without a
  recommendation (409) and for `source='simulation'` (409). Records `accepted`
  vs `edited` by comparing the submitted text to the suggestion.
- **`DELETE /api/v1/impacts/{id}/patch`** — withdraw and reopen to `in_review`.
  The patch row is kept and marked `reverted`; both acts stay in the record.
- **`GET /impacts/{id}`** gained `patch`, `audit_trail` (merged impact +
  patch `audit_events`), `other_open_impacts` (drives "next affected clause"),
  and `capabilities.approve_patch` / `.revert_patch`.
- **`GET /documents/{id}`** gained `patches[]`, and per chunk `severity`,
  `impacts[]`, `patches[]`, plus `document.max_severity` / `.patch_count`.
  Open impacts are grouped in one batched query, not per chunk.

### Frontend, as built

`web/src/lib/diff.ts` (LCS word-level redline + `splitSpan`), review types in
`lib/types.ts`, `web/src/components/review/` — `impacts-queue-page.tsx`,
`review-page.tsx`, `requirement-diff.tsx`, `clause-evidence.tsx`,
`redline-editor.tsx`, `decision-bar.tsx`, `audit-timeline.tsx` — plus the two
routes under `app/(app)/impacts/` and the `Impacts` nav entry.

The queue groups by document (the unit of work is a document, not a clause).
The decision bar only offers moves in `capabilities.allowed_transitions`, and
names the reason when Approve is unavailable.

### Bugs found and fixed while building it

1. **`POST /impacts/{id}/recommendation` 422'd on every newly detected impact.**
   It transitioned straight to `patch_proposed`, which is only reachable from
   `in_review` — so the review screen's *first* button failed every time. It
   now walks `detected → in_review → patch_proposed`, recording both steps,
   which is the honest record as well as the legal one. Pinned by
   `test_generating_wording_walks_a_detected_impact_through_review`.
2. **Audit ordering was non-deterministic** — see the landmines table. Fixed to
   `rowid` in four queries across `impacts.py` and `recommendations.py`.
3. `value` + `value_unit` rendered as "5 years years"; extraction stores the
   unit in both fields.
4. **Every review-queue row was titled "Section unavailable"** (user-reported).
   Fixed by `api/services/clauses.py` above; `tests/test_clauses.py` pins that
   a label is never the word "unavailable" and never names the wrong section of
   a multi-section chunk.

### Verified

`tests/test_patching.py` (16 tests, including the SQL-trace assertion that
`apply_patch` never issues a statement touching `document_chunks`) and
`tests/test_clauses.py` (14). Suite is at **17 failed / 91 passed**; the
patching set was checked stable over 8 consecutive runs.

Live end-to-end against the real PDPF corpus and a real 37KB `.docx`: generated
wording with a real `gpt-5` call, approved, then reverted and re-approved. The
chunk content SHA and the file SHA were **byte-identical throughout**, and the
overlay composed back to the corrected sentence.

### Phase 3 visual debt — paid in Phase 4

`impacts-queue-page.tsx` and `review-page.tsx` now use the shared `PageFrame`,
`PageHeader`, `Surface`, `EmptyState`, and `LoadingSkeleton` primitives created
in Phase 4. Their one-off page headers, empty box, and loading spinners are gone.
Nothing else in Phase 3 is outstanding.

---

## 3. Phase 4 — personalized dashboard (Area 2) — **DONE**

### Delivery record

- `api/services/relevance.py` implements owner → assignee → collaborator →
  team → follow precedence. Every requested document receives a display reason;
  documents without a personal signal receive the workspace-monitoring reason.
  This service never participates in authorization.
- `/dashboard?scope=me|all` now returns the five cards, ranked impact feed,
  relevance reason/weight, severity/confidence/due date/next action, a capped
  graph preview, recent resolutions, team activity, and last-scan time.
- Added `/teams`, `/documents/{id}/teams`, `/follows`, and `/notifications`
  endpoints in `api/routers/personalization.py`.
- PDPF seeding now creates Data Protection and Incident Response teams,
  document-team assignments, follows, and impact assignees, and verifies these
  additions before committing the sample environment.
- Shared primitives live in `web/src/components/ui/workspace.tsx`:
  `PageFrame`, `PageHeader`, `SectionHeader`, `Surface`, `MetricCard`,
  `EmptyState`, `LoadingSkeleton`, and `InlineAction`. Reduced-motion behavior
  and consistent keyboard focus are defined globally.
- `web/src/components/dashboard/` owns the new dashboard. The active session
  supplies the greeting, and `session-context.tsx` exposes a revision counter so
  account switching refetches the page without navigation or a full reload.
- The app header now contains horizontal navigation overflow at narrow widths,
  and account switching closes its menu correctly.
- Axe found marginal contrast failures in the existing high/attention tokens;
  their light-theme values were darkened. The narrow dashboard now passes axe.
- Tests: `tests/test_relevance.py`, `tests/test_dashboard.py`, and
  `web/e2e/dashboard.spec.ts`. Verified at **95 passed / 17 failed**, clean
  TypeScript and production build, the unchanged lint baseline, and three
  passing Chromium E2E tests.

The implementation specification below is retained as the acceptance record.

### Backend

- **`api/services/relevance.py`** (new) —
  `relevance_for(conn, user_id, document_ids) -> {doc_id: {reason, weight}}`.
  Precedence: owner → assignee → collaborator → team → follow. Returns the
  display string ("You own this document.", "Assigned to your Data Protection
  team.").
- **`GET /api/v1/dashboard`** — rewrite. Add `?scope=me|all`. Return:
  - `cards{action_required, review_required, awaiting_approval, resolved_recently, documents_monitored}`
  - `feed[]` with `severity`, `confidence`, `relevance{reason,weight}`,
    `due_date`, `next_action`, `affected_clause_count`
  - `graph_preview{nodes,edges}` capped at ~40
  - keep `severity_counts` (added in Phase 2)
- Small new endpoints: `GET /teams`, `POST /documents/{id}/teams`,
  `PUT /follows`, `GET|PATCH /notifications`.
- **Seed**: add a `teams` block to `sample-environment/scenarios.json` and write
  `document_teams`, a few `follows` and a few `assigned_to` in
  `api/services/environment.py`. Add these to the `checks` dict in
  `load_sample()` so a bad seed still 500s.

### Frontend

`web/src/components/dashboard/` — `dashboard-page.tsx`, `summary-cards.tsx`,
`impact-feed.tsx`, `feed-card.tsx`, `graph-preview.tsx`, `activity-list.tsx`.
Extract `DashboardView` out of `insights-page.tsx` (leave `ChangesView` there).

The dashboard is the clearest expression of the visual consistency contract.
Build it in this order:

1. **Personal welcome header.** Render `Hi, {firstName}!` as the primary
   greeting and `Here's what's new today.` as the supporting line. Source the
   name from the active session/account rather than hard-coding it. Keep the
   header compact enough that actionable information remains above the fold.
2. **Daily overview hierarchy.** Place the most important personalized summary
   immediately beneath the greeting: what changed, what needs action, and what
   can wait. Use concise copy and clear sections instead of a uniform grid of
   equally prominent cards.
3. **Summary cards.** Render the five backend `cards{...}` values through the
   shared `MetricCard` primitive. Each card has a label, tabular count, subtle
   icon, optional supporting line, and direct destination. Use existing
   semantic status/severity components; do not assign dashboard-specific
   colours.
4. **What's new today.** Make this the primary feed section. Each `FeedCard`
   shows the change, affected document, affected-clause count, severity,
   confidence, relevance reason, due date/status, and one obvious next action.
   Keep cards scannable through spacing and type hierarchy; do not bury the
   action under hover-only controls.
5. **Secondary panels.** Place graph preview, recently resolved work, monitored
   documents/last scan, and team activity in visually quieter surfaces. Their
   relative placement should adapt responsively rather than force a crowded
   desktop grid onto narrow screens.
6. **Purposeful motion.** On initial load, allow a short stagger or fade for the
   greeting and major sections; animate count/status changes and the graph
   preview subtly. Do not replay entrance motion on routine refetches, and use
   the shared reduced-motion behavior.
7. **Responsive composition.** Preserve the reading order: greeting → urgent
   summary → What's new today → secondary context. At narrow widths, stack
   surfaces, prevent horizontal card overflow, and keep the primary action and
   severity/status information visible without hover.
8. **Shared-state coverage.** Build visually consistent skeleton, empty,
   partial-processing, error, and permission states using the shared primitives.
   With no urgent impacts, retain the greeting and replace urgency with a calm
   up-to-date summary plus monitored documents and last scan time.
9. **Cross-site propagation.** Reuse the same `PageHeader`, section spacing,
   surface, metric, icon, typography, and motion patterns on Phase 3 review
   pages, Phase 5 graph inspector/controls, and Phase 6 simulation summaries.
   If dashboard implementation introduces a better generic primitive, migrate
   existing equivalent call sites rather than keeping a dashboard-only copy.

Feed ranked by severity × relevance × due date. **Every item shows its relevance
reason.** Density per PRD §10.1 rule 9 — table-like rows, tabular numerals,
~15 visible. Build the empty / loading / processing / error / permission states;
with no urgent impacts, show monitored documents and last scan time rather than
an empty box.

**Definition of done:** every feed item carries a reason; switching accounts in
the header changes the greeting, counts, feed, graph preview, and relevance
reasons without a full reload. The dashboard uses shared primitives and contains
no new page-specific colour literals, arbitrary radius/shadow values, or bespoke
motion timings. Its desktop and narrow layouts preserve the required information
hierarchy, and reduced-motion mode remains fully understandable. Note
`session-context.tsx`'s `chooseAccount` does **not** currently refetch page data
on switch — fix that here.

---

## 4. Phase 5 — force-directed graph (Area 1, largest) — **DONE**

### Delivery record

- `GET /api/v1/graph` now supports the 250-node cap and the `seed`, severity,
  team, review-status and simulation filters. It reports truthful hidden
  document and omitted node/edge counts.
- `api/services/contributions.py::for_spans()` resolves graph authorship in one
  batched query. `tests/test_graph_api.py` covers caps, truncation, combined
  filters, simulation filtering and guards against restoring the per-edge
  lookup.
- The old React Flow component was removed. `web/src/components/graph/` now
  contains the force graph, filters, legend, inspector, parity table and
  URL-backed state hook. `GraphView` points at the new implementation.
- The canvas uses the specified charge, confidence-weighted link distance,
  collision radius and cooldown. Document type owns the stable fill; severity,
  detected changes and simulations use separate non-colour ring treatments.
- First click selects and enters local one-hop mode, a second document click
  navigates, and drag pins without selecting. Selection and filters survive
  browser history. Fetches abort when filters change.
- The graph chrome uses the Phase 4 workspace primitives and semantic tokens.
  The keyboard-accessible table exposes every returned edge and its evidence.
  Reduced-motion mode performs a synchronous warm-up rather than displaying a
  moving simulation.
- `web/e2e/graph.spec.ts` covers first/second click, drag suppression, browser
  back, filters, table equivalence, narrow layout, reduced motion and axe.

### Phase 5 verification

- `py -3.12 run.py test`: **99 passed / exactly 17 expected legacy failures**
  (the increase from 95 is the four new graph tests).
- `npx tsc --noEmit` and `npm run build`: pass.
- `npm run lint`: unchanged baseline of one error in `scans-page.tsx` and one
  warning in `settings-page.tsx`; no graph findings.
- `npm run test:e2e`: **7 passed**.
- Chromium screenshots were inspected at desktop and 390px reduced-motion
  width. The live corpus currently returns 15 nodes / 8 edges, so it cannot
  demonstrate 200+ real nodes; cap and truncation are exercised synthetically.
- The Playwright MCP browser capability was not exposed in the Phase 5 session.
  Verification used the installed Playwright Chromium runner and screenshot
  inspection instead. If the MCP is available in Phase 6, repeat the live graph
  smoke test there.
- The verification API process was stopped afterward. At handoff time `:3000`
  was still listening and `:8000` was not; check both before starting servers.

`npm i react-force-graph-2d`. Import with `dynamic(..., { ssr: false })`.

### Backend (`api/routers/graph.py`)

- Add `limit=250`, `seed=changes|mine|all`, `severity`, `team_id`,
  `review_status`, `simulation_id`.
- **Fix the N+1**: `contributions.for_span()` is called once per edge. Batch it.
- Return a real `hidden_document_count` (currently hard-coded `0`) and
  `truncated{nodes_omitted, edges_omitted}`.

### Frontend (`web/src/components/graph/`)

`force-graph.tsx`, `graph-inspector.tsx`, `graph-filters.tsx`,
`graph-legend.tsx`, `graph-table.tsx` (a11y fallback), `use-graph-state.ts`.

- **Physics**: `charge.strength(-260)`,
  `link.distance(d => 40 + 90 * (1 - d.confidence))` (confidence tightens the
  spring), `collide.radius(r + 6)`, `cooldownTicks ≈ 200` so it settles.
- **Node paint** (`nodeCanvasObject`): documents get a stable fill hashed from
  `doc_type` (10 types, fixed palette), radius `8 + 3*log2(1 + dependency_count)`,
  a type glyph, and **severity on an outer ring only — never replacing the fill**.
  Requirements are black and smaller; `changed` = red double ring; simulated =
  purple dashed ring.
- **Click vs drag**: < 4px movement and < 300ms = click. First click selects,
  reveals one-hop neighbours, dims the rest. Second click on an already-selected
  document navigates to `/documents/{id}`. A drag does neither.
- **Perf**: cap 250 nodes; memoize the transform; keep hover/selection in a ref
  so physics ticks never re-render React; `AbortController` on refetch.
- **URL state**: `?node=&mode=local|global&sim=&severity=&team=&owner=&q=`.
- Replace `dependency-graph.tsx` once at parity, then delete it and re-point
  `GraphView` in `insights-page.tsx`.

**Definition of done:** 200+ nodes interactive; click-vs-drag correct; back
button restores selection and filters; the table view is a complete alternative.

---

## 5. Phase 6 — ripple simulation + clause rail (Areas 1 and 4)

### Delivery record

- Both simulation entry points create persisted `simulation_run` jobs and return real job IDs with HTTP 202. The runner records `preparing_simulation`, `evaluating_dependencies`, `summarizing_results`, completion/failure, progress, counters, usage, results, and retry lineage.
- `api/services/simulations.py` owns immutable proposal overlays, truthful `impact_cache` estimates, and execution. Simulation run/re-run/discard never writes regulatory requirements, chunk content, dependencies, or uploaded files.
- `/simulations` and `/simulations/[id]` now provide create/edit/estimate/run/progress/ripple/summary/discard against the real API, with the shared workspace primitives and purple simulation treatment throughout. The nav entry sits after Graph.
- `use-ripple-animation.ts` sequences the purple origin pulse, travelling edge dots, target severity rings and target pulse, and settled summary. It is skippable; reduced motion applies identical final state immediately.
- `document-detail-page.tsx` now renders the 4px semantic severity rail, restrained token tint, badge, exact-span underline, server `clause_label`, severity strip, affected-only filter, previous/next navigation, and approved patch overlays without changing source content.
- `tests/test_simulations.py` adds five focused job/cache/failure/discard/invariant tests. `web/e2e/simulations.spec.ts` covers the complete simulation and clause-rail journeys, reduced motion, simulated badges, narrow overflow, and axe.

### Phase 6 verification

- `py -3.12 run.py test`: **104 passed / exactly 17 expected legacy failures**.
- `npx tsc --noEmit` and `npm run build`: pass.
- `npm run lint`: unchanged baseline of one error in `scans-page.tsx` and one warning in `settings-page.tsx`; no Phase 6 findings.
- `npm run test:e2e`: **10 passed** (all dashboard, graph, simulation, clause-rail, reduced-motion, narrow-layout, and axe journeys).
- Real Chromium PDPF exercise: temporarily selected the existing immutable PDPF-001 v1 as the lineage baseline, simulated `5 years → 7 years`, and observed the ripple reach **Customer Data SOP** and **Privacy Playbook**. The lineage pointer was restored afterward.
- Before/after SHA-256 values were identical: `regulatory_requirements` `880a5c7d960a491ed90231e5c7db32d7fc47ba5401eafaa8112bd9cc87dcebe2`; `document_chunks(id,content)` `a67fd69220bfbea30d7ce8205adf91ee6bdf63ec13b50e0197ec20be95bcdfe0`; 10 uploaded document files `1915c757a10a551fcf94f4c8996fb92427ae41e4649b934ca495991b7852b855`.
- Desktop, 390px, and 390px reduced-motion screenshots were inspected from the installed Playwright Chromium runner. **Playwright MCP browser tools were not exposed in this session's callable tool inventory**, so no MCP verification is claimed.
- The Phase 6 style audit found no raw page-specific colour utilities or arbitrary surface radius/shadow classes. Ripple timing is centralized in the global animation utilities.

### Simulation

- Move `POST /simulations/{id}/run` and `POST /requirements/{id}/simulate` off
  in-request execution onto `jobs.run_job` so they return a real `job_id`
  (both currently return `202` with `job_id: null`).
- Replace the invented constant in `POST /simulations/{id}/estimate`
  (`simulations.py`, `cached_count` hard-coded `0`) with a real `impact_cache`
  lookup.
- Build `/simulations/[id]`; `/simulations` currently renders `NotBuiltYet`
  even though `api/routers/simulations.py` is fully implemented, and has no nav
  link.

### Ripple animation (`use-ripple-animation.ts`)

Origin requirement pulses purple → a travelling dot animates along each
dependency edge → on arrival the target gains its severity ring and pulses once
→ settles. Skippable; under `prefers-reduced-motion` rings apply instantly with
no animation. Then a summary: documents examined, affected, by severity,
likely-unaffected, confidence.

**Simulated content must never be mistakable for real** (PRD §10.4) — purple
chip on every list, card and header.

### Clause rail (`document-detail-page.tsx`)

Left severity rail (4px bars per chunk), restrained tint (`bg-{sev}/5` — replaces
the hard-coded `bg-yellow-50/70`), badge per affected chunk, underline on the
span only, "Only affected clauses" toggle, severity count strip, prev/next
navigation between affected clauses. Replace the remaining raw `yellow-*` /
`sky-*` literals with tokens.

---

## 6. Testing to add

**Backend** (`tests/`):
- ~~`test_patching.py`~~ — **done** (16 tests). Asserts unchanged chunk content,
  unchanged file bytes, *and* that no statement touching `document_chunks` is
  ever issued, so a future refactor cannot route around it.  Reuses
  `tests/test_workflow.build_impact` for the regulation → … → impact chain;
  `seed_reviewable_impact` adds the recommendation, the conflict span and a real
  file on disk.
- ~~`test_relevance.py`~~ — **done** (2 tests): precedence order, fallback
  explanation, and owner dominance over lower signals.
- ~~`test_graph_api.py`~~ — **done** (4 tests): caps, truthful truncation,
  filters, simulation selection and the batched-contribution guard.
- ~~`test_dashboard.py`~~ — **done** (2 tests): every feed item has a relevance
  reason; `scope=me` differs from `scope=all` without changing access.

**Frontend** — Playwright and axe are installed and configured. Phase 4 added
the runner and its dashboard/review coverage; Phases 5–6 must add the remaining
graph, simulation, and clause-rail journeys below.
- E1 dashboard → feed item → review → approve → resolved.
- ~~E2 graph~~ — **done**: first click = local graph, second = navigate;
  drag ≠ click, browser-back restoration, filter behavior and table parity.
- E3 simulate → ripple → summary → discard; assert the real requirement is
  untouched.
- E4 clause rail: "Only affected clauses", prev/next.
- E5 `prefers-reduced-motion` → no animation, results still correct.
- ~~E6 dashboard~~ — **done**: active user's first name renders; account switching refreshes
  greeting, cards, feed and graph preview; narrow viewport has no horizontal
  overflow and retains the primary action.
- A11y: `@axe-core/playwright` is wired and passing on the dashboard; extend it
  to the graph, simulation, and document clause-rail screens as those land.

Add a manual visual-consistency check to each Phase 3–6 sign-off: compare page
header alignment, section spacing, card padding/radius/shadow, typography,
icons, states, and motion at desktop and narrow widths. Search changed feature
files for new raw colour, shadow, radius, and animation literals; any necessary
exception must be documented, while ordinary surfaces must use shared tokens or
variants.

Seed determinism: run every E2E after
`POST /settings/sample-environment {"scenario_id":"pdpf"}`, which self-verifies
six invariants and 500s on a bad load.

---

## 7. Final acceptance checklist

- [x] One severity vocabulary — `critical|high|medium|low|none` — rendered
      identically in graph nodes, graph edges, dashboard cards, document rows,
      clause rail, badges, filters, review screen, legend. *(Phase 2 did all but
      the clause rail and the new screens.)*
- [ ] Severity, confidence and status are three visually distinct dimensions; a
      high-severity low-confidence finding reads "urgent review", never
      "confirmed non-compliance". *(Done in Phase 2.)*
- [x] Graph runs force-directed physics, settles, supports
      drag/pan/zoom/pin/re-centre and is capped at 250 nodes. *(The live corpus
      has only 15 nodes; synthetic API tests cover cap/truncation.)*
- [x] Document fill colour is identity; severity is an outer ring only.
      Requirements black; simulations purple; detected changes red-ringed.
- [x] First click on a document = local graph; second = navigate; a drag = neither.
- [x] Simulation runs the real pipeline, animates the ripple, and leaves
      `regulatory_requirements` byte-identical.
- [x] Every dashboard item shows a relevance reason; relevance never grants access.
- [x] Dashboard opens with the active user's `Hi, {firstName}!` greeting and
      `Here's what's new today.`, followed by a clear urgent-to-secondary
      information hierarchy that remains intact on narrow screens.
- [x] Dashboard and Phase 3 review pages reuse one site-wide system for spacing, surfaces,
      typography, icons, interaction states, and motion; the dashboard does not
      introduce a separate palette or isolated component language.
- [x] Dashboard and review screens implement generous spacing, soft shadows, rounded corners, clean typography, subtle
      icons, and small purposeful animations are implemented through shared
      tokens/variants and propagated across review, dashboard, graph chrome,
      simulation, and document-impact interfaces.
- [x] detected → assigned → reviewed → patch proposed → approved → resolved,
      every step in `impact_review_events` + `audit_events`. *(Phase 3.)*
- [x] **Approve never modifies `document_chunks.content` or the file on disk** —
      proven by test. *(Phase 3: `tests/test_patching.py`, including a SQL-trace
      assertion and a live check against a real .docx.)*
- [ ] Every displayed impact exposes
      `changed provision → dependency evidence → affected clause → document`.
      No evidence-backed path, no confirmed impact shown.
- [x] Non-colour indicators throughout; WCAG AA contrast; keyboard-reachable
      primary actions; `prefers-reduced-motion` respected; graph table view is a
      complete alternative. *(Graph portion done; Phase 6 surfaces remain.)*
- [x] `py -3.12 run.py test` remains at the 17-failure baseline; `npm run build`
      and `npm run test:e2e` pass. `npm run lint` remains at its documented
      pre-existing 1-error/1-warning baseline rather than clean.
- [ ] Ingestion, parsing, mapping, search, change detection, scanning and
      recommendations all still work — verified by loading PDPF end to end.

---

## 8. Verification commands

```bash
# from the repo root
py -3.12 run.py dev          # API :8000 + web :3000, Ctrl+C stops both
py -3.12 run.py test         # compare against 99 passed / 17 failed

cd web && npx tsc --noEmit && npm run lint && npm run build && npm run test:e2e
```

Then, as Priya in the browser: load PDPF at `/settings` → `/dashboard` shows a
personalized feed with relevance reasons → open an impact → approve a patch →
confirm `/documents/{id}` renders the patch as an overlay while
`document_chunks.content` is unchanged in `data/ripple.db` → `/graph` settles
under physics and first/second click differ → simulate PDPF-001 `5 years →
7 years` and watch the ripple reach Customer Data SOP and Privacy Playbook.

**Nothing is committed.** `data/ripple.db.pre008.bak` is a pre-migration backup.

### Live DB state after the Phase 4 session

`data/ripple.db` still holds the PDPF corpus with Phase 3's verification run baked in;
Phase 4 browser verification deliberately did not reset it or incur model calls.
Therefore the new deterministic team/follow/assignment seed has not yet been
applied to this live file. The existing state is:
impact `a7ceede9…` (Customer Data SOP, 7.1 Retention Period) is **resolved**
with one applied patch (`5 years` → `7 years`) and one reverted patch behind it,
and three impacts remain open (Privacy Playbook, Data Breach Response
Procedure, Data Subject Request Procedure). Re-seed from `/settings` for a clean
slate — remembering it re-seeds users with new ids, so re-login afterwards.

At the Phase 5 handoff, the web process on `:3000` was still running but the
temporary API process on `:8000` had been stopped. Check both ports before
starting anything; if that state is unchanged, start only the API or restart
the identified development pair without blanket-killing Node.

## 9. Known stale docs (not yet fixed)

- **PRD §15** describes `run.py seed`, `PDPA 2020.pdf`, 5 documents, and
  per-account visibility differences. All wrong now.
- **PRD §5.5 / lines 196–198** still list Alex Tan and Sam Rahim as `member`.
- **`README.md`** says the scoping rules "are implemented and tested exactly as
  specified" — false since `ec59e33`. PRD line 1185 calls a misleading README
  "the worst defect this project can ship".
- **`web/README.md`** is untouched `create-next-app` boilerplate.
