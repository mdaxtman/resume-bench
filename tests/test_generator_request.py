"""What the generator's request says about length.

A length rule inside the ~18k-character system prompt was ignored: 25–28
bullets against a cap of 18. Restated as the last thing the model reads, it
was mostly kept. So the budget has to reach the request itself, and the number
has to live in one place.
"""

from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from pipeline import generator


def _request() -> dict[str, Any]:
    with patch.object(generator, "call_model", return_value={}) as call:
        generator.run_generator("narratives", {"matches": []}, None, "Posting text")
    return dict(call.call_args.kwargs)


def _user_text(request: dict[str, Any]) -> str:
    return "".join(b["text"] for b in request["messages"][0]["content"])


def test_the_bullet_budget_is_the_last_thing_the_generator_reads() -> None:
    text = _user_text(_request())
    assert text.rstrip().endswith("Count them before you submit.")
    assert f"at most {generator.BULLET_BUDGET} bullets" in text


def test_the_system_prompt_defers_to_the_request_for_the_number() -> None:
    """The prompt states the policy; the count lives only in BULLET_BUDGET."""
    system = "".join(b["text"] for b in _request()["system"])
    assert "The request states the most bullets" in system
    assert f"{generator.BULLET_BUDGET} bullets" not in system


def test_the_posting_reaches_the_generator() -> None:
    """Without it the generator knows the posting only through the fit
    assessment's paraphrase, while its request asks for the JD's exact terms."""
    text = _user_text(_request())
    assert "<job_description>\nPosting text\n</job_description>" in text
    assert text.index("<job_description>") < text.index("<fit_assessment>")


def test_the_sweep_hands_the_generator_the_posting() -> None:
    from evaluation import sweep

    stages = {
        "run_fit_assessment": {"matches": [{"requirement": "React"}]},
        "run_generator": {},
        "build_resume_markdown": "draft",
        "run_screener": {},
        "run_refinement": {"refined_content": "final"},
    }
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch.object(sweep, name, return_value=value))
            for name, value in stages.items()
        }
        sweep.generate_pipeline_arm("Posting text", "narratives", None)
    assert mocks["run_generator"].call_args.args[3] == "Posting text"
