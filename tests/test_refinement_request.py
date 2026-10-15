"""What refinement is given to edit.

Refinement copies the layout of whatever it receives. It used to receive its
own reformatting of the structured draft — roles as bold lines, the same weight
as project names — and every refined document came back that way, while the
draft the screener read had `###` role headings. The judges score structure on
how findable roles and dates are, and the pipeline trailed the control there.
"""

from typing import Any
from unittest.mock import patch

from evaluation import sweep
from pipeline import refinement
from render import build_resume_markdown

RESUME_DATA = {
    "summary": "Frontend engineer.",
    "experience": [
        {
            "company": "Acme",
            "title": "Senior Engineer",
            "dates": "2020 – 2024",
            "projects": [{"name": "Console", "bullets": ["Built the console."]}],
        }
    ],
    "skills": ["React"],
}


def _user_text(call: Any) -> str:
    return str(call.call_args.kwargs["messages"][0]["content"])


def test_refinement_edits_the_rendered_draft() -> None:
    draft = build_resume_markdown(RESUME_DATA)
    with patch.object(refinement, "call_model", return_value={"refined_content": ""}) as call:
        refinement.run_refinement(draft, {}, "narratives", "jd")
    assert f"<generated_resume>\n{draft}\n</generated_resume>" in _user_text(call)
    assert "### Senior Engineer at Acme" in _user_text(call)


def test_the_pipeline_hands_refinement_the_draft_the_screener_read() -> None:
    with (
        patch.object(sweep, "run_fit_assessment", return_value={"matches": [{"requirement": "x"}]}),
        patch.object(sweep, "run_generator", return_value=RESUME_DATA),
        patch.object(sweep, "run_screener", return_value={}) as screener,
        patch.object(sweep, "run_refinement", return_value={"refined_content": "done"}) as refine,
    ):
        resume, artefacts = sweep.generate_pipeline_arm("jd", "narratives", None)
    screened = screener.call_args.args[1]
    assert refine.call_args.args[0] == screened == artefacts["draft"]
    assert resume == "done"
