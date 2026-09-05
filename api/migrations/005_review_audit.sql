ALTER TABLE recommendations ADD COLUMN source_citations TEXT;
ALTER TABLE recommendations ADD COLUMN generation_method TEXT NOT NULL DEFAULT 'model'
  CHECK (generation_method IN ('model','deterministic_fallback'));

CREATE TABLE IF NOT EXISTS recommendation_decisions (
  id                TEXT PRIMARY KEY,
  recommendation_id TEXT NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
  status            TEXT NOT NULL CHECK (status IN ('accepted','rejected','edited')),
  edited_text       TEXT,
  decision_note     TEXT,
  decided_by        TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  decided_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recommendation_decisions_recommendation
  ON recommendation_decisions(recommendation_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS impact_review_events (
  id              TEXT PRIMARY KEY,
  impact_id       TEXT NOT NULL REFERENCES impacts(id) ON DELETE CASCADE,
  previous_status TEXT NOT NULL,
  new_status      TEXT NOT NULL,
  changed_by      TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  changed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_impact_review_events_impact
  ON impact_review_events(impact_id, changed_at DESC);
