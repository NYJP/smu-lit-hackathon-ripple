"""PDF/DOCX/TXT parsing and chunking (PRD section 7.1 and section 7.3).

Two entry points:

  * `parse_regulation_pdf(path)` — section 7.1. Page-numbered text with
    detected section headings, and the scanned-PDF check. This wave stops
    at parsed text; requirement extraction (section 7.2) is wave 3, so
    nothing here calls OpenAI or produces a `regulatory_requirements` row.

  * `parse_and_chunk_document(path, mime_type)` — section 7.3. Turns an
    internal document (PDF, DOCX, or TXT) into an ordered list of
    `ChunkRecord`s ready to insert into `document_chunks`, with
    `section_path` breadcrumbs, `char_start`/`char_end` offsets, and the
    merge/hard-split thresholds already applied.

Both PDF paths (regulations and internal documents) share the same
section-heading regex ladder and the same scanned-PDF detection, since both
are pymupdf extractions of the same kind of input. DOCX gets its headings
from paragraph styles instead (there is no regex ladder to run), and TXT
gets them from the same regex ladder as PDF, applied to plain lines.
"""

from __future__ import annotations

import re
from math import ceil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz  # pymupdf
from docx import Document as DocxDocument
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

# ---------------------------------------------------------------- errors --


class ScannedPdfError(Exception):
    """Raised when a PDF fails the scanned-document check (section 7.1,
    acceptance criterion 7). The message is the literal user-facing string
    that becomes `jobs.error_message` / `{regulations,documents}.error_message`
    — never reworded, so the UI and this module agree on what it says."""


SCANNED_PDF_MESSAGE = "Scanned PDF — OCR is not supported in the MVP"

# Below this many characters of extracted text, a page counts as "yielded
# nothing" for the scanned-PDF check (section 7.1).
_SCANNED_PAGE_CHAR_THRESHOLD = 40
# At or above this fraction of such pages, the whole PDF is treated as scanned.
_SCANNED_PAGE_FRACTION = 0.30

# A line recurring on at least this fraction of pages is a repeated
# header/footer and is dropped before section detection (section 7.1).
_REPEATED_LINE_FRACTION = 0.60

# --------------------------------------------------------- section ladder --

# The regex ladder (section 7.1), run in order; the first pattern that
# matches a line's stripped text wins. Index in this list doubles as a
# heading "level" for section_path breadcrumbs in section 7.3 — a lower
# index is a broader heading (e.g. "Part IV" outranks "Section 12").
SECTION_HEADING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(Part|PART)\s+[IVXLC]+\b"),
    re.compile(r"^\d+\.(\d+)*"),
    re.compile(r"^\(\d+\)"),
    re.compile(r"^\([a-z]\)"),
    re.compile(r"^(Section|Reg\.|Regulation|Article)\s+\d+", re.IGNORECASE),
]


def _match_heading_level(line: str) -> int | None:
    """Return the ladder index of the first pattern matching `line`, or
    None if it matches none of them."""
    stripped = line.strip()
    if not stripped:
        return None
    for level, pattern in enumerate(SECTION_HEADING_PATTERNS):
        if pattern.match(stripped):
            return level
    return None


# -------------------------------------------------------------- PDF pages --


def _extract_raw_pages(path: Path) -> list[str]:
    """One text string per page, in reading order, via pymupdf."""
    with fitz.open(str(path)) as doc:
        return [page.get_text("text") for page in doc]


def _find_repeated_lines(pages: list[str]) -> set[str]:
    """Lines recurring on >= 60% of pages — repeated headers/footers
    (section 7.1). Compared on stripped text so trailing whitespace or page
    numbers glued to an otherwise-identical line don't defeat detection."""
    # A line cannot recur in a one-page document. Treating every line as a
    # header there would erase the entire source before chunking.
    if len(pages) < 2:
        return set()
    counts: Counter[str] = Counter()
    for page_text in pages:
        lines_on_page = {ln.strip() for ln in page_text.splitlines() if ln.strip()}
        counts.update(lines_on_page)
    threshold = max(1, ceil(len(pages) * _REPEATED_LINE_FRACTION))
    return {line for line, count in counts.items() if count >= threshold}


