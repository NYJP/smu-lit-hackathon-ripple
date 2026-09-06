"""Display-PDF rendering for uploads that are not already PDFs.

`GET /files/documents/{id}` serves the original upload byte for byte, which
is what the download button needs. A browser can only *display* a PDF,
though, so the reader used to embed a page view for PDF uploads and show
nothing at all for the .docx and .txt files that make up most of a real
corpus. This module renders those into a PDF and caches it beside the
original, so every document gets the same viewer.

The rendered file is a display artefact, never a replacement. The original
is untouched, `documents.file_path` still points at it, and parsing,
chunking, and evidence offsets all continue to run off the original. The
page is laid out from the same chunks the clause rail shows, so an evidence
span highlighted in the rail is present verbatim in the rendered text and
the viewer's quotation search can find it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Mapping
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from api.services import parsing, storage

PDF_MIME_TYPE = "application/pdf"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    body = ParagraphStyle(
        "ripple_body", parent=base, fontName="Helvetica",
        fontSize=9.5, leading=13.5, spaceAfter=6,
    )
    return {
        "title": ParagraphStyle(
            "ripple_title", parent=body, fontName="Helvetica-Bold",
            fontSize=14, leading=18, spaceAfter=12,
        ),
        "heading": ParagraphStyle(
            "ripple_heading", parent=body, fontName="Helvetica-Bold",
            fontSize=10.5, leading=14, spaceBefore=10, spaceAfter=5,
        ),
        "paragraph": body,
        "list_item": ParagraphStyle("ripple_list", parent=body, leftIndent=10),
    }


def _flowables(chunks: list[parsing.ChunkRecord], title: str) -> list:
    styles = _styles()
    flow = [Paragraph(escape(title), styles["title"])]
    for chunk in chunks:
        style = styles["heading"] if chunk.chunk_type == "heading" else styles.get(chunk.chunk_type, styles["paragraph"])
        for line in chunk.content.splitlines():
            text = line.strip()
            if not text:
                flow.append(Spacer(1, 4))
                continue
            flow.append(Paragraph(escape(text), style))
    return flow


def _render(source: Path, mime_type: str, title: str, target: Path) -> None:
    parsed = parsing.parse_and_chunk_document(source, mime_type)
    target.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(target), pagesize=A4, title=title,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    ).build(_flowables(parsed.chunks, title))


def display_pdf(document: Mapping[str, object] | sqlite3.Row) -> Path:
    """Absolute path to a PDF that can be embedded for `document`.

    Returns the original file when it is already a PDF. Otherwise renders one
    on first request and reuses it until the source file changes, so the
    common case costs a stat call rather than a re-render.
    """
    source = storage.absolute_path(str(document["file_path"]))
    if str(document["mime_type"]) == PDF_MIME_TYPE:
        return source
    target = source.with_suffix(".display.pdf")
    if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
        _render(source, str(document["mime_type"]), str(document["name"]), target)
    return target
