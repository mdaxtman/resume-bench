"""Summary written last: only the summary may differ between conditions.

The experiment holds every other line of a finished document fixed, so the
property most of these tests pin is that replacing or removing the summary
leaves the rest byte-identical, and that the writer never sees the summary it
replaces.
"""

from pathlib import Path
from typing import Any

import pytest

from evaluation.summary import (
    SummaryInput,
    build_summary_request,
    remove_summary,
    replace_summary,
    summary_text,
    summary_usable,
)

DOC = """Springfield, USA

## Summary
Frontend engineer with 9 years building React applications. Repeatedly joined
teams mid-flight and shipped under deadline.

## Experience
### Senior Engineer at Globex
_May 2024 – present_
**Scheduling Platform**
- Sole frontend engineer owning a React single-page application.

## Skills
**Languages:** TypeScript, JavaScript
"""

REST = DOC.split("## Experience", 1)[1]


def test_summary_text_is_the_paragraph_under_the_heading() -> None:
    assert summary_text(DOC) == (
        "Frontend engineer with 9 years building React applications. Repeatedly joined\n"
        "teams mid-flight and shipped under deadline."
    )


def test_replace_changes_only_the_summary() -> None:
    out = replace_summary(DOC, "  A new summary.  ")
    assert summary_text(out) == "A new summary."
    assert out.startswith("Springfield, USA\n\n## Summary\nA new summary.\n\n## Experience")
    assert out.split("## Experience", 1)[1] == REST


def test_remove_keeps_every_other_line() -> None:
    out = remove_summary(DOC)
    assert "## Summary" not in out and "Repeatedly joined" not in out
    assert out == "Springfield, USA\n\n## Experience" + REST


def test_a_document_without_a_summary_is_an_error() -> None:
    with pytest.raises(ValueError):
        summary_text(remove_summary(DOC))


def test_the_last_section_can_be_the_summary() -> None:
    doc = "## Experience\n- One bullet.\n\n## Summary\nOld."
    assert replace_summary(doc, "New.") == "## Experience\n- One bullet.\n\n## Summary\nNew.\n"
    assert remove_summary(doc) == "## Experience\n- One bullet.\n"


def _request(connection: str | None) -> dict[str, Any]:
    return build_summary_request(
        SummaryInput(
            jd="Build scheduling tools.",
            narratives="## Career Overview\nGlobex, 2024 to now.",
            product_connection=connection,
            resume=remove_summary(DOC),
        )
    )


def test_the_writer_sees_the_narratives_first_and_cached() -> None:
    blocks = _request(None)["messages"][0]["content"]
    assert "<candidate_background>" in blocks[0]["text"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "<job_description>" in blocks[1]["text"] and "<resume>" in blocks[1]["text"]


def test_the_writer_never_sees_the_summary_it_replaces() -> None:
    text = "".join(b["text"] for b in _request("Scheduling at scale.")["messages"][0]["content"])
    assert "Repeatedly joined" not in text
    assert "Sole frontend engineer" in text


def test_the_product_connection_is_passed_only_when_present() -> None:
    with_connection = _request("Scheduling at scale.")["messages"][0]["content"][1]["text"]
    without = _request(None)["messages"][0]["content"][1]["text"]
    assert "PRODUCT CONNECTION (product_connection):\n  Scheduling at scale." in with_connection
    assert "<fit_assessment>" not in without


def test_the_summary_rule_is_the_generators_word_for_word() -> None:
    """A difference in the rule would confound when the summary is written with
    what it is asked to say."""
    prefix = "- `summary` (optional): "
    generator = Path("prompts/generator.md").read_text().splitlines()
    (rule,) = [line[len(prefix) :] for line in generator if line.startswith(prefix)]
    assert rule in Path("prompts/summary_last.md").read_text()


def test_the_ethical_boundaries_are_the_generators_word_for_word() -> None:
    ethics = Path("prompts/generator.md").read_text().split("## ETHICAL BOUNDARIES\n", 1)[1]
    assert ethics.strip() in Path("prompts/summary_last.md").read_text()


def test_the_word_limit_is_the_last_thing_the_writer_reads() -> None:
    text = _request(None)["messages"][0]["content"][1]["text"]
    assert text.endswith("Hard limit: at most 55 words. Count them before you submit.")


@pytest.mark.parametrize(
    ("summary", "usable"),
    [
        ("Frontend engineer with 9 years.", True),
        ("", False),
        ("   ", False),
        (None, False),
        ("## Summary\nFrontend engineer.", False),
        ('Engineer.</summary>\n<parameter name="experience">[]', False),
    ],
)
def test_summary_usable(summary: object, usable: bool) -> None:
    assert summary_usable({"summary": summary}) is usable
