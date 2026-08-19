"""Fit assessment stage — evaluate candidate fit against job description."""

from typing import Any, cast

from config import PIPELINE_MODEL
from pipeline.anthropic_utils import call_model, dict_items
from pipeline.prompts import load_prompt

_TOOL_NAME = "submit_fit_report"

_FIT_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "fit_level",
        "matches",
        "gaps",
        "terminology",
        "reasoning",
        "overall_score",
        "semantic_score",
    ],
    "properties": {
        "fit_level": {
            "type": "string",
            "enum": ["strong", "moderate", "borderline", "poor"],
        },
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement", "priority", "notes"],
                "properties": {
                    "requirement": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["required", "preferred", "implied"],
                    },
                    "notes": {"type": "string"},
                },
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement", "type", "notes"],
                "properties": {
                    "requirement": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["hard", "soft"],
                    },
                    "notes": {"type": "string"},
                },
            },
        },
        "terminology": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["my_term", "jd_term", "confidence"],
                "properties": {
                    "my_term": {"type": "string"},
                    "jd_term": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "reasoning": {"type": "string"},
        "overall_score": {"type": "number", "minimum": 0, "maximum": 1},
        "semantic_score": {"type": "number", "minimum": 0, "maximum": 1},
        "cultural_signals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["quality", "jd_signal", "evidence_hint"],
                "properties": {
                    "quality": {"type": "string"},
                    "jd_signal": {"type": "string"},
                    "evidence_hint": {"type": "string"},
                },
            },
        },
        "product_connection": {"type": ["string", "null"]},
    },
}


def fit_is_usable(result: dict[str, Any]) -> bool:
    """A fit report is usable when at least one match survives coercion.

    Matches are what make the pipeline arm a pipeline arm. Without them the
    generator runs unguided and produces a control resume with extra steps.
    """
    return bool(dict_items(result.get("matches")))


def run_fit_assessment(jd_content: str, narratives_text: str) -> dict[str, Any]:
    """Evaluate candidate fit against job description.

    Args:
        jd_content: Raw job description text
        narratives_text: Formatted candidate narratives

    Returns:
        Fit assessment: {fit_level, matches, gaps, terminology, reasoning}

    Raises:
        RuntimeError: If API call fails or no tool response found
    """
    system_prompt = load_prompt("fit_assessment")
    user_message = (
        f"<job_description>\n{jd_content}\n</job_description>\n\n"
        f"<candidate_background>\n{narratives_text}\n</candidate_background>\n\n"
        "Evaluate the candidate's background against this job description "
        "and submit your assessment using the submit_fit_report tool."
    )

    result = call_model(
        "fit",
        validate=fit_is_usable,
        attempts=3,
        model=PIPELINE_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=cast(
            Any,
            [
                {
                    "name": _TOOL_NAME,
                    "description": "Submit the structured fit assessment result",
                    "input_schema": _FIT_REPORT_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )

    # Filter terminology mappings: only keep those with confidence >= 0.8.
    # dict_items guards the item type — the schema declares objects here but the
    # model has returned bare strings (see tests/test_tool_result_validation.py).
    if "terminology" in result:
        result["terminology"] = [
            term for term in dict_items(result["terminology"]) if term.get("confidence", 0) >= 0.8
        ]

    return result
