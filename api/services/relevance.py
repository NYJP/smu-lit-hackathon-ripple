"""Personal relevance signals for dashboard ranking, never authorization."""

from __future__ import annotations

from api.sqlite_driver import sqlite3


def relevance_for(
    conn: sqlite3.Connection, user_id: str, document_ids: list[str]
) -> dict[str, dict[str, object]]:
    """Return the strongest relevance reason for each requested document.

    Precedence is owner, impact assignee, collaborator, team assignment, then
    follow. Missing signals remain visible and receive a workspace-level reason.
    """
    if not document_ids:
        return {}
    unique_ids = list(dict.fromkeys(document_ids))
    placeholders = ",".join("?" * len(unique_ids))
    result = {
        document_id: {"reason": "Monitored across your workspace.", "weight": 0}
        for document_id in unique_ids
    }

    def apply(rows: list[sqlite3.Row], weight: int, reason) -> None:
        for row in rows:
            document_id = row["document_id"]
            if int(result[document_id]["weight"]) < weight:
                result[document_id] = {"reason": reason(row), "weight": weight}

    apply(
        conn.execute(
            f"SELECT id AS document_id FROM documents WHERE owner_id=? AND id IN ({placeholders})",
            [user_id, *unique_ids],
        ).fetchall(),
        5,
        lambda _row: "You own this document.",
    )
    apply(
        conn.execute(
            f"SELECT DISTINCT document_id FROM impacts WHERE assigned_to=? AND document_id IN ({placeholders})",
            [user_id, *unique_ids],
        ).fetchall(),
        4,
        lambda _row: "An impact on this document is assigned to you.",
    )
    apply(
        conn.execute(
            f"SELECT document_id FROM document_collaborators WHERE user_id=? AND document_id IN ({placeholders})",
            [user_id, *unique_ids],
        ).fetchall(),
        3,
        lambda _row: "You collaborate on this document.",
    )
    apply(
        conn.execute(
            f"""SELECT dt.document_id, t.name AS team_name
                  FROM document_teams dt
                  JOIN teams t ON t.id=dt.team_id
                  JOIN team_members tm ON tm.team_id=dt.team_id
                 WHERE tm.user_id=? AND dt.document_id IN ({placeholders})
                 ORDER BY t.name COLLATE NOCASE""",
            [user_id, *unique_ids],
        ).fetchall(),
        2,
        lambda row: f"Assigned to your {row['team_name']} team.",
    )
    apply(
        conn.execute(
            f"""SELECT DISTINCT d.id AS document_id
                  FROM documents d
                  JOIN dependencies dep ON dep.document_id=d.id AND dep.status='active'
                  JOIN requirement_lineages l ON l.id=dep.lineage_id
                  JOIN follows f ON f.user_id=? AND (
                       (f.subject_type='document' AND f.subject_id=d.id)
                    OR (f.subject_type='lineage' AND f.subject_id=l.id)
                    OR (f.subject_type='regulation' AND f.subject_id=l.origin_regulation_id))
                 WHERE d.id IN ({placeholders})""",
            [user_id, *unique_ids],
        ).fetchall(),
        1,
        lambda _row: "You follow this document or its regulation.",
    )
    # A direct document follow need not have a dependency yet.
    apply(
        conn.execute(
            f"""SELECT subject_id AS document_id FROM follows
                 WHERE user_id=? AND subject_type='document' AND subject_id IN ({placeholders})""",
            [user_id, *unique_ids],
        ).fetchall(),
        1,
        lambda _row: "You follow this document.",
    )
    return result
