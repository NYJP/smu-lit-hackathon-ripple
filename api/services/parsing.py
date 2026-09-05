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
from dataclasses import dataclass, field
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
    if not pages:
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


def _blocks_from_pdf(path: Path) -> tuple[list[_Block], int]:
    """PDF -> pymupdf (section 7.3). Paragraphs are blank-line-separated runs
    of text within a page; a paragraph whose first line matches the section
    7.1 regex ladder becomes a heading block instead."""
    raw_pages = _extract_raw_pages(path)
    if is_scanned(raw_pages):
        raise ScannedPdfError(SCANNED_PDF_MESSAGE)
    repeated = _find_repeated_lines(raw_pages)

    blocks: list[_Block] = []
    for page_index, raw_text in enumerate(raw_pages):
        page_number = page_index + 1
        kept_lines = [ln for ln in raw_text.splitlines() if ln.strip() not in repeated]
        cleaned = "\n".join(kept_lines)
        for para in re.split(r"\n\s*\n", cleaned):
            para = para.strip()
            if not para:
                continue
            first_line = para.splitlines()[0]
            level = _match_heading_level(first_line)
            if level is not None and len(para.splitlines()) == 1:
                blocks.append(_Block("heading", para, page_number, level))
            else:
                normalised = " ".join(line.strip() for line in para.splitlines() if line.strip())
                blocks.append(_Block("paragraph", normalised, page_number))
    return blocks, len(raw_pages)


_DOCX_HEADING_STYLE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)
_DOCX_LIST_STYLE = re.compile(r"list", re.IGNORECASE)


def _blocks_from_docx(path: Path) -> list[_Block]:
    """DOCX -> python-docx (section 7.3): paragraph styles Heading 1..6
    build section_path; tables are read row by row. Reads body elements in
    document order so table rows land where they actually appear rather
    than all at the end."""
    doc = DocxDocument(str(path))
    blocks: list[_Block] = []
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
                blocks.append(_Block("heading", text, None, level))
            elif _DOCX_LIST_STYLE.search(style_name or ""):
                blocks.append(_Block("list_item", text, None))
            else:
                blocks.append(_Block("paragraph", text, None))
        elif child.tag.endswith("}tbl"):
            table = DocxTable(child, doc)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                row_text = " | ".join(c for c in cells if c)
                if row_text:
                    blocks.append(_Block("table_row", row_text, None))
    return blocks


def _blocks_from_txt(path: Path) -> list[_Block]:
    """TXT -> split on blank lines (section 7.3). The same heading ladder
    used for PDFs still applies, since a plain-text export of a numbered
    regulation or policy carries the same numbering conventions."""
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks: list[_Block] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        first_line = para.splitlines()[0]
        level = _match_heading_level(first_line)
        if level is not None and len(para.splitlines()) == 1:
            blocks.append(_Block("heading", para, None, level))
        else:
            normalised = " ".join(line.strip() for line in para.splitlines() if line.strip())
            blocks.append(_Block("paragraph", normalised, None))
    return blocks


def _sentence_split(text: str, limit: int) -> list[str]:
    """Break `text` into pieces no longer than `limit`, at sentence
    boundaries where possible (section 7.3 hard-split). Falls back to a
    hard character cut for a single sentence longer than the limit, so this
    always terminates and never returns an empty piece for non-empty input."""
    sentences = _SENTENCE_BOUNDARY.split(text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(sentence) <= limit:
            current = sentence
        else:
            # A single sentence longer than the limit: hard character cut.
            for start in range(0, len(sentence), limit):
                pieces.append(sentence[start : start + limit])
            current = ""
    if current:
        pieces.append(current)
    return pieces or [text]


def _build_chunks(blocks: list[_Block]) -> list[ChunkRecord]:
    """Section 7.3: breadcrumbs, the merge-under-200 and hard-split-over-1500
    thresholds, and char_start/char_end against the concatenated full text.

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

        combined_text = block.text
        combined_kind = block.kind
        last_absorbed = i
        k = i + 1
        while k < len(blocks) and blocks[k].kind != "heading" and len(combined_text) < _MERGE_UNDER_CHARS:
            combined_text = f"{combined_text} {blocks[k].text}".strip()
            combined_kind = blocks[k].kind
            last_absorbed = k
            k += 1
        merged.append(_Block(combined_kind, combined_text, block.page_number))
        i = last_absorbed + 1

    # Pass 2: hard-split anything still over 1500 chars, headings included
    # only in principle — in practice a heading line never reaches this
    # length, so this only ever fires for content chunks.
    split_blocks: list[_Block] = []
    for block in merged:
        if len(block.text) <= _HARD_SPLIT_OVER_CHARS:
            split_blocks.append(block)
        else:
            for piece in _sentence_split(block.text, _HARD_SPLIT_OVER_CHARS):
                split_blocks.append(_Block(block.kind, piece, block.page_number, block.heading_level))

    # Pass 3: breadcrumbs + offsets.
    records: list[ChunkRecord] = []
    stack: list[tuple[int, str]] = []  # (level, heading text)
    offset = 0
    for ordinal, block in enumerate(split_blocks):
        parent_path = " > ".join(text for _, text in stack) or None
        nearest_heading = stack[-1][1] if stack else None

        start = offset
        end = start + len(block.text)
        offset = end + 2  # matches the "\n\n" join used to reconstruct full text

        if block.kind == "heading":
            records.append(
                ChunkRecord(
                    ordinal=ordinal,
                    content=block.text,
                    section_path=parent_path,
                    section_title=block.text,
                    page_number=block.page_number,
                    char_start=start,
                    char_end=end,
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
                    char_start=start,
                    char_end=end,
                    chunk_type=block.kind,
                )
            )
    return records


def parse_and_chunk_document(path: Path, mime_type: str) -> DocumentParseResult:
    """Section 7.3 entry point. Dispatches on `mime_type` (set from the
    upload's file extension by the caller — see api/services/storage.py)."""
    if mime_type == "application/pdf":
        blocks, page_count = _blocks_from_pdf(path)
    elif mime_type == "text/plain":
        blocks, page_count = _blocks_from_txt(path), None
    elif mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        blocks, page_count = _blocks_from_docx(path), None
    else:
        raise ValueError(f"Unsupported mime type for chunking: {mime_type}")

    chunks = _build_chunks(blocks)
    return DocumentParseResult(chunks=chunks, page_count=page_count)
