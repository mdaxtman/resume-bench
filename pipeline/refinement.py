"""Refinement stage — improve resume while preserving voice."""

from typing import Any, NotRequired, TypedDict, cast

from config import PIPELINE_MODEL
from pipeline.anthropic_utils import call_model
from pipeline.prompts import load_prompt


class ChangeMade(TypedDict):
    section: str
    change_description: str


class RemainingGap(TypedDict):
    requirement: str
    why_unfixable: str


class RefinementOutput(TypedDict):
    refined_content: str
    changes_made: NotRequired[list[ChangeMade]]
    remaining_gaps: NotRequired[list[RemainingGap]]
    coverage_improvement: NotRequired[float]


_TOOL_NAME = "submit_refined_resume"

# Tool schema for Claude tool_use
_REFINEMENT_SCHEMA = {
    "type": "object",
    "required": ["refined_content"],
    "properties": {
        "refined_content": {"type": "string"},
        "changes_made": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["section", "change_description"],
                "properties": {
                    "section": {"type": "string"},
                    "change_description": {"type": "string"},
                },
            },
        },
        "remaining_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement", "why_unfixable"],
                "properties": {
                    "requirement": {"type": "string"},
                    "why_unfixable": {"type": "string"},
                },
            },
        },
        "coverage_improvement": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def _format_resume_for_screener(resume_data: dict[str, Any]) -> str:
    """Format generated resume back into text for screener analysis."""
    lines = []
    if resume_data.get("summary"):
        lines.append(f"## Summary\n{resume_data['summary']}")
    if resume_data.get("experience"):
        lines.append("## Experience")
        for job in resume_data["experience"]:
            lines.append(f"**{job['title']}** at {job['company']} ({job['dates']})")
            for project in job.get("projects", []):
                project_line = f"**{project['name']}"
                if project.get("dates"):
                    project_line += f"** ({project['dates']})"
                else:
                    project_line += "**"
                lines.append(project_line)
                for bullet in project.get("bullets", []):
                    lines.append(f"- {bullet}")
    if resume_data.get("skills"):
        lines.append(f"## Skills\n{', '.join(resume_data['skills'])}")
    if resume_data.get("education"):
        lines.append("## Education")
        for edu in resume_data["education"]:
            lines.append(f"- {edu['name']}: {edu['degree']} ({edu['year']})")
    return "\n\n".join(lines)


def run_refinement(
    resume_data: dict[str, Any],
    screener_report: dict[str, Any],
    narratives_text: str,
    jd_content: str,
) -> RefinementOutput:
    """Step 3: Refinement perspective — improve resume while preserving voice.

    Args:
        resume_data: Structured resume from generator
        screener_report: Screener analysis output
        narratives_text: Candidate narratives for voice reference
        jd_content: Job description

    Returns:
        Refinement output: {refined_content, changes_made?, remaining_gaps?, coverage_improvement?}

    Raises:
        RuntimeError: If API call fails or no tool response found
    """
    system_prompt = load_prompt("refinement")
    resume_text = _format_resume_for_screener(resume_data)

    user_message = (
        f"<job_description>\n{jd_content}\n</job_description>\n\n"
        f"<generated_resume>\n{resume_text}\n</generated_resume>\n\n"
        f"<screener_feedback>\n{screener_report}\n</screener_feedback>\n\n"
        f"<candidate_narratives>\n{narratives_text}\n</candidate_narratives>\n\n"
        "Refine the resume using the screener feedback while preserving authentic voice "
        "from the narratives. "
        "Use the submit_refined_resume tool to submit the refined resume and changes."
    )

    result = call_model(
        "refine",
        model=PIPELINE_MODEL,
        # 8192: refined full-resume output; 4096 truncated under the
        # claude-sonnet-5 tokenizer (observed stop_reason=max_tokens)
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=cast(
            Any,
            [
                {
                    "name": _TOOL_NAME,
                    "description": "Submit the refined resume",
                    "input_schema": _REFINEMENT_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )

    # claude-sonnet-5 occasionally drifts the key name despite the schema
    # (tool schemas are not strictly enforced without strict mode, which
    # our min/max constraints preclude for now). Normalize before use.
    if "refined_content" not in result and "refined_resume" in result:
        result["refined_content"] = result.pop("refined_resume")
    if "refined_content" not in result:
        raise RuntimeError(
            f"refinement returned no refined_content (keys: {sorted(result.keys())})"
        )

    return cast(RefinementOutput, result)
