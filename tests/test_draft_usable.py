"""A generator draft with the rest of its tool call folded into `summary`.

Nine drafts across the runs so far, every one `stop_reason=tool_use`:

  - `summary` ends `</summary>` then `<parameter name="experience">` and the
    roles as raw JSON text; the `experience` field itself is absent, so the
    rendered resume has no role headings at all
  - the same with `<parameter name="skills">`, and no Skills section

The schema requires both fields; the input_schema is advisory. The cold-read
judge scored one such draft 9.0 on jd alignment, so a score will not catch it,
and refinement used to paper over it. The draft has to be rejected and retried.
"""

from unittest.mock import patch

from pipeline import generator
from pipeline.generator import draft_is_usable

ROLE = {"company": "Acme", "title": "Engineer", "dates": "2020 – 2024", "projects": []}
GOOD = {"summary": "Frontend engineer.", "experience": [ROLE], "skills": ["React"]}
EXPERIENCE_IN_SUMMARY = {
    "summary": 'Frontend engineer.</summary>\n<parameter name="experience">[{"company": "Acme"}]',
    "skills": ["React"],
}
SKILLS_IN_SUMMARY = {
    "summary": 'Frontend engineer.</summary>\n<parameter name="skills">["React", "TypeScript"]',
    "experience": [ROLE],
}


def test_a_complete_draft_is_usable() -> None:
    assert draft_is_usable(GOOD)


def test_roles_folded_into_the_summary_are_rejected() -> None:
    assert not draft_is_usable(EXPERIENCE_IN_SUMMARY)


def test_skills_folded_into_the_summary_are_rejected() -> None:
    assert not draft_is_usable(SKILLS_IN_SUMMARY)


def test_markup_is_rejected_even_when_every_field_is_present() -> None:
    assert not draft_is_usable({**GOOD, "summary": "Frontend engineer.</summary>"})


def test_the_generator_validates_and_retries() -> None:
    with patch.object(generator, "call_model", return_value=GOOD) as call:
        generator.run_generator("narratives", {"matches": []}, None, "posting")
    assert call.call_args.kwargs["validate"] is draft_is_usable
    assert call.call_args.kwargs["attempts"] > 1
