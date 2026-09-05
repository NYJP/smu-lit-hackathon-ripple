-- Ripple — initial schema (PRD section 6 and 6.1).
-- SQLite. TEXT holds UUIDs (uuid4().hex) and ISO-8601 timestamps.
-- Applied by api/db.py's migration runner, which must be idempotent on an
-- existing database (each statement uses IF NOT EXISTS).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------- accounts ----------
CREATE TABLE IF NOT EXISTS organizations (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- Exactly one row. Enforced by a trigger; the column exists so the Postgres
-- port in section 16 is a filter change, not a schema change.
CREATE TRIGGER IF NOT EXISTS trg_organizations_single_row
BEFORE INSERT ON organizations
WHEN (SELECT COUNT(*) FROM organizations) >= 1
BEGIN
  SELECT RAISE(ABORT, 'organizations is a single-row table');
END;

-- No credentials. Seeded with three rows on first boot (section 5.5).
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
  role          TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  created_at    TEXT NOT NULL,
  last_seen_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT PRIMARY KEY,                    -- opaque 256-bit random id, held in the cookie
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, expires_at);

-- ---------- regulations ----------
CREATE TABLE IF NOT EXISTS regulations (
  id                   TEXT PRIMARY KEY,
  title                TEXT NOT NULL,
  short_name           TEXT,
  jurisdiction         TEXT,
  document_kind        TEXT NOT NULL DEFAULT 'primary'
                       CHECK (document_kind IN ('primary','amendment','guidance','notice','decision','consultation')),
  amends_regulation_id TEXT REFERENCES regulations(id) ON DELETE SET NULL,
  effective_date       TEXT,                       -- ISO date
  file_path            TEXT NOT NULL,              -- relative to RIPPLE_DATA_DIR
  file_name            TEXT NOT NULL,
  page_count           INTEGER,
  status               TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','processing','ready','failed')),
  error_message        TEXT,
  created_at           TEXT NOT NULL
);

