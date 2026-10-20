"""One-sentence summary: only the summary may differ between conditions.

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
    first_sentence,
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


GENERATOR = Path("prompts/generator.md").read_text()
PROMPT = Path("prompts/summary_one.md").read_text()


@pytest.mark.parametrize(
    "caution",
    [
        "A comparison to a system the candidate never worked on is a claim the narratives "
        "cannot support; the reader draws the connection.",
        "do not name or describe the employer's product, and do not assert a parallel to it",
        "The same caution governs proportion language.",
        "Use one only when the narratives' own dates and role breakdown make the share verifiable;",
    ],
)
def test_the_generators_summary_cautions_carry_over_word_for_word(caution: str) -> None:
    """The one-sentence rule drops the third sentence, not the generator's
    cautions about what a summary may claim."""
    assert caution in GENERATOR and caution in PROMPT


def test_the_ethical_boundaries_are_the_generators_word_for_word() -> None:
    ethics = GENERATOR.split("## ETHICAL BOUNDARIES\n", 1)[1]
    assert ethics.strip() in PROMPT


def test_the_word_limit_is_the_last_thing_the_writer_reads() -> None:
    text = _request(None)["messages"][0]["content"][1]["text"]
    assert text.endswith(
        "Hard limit: one sentence, at most 30 words. Count them before you submit."
    )


@pytest.mark.parametrize(
    ("summary", "first"),
    [
        ("Frontend engineer with 9 years. Repeatedly shipped.", "Frontend engineer with 9 years."),
        (
            "Engineer with ~9.5 years, including v2→v3 migrations. Led teams.",
            "Engineer with ~9.5 years, including v2→v3 migrations.",
        ),
        ("Engineer at Globex.\n2 roles since.", "Engineer at Globex."),
        ("One sentence only", "One sentence only"),
    ],
)
def test_first_sentence(summary: str, first: str) -> None:
    assert first_sentence(summary) == first


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
