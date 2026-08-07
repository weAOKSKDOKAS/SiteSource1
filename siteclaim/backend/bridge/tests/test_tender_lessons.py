"""Lessons learned — human-authored, appended, ordered. The machine never writes one."""

import pytest

from bridge import closeout


def test_a_lesson_is_added_and_listed():
    row = closeout.add_lesson("nd-2025-04", "pricing", "Drilling rate was 12% light on hard rock.")
    assert row["category"] == "pricing" and "hard rock" in row["lesson"]

    lessons = closeout.list_lessons("nd-2025-04")
    assert len(lessons) == 1 and lessons[0]["id"] == row["id"]


def test_lessons_list_oldest_first():
    for i in range(3):
        closeout.add_lesson("nd-2025-04", "scope", f"lesson {i}")
    assert [l["lesson"] for l in closeout.list_lessons("nd-2025-04")] == ["lesson 0", "lesson 1", "lesson 2"]


@pytest.mark.parametrize("cat", ["pricing", "scope", "programme", "commercial", "other"])
def test_every_known_category_is_kept(cat):
    assert closeout.add_lesson("nd-2025-04", cat, "x")["category"] == cat


def test_an_unknown_category_falls_to_other_rather_than_being_refused():
    """A lesson worth writing must never be lost to a taxonomy quibble."""
    assert closeout.add_lesson("nd-2025-04", "vibes", "still worth keeping")["category"] == "other"


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_an_empty_lesson_is_refused(blank):
    with pytest.raises(ValueError, match="a lesson needs text"):
        closeout.add_lesson("nd-2025-04", "pricing", blank)


def test_the_text_is_stored_verbatim():
    assert closeout.add_lesson("nd-2025-04", "other", "  trimmed  ")["lesson"] == "trimmed"


def test_two_tenders_keep_their_own_lessons():
    closeout.add_lesson("nd-2025-04", "pricing", "A")
    closeout.add_lesson("ge-2026-14", "scope", "B")

    assert [l["lesson"] for l in closeout.list_lessons("nd-2025-04")] == ["A"]
    assert [l["lesson"] for l in closeout.list_lessons("ge-2026-14")] == ["B"]


def test_a_tender_with_no_lessons_reads_back_empty():
    assert closeout.list_lessons("never-touched") == []


def test_an_empty_set_id_is_refused():
    with pytest.raises(ValueError):
        closeout.add_lesson("", "pricing", "x")
