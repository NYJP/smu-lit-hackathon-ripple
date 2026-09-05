"""Sentence-level authorship for internal documents."""
from __future__ import annotations

import random
import re
import sqlite3
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sentence_ranges(text: str) -> list[tuple[int, int]]:
    """Return trimmed sentence offsets relative to one document chunk."""
    if not text.strip():
        return []
    boundaries = [match.end() for match in re.finditer(r"[.!?](?=\s|$)", text)]
    if not boundaries or boundaries[-1] < len(text):
        boundaries.append(len(text))
    ranges: list[tuple[int, int]] = []
    start = 0
    for boundary in boundaries:
        sentence_start = start
        while sentence_start < boundary and text[sentence_start].isspace():
            sentence_start += 1
        sentence_end = boundary
        while sentence_end > sentence_start and text[sentence_end - 1].isspace():
            sentence_end -= 1
        if sentence_end > sentence_start:
            ranges.append((sentence_start, sentence_end))
        start = boundary
    return ranges


def _insert(
    conn: sqlite3.Connection,
    document_id: str,
    chunk_id: str,
    user_id: str,
    start: int,
    end: int,
    contributed_at: str,
) -> None:
    conn.execute(
        """INSERT INTO document_contributions
           (id, document_id, document_chunk_id, user_id, sentence_start,
            sentence_end, contributed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uuid.uuid4().hex, document_id, chunk_id, user_id, start, end, contributed_at),
    )


def assign_document_to_owner(
    conn: sqlite3.Connection,
    document_id: str,
    owner_id: str,
) -> None:
    """Attribute a normally uploaded document to its uploader."""
    conn.execute("DELETE FROM document_contributions WHERE document_id = ?", (document_id,))
    now = _now()
    chunks = conn.execute(
        "SELECT id, content FROM document_chunks WHERE document_id = ? ORDER BY ordinal",
        (document_id,),
    ).fetchall()
    for chunk in chunks:
        for start, end in sentence_ranges(chunk["content"]):
            _insert(conn, document_id, chunk["id"], owner_id, start, end, now)


def assign_sample_contributors(conn: sqlite3.Connection, document_id: str) -> None:
    """Randomly and evenly distribute sample sentences across all seeded people."""
    users = conn.execute("SELECT id FROM users ORDER BY display_name COLLATE NOCASE").fetchall()
    user_ids = [row["id"] for row in users]
    if not user_ids:
        return
    assignments: list[tuple[str, int, int]] = []
    chunks = conn.execute(
        "SELECT id, content FROM document_chunks WHERE document_id = ? ORDER BY ordinal",
        (document_id,),
    ).fetchall()
    for chunk in chunks:
        assignments.extend((chunk["id"], start, end) for start, end in sentence_ranges(chunk["content"]))
    shuffled = user_ids.copy()
    random.SystemRandom().shuffle(shuffled)
    offset = random.SystemRandom().randrange(len(shuffled))
    conn.execute("DELETE FROM document_contributions WHERE document_id = ?", (document_id,))
    now = _now()
    for index, (chunk_id, start, end) in enumerate(assignments):
        user_id = shuffled[(index + offset) % len(shuffled)]
        _insert(conn, document_id, chunk_id, user_id, start, end, now)
    owner = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (document_id,)).fetchone()
    if owner:
        for user_id in user_ids:
            if user_id == owner["owner_id"]:
                continue
            conn.execute(
                """INSERT INTO document_collaborators
                   (document_id, user_id, access, added_by, added_at)
                   VALUES (?, ?, 'reviewer', ?, ?)
                   ON CONFLICT(document_id, user_id) DO NOTHING""",
                (document_id, user_id, owner["owner_id"], now),
            )


def for_document(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT DISTINCT u.id, u.display_name FROM users u
           WHERE u.id IN (
             SELECT owner_id FROM documents WHERE id = ?
             UNION SELECT user_id FROM document_collaborators WHERE document_id = ?
             UNION SELECT user_id FROM document_contributions WHERE document_id = ?
           )
           ORDER BY u.display_name COLLATE NOCASE""",
        (document_id, document_id, document_id),
    ).fetchall()
    return [dict(row) for row in rows]


def for_chunk(conn: sqlite3.Connection, chunk_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT dc.sentence_start, dc.sentence_end, dc.contributed_at,
                  u.id AS user_id, u.display_name
           FROM document_contributions dc
           LEFT JOIN users u ON u.id = dc.user_id
           WHERE dc.document_chunk_id = ?
           ORDER BY dc.sentence_start""",
        (chunk_id,),
    ).fetchall()
    return [
        {
            "start": row["sentence_start"],
            "end": row["sentence_end"],
            "contributed_at": row["contributed_at"],
            "user": {"id": row["user_id"], "display_name": row["display_name"]}
            if row["user_id"] else None,
        }
        for row in rows
    ]


def for_span(
    conn: sqlite3.Connection,
    chunk_id: str,
    start: int | None,
    end: int | None,
) -> dict | None:
    """Find the author of the sentence overlapping an affected text span."""
    if start is None:
        row = conn.execute(
            """SELECT u.id, u.display_name FROM document_contributions dc
               JOIN users u ON u.id = dc.user_id
               WHERE dc.document_chunk_id = ? ORDER BY dc.sentence_start LIMIT 1""",
            (chunk_id,),
        ).fetchone()
    else:
        span_end = end if end is not None and end > start else start + 1
        row = conn.execute(
            """SELECT u.id, u.display_name FROM document_contributions dc
               JOIN users u ON u.id = dc.user_id
               WHERE dc.document_chunk_id = ?
                 AND dc.sentence_start < ? AND dc.sentence_end > ?
               ORDER BY dc.sentence_start LIMIT 1""",
            (chunk_id, span_end, start),
        ).fetchone()
    return dict(row) if row else None
