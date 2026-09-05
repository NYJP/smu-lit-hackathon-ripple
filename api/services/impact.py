"""Deterministic impact classification for changed requirements."""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone

from api import access


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify(content: str, old_value: str | None, new_value: str | None, relationship: str) -> tuple[str, str, str | None, int | None, int | None]:
    if old_value and old_value.casefold() in content.casefold():
        start = content.casefold().find(old_value.casefold())
        end = start + len(old_value)
        return "high", "The passage contains the superseded value.", content[start:end], start, end
    if relationship == "references":
        return "medium", "The passage defers to the changed requirement.", None, None, None
    if re.search(r"applicable\s+(law|regulation)|as\s+required\s+by", content, re.I):
        return "medium", "The passage defers generically to applicable rules.", None, None, None
    return "low", "The passage depends on the changed requirement but contains no literal superseded value.", None, None, None


def analyse_change(conn: sqlite3.Connection, change_id: str) -> int:
    change = conn.execute("SELECT * FROM regulatory_changes WHERE id = ?", (change_id,)).fetchone()
    if change is None:
        return 0
    rows = conn.execute(
        """SELECT d.*, c.content, dep.relationship_type FROM dependencies dep
           JOIN document_chunks c ON c.id = dep.document_chunk_id
           JOIN documents d ON d.id = dep.document_id
           WHERE dep.lineage_id = ? AND dep.status = 'active'""", (change["lineage_id"],)
    ).fetchall()
    created = 0
    for row in rows:
        level, reason, span, start, end = classify(row["content"], change["old_value"], change["new_value"], row["relationship_type"])
        conn.execute(
            """INSERT INTO impacts (id, regulatory_change_id, dependency_id, document_id, document_chunk_id, impact_level, confidence, reason, conflicting_span, conflicting_start, conflicting_end, created_at)
               SELECT ?, ?, dep.id, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM dependencies dep
               WHERE dep.lineage_id = ? AND dep.document_chunk_id = ?
               ON CONFLICT(regulatory_change_id, dependency_id) DO UPDATE SET impact_level=excluded.impact_level, confidence=excluded.confidence, reason=excluded.reason, conflicting_span=excluded.conflicting_span, conflicting_start=excluded.conflicting_start, conflicting_end=excluded.conflicting_end""",
            (uuid.uuid4().hex, change_id, row["id"], row["id"], level, 0.95 if level == "high" else 0.75, reason, span, start, end, _now(), change["lineage_id"], row["id"]),
        )
        created += 1
    conn.execute("UPDATE regulatory_changes SET analysis_status = 'complete' WHERE id = ?", (change_id,))
    conn.commit()
    return created


def visible_change(conn: sqlite3.Connection, user: sqlite3.Row, change_id: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM regulatory_changes WHERE id = ?", (change_id,)).fetchone()
    if row is None:
        return None
    visible = access.visible_document_ids(conn, user)
    if not conn.execute("SELECT 1 FROM impacts WHERE regulatory_change_id = ? AND document_id IN ({}) LIMIT 1".format(",".join("?" * len(visible)) if visible else "NULL"), [change_id, *visible]).fetchone() and user["role"] != "admin":
        return None
    return row
