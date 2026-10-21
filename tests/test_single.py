"""The single-call arm: the generator's rules, one call, no fit report."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from config import PROMPTS_DIR
from evaluation import single, sweep
from pipeline.generator import BULLET_BUDGET

DRAFT = {
    "summary": "Frontend engineer.",
    "experience": [
        {"company": "Initech", "title": "Engineer", "dates": "2019 – 2025", "projects": []},
        {
            "company": "Globex",
            "title": "Senior Engineer",
            "dates": "2025 – present",
            "projects": [],
        },
    ],
    "skills": ["React"],
}


def _fit_free(line: str) -> bool:
    lowered = line.lower()
    return not any(
        term in lowered for term in ("fit report", "fit assessment", "product_connection")
    )


def test_the_prompt_changes_only_what_referred_to_the_fit_report() -> None:
    """Every rule that does not mention the fit report is carried word for word,
    so the arm differs from the generator only by the fit stage."""
    generator = (PROMPTS_DIR / "generator.md").read_text().splitlines()
    variant = (PROMPTS_DIR / "generator_single.md").read_text()
    assert all(_fit_free(line) for line in variant.splitlines())
    kept = [line for line in generator if _fit_free(line)]
    assert all(line in variant for line in kept)


def _request() -> dict[str, Any]:
    with patch.object(single, "call_model", return_value=DRAFT) as call:
        markdown = single.run_single("the posting", "my history", {"email": "a@b.c"})
    assert markdown.index("Globex") < markdown.index("Initech"), "roles are sorted"
    return dict(call.call_args.kwargs)


def test_one_call_reads_the_narratives_then_the_posting_and_no_fit_report() -> None:
    cached, tail = _request()["messages"][0]["content"]
    assert cached["text"] == "<candidate_background>\nmy history\n</candidate_background>\n\n"
    assert tail["text"].startswith("<job_description>\nthe posting\n</job_description>")
    assert "<fit_assessment>" not in tail["text"] and "a@b.c" in tail["text"]
    assert tail["text"].endswith(
        f"at most {BULLET_BUDGET} bullets in total across every role and project. "
        "Count them before you submit."
    )


def test_it_uses_the_variant_prompt() -> None:
    system = _request()["system"][0]["text"]
    assert "## TAILORING TO THE POSTING" in system and "## FIT REPORT GUIDANCE" not in system


def test_the_draft_arm_scores_the_pipelines_own_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(single, "RUNS_DIR", tmp_path)
    sample = tmp_path / "s" / "job" / "pipeline" / "sample-2"
    sample.mkdir(parents=True)
    (sample / "artefacts.json").write_text(json.dumps({"draft": "the draft"}))
    assert single.pipeline_draft("s", "job", 2) == "the draft"
    with pytest.raises(ValueError):
        single.pipeline_draft("s", "job", 3)


def test_the_experiment_arms_are_opt_in() -> None:
    assert sweep.ARMS == ("pipeline", "control")
    assert sweep.EXPERIMENT_ARMS == ("single", "draft")
