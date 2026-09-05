-- Sentence-level authorship for internal corpus documents.
CREATE TABLE IF NOT EXISTS document_contributions (
  id                TEXT PRIMARY KEY,
  document_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  document_chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  user_id           TEXT REFERENCES users(id) ON DELETE SET NULL,
  sentence_start    INTEGER NOT NULL,
  sentence_end      INTEGER NOT NULL,
  contributed_at    TEXT NOT NULL,
  CHECK (sentence_start >= 0 AND sentence_end > sentence_start),
  UNIQUE (document_chunk_id, sentence_start, sentence_end)
);

CREATE INDEX IF NOT EXISTS idx_document_contributions_document
  ON document_contributions(document_id, user_id);
CREATE INDEX IF NOT EXISTS idx_document_contributions_chunk
  ON document_contributions(document_chunk_id, sentence_start, sentence_end);
