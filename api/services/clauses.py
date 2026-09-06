"""Naming and quoting the passage an impact points at.

Every screen that lists a finding has to answer "where in the document is
this?". The obvious answer, `document_chunks.section_path`, is populated for
only about a third of a real corpus — parsing lifts a heading into structured
metadata when the file's styles make that possible, and silently does not when
they do not. Rendering the absence directly gives a review queue in which every
row is titled "Section unavailable", which locates nothing.

The heading is usually still *there*, just as text inside the chunk. A chunk
often spans several numbered sections, so the useful label is not the chunk's
first line — it is the nearest numbered heading at or above the affected span:

    3 Regulatory assessment
    The Privacy Office determines whether harm is likely, ...

    4 Notification
    Notifiable breaches must be reported within [72 hours] ...
                                                 ^ the impact
    -> "4 Notification", not "3 Regulatory assessment"

Nothing here is invented: a derived label is a line copied verbatim out of the
document being described. Structured metadata still wins when it exists, so a
document that parsed cleanly is unaffected by any of this.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Mapping

# A numbered heading: "4 Notification", "7.1 Retention Period", "2.3.1 Scope".
# Deliberately narrow. A looser rule (short line, title case) matches ordinary
# sentence fragments and would put misleading text in a locator, which is worse
# than saying nothing.
_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(\S.{0,78})$")

# Sentence-terminal punctuation disqualifies a line: "1 in 4 records were
# retained." is prose that happens to start with a digit, not a heading.
_TERMINATORS = (".", ";", ",", ":")

MAX_EXCERPT = 220


def _get(row: Mapping[str, Any] | sqlite3.Row | None, key: str, default: Any = None) -> Any:
    """Read a column from either a sqlite3.Row or a plain dict."""
    if row is None:
        return default
    if isinstance(row, sqlite3.Row):
        return row[key] if key in row.keys() else default
    return row.get(key, default)


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.endswith(_TERMINATORS):
        return False
    return bool(_HEADING.match(stripped))


def derive_heading(content: str, position: int | None) -> str | None:
    """The nearest numbered heading at or above `position` in `content`.

    `position` is a character offset — the start of the affected span. With no
    offset, the chunk's first heading is the best available answer.
    """
    if not content:
        return None

    headings: list[tuple[int, str]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        if _is_heading(line):
            headings.append((offset, line.strip()))
        offset += len(line)
    if not headings:
        return None

    # Without a span we cannot say which section inside the chunk is meant, and
    # the whole passage is being shown anyway — so name where it begins. The
    # *last* heading would name the tail of what the reader is looking at.
    if position is None:
        return headings[0][1]

    limit = max(0, min(position, len(content)))
    preceding = [text for start, text in headings if start <= limit]
    # No heading precedes the span; the first one still names the passage the
    # reader is being shown, which beats naming nothing.
    return preceding[-1] if preceding else headings[0][1]


def clause_label(
    chunk: Mapping[str, Any] | sqlite3.Row,
    *,
    position: int | None = None,
) -> str:
    """Where this passage sits, in the most specific terms available.

    Precedence: parsed `section_path` -> parsed `section_title` -> a heading
    derived from the chunk's own text -> the chunk's position in the document.
    Always returns something a reader can act on; never "unavailable".
    """
    for key in ("section_path", "section_title"):
        value = _get(chunk, key)
        if value and str(value).strip():
            return str(value).strip()

    derived = derive_heading(str(_get(chunk, "content") or ""), position)
    if derived:
        return derived

    ordinal = _get(chunk, "ordinal")
    if isinstance(ordinal, int):
        return f"Clause {ordinal + 1}"
    return "Untitled passage"


def clause_excerpt(
    content: str | None,
    start: int | None = None,
    end: int | None = None,
    *,
    limit: int = MAX_EXCERPT,
) -> str:
    """The sentence around the affected span, for scanning a list of findings.

    A queue row needs the words that are wrong, not the first `n` characters of
    whatever chunk they landed in. Falls back to the head of the passage when
    there is no span to centre on.
    """
    text = (content or "").strip()
    if not text:
        return ""
    if start is None or end is None or not (0 <= start < end <= len(content or "")):
        return _clip(" ".join(text.split()), limit)

    # Widen to sentence boundaries around the span, then clip symmetrically.
    left = max(
        (content.rfind(mark, 0, start) for mark in (". ", "\n", "? ", "! ")),
        default=-1,
    )
    right_candidates = [
        index for index in (
            content.find(mark, end) for mark in (". ", "\n", "? ", "! ")
        ) if index != -1
    ]
    right = min(right_candidates) + 1 if right_candidates else len(content)
    sentence = content[left + 1 if left != -1 else 0 : right].strip()
    return _clip(" ".join(sentence.split()), limit)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
