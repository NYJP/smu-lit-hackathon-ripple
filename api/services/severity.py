"""The one place severity is decided (PRD section 8.3, extended).

`impacts.impact_level` still stores exactly what the model returned:
`high` / `medium` / `low` / `none`. That is deliberate — the section 8.3
system prompt is bound to those four words, the deterministic literal
override writes `high`, and `impact_cache` is keyed on results produced
under that scale. Widening the stored vocabulary would invalidate every
cached row and require re-running the whole corpus.

`critical` is therefore *derived* here rather than stored: it is a reading
of an already-stored `high` in light of how close the deadline is and what
kind of change it was. Nothing else in the codebase may rank severity
inline — graph, dashboard, impacts, changes and documents all call in here
so a passage cannot be critical on one screen and high on the next.

Severity answers "how bad could this be". It is NOT confidence, which
answers "how sure are we", and it is NOT review status, which answers
"where is this in the queue". Those three stay separate all the way to the
UI: a critical finding at 40% confidence is an urgent thing to *read*, not
a confirmed breach.
"""

from __future__ import annotations

from api.sqlite_driver import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

# Ascending. Index into this for comparisons; never compare severity strings.
SEVERITY_ORDER: tuple[str, ...] = ("none", "low", "medium", "high", "critical")

SEVERITY_RANK: dict[str, int] = {name: index for index, name in enumerate(SEVERITY_ORDER)}

# The stored levels, for callers that need to talk to the database.
STORED_LEVELS: tuple[str, ...] = ("none", "low", "medium", "high")

# --- the critical rule ------------------------------------------------------
# `critical` means "strong evidence AND the clock is running": a stored `high`
# whose evidence is solid and whose obligation commences inside the window (or
# already has).
#
# An earlier draft also escalated on `change_type in (threshold, duration,
# obligation)`. That was dropped after running it against the corpus: those
# three types cover nearly every real regulatory change, so the branch marked
# 100% of impacts critical and the tier carried no information. Severity here
# tracks urgency, which is what a reviewer actually triages on; how serious the
# *kind* of change is already lives in `impact_level`.
#
# These two constants are the entire product judgement in this module.
CRITICAL_MIN_CONFIDENCE = 0.9
CRITICAL_DEADLINE_DAYS = 30


def _get(row: Mapping[str, Any] | sqlite3.Row | None, key: str, default: Any = None) -> Any:
    """Read a column from either a sqlite3.Row or a plain dict.

    Callers pass whichever they already have; sqlite3.Row raises IndexError
    rather than returning None for an absent column, so this normalises both.
    """
    if row is None:
        return default
    if isinstance(row, sqlite3.Row):
        return row[key] if key in row.keys() else default
    return row.get(key, default)


def _parse_date(value: Any) -> date | None:
    """Parse an ISO date or datetime string; None if absent or unparseable.

    Effective dates arrive as either `2026-04-01` or a full timestamp
    depending on whether they came from extraction or from a seed file.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def days_until(value: Any, *, today: date | None = None) -> int | None:
    """Whole days from today until `value`. Negative once it has passed."""
    parsed = _parse_date(value)
    if parsed is None:
        return None
    reference = today or datetime.now(timezone.utc).date()
    return (parsed - reference).days


def derive_severity(
    impact: Mapping[str, Any] | sqlite3.Row,
    change: Mapping[str, Any] | sqlite3.Row | None = None,
    *,
    today: date | None = None,
) -> str:
    """Return one of SEVERITY_ORDER for a stored impact row.

    `change` is the parent `regulatory_changes` row when the caller has it.
    Without it the impact can never escalate past its stored level, which is
    the safe direction: severity may be under-stated by a missing join, never
    over-stated.
    """
    level = _get(impact, "impact_level") or "none"
    if level != "high":
        return level if level in SEVERITY_RANK else "none"

    confidence = _get(impact, "confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < CRITICAL_MIN_CONFIDENCE:
        return "high"

    if change is None:
        return "high"

    remaining = days_until(_get(change, "effective_date"), today=today)
    # An already-commenced obligation is at least as urgent as an imminent one.
    # A change with no stated effective date cannot be shown to be urgent, so
    # it stays `high` rather than being escalated on a guess.
    if remaining is not None and remaining <= CRITICAL_DEADLINE_DAYS:
        return "critical"

    return "high"


def max_severity(values: Iterable[str | None]) -> str:
    """Highest severity in `values`, or 'none' when empty."""
    best = "none"
    for value in values:
        if value and SEVERITY_RANK.get(value, 0) > SEVERITY_RANK[best]:
            best = value
    return best


def is_open_severity(value: str | None) -> bool:
    """True when the severity represents something a person still must read."""
    return SEVERITY_RANK.get(value or "none", 0) >= SEVERITY_RANK["low"]


def counts_template() -> dict[str, int]:
    """A zeroed count bucket per severity, so a screen never omits a level."""
    return {name: 0 for name in SEVERITY_ORDER}