-- Stable identity of a requirement across amendments.
CREATE TABLE IF NOT EXISTS requirement_lineages (
  id                   TEXT PRIMARY KEY,
  public_ref           TEXT NOT NULL UNIQUE,       -- 'REQ-001'
  subject              TEXT NOT NULL,              -- snake_case, e.g. 'cannabis_possession'
  origin_regulation_id TEXT NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  current_version_id   TEXT,                       -- -> regulatory_requirements.id
  created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lineage_subject ON requirement_lineages(subject);

CREATE TABLE IF NOT EXISTS regulatory_requirements (
  id               TEXT PRIMARY KEY,
  lineage_id       TEXT NOT NULL REFERENCES requirement_lineages(id) ON DELETE CASCADE,
  regulation_id    TEXT NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  version          INTEGER NOT NULL DEFAULT 1,
  requirement_text TEXT NOT NULL,                  -- one-sentence normalised statement
  verbatim_text    TEXT,                           -- quoted source sentence(s)
  requirement_type TEXT NOT NULL
                   CHECK (requirement_type IN ('threshold','duration','prohibition','obligation',
                                               'definition','notification','exception','procedure','other')),
  subject          TEXT NOT NULL,
  value            TEXT,                           -- normalised display value, e.g. '15 g', '7 years'
  value_numeric    REAL,
  value_unit       TEXT,                           -- 'g', 'years', 'days', 'SGD'
  comparator       TEXT CHECK (comparator IN ('gt','gte','lt','lte','eq','between') OR comparator IS NULL),
  condition        TEXT,
  exception        TEXT,
  source_section   TEXT,                           -- 'Section 12(2)'
  source_page      INTEGER,
  effective_date   TEXT,
  origin           TEXT NOT NULL DEFAULT 'extracted'
                   CHECK (origin IN ('extracted','manual')),
  superseded_by    TEXT REFERENCES regulatory_requirements(id) ON DELETE SET NULL,
  is_current       INTEGER NOT NULL DEFAULT 1,
  created_at       TEXT NOT NULL,
  UNIQUE (lineage_id, version)
);
CREATE INDEX IF NOT EXISTS idx_req_current ON regulatory_requirements(is_current);
CREATE INDEX IF NOT EXISTS idx_req_lineage ON regulatory_requirements(lineage_id, version DESC);

-- ---------- internal documents ----------
CREATE TABLE IF NOT EXISTS documents (
  id            TEXT PRIMARY KEY,
  owner_id      TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  name          TEXT NOT NULL,
  doc_type      TEXT NOT NULL DEFAULT 'policy'
                CHECK (doc_type IN ('policy','playbook','sop','template','clause_library',
                                    'checklist','opinion','advisory','training','other')),
  version_label TEXT,
  file_path     TEXT NOT NULL,
  file_name     TEXT NOT NULL,
  mime_type     TEXT NOT NULL,
  page_count    INTEGER,
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','processing','ready','failed')),
  error_message TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id, created_at DESC);

-- People tagged onto a document at upload time or later.
CREATE TABLE IF NOT EXISTS document_collaborators (
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  access      TEXT NOT NULL DEFAULT 'reviewer' CHECK (access IN ('viewer','reviewer')),
  added_by    TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  added_at    TEXT NOT NULL,
  PRIMARY KEY (document_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_collab_user ON document_collaborators(user_id);

CREATE TABLE IF NOT EXISTS document_chunks (
  id            TEXT PRIMARY KEY,
  document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal       INTEGER NOT NULL,                  -- 0-based order within the document
  content       TEXT NOT NULL,
  section_path  TEXT,                              -- 'Part III > 4.2 Prohibited Substances'
  section_title TEXT,
  page_number   INTEGER,
  char_start    INTEGER,                           -- offset into the document's full extracted text
  char_end      INTEGER,
  chunk_type    TEXT NOT NULL DEFAULT 'paragraph'
                CHECK (chunk_type IN ('paragraph','heading','list_item','table_row','other')),
  created_at    TEXT NOT NULL,
  UNIQUE (document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON document_chunks(document_id, ordinal);

-- ---------- scans ----------
-- Defined before mapping_passes and dependencies because both reference it.
CREATE TABLE IF NOT EXISTS scans (
  id                TEXT PRIMARY KEY,
  trigger           TEXT NOT NULL
                    CHECK (trigger IN ('policy_change','document_added','manual','simulation')),
  scope             TEXT NOT NULL DEFAULT 'stale'
                    CHECK (scope IN ('stale','full','document','lineage')),
  scope_id          TEXT,                          -- document_id or lineage_id when scope is narrowed
  initiated_by      TEXT REFERENCES users(id) ON DELETE SET NULL,   -- NULL for automatic scans
  status            TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','succeeded','failed')),
  -- What the scan found and did. Written incrementally so the UI can narrate progress.
  documents_scanned     INTEGER NOT NULL DEFAULT 0,
  requirements_scanned  INTEGER NOT NULL DEFAULT 0,
  dependencies_added    INTEGER NOT NULL DEFAULT 0,
  dependencies_removed  INTEGER NOT NULL DEFAULT 0,
  impacts_created       INTEGER NOT NULL DEFAULT 0,
  new_high_impacts      INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd    REAL NOT NULL DEFAULT 0,
  error_message     TEXT,
  started_at        TEXT,
  finished_at       TEXT,
  created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_recent ON scans(created_at DESC);

-- ---------- the dependency map ----------
CREATE TABLE IF NOT EXISTS dependencies (
  id                TEXT PRIMARY KEY,
  lineage_id        TEXT NOT NULL REFERENCES requirement_lineages(id) ON DELETE CASCADE,
  document_chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  document_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,   -- denormalised for filtering
  relationship_type TEXT NOT NULL
                    CHECK (relationship_type IN ('restates','implements','references','defines')),
  confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  rationale         TEXT NOT NULL,
  evidence_span     TEXT,                          -- exact substring of chunk.content carrying the dependency
  evidence_start    INTEGER,
  evidence_end      INTEGER,
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','dismissed')),
  found_by_scan_id  TEXT REFERENCES scans(id) ON DELETE SET NULL,
  created_at        TEXT NOT NULL,
  UNIQUE (lineage_id, document_chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_dep_lineage ON dependencies(lineage_id, status);
CREATE INDEX IF NOT EXISTS idx_dep_document ON dependencies(document_id, status);

-- Evidence that a document was checked against a requirement, INCLUDING when nothing matched.
-- This is what lets Ripple say "checked against 214 requirements, 3 matched" instead of
-- silently implying absence. It is also how the scanner knows what is stale.
CREATE TABLE IF NOT EXISTS mapping_passes (
  document_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  lineage_id       TEXT NOT NULL REFERENCES requirement_lineages(id) ON DELETE CASCADE,
  direction        TEXT NOT NULL CHECK (direction IN ('requirement_first','document_first')),
  dependency_found INTEGER NOT NULL DEFAULT 0,
  candidates_seen  INTEGER NOT NULL DEFAULT 0,
  scan_id          TEXT REFERENCES scans(id) ON DELETE SET NULL,
  mapped_at        TEXT NOT NULL,
  PRIMARY KEY (document_id, lineage_id)
);
CREATE INDEX IF NOT EXISTS idx_pass_lineage ON mapping_passes(lineage_id);

-- ---------- what-if simulation ----------
-- A simulation is a set of proposed edits to stored requirements that has NOT been applied.
-- Running one produces regulatory_changes rows tagged with simulation_id; everything
-- downstream (impacts, recommendations, the review UI) is identical to a real change.
CREATE TABLE IF NOT EXISTS simulations (
  id          TEXT PRIMARY KEY,
  created_by  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,                      -- 'PDPA consultation: 5y -> 7y'
  note        TEXT,
  status      TEXT NOT NULL DEFAULT 'draft'
              CHECK (status IN ('draft','running','complete','failed','promoted','discarded')),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_edits (
  id                    TEXT PRIMARY KEY,
  simulation_id         TEXT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
  lineage_id            TEXT REFERENCES requirement_lineages(id) ON DELETE CASCADE,
  op                    TEXT NOT NULL CHECK (op IN ('modify','repeal','add')),
  -- Proposed field values. NULL means "unchanged from the current version".
  -- For op='add' these define the hypothetical new requirement; lineage_id is NULL.
  proposed_requirement_text TEXT,
  proposed_value            TEXT,
  proposed_value_numeric    REAL,
  proposed_value_unit       TEXT,
  proposed_comparator       TEXT,
  proposed_condition        TEXT,
  proposed_exception        TEXT,
  proposed_effective_date   TEXT,
  created_at            TEXT NOT NULL,
  CHECK ((op = 'add' AND lineage_id IS NULL) OR (op <> 'add' AND lineage_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_simedit_sim ON simulation_edits(simulation_id);

-- ---------- change detection ----------
CREATE TABLE IF NOT EXISTS regulatory_changes (
  id                          TEXT PRIMARY KEY,
  lineage_id                  TEXT NOT NULL REFERENCES requirement_lineages(id) ON DELETE CASCADE,
  source                      TEXT NOT NULL DEFAULT 'amendment'
                              CHECK (source IN ('amendment','manual','simulation')),
  detected_from_regulation_id TEXT REFERENCES regulations(id) ON DELETE CASCADE,  -- NULL for manual/simulation
  simulation_id               TEXT REFERENCES simulations(id) ON DELETE CASCADE,  -- NULL unless source='simulation'
  previous_requirement_id     TEXT REFERENCES regulatory_requirements(id) ON DELETE SET NULL,
  new_requirement_id          TEXT REFERENCES regulatory_requirements(id) ON DELETE SET NULL,
  proposed_snapshot           TEXT,               -- JSON of the hypothetical requirement, when it has no stored row
  change_type                 TEXT NOT NULL
                              CHECK (change_type IN ('added','removed','threshold','duration','scope',
                                                     'definition','obligation','exception',
                                                     'effective_date','editorial')),
  old_value                   TEXT,
  new_value                   TEXT,
  summary                     TEXT NOT NULL,       -- 'Possession threshold: 30 g -> 15 g'
  source_section              TEXT,
  effective_date              TEXT,
  analysis_status             TEXT NOT NULL DEFAULT 'pending'
                              CHECK (analysis_status IN ('pending','analysing','complete','failed')),
  created_at                  TEXT NOT NULL,
  CHECK ((source = 'amendment'  AND detected_from_regulation_id IS NOT NULL AND simulation_id IS NULL)
      OR (source = 'manual'     AND simulation_id IS NULL)
      OR (source = 'simulation' AND simulation_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_change_simulation ON regulatory_changes(simulation_id);
CREATE INDEX IF NOT EXISTS idx_change_source ON regulatory_changes(source, created_at DESC);

CREATE TABLE IF NOT EXISTS impacts (
  id                   TEXT PRIMARY KEY,
  regulatory_change_id TEXT NOT NULL REFERENCES regulatory_changes(id) ON DELETE CASCADE,
  dependency_id        TEXT NOT NULL REFERENCES dependencies(id) ON DELETE CASCADE,
  document_id          TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  document_chunk_id    TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  impact_level         TEXT NOT NULL CHECK (impact_level IN ('high','medium','low','none')),
  confidence           REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  reason               TEXT NOT NULL,
  conflicting_span     TEXT,                       -- exact substring of the chunk now contradicted
  conflicting_start    INTEGER,
  conflicting_end      INTEGER,
  review_status        TEXT NOT NULL DEFAULT 'open'
                       CHECK (review_status IN ('open','in_review','resolved','dismissed')),
  assigned_to          TEXT REFERENCES users(id) ON DELETE SET NULL,
  resolved_by          TEXT REFERENCES users(id) ON DELETE SET NULL,
  resolved_at          TEXT,
  created_by_scan_id   TEXT REFERENCES scans(id) ON DELETE SET NULL,
  created_at           TEXT NOT NULL,
  UNIQUE (regulatory_change_id, dependency_id)
);
CREATE INDEX IF NOT EXISTS idx_impact_change ON impacts(regulatory_change_id, impact_level);
CREATE INDEX IF NOT EXISTS idx_impact_review ON impacts(review_status);

CREATE TABLE IF NOT EXISTS recommendations (
  id             TEXT PRIMARY KEY,
  impact_id      TEXT NOT NULL REFERENCES impacts(id) ON DELETE CASCADE,
  current_text   TEXT NOT NULL,
  suggested_text TEXT NOT NULL,
  rationale      TEXT NOT NULL,
  requires_human_decision INTEGER NOT NULL DEFAULT 0,
  decision_note  TEXT,
  status         TEXT NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','accepted','edited','rejected')),
  edited_text    TEXT,
  decided_by     TEXT REFERENCES users(id) ON DELETE SET NULL,
  decided_at     TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rec_impact ON recommendations(impact_id);

-- ---------- async work ----------
CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  job_type      TEXT NOT NULL,
  subject_type  TEXT NOT NULL,                     -- 'regulation' | 'document' | 'regulatory_change'
  subject_id    TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','succeeded','failed')),
  progress      REAL NOT NULL DEFAULT 0,
  step          TEXT,                              -- human-readable current step
  error_message TEXT,
  result        TEXT,                              -- JSON
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_recent ON jobs(created_at DESC);

-- ---------- vector and full-text tables (section 6.1) ----------
-- sqlite-vec. Dimension MUST match RIPPLE_EMBEDDING_MODEL (1536 for text-embedding-3-small).
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
  chunk_id TEXT PRIMARY KEY,
  embedding FLOAT[1536]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_requirements USING vec0(
  requirement_id TEXT PRIMARY KEY,
  embedding FLOAT[1536]
);

-- FTS5 for lexical retrieval and keyword search.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
  chunk_id UNINDEXED,
  content,
  section_path,
  tokenize = 'porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_requirements USING fts5(
  requirement_id UNINDEXED,
  requirement_text,
  verbatim_text,
  tokenize = 'porter unicode61'
);
