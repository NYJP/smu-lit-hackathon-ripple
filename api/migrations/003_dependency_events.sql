CREATE TABLE IF NOT EXISTS dependency_events (
  id             TEXT PRIMARY KEY,
  dependency_id  TEXT NOT NULL REFERENCES dependencies(id) ON DELETE CASCADE,
  event_type     TEXT NOT NULL CHECK (event_type IN ('reactivated')),
  previous_status TEXT NOT NULL,
  new_status      TEXT NOT NULL,
  previous_relationship_type TEXT,
  new_relationship_type      TEXT,
  previous_evidence_span     TEXT,
  new_evidence_span          TEXT,
  scan_id        TEXT REFERENCES scans(id) ON DELETE SET NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dependency_events_dependency
  ON dependency_events(dependency_id, created_at DESC);