def is_scanned(pages: list[str]) -> bool:
    """Section 7.1 / acceptance criterion 7: >= 30% of pages yield under 40
    characters of extracted text => treat the PDF as scanned."""
    if not pages:
        return True
    short_pages = sum(1 for p in pages if len(p.strip()) < _SCANNED_PAGE_CHAR_THRESHOLD)
    return (short_pages / len(pages)) >= _SCANNED_PAGE_FRACTION


@dataclass
class RegulationPage:
    page_number: int  # 1-based
    text: str  # header/footer lines stripped
    current_section: str | None  # most recent heading-ladder match, carried forward


@dataclass
class RegulationParseResult:
    pages: list[RegulationPage]
    page_count: int


def parse_regulation_pdf(path: Path) -> RegulationParseResult:
    """Section 7.1: page-numbered text with detected section headings.

    Raises `ScannedPdfError` (with the exact required message) rather than
    returning a result when the scanned-PDF check trips — the caller must
    never persist a "successful" empty parse.
    """
    raw_pages = _extract_raw_pages(path)
    if is_scanned(raw_pages):
        raise ScannedPdfError(SCANNED_PDF_MESSAGE)

    repeated = _find_repeated_lines(raw_pages)
    pages: list[RegulationPage] = []
    current_section: str | None = None
    for index, raw_text in enumerate(raw_pages):
        kept_lines = [ln for ln in raw_text.splitlines() if ln.strip() not in repeated]
        for ln in kept_lines:
            if _match_heading_level(ln) is not None:
                current_section = ln.strip()
        pages.append(
            RegulationPage(
                page_number=index + 1,
                text="\n".join(kept_lines),
                current_section=current_section,
            )
        )
    return RegulationParseResult(pages=pages, page_count=len(raw_pages))


# --------------------------------------------------------- document chunks --

ChunkType = Literal["paragraph", "heading", "list_item", "table_row", "other"]

# Section 7.3 thresholds.
_MERGE_UNDER_CHARS = 200
_HARD_SPLIT_OVER_CHARS = 1500

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass
class _Block:
    """One raw unit of content before merge/split is applied: a paragraph,
    list item, table row, or heading, still tagged with its heading level
    (headings only) so the breadcrumb stack can be rebuilt."""

    kind: ChunkType
    text: str
    page_number: int | None
    source_start: int
    source_end: int
    heading_level: int | None = None


@dataclass
class ChunkRecord:
    ordinal: int
    content: str
    section_path: str | None
    section_title: str | None
    page_number: int | None
    char_start: int
    char_end: int
    chunk_type: ChunkType


@dataclass
class DocumentParseResult:
    chunks: list[ChunkRecord]
    page_count: int | None


def _blocks_from_pdf(path: Path) -> tuple[list[_Block], int, str]:
    """Extract PDF blocks with offsets into the unmodified full PDF text.

    PDF producers commonly place a section heading and its body on consecutive
    lines, rather than separating them with an empty line.  Treating a heading
    as a line-level boundary preserves that structure and lets the following
    body block inherit the section path.  The text stored in each block is a
    direct slice of the original extraction, so its source range remains useful
    even after a later merge or split.
    """
    raw_pages = _extract_raw_pages(path)
    if is_scanned(raw_pages):
        raise ScannedPdfError(SCANNED_PDF_MESSAGE)
    repeated = _find_repeated_lines(raw_pages)
    full_text = "\n".join(raw_pages)

    blocks: list[_Block] = []
    page_offset = 0
    for page_index, raw_text in enumerate(raw_pages):
        page_number = page_index + 1
        current_start: int | None = None
        current_end: int | None = None

        def flush_paragraph() -> None:
            nonlocal current_start, current_end
            if current_start is None or current_end is None:
                return
            blocks.append(
                _Block(
                    "paragraph",
                    raw_text[current_start:current_end],
                    page_number,
                    page_offset + current_start,
                    page_offset + current_end,
                )
            )
            current_start = current_end = None

        line_offset = 0
        for line in raw_text.splitlines(keepends=True):
            without_newline = line.rstrip("\r\n")
            stripped = without_newline.strip()
            left_trim = len(without_newline) - len(without_newline.lstrip())
            line_start = line_offset + left_trim
            line_end = line_start + len(stripped)
            line_offset += len(line)
            if not stripped or stripped in repeated:
                flush_paragraph()
                continue
            level = _match_heading_level(stripped)
            if level is not None:
                flush_paragraph()
                blocks.append(
                    _Block("heading", stripped, page_number, page_offset + line_start, page_offset + line_end, level)
                )
                continue
            if current_start is None:
                current_start = line_start
            current_end = line_end
        flush_paragraph()
        page_offset += len(raw_text) + 1
    return blocks, len(raw_pages), full_text


