"""Severity derivation (api/services/severity.py).

`critical` is a reading of a stored `high`, not a stored level of its own.
These tests pin the two properties that matter: it never contradicts what the
model actually returned, and it never escalates on weak evidence.
"""

from __future__ import annotations

from datetime import date

import pytest

from api.services import severity


def _impact(level: str = "high", confidence: float = 1.0) -> dict:
    return {"impact_level": level, "confidence": confidence}


def _change(change_type: str = "editorial", effective_date: str | None = None) -> dict:
    return {"change_type": change_type, "effective_date": effective_date}


TODAY = date(2026, 3, 1)


def test_stored_levels_below_high_pass_through_untouched():
    """Fail if a medium or low is ever reported as something else."""
    for level in ("none", "low", "medium"):
        assert severity.derive_severity(_impact(level), _change("threshold")) == level


def test_high_escalates_to_critical_on_an_imminent_deadline():
    soon = _change("duration", "2026-03-20")   # 19 days out
    assert severity.derive_severity(_impact(), soon, today=TODAY) == "critical"


def test_a_deadline_already_passed_is_still_critical():
    """Fail if an overdue obligation quietly de-escalates."""
    overdue = _change("duration", "2026-01-01")
    assert severity.derive_severity(_impact(), overdue, today=TODAY) == "critical"


def test_a_distant_deadline_stays_high():
    far = _change("duration", "2027-01-01")
    assert severity.derive_severity(_impact(), far, today=TODAY) == "high"


def test_change_type_alone_never_escalates():
    """Regression guard for the rule this replaced.

    `threshold` / `duration` / `obligation` cover nearly every real change, so
    escalating on the type alone marked 100% of the corpus critical. Urgency
    must come from the deadline, never from the kind of change.
    """
    for change_type in ("threshold", "duration", "obligation", "removed", "scope"):
        assert severity.derive_severity(_impact(), _change(change_type, None), today=TODAY) == "high"


def test_the_boundary_day_is_inclusive():
    on_the_edge = _change("duration", "2026-03-31")   # exactly 30 days out
    just_outside = _change("duration", "2026-04-01")  # 31 days out
    assert severity.derive_severity(_impact(), on_the_edge, today=TODAY) == "critical"
    assert severity.derive_severity(_impact(), just_outside, today=TODAY) == "high"


def test_low_confidence_never_escalates():
    """The whole point of keeping confidence separate: weak evidence on an
    imminent deadline is 'read this next', not 'this is critical'."""
    weak = _impact(confidence=0.5)
    assert severity.derive_severity(weak, _change("duration", "2026-03-05"), today=TODAY) == "high"


def test_missing_change_row_cannot_escalate():
    """A missing join must under-state severity, never over-state it."""
    assert severity.derive_severity(_impact(), None, today=TODAY) == "high"


def test_unparseable_effective_date_is_ignored_not_fatal():
    assert severity.derive_severity(_impact(), _change("duration", "not a date"), today=TODAY) == "high"
    assert severity.days_until("not a date") is None


def test_a_full_timestamp_effective_date_is_accepted():
    """Extraction yields a bare date; seed files yield a timestamp."""
    stamped = _change("duration", "2026-03-10T00:00:00+00:00")
    assert severity.derive_severity(_impact(), stamped, today=TODAY) == "critical"


def test_derived_severity_never_contradicts_the_stored_level():
    """Property: derivation may only ever raise 'high' to 'critical'."""
    for level in ("none", "low", "medium", "high"):
        for change_type in ("threshold", "editorial", "obligation", "scope"):
            for effective in (None, "2026-03-02", "2030-01-01"):
                result = severity.derive_severity(
                    _impact(level), _change(change_type, effective), today=TODAY
                )
                if level == "high":
                    assert result in {"high", "critical"}
                else:
                    assert result == level


def test_max_severity_ranks_critical_above_high():
    assert severity.max_severity(["low", "critical", "high"]) == "critical"
    assert severity.max_severity(["low", "medium"]) == "medium"
    assert severity.max_severity([]) == "none"
    assert severity.max_severity([None, None]) == "none"


def test_counts_template_covers_every_level():
    template = severity.counts_template()
    assert set(template) == set(severity.SEVERITY_ORDER)
    assert all(value == 0 for value in template.values())


@pytest.mark.parametrize(
    "value,expected",
    [("none", False), ("low", True), ("medium", True), ("high", True), ("critical", True), (None, False)],
)
def test_is_open_severity(value, expected):
    assert severity.is_open_severity(value) is expected
