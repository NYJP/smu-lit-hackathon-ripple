"""Shared accessors for real and simulated regulatory changes."""

from __future__ import annotations

import hashlib
import json
from api.sqlite_driver import sqlite3
from collections.abc import Mapping
from typing import Any


def _value(row: Mapping[str, Any] | sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def requirement_content_hash(row: Mapping[str, Any] | sqlite3.Row | None) -> str:
    """Hash only fields that can materially change requirement meaning."""
    if row is None:
        return _canonical_hash(None)
    fields = (
        "requirement_text",
        "verbatim_text",
        "requirement_type",
        "subject",
        "value",
        "value_numeric",
        "value_unit",
        "comparator",
        "condition",
        "exception",
        "source_section",
        "effective_date",
    )
    return _canonical_hash({field: _value(row, field) for field in fields})


def document_chunk_hash(row: Mapping[str, Any] | sqlite3.Row) -> str:
    """Hash chunk content and its stable source location."""
    fields = ("document_id", "ordinal", "section_path", "page_number", "content")
    return _canonical_hash({field: _value(row, field) for field in fields})


def get_change_requirement_pair(
    conn: sqlite3.Connection,
    change_row: Mapping[str, Any] | sqlite3.Row,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve immutable previous/proposed content for a change."""
    simulation_id = _value(change_row, "simulation_id")
    lineage_id = _value(change_row, "lineage_id")
    if simulation_id:
        snapshot = conn.execute(
            """SELECT previous_requirement_json, proposed_requirement_json
               FROM simulation_requirement_snapshots
               WHERE simulation_id = ?
                 AND (lineage_id = ? OR (? IS NULL AND lineage_id IS NULL))
               ORDER BY created_at DESC LIMIT 1""",
            (simulation_id, lineage_id, lineage_id),
        ).fetchone()
        if snapshot is not None:
            previous = (
                json.loads(snapshot["previous_requirement_json"])
                if snapshot["previous_requirement_json"] else None
            )
            proposed = (
                json.loads(snapshot["proposed_requirement_json"])
                if snapshot["proposed_requirement_json"] else None
            )
            return previous, proposed

    previous_id = _value(change_row, "previous_requirement_id")
    new_id = _value(change_row, "new_requirement_id")
    previous = (
        conn.execute("SELECT * FROM regulatory_requirements WHERE id = ?", (previous_id,)).fetchone()
        if previous_id else None
    )
    current = (
        conn.execute("SELECT * FROM regulatory_requirements WHERE id = ?", (new_id,)).fetchone()
        if new_id else None
    )
    proposed_snapshot = _value(change_row, "proposed_snapshot")
    if current is None and proposed_snapshot:
        return _row_dict(previous), json.loads(proposed_snapshot)
    return _row_dict(previous), _row_dict(current)


def change_visibility_sql(
    user: Mapping[str, Any] | sqlite3.Row,
    alias: str = "c",
) -> tuple[str, list[Any]]:
    """Return the single-organization predicate for an authenticated user."""
    del user, alias
    return "1 = 1", []