_DOCX_HEADING_STYLE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)
_DOCX_LIST_STYLE = re.compile(r"list", re.IGNORECASE)


def _blocks_from_docx(path: Path) -> tuple[list[_Block], str]:
    """DOCX -> python-docx (section 7.3): paragraph styles Heading 1..6
    build section_path; tables are read row by row. Reads body elements in
    document order so table rows land where they actually appear rather
    than all at the end."""
    doc = DocxDocument(str(path))
    blocks: list[_Block] = []
    source_parts: list[str] = []
    source_offset = 0

    def append(kind: ChunkType, text: str, heading_level: int | None = None) -> None:
        nonlocal source_offset
        if source_parts:
            source_parts.append("\n\n")
            source_offset += 2
        start = source_offset
        source_parts.append(text)
        source_offset += len(text)
        blocks.append(_Block(kind, text, None, start, source_offset, heading_level))

    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            para = DocxParagraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style_name = para.style.name if para.style is not None else ""
            heading_match = _DOCX_HEADING_STYLE.match(style_name or "")
            if heading_match:
                level = max(0, int(heading_match.group(1)) - 1)
                append("heading", text, level)
            elif _DOCX_LIST_STYLE.search(style_name or ""):
                append("list_item", text)
            else:
                append("paragraph", text)
        elif child.tag.endswith("}tbl"):
            table = DocxTable(child, doc)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                row_text = " | ".join(c for c in cells if c)
                if row_text:
                    append("table_row", row_text)
    return blocks, "".join(source_parts)


def _blocks_from_txt(path: Path) -> tuple[list[_Block], str]:
    """TXT -> split on blank lines (section 7.3). The same heading ladder
    used for PDFs still applies, since a plain-text export of a numbered
    regulation or policy carries the same numbering conventions."""
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks: list[_Block] = []
    for match in re.finditer(r"(?s)\S(?:.*?\S)?(?=\s*\n\s*\n|\s*\Z)", text):
        para = match.group(0)
        if not para.strip():
            continue
        first_line = para.splitlines()[0]
        level = _match_heading_level(first_line)
        if level is not None and len(para.splitlines()) == 1:
            blocks.append(_Block("heading", para, None, match.start(), match.end(), level))
        else:
            blocks.append(_Block("paragraph", para, None, match.start(), match.end()))
    return blocks, text


def _split_block(block: _Block) -> list[_Block]:
    """Split a source-faithful block without inventing reconstructed offsets."""
    if len(block.text) <= _HARD_SPLIT_OVER_CHARS:
        return [block]

    pieces: list[_Block] = []
    start = 0
    text = block.text
    while start < len(text):
        hard_end = min(start + _HARD_SPLIT_OVER_CHARS, len(text))
        if hard_end == len(text):
            end = hard_end
            next_start = end
        else:
            boundaries = list(_SENTENCE_BOUNDARY.finditer(text, start, hard_end + 1))
            if boundaries:
                boundary = boundaries[-1]
                end = boundary.start()
                next_start = boundary.end()
            else:
                end = hard_end
                next_start = end
        if end == start:
            end = hard_end
            next_start = end
        pieces.append(
            _Block(
                block.kind,
                text[start:end],
                block.page_number,
                block.source_start + start,
                block.source_start + end,
                block.heading_level,
            )
        )
        start = next_start
    return pieces


