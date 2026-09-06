-- Workflow status, severity support, and personalization relevance data.
--
-- Two things happen here:
--   1. `impacts.review_status` gains the full workflow vocabulary. SQLite
--      cannot ALTER a CHECK constraint, so this is the documented 12-step
--      table rebuild. `recommendations` and `impact_review_events` both
--      cascade-delete from `impacts`, so foreign keys MUST be off across
--      the DROP or accepting a recommendation would take its audit trail
--      with it. `executescript` commits any pending transaction before it
--      runs, so the PRAGMA below is outside a transaction and takes effect
--      (verified on this SQLite build before this migration was written).
--   2. Relevance tables (teams / follows / assignment) and the workflow
--      artifacts (patches, notifications, audit). These rank and explain a
--      member's feed; they are deliberately NOT access control -- every
--      account remains an admin that can see everything.

PRAGMA foreign_keys=OFF;

CREATE TABLE impacts_new (
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
  review_status        TEXT NOT NULL DEFAULT 'detected'
                       CHECK (review_status IN ('detected','awaiting_review','in_review',
                                                'needs_analysis','patch_proposed','awaiting_approval',
                                                'resolved','dismissed','superseded')),
  assigned_to          TEXT REFERENCES users(id) ON DELETE SET NULL,
  resolved_by          TEXT REFERENCES users(id) ON DELETE SET NULL,
  resolved_at          TEXT,
  due_date             TEXT,
  updated_at           TEXT,
  created_by_scan_id   TEXT REFERENCES scans(id) ON DELETE SET NULL,
  created_at           TEXT NOT NULL,
  UNIQUE (regulatory_change_id, dependency_id)
);

-- 'open' is the only value that changes name; the other three carry over.
INSERT INTO impacts_new (
  id, regulatory_change_id, dependency_id, document_id, document_chunk_id,
  impact_level, confidence, reason, conflicting_span, conflicting_start, conflicting_end,
  review_status, assigned_to, resolved_by, resolved_at, due_date, updated_at,
  created_by_scan_id, created_at
)
SELECT
  id, regulatory_change_id, dependency_id, document_id, document_chunk_id,
  impact_level, confidence, reason, conflicting_span, conflicting_start, conflicting_end,
  CASE review_status WHEN 'open' THEN 'detected' ELSE review_status END,
  assigned_to, resolved_by, resolved_at, NULL, NULL,
  created_by_scan_id, created_at
FROM impacts;

DROP TABLE impacts;
ALTER TABLE impacts_new RENAME TO impacts;

CREATE INDEX IF NOT EXISTS idx_impact_change ON impacts(regulatory_change_id, impact_level);
CREATE INDEX IF NOT EXISTS idx_impact_review ON impacts(review_status);
CREATE INDEX IF NOT EXISTS idx_impacts_assigned ON impacts(assigned_to, review_status);
CREATE INDEX IF NOT EXISTS idx_impacts_due ON impacts(due_date);

PRAGMA foreign_keys=ON;

-- One recommendation per impact. Three call sites already assume this
-- (services/recommendations.py:137, routers/changes.py:201, routers/impacts.py).
-- A UNIQUE INDEX gives the constraint without a second table rebuild; drop
-- any historical duplicates first, keeping the most recent.
DELETE FROM recommendations
 WHERE rowid NOT IN (
   SELECT MAX(rowid) FROM recommendations GROUP BY impact_id
 );
CREATE UNIQUE INDEX IF NOT EXISTS idx_recommendations_impact_unique
  ON recommendations(impact_id);

-- ---------------------------------------------------------------- teams --

CREATE TABLE IF NOT EXISTS teams (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
  practice_area  TEXT,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_members (
  team_id   TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role      TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member','lead')),
  added_at  TEXT NOT NULL,
  PRIMARY KEY (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);

CREATE TABLE IF NOT EXISTS document_teams (
  document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  team_id      TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  assigned_at  TEXT NOT NULL,
  PRIMARY KEY (document_id, team_id)
);
CREATE INDEX IF NOT EXISTS idx_document_teams_team ON document_teams(team_id);

-- Follows are a relevance signal only; they never widen what an account sees.
CREATE TABLE IF NOT EXISTS follows (
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  subject_type  TEXT NOT NULL CHECK (subject_type IN ('document','regulation','lineage')),
  subject_id    TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  PRIMARY KEY (user_id, subject_type, subject_id)
);
CREATE INDEX IF NOT EXISTS idx_follows_subject ON follows(subject_type, subject_id);

-- ------------------------------------------------------ workflow output --

CREATE TABLE IF NOT EXISTS notifications (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_type    TEXT NOT NULL,
  subject_type  TEXT NOT NULL,
  subject_id    TEXT NOT NULL,
  title         TEXT NOT NULL,
  body          TEXT,
  read_at       TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user
  ON notifications(user_id, read_at, created_at DESC);

-- An accepted recommendation lands here, never in document_chunks and never
-- in the file on disk. The reader renders these as an overlay, which is what
-- keeps the footer promise ("never edits your documents") literally true.
CREATE TABLE IF NOT EXISTS document_patches (
  id                 TEXT PRIMARY KEY,
  document_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  document_chunk_id  TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  impact_id          TEXT REFERENCES impacts(id) ON DELETE SET NULL,
  recommendation_id  TEXT REFERENCES recommendations(id) ON DELETE SET NULL,
  original_text      TEXT NOT NULL,
  patched_text       TEXT NOT NULL,
  char_start         INTEGER,
  char_end           INTEGER,
  status             TEXT NOT NULL DEFAULT 'applied' CHECK (status IN ('applied','reverted')),
  created_by         TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at         TEXT NOT NULL,
  reverted_by        TEXT REFERENCES users(id) ON DELETE SET NULL,
  reverted_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_document_patches_document
  ON document_patches(document_id, status);
CREATE INDEX IF NOT EXISTS idx_document_patches_chunk
  ON document_patches(document_chunk_id, status);

-- General audit. The three existing narrow event tables (impact_review_events,
-- recommendation_decisions, dependency_events) stay authoritative for their
-- own subjects; this covers everything else.
CREATE TABLE IF NOT EXISTS audit_events (
  id            TEXT PRIMARY KEY,
  actor_id      TEXT REFERENCES users(id) ON DELETE SET NULL,
  action        TEXT NOT NULL,
  subject_type  TEXT NOT NULL,
  subject_id    TEXT NOT NULL,
  detail_json   TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_subject
  ON audit_events(subject_type, subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor
  ON audit_events(actor_id, created_at DESC);
