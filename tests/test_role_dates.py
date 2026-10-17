"""Role dates and order: facts from the career overview, kept in code.

The generator copied every role's dates from the career overview correctly,
but one draft in 39 listed the current role second. The screener, which did
not know today's date, flagged the current role's recent start as a future
typo in 4 of 39 documents, and refinement moved it back a year or two in
exactly those four. The authenticity judge then charged each moved date as an
untraceable claim.
"""

from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

from pipeline import refinement
from pipeline.generator import order_roles
from pipeline.prompts import load_prompt
from pipeline.refinement import keep_role_dates
from render import build_resume_markdown


def _role(company: str, dates: str) -> dict[str, Any]:
    return {"company": company, "title": "Engineer", "dates": dates, "projects": []}


CURRENT = _role("Globex", "March 2025 – present")
PREVIOUS = _role("Initech", "June 2019 – March 2025")
FIRST = _role("Springfield Labs", "February 2016 – June 2019")


def _companies(data: dict[str, Any]) -> list[str]:
    return [role["company"] for role in data["experience"]]


def test_the_current_role_listed_second_is_put_first() -> None:
    data = {"experience": [PREVIOUS, CURRENT, FIRST], "skills": ["React"]}
    assert _companies(order_roles(data)) == ["Globex", "Initech", "Springfield Labs"]


def test_roles_already_in_order_are_unchanged() -> None:
    data = {"experience": [CURRENT, PREVIOUS, FIRST]}
    assert order_roles(data) == data


@pytest.mark.parametrize(
    ("newer", "older"),
    [
        ("2021–present", "2018 – 2021"),
        ("Sept. 2023 – Current", "Jan 2019 – Aug 2023"),
        ("2022", "2016 – 2019"),
        ("March 2024 – June 2024", "January 2024 – March 2024"),
    ],
)
def test_date_formats_order_by_end_then_start(newer: str, older: str) -> None:
    data = {"experience": [_role("Older", older), _role("Newer", newer)]}
    assert _companies(order_roles(data)) == ["Newer", "Older"]


def test_a_role_without_a_year_leaves_the_order_alone() -> None:
    data = {"experience": [PREVIOUS, _role("Globex", "Recent"), FIRST]}
    assert order_roles(data) == data


DRAFT = build_resume_markdown(
    {"summary": "Frontend engineer.", "experience": [CURRENT, PREVIOUS], "skills": ["React"]}
)


def test_a_date_refinement_moved_is_restored() -> None:
    refined = DRAFT.replace("_March 2025 – present_", "_March 2023 – present_")
    assert keep_role_dates(DRAFT, refined) == DRAFT


def test_a_reworded_heading_is_left_alone() -> None:
    refined = DRAFT.replace("### Engineer at Globex", "### Senior Engineer at Globex").replace(
        "_March 2025 – present_", "_March 2023 – present_"
    )
    assert keep_role_dates(DRAFT, refined) == refined


def test_other_edits_are_untouched() -> None:
    refined = DRAFT.replace("Frontend engineer.", "Frontend engineer, tightened.") + "\n"
    assert keep_role_dates(DRAFT, refined) == refined


def test_refinement_returns_the_draft_dates() -> None:
    moved = DRAFT.replace("_March 2025 – present_", "_March 2024 – present_")
    with patch.object(refinement, "call_model", return_value={"refined_content": moved}):
        result = refinement.run_refinement(DRAFT, {}, "narratives", "jd")
    assert result["refined_content"] == DRAFT


@pytest.mark.parametrize("stage", ["resume_screener", "refinement"])
def test_the_stages_that_read_dates_know_today(stage: str) -> None:
    prompt = load_prompt(stage)
    assert f"Today's date is {date.today().isoformat()}." in prompt
    assert "{today}" not in prompt
