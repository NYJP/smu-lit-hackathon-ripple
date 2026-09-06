"""Naming the passage an impact points at (api/services/clauses.py).

The review queue used to title every row "Section unavailable", because only
about a third of a real corpus carries a parsed `section_path`. The heading is
usually still present as text inside the chunk, so these tests pin the two
things that makes safe: the derived label is a line copied verbatim out of the
document, and structured metadata always wins over derivation.
"""

from __future__ import annotations

from api.services import clauses

# The shape that broke the queue: one chunk spanning several numbered sections,
# with no parsed section metadata at all. Taken from the PDPF corpus.
BREACH_CHUNK = (
    "3 Regulatory assessment\n"
    "The Privacy Office determines whether harm is likely, records the categories "
    "and approximate volume of affected data, and identifies affected individuals.\n"
    "\n"
    "4 Notification\n"
    "Notifiable personal-data breaches must be reported to the regulator within "
    "72 hours after confirmation. The incident lead prepares the chronology."
)


def test_label_prefers_parsed_section_path():
    """A document that parsed cleanly is unaffected by any derivation."""
    chunk = {
        "section_path": "7 Retention and Disposal > 7.1 Retention Period",
        "section_title": "7.1 Retention Period",
        "content": BREACH_CHUNK,
        "ordinal": 5,
    }
    assert clauses.clause_label(chunk) == "7 Retention and Disposal > 7.1 Retention Period"


def test_label_falls_back_to_section_title():
    chunk = {"section_path": None, "section_title": "7.1 Retention Period", "content": "", "ordinal": 5}
    assert clauses.clause_label(chunk) == "7.1 Retention Period"


def test_label_uses_the_heading_above_the_affected_span_not_the_first_one():
    """The chunk spans two sections; the label must name the right one.

    `72 hours` sits under "4 Notification". Labelling it "3 Regulatory
    assessment" — the chunk's first heading — would point a reviewer at the
    wrong part of their own document.
    """
    chunk = {"section_path": None, "section_title": None, "content": BREACH_CHUNK, "ordinal": 1}
    position = BREACH_CHUNK.index("72 hours")
    assert clauses.clause_label(chunk, position=position) == "4 Notification"


def test_label_with_no_span_uses_the_first_heading():
    chunk = {"section_path": None, "section_title": None, "content": BREACH_CHUNK, "ordinal": 1}
    assert clauses.clause_label(chunk) == "3 Regulatory assessment"


def test_label_falls_back_to_position_when_there_is_no_heading_at_all():
    chunk = {
        "section_path": None,
        "section_title": None,
        "content": "Records are retained for five years. No headings here.",
        "ordinal": 3,
    }
    assert clauses.clause_label(chunk) == "Clause 4"


def test_label_is_never_the_word_unavailable():
    """The regression this module exists to prevent."""
    for chunk in (
        {"section_path": None, "section_title": None, "content": "", "ordinal": 0},
        {"section_path": "", "section_title": "  ", "content": "", "ordinal": 2},
        {"section_path": None, "section_title": None, "content": BREACH_CHUNK, "ordinal": 1},
    ):
        label = clauses.clause_label(chunk)
        assert label and "unavailable" not in label.lower()


def test_derived_headings_are_verbatim_lines_from_the_document():
    """Never synthesise a locator — it must be findable by Ctrl-F in the file."""
    label = clauses.clause_label(
        {"section_path": None, "section_title": None, "content": BREACH_CHUNK, "ordinal": 1},
        position=BREACH_CHUNK.index("72 hours"),
    )
    assert label in BREACH_CHUNK


def test_prose_starting_with_a_digit_is_not_mistaken_for_a_heading():
    """"1 in 4 records were retained." is a sentence, not a section title."""
    content = "1 in 4 records were retained for 5 years beyond the stated period."
    assert clauses.derive_heading(content, None) is None


def test_a_heading_ending_in_punctuation_is_rejected():
    assert clauses.derive_heading("4 Notification, escalation and review of the,", None) is None


def test_excerpt_centres_on_the_affected_sentence():
    """A queue row needs the words that are wrong, not the chunk's first line."""
    start = BREACH_CHUNK.index("72 hours")
    excerpt = clauses.clause_excerpt(BREACH_CHUNK, start, start + len("72 hours"))
    assert "72 hours" in excerpt
    assert excerpt.startswith("Notifiable personal-data breaches")
    # The unrelated earlier section must not bleed in.
    assert "Regulatory assessment" not in excerpt


def test_excerpt_without_a_span_falls_back_to_the_head_of_the_passage():
    excerpt = clauses.clause_excerpt(BREACH_CHUNK, None, None)
    assert excerpt.startswith("3 Regulatory assessment")


def test_excerpt_is_clipped_and_whitespace_normalised():
    long_text = "A" + " word" * 200
    excerpt = clauses.clause_excerpt(long_text, None, None, limit=60)
    assert len(excerpt) <= 60
    assert excerpt.endswith("…")
    assert "\n" not in clauses.clause_excerpt("one\n\n  two   three", None, None)


def test_excerpt_of_empty_content_is_empty():
    assert clauses.clause_excerpt(None) == ""
    assert clauses.clause_excerpt("   ") == ""


def test_out_of_range_spans_degrade_rather_than_slice_wrongly():
    assert clauses.clause_excerpt(BREACH_CHUNK, 5, 2).startswith("3 Regulatory assessment")
    assert clauses.clause_excerpt(BREACH_CHUNK, 0, 99_999).startswith("3 Regulatory assessment")
