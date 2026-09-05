-- Ripple PRD completion foundations. This migration contains ALTER TABLE
-- statements and must be executed exactly once by api.db.run_migrations().

ALTER TABLE users ADD COLUMN organization_id TEXT REFERENCES organizations(id);
ALTER TABLE documents ADD COLUMN organization_id TEXT REFERENCES organizations(id);
ALTER TABLE regulations ADD COLUMN organization_id TEXT REFERENCES organizations(id);
ALTER TABLE scans ADD COLUMN organization_id TEXT REFERENCES organizations(id);
ALTER TABLE simulations ADD COLUMN organization_id TEXT REFERENCES organizations(id);

UPDATE users SET role = 'admin';
UPDATE users SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE organization_id IS NULL;
UPDATE documents SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE organization_id IS NULL;
UPDATE regulations SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE organization_id IS NULL;
UPDATE scans SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE organization_id IS NULL;
UPDATE simulations SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE organization_id IS NULL;

-- Existing insert statements need no duplicated organization lookup.
CREATE TRIGGER IF NOT EXISTS trg_users_default_organization
AFTER INSERT ON users WHEN NEW.organization_id IS NULL
BEGIN
  UPDATE users SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_documents_default_organization
AFTER INSERT ON documents WHEN NEW.organization_id IS NULL
BEGIN
  UPDATE documents SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_regulations_default_organization
AFTER INSERT ON regulations WHEN NEW.organization_id IS NULL
BEGIN
  UPDATE regulations SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_scans_default_organization
AFTER INSERT ON scans WHEN NEW.organization_id IS NULL
BEGIN
  UPDATE scans SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_simulations_default_organization
AFTER INSERT ON simulations WHEN NEW.organization_id IS NULL
BEGIN
  UPDATE simulations SET organization_id = (SELECT id FROM organizations LIMIT 1) WHERE id = NEW.id;
END;

ALTER TABLE mapping_passes ADD COLUMN basis_hash TEXT;
ALTER TABLE mapping_passes ADD COLUMN materially_checked_at TEXT;

ALTER TABLE jobs ADD COLUMN initiated_by TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE jobs ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN estimated_cost_usd REAL;
ALTER TABLE jobs ADD COLUMN retry_of_job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_initiated_by ON jobs(initiated_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_retry_of ON jobs(retry_of_job_id);

CREATE TABLE IF NOT EXISTS impact_cache (
  dependency_id             TEXT NOT NULL REFERENCES dependencies(id) ON DELETE CASCADE,
  previous_requirement_hash TEXT NOT NULL,
  new_requirement_hash      TEXT NOT NULL,
  document_chunk_hash       TEXT NOT NULL,
  model                     TEXT NOT NULL,
  result_json               TEXT NOT NULL,
  prompt_tokens             INTEGER NOT NULL DEFAULT 0,
  completion_tokens         INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd        REAL,
  created_at                TEXT NOT NULL,
  updated_at                TEXT NOT NULL,
  PRIMARY KEY (dependency_id, previous_requirement_hash, new_requirement_hash, document_chunk_hash, model)
);

CREATE TABLE IF NOT EXISTS simulation_requirement_snapshots (
  id                        TEXT PRIMARY KEY,
  simulation_id             TEXT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
  lineage_id                TEXT REFERENCES requirement_lineages(id) ON DELETE SET NULL,
  operation                 TEXT NOT NULL CHECK (operation IN ('modify','remove','add')),
  previous_requirement_json TEXT,
  proposed_requirement_json TEXT,
  created_at                TEXT NOT NULL,
  UNIQUE (simulation_id, lineage_id, operation)
);
CREATE INDEX IF NOT EXISTS idx_simulation_snapshots_simulation
  ON simulation_requirement_snapshots(simulation_id);
