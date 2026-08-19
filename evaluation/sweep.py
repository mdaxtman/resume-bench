"""The sweep runner: generate both arms for every JD, score them, persist.

One sample is (jd, arm, index). Samples are independent and idempotent — a
finished sample writes `scores.json`, and a rerun skips anything that already
has one. That makes a crashed or interrupted sweep resumable by re-invoking the
same command, which matters because a full sweep is minutes of wall clock and
real API spend.

n > 1 is not optional in practice. LLM judges vary by roughly half a point per
axis on an identical document, so a single-sample delta between two configs is
not a result. The report prints spread alongside every mean for that reason.
"""

import json
from pathlib import Path
from typing import Any

from config import RUNS_DIR, WEIGHTS
from corpus import load_jd
from evaluation.contracts import AuthenticityInput, ColdReadInput
from evaluation.control import run_control
from evaluation.judges import run_authenticity, run_cold_read
from pipeline.anthropic_utils import dict_items
from pipeline.fit_assessment import run_fit_assessment
from pipeline.generator import run_generator
from pipeline.refinement import run_refinement
from pipeline.screener import run_screener
from provenance import sweep_metadata
from render import build_resume_markdown
from telemetry import tracing

ARMS = ("pipeline", "control")


def _sample_dir(sweep_id: str, slug: str, arm: str, index: int) -> Path:
    return RUNS_DIR / sweep_id / slug / arm / f"sample-{index}"


def write_metadata(sweep_id: str) -> dict[str, Any]:
    """Record the conditions once, at sweep start.

    Without this a sweep is an uninterpretable number: two runs a week apart
    are indistinguishable, and "did this prompt change help" — the question
    the harness exists to answer — has no evidence behind it. Written only if
    absent, so resuming a sweep does not restamp it with later conditions.
    """
    path = RUNS_DIR / sweep_id / "meta.json"
    if path.is_file():
        return dict(json.loads(path.read_text()))
    meta = sweep_metadata()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2))
    return meta


def read_metadata(sweep_id: str) -> dict[str, Any]:
    path = RUNS_DIR / sweep_id / "meta.json"
    return dict(json.loads(path.read_text())) if path.is_file() else {}


def require_usable_fit(fit: dict[str, Any]) -> None:
    """Reject a fit report the generator cannot act on.

    The pipeline arm is only the pipeline arm because the generator is guided by
    this report. When coercion yields nothing, what runs is a control arm with
    two extra edit passes — and it scores like one. That must surface as a failed
    sample rather than quietly becoming a data point, because a silently
    degraded arm biases every aggregate it lands in.
    """
    if not dict_items(fit.get("matches")):
        raise ValueError(
            "fit report unusable: no matches survived coercion "
            f"(raw type {type(fit.get('matches')).__name__}). "
            "The generator would run unguided; refusing to record this sample."
        )


def generate_pipeline_arm(
    jd: str, narratives: str, contact: dict[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """Four staged calls. Returns (final markdown, intermediate artefacts)."""
    fit = run_fit_assessment(jd, narratives)
    require_usable_fit(fit)
    resume_data = run_generator(narratives, fit, contact)
    draft = build_resume_markdown(resume_data)
    screener = run_screener(jd, draft)
    refined = run_refinement(resume_data, dict(screener), narratives, jd)
    return refined["refined_content"], {"fit": fit, "screener": screener, "draft": draft}


def composite(jd_alignment: float, readability: float, authenticity: float) -> float:
    return round(
        jd_alignment * WEIGHTS["jd_alignment"]
        + readability * WEIGHTS["recruiter_readability"]
        + authenticity * WEIGHTS["authenticity"],
        3,
    )


def run_sample(
    sweep_id: str,
    slug: str,
    arm: str,
    index: int,
    narratives: str,
    contact: dict[str, Any] | None,
) -> dict[str, Any]:
    """Generate and score one (jd, arm, sample). Returns the scores dict."""
    out = _sample_dir(sweep_id, slug, arm, index)
    scores_path = out / "scores.json"
    if scores_path.is_file():
        return dict(json.loads(scores_path.read_text()))

    out.mkdir(parents=True, exist_ok=True)
    jd = load_jd(slug)

    with tracing(out / "trace.jsonl"):
        if arm == "pipeline":
            resume, artefacts = generate_pipeline_arm(jd, narratives, contact)
            (out / "artefacts.json").write_text(json.dumps(artefacts, indent=2, default=str))
        else:
            resume = run_control(jd, narratives)
        (out / "resume.md").write_text(resume)

        cold = run_cold_read(ColdReadInput(jd=jd, resume=resume))
        auth = run_authenticity(AuthenticityInput(resume=resume, narratives=narratives))

    scores = {
        "slug": slug,
        "arm": arm,
        "sample": index,
        "jd_alignment": cold.jd_alignment,
        "recruiter_readability": cold.recruiter_readability,
        "hire_intent": cold.hire_intent,
        "authenticity": auth.authenticity,
        "claims_checked": auth.claims_checked,
        "untraceable": auth.untraceable,
        "overstatements": auth.overstatements,
        "composite": composite(cold.jd_alignment, cold.recruiter_readability, auth.authenticity),
        "notes": cold.notes,
    }
    scores_path.write_text(json.dumps(scores, indent=2))
    return scores
