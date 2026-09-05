ALTER TABLE dependency_events RENAME TO dependency_events_legacy;

CREATE TABLE dependency_events (
  id             TEXT PRIMARY KEY,
  dependency_id  TEXT NOT NULL REFERENCES dependencies(id) ON DELETE CASCADE,
  event_type     TEXT NOT NULL CHECK (event_type IN ('dismissed','reactivated')),
  previous_status TEXT NOT NULL,
  new_status      TEXT NOT NULL,
  previous_relationship_type TEXT,
  new_relationship_type      TEXT,
  previous_evidence_span     TEXT,
  new_evidence_span          TEXT,
  scan_id        TEXT REFERENCES scans(id) ON DELETE SET NULL,
  created_at     TEXT NOT NULL
);

INSERT INTO dependency_events SELECT * FROM dependency_events_legacy;
DROP TABLE dependency_events_legacy;
CREATE INDEX idx_dependency_events_dependency
  ON dependency_events(dependency_id, created_at DESC);
