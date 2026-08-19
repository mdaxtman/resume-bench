"""Screener stage — analyze resume against JD from ATS perspective."""

from typing import Any, Literal, NotRequired, TypedDict, cast

from config import PIPELINE_MODEL
from pipeline.anthropic_utils import call_model
from pipeline.prompts import load_prompt


class TerminologyMismatch(TypedDict):
    my_term: str
    jd_term: str


class CoverageGap(TypedDict):
    requirement: str
    gap_type: Literal["hard", "soft"]
    impact: str


class ScreenerReport(TypedDict):
    keyword_coverage: dict[str, Any]
    semantic_score: float
    terminology_mismatches: list[TerminologyMismatch]
    overall_score: float
    coverage_gaps: NotRequired[list[CoverageGap]]


# Tool schema for Claude tool_use
_SCREENER_SCHEMA = {
    "type": "object",
    "required": ["keyword_coverage", "semantic_score", "terminology_mismatches", "overall_score"],
    "properties": {
        "keyword_coverage": {"type": "object"},
        "semantic_score": {"type": "number", "minimum": 0, "maximum": 1},
        "coverage_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement", "gap_type", "impact"],
                "properties": {
                    "requirement": {"type": "string"},
                    "gap_type": {"enum": ["hard", "soft"], "type": "string"},
                    "impact": {"type": "string"},
                },
            },
        },
        "terminology_mismatches": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["my_term", "jd_term"],
                "properties": {
                    "my_term": {"type": "string"},
                    "jd_term": {"type": "string"},
                },
            },
        },
        "overall_score": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

_TOOL_NAME = "submit_screener_analysis"


def run_screener(jd_content: str, resume_text: str) -> ScreenerReport:
    """Step 2: Screener perspective — analyze resume against JD.

    Args:
        jd_content: Raw job description text
        resume_text: Formatted resume as text

    Returns:
        Screener analysis: {keyword_coverage, semantic_score, terminology_mismatches,
            overall_score, coverage_gaps?}

    Raises:
        RuntimeError: If API call fails or no tool response found
    """
    system_prompt = load_prompt("resume_screener")
    user_message = (
        f"<job_description>\n{jd_content}\n</job_description>\n\n"
        f"<resume>\n{resume_text}\n</resume>\n\n"
        "Analyze this resume against the job description from an ATS perspective. "
        "Use the submit_screener_analysis tool to submit your assessment."
    )

    result = call_model(
        "screen",
        model=PIPELINE_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=cast(
            Any,
            [
                {
                    "name": _TOOL_NAME,
                    "description": "Submit the ATS screener analysis",
                    "input_schema": _SCREENER_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )

    return cast(ScreenerReport, result)