def _build_chunks(blocks: list[_Block], source_text: str) -> list[ChunkRecord]:
    """Section 7.3: breadcrumbs, the merge-under-200 and hard-split-over-1500
    thresholds, and char_start/char_end against the original extracted text.

    Merge direction is forward-only, matching the PRD's literal wording
    ("merge chunks under 200 characters into the following chunk"): a short
    paragraph/list_item/table_row is folded into the next non-heading
    chunk. A short chunk immediately before a heading, or at the end of the
    document, has nothing valid to merge into and is kept as-is — merging
    it backward, or into the heading itself, isn't what the PRD says and
    would corrupt the heading's own boundary.
    """
    # Pass 1: forward-merge short non-heading blocks. A heading never
    # participates in the loop below (excluded by the guard) — a merge run
    # can only ever absorb chunks up to, never including, the next heading,
    # so a heading is never silently dropped by this pass.
    merged: list[_Block] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.kind == "heading" or len(block.text) >= _MERGE_UNDER_CHARS:
            merged.append(block)
            i += 1
            continue

        combined = block
        combined_kind = block.kind
        last_absorbed = i
        k = i + 1
        while (
            k < len(blocks)
            and blocks[k].kind != "heading"
            and len(combined.text) < _MERGE_UNDER_CHARS
            and blocks[k].page_number == combined.page_number
            and not source_text[combined.source_end:blocks[k].source_start].strip()
        ):
            next_block = blocks[k]
            combined_kind = next_block.kind
            combined = _Block(
                combined_kind,
                source_text[combined.source_start:next_block.source_end],
                combined.page_number,
                combined.source_start,
                next_block.source_end,
            )
            last_absorbed = k
            k += 1
        merged.append(combined)
        i = last_absorbed + 1

    # Pass 2: hard-split anything still over 1500 chars, headings included
    # only in principle — in practice a heading line never reaches this
    # length, so this only ever fires for content chunks.
    split_blocks: list[_Block] = []
    for block in merged:
        split_blocks.extend(_split_block(block))

    # Pass 3: breadcrumbs + offsets.
    records: list[ChunkRecord] = []
    stack: list[tuple[int, str]] = []  # (level, heading text)
    for ordinal, block in enumerate(split_blocks):
        parent_path = " > ".join(text for _, text in stack) or None
        nearest_heading = stack[-1][1] if stack else None

        if block.kind == "heading":
            records.append(
                ChunkRecord(
                    ordinal=ordinal,
                    content=block.text,
                    section_path=parent_path,
                    section_title=block.text,
                    page_number=block.page_number,
                    char_start=block.source_start,
                    char_end=block.source_end,
                    chunk_type="heading",
                )
            )
            level = block.heading_level if block.heading_level is not None else len(SECTION_HEADING_PATTERNS)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, block.text))
        else:
            records.append(
                ChunkRecord(
                    ordinal=ordinal,
                    content=block.text,
                    section_path=parent_path,
                    section_title=nearest_heading,
                    page_number=block.page_number,
                    char_start=block.source_start,
                    char_end=block.source_end,
                    chunk_type=block.kind,
                )
            )
    return records


def parse_and_chunk_document(path: Path, mime_type: str) -> DocumentParseResult:
    """Section 7.3 entry point. Dispatches on `mime_type` (set from the
    upload's file extension by the caller — see api/services/storage.py)."""
    if mime_type == "application/pdf":
        blocks, page_count, source_text = _blocks_from_pdf(path)
    elif mime_type == "text/plain":
        blocks, source_text = _blocks_from_txt(path)
        page_count = None
    elif mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        blocks, source_text = _blocks_from_docx(path)
        page_count = None
    else:
        raise ValueError(f"Unsupported mime type for chunking: {mime_type}")

    chunks = _build_chunks(blocks, source_text)
    return DocumentParseResult(chunks=chunks, page_count=page_count)
