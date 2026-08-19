"""The three judges, and the arithmetic derived from their findings.

Two cold-read judges score one resume each against the JD, blind to the
narratives and to the competing arm. One authenticity judge fact-checks a
resume against the narratives, blind to the JD. The isolation is carried by the
input types in `evaluation.contracts`, not by discipline at the call site.

Request construction is split out from execution (`build_*_request` vs `run_*`)
so the payload can be asserted on directly in tests. Contamination is a
property of what reaches the API, so that is what the tests inspect.
"""

from typing import Any, cast

from config import JUDGE_MODEL, PROMPTS_DIR
from evaluation.contracts import (
    AuthenticityInput,
    AuthenticityScores,
    ColdReadInput,
    ColdReadScores,
)
from pipeline.anthropic_utils import call_model, str_items

_COLD_READ_TOOL = "submit_cold_read"
_AUTHENTICITY_TOOL = "submit_authenticity"

_SCORE = {"type": "number", "minimum": 0, "maximum": 10}

_COLD_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["jd_alignment", "recruiter_readability", "hire_intent", "notes"],
    "properties": {
        "jd_alignment": _SCORE,
        "recruiter_readability": _SCORE,
        "hire_intent": _SCORE,
        "notes": {
            "type": "object",
            "required": ["jd_alignment", "recruiter_readability", "hire_intent"],
            "properties": {
                "jd_alignment": {"type": "string"},
                "recruiter_readability": {"type": "string"},
                "hire_intent": {"type": "string"},
            },
        },
    },
}

_AUTHENTICITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["claims_checked", "untraceable", "overstatements"],
    "properties": {
        "claims_checked": {"type": "integer", "minimum": 1},
        "untraceable": {"type": "array", "items": {"type": "string"}},
        "overstatements": {"type": "array", "items": {"type": "string"}},
    },
}

# Weight of each finding type in penalty points.
_UNTRACEABLE_PENALTY = 2.0
_OVERSTATEMENT_PENALTY = 1.0


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def _tool_call(prompt_name: str, tool: str, schema: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "model": JUDGE_MODEL,
        "max_tokens": 2048,
        "system": _prompt(prompt_name),
        "messages": [{"role": "user", "content": message}],
        "tools": [{"name": tool, "description": f"Submit {tool} results", "input_schema": schema}],
        "tool_choice": {"type": "tool", "name": tool},
    }


def build_cold_read_request(inp: ColdReadInput) -> dict[str, Any]:
    """Payload for a blind recruiter judge. Contains the JD and one resume."""
    return _tool_call(
        "judge_cold_read",
        _COLD_READ_TOOL,
        _COLD_READ_SCHEMA,
        f"<job_description>\n{inp.jd}\n</job_description>\n\n"
        f"<resume>\n{inp.resume}\n</resume>\n\n"
        "Score this resume against the job description using the "
        f"{_COLD_READ_TOOL} tool.",
    )


def build_authenticity_request(inp: AuthenticityInput) -> dict[str, Any]:
    """Payload for the authenticity judge. Contains one resume and ground truth."""
    return _tool_call(
        "judge_authenticity",
        _AUTHENTICITY_TOOL,
        _AUTHENTICITY_SCHEMA,
        f"<candidate_narratives>\n{inp.narratives}\n</candidate_narratives>\n\n"
        f"<resume>\n{inp.resume}\n</resume>\n\n"
        "Fact-check every claim in this resume against the narratives and submit "
        f"your findings using the {_AUTHENTICITY_TOOL} tool.",
    )


def authenticity_score(claims_checked: int, untraceable: int, overstatements: int) -> float:
    """Length-normalised authenticity, 0–10.

    The rubric this replaces deducted a flat 2 per untraceable claim and 1 per
    overstatement from a starting 10, with no relation to document length. That
    is monotonically unfair to longer resumes: on the 2026-08-15 Anthropic run a
    control resume that was roughly 95% accurate took -11 and floored at 0,
    which made the composite gap uninterpretable even though the ranking was
    right.

    Here the same penalty weights are divided by the worst case for a document
    of this length — every claim untraceable — so the score reads as "how much
    of what this resume asserts is supported" rather than "how many mistakes did
    a reader find". Raw counts are preserved on the result either way, so this
    policy can be revisited without re-running a sweep.
    """
    if claims_checked <= 0:
        raise ValueError("claims_checked must be positive to normalise a score")
    penalty = _UNTRACEABLE_PENALTY * untraceable + _OVERSTATEMENT_PENALTY * overstatements
    worst_case = _UNTRACEABLE_PENALTY * claims_checked
    return round(max(0.0, 10.0 * (1.0 - penalty / worst_case)), 2)


def run_cold_read(inp: ColdReadInput, stage: str = "judge_cold_read") -> ColdReadScores:
    result = call_model(stage, **build_cold_read_request(inp))
    return ColdReadScores(
        jd_alignment=float(result["jd_alignment"]),
        recruiter_readability=float(result["recruiter_readability"]),
        hire_intent=float(result["hire_intent"]),
        notes=cast(dict[str, str], result.get("notes", {})),
    )


def authenticity_findings(result: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    """Validate and coerce the judge's raw findings.

    More findings than claims checked is arithmetically impossible, so it means
    the response is malformed rather than that the resume is catastrophic. The
    previous code clamped instead, producing a confident 0.0 that carried 0.4 of
    the composite and dragged the corpus mean with it. Raising surfaces the bad
    sample instead of burying it in an average.
    """
    claims = int(result.get("claims_checked", 0) or 0)
    if claims <= 0:
        raise ValueError(f"authenticity judge reported claims_checked={claims}; cannot score")

    untraceable = str_items(result.get("untraceable"))
    overstatements = str_items(result.get("overstatements"))
    if len(untraceable) + len(overstatements) > claims:
        raise ValueError(
            f"impossible authenticity findings: {len(untraceable)} untraceable + "
            f"{len(overstatements)} overstatements against {claims} claims checked"
        )
    return claims, untraceable, overstatements


def run_authenticity(inp: AuthenticityInput) -> AuthenticityScores:
    result = call_model("judge_authenticity", **build_authenticity_request(inp))
    claims, untraceable, overstatements = authenticity_findings(result)
    return AuthenticityScores(
        claims_checked=claims,
        untraceable=untraceable,
        overstatements=overstatements,
        authenticity=authenticity_score(claims, len(untraceable), len(overstatements)),
    )
