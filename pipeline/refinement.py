"""Refinement stage — improve resume while preserving voice."""

import re
from typing import Any, NotRequired, TypedDict, cast

from config import PIPELINE_MODEL
from pipeline.anthropic_utils import cached_system, call_model, split_for_cache
from pipeline.prompts import load_prompt


class ChangeMade(TypedDict):
    section: str
    change_description: str
    narrative_evidence: NotRequired[str]


class RemainingGap(TypedDict):
    requirement: str
    why_unfixable: str


class RefinementOutput(TypedDict):
    refined_content: str
    changes_made: NotRequired[list[ChangeMade]]
    remaining_gaps: NotRequired[list[RemainingGap]]
    coverage_improvement: NotRequired[float]


# Restated as the last thing refinement reads, where the generator kept a rule
# it ignored inside its system prompt. Before the closed list of edits, the
# system prompt already forbade new claims and refinement added 1.3
# overstatements a document regardless; with both, it adds none (+0.00 against
# the same drafts) — and its jd-alignment gain goes with them.
ADD_NOTHING = (
    "Change the draft only by substituting a term (with a verbatim narrative sentence "
    "as evidence), tightening, or hygiene. Add nothing: no bullets, no clauses, no "
    "skills, no summary sentences."
)

# A role heading and the date line the renderer puts under it.
_ROLE_HEADING = re.compile(r"^###(?!#)")
_DATE_LINE = re.compile(r"^_[^_].*_$")


def _role_dates(md: str) -> dict[str, str]:
    lines = [line.strip() for line in md.splitlines()]
    return {
        line: lines[i + 1]
        for i, line in enumerate(lines[:-1])
        if _ROLE_HEADING.match(line) and _DATE_LINE.match(lines[i + 1])
    }


def keep_role_dates(draft: str, refined: str) -> str:
    """Restore any role's date line that refinement changed.

    None of refinement's three edits changes a date. Without today's date,
    refinement took the current role's recent start for a typo and moved it
    back a year or two in 4 of 39 documents. The draft's dates are the career
    overview's (the generator had all 39 right), so the draft's line goes back
    under the same heading. A heading refinement reworded is left alone.
    """
    want = _role_dates(draft)
    lines = refined.splitlines()
    changed = False
    for i, line in enumerate(lines[:-1]):
        dates = want.get(line.strip())
        below = lines[i + 1].strip()
        if dates is not None and _DATE_LINE.match(below) and below != dates:
            lines[i + 1] = dates
            changed = True
    if not changed:
        return refined
    return "\n".join(lines) + ("\n" if refined.endswith("\n") else "")


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
                    "narrative_evidence": {"type": "string"},
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


def run_refinement(
    draft: str,
    screener_report: dict[str, Any],
    narratives_text: str,
    jd_content: str,
) -> RefinementOutput:
    """Step 3: Refinement perspective — improve resume while preserving voice.

    Refinement edits the rendered draft — the document the screener read. It
    used to receive its own reformatting of the structured draft, which wrote
    every role as a bold line indistinguishable from a project name; refinement
    copied that layout into every document of a sweep whose draft had role
    headings (38 of 38), and a re-run on the rendered drafts raised structure
    +0.33 with nothing else moving.

    Args:
        draft: Rendered markdown draft from the generator
        screener_report: Screener analysis output
        narratives_text: Candidate narratives for voice reference
        jd_content: Job description

    Returns:
        Refinement output: {refined_content, changes_made?, remaining_gaps?, coverage_improvement?}

    Raises:
        RuntimeError: If API call fails or no tool response found
    """
    system_prompt = load_prompt("refinement")

    # Only the posting is shared, by the samples of a posting. The narratives
    # come after the draft, so they cannot join the cached prefix without
    # reordering the message, which would change what the model reads.
    posting = f"<job_description>\n{jd_content}\n</job_description>\n\n"
    user_message = (
        f"<generated_resume>\n{draft}\n</generated_resume>\n\n"
        f"<screener_feedback>\n{screener_report}\n</screener_feedback>\n\n"
        f"<candidate_narratives>\n{narratives_text}\n</candidate_narratives>\n\n"
        "Refine the resume using the screener feedback while preserving authentic voice "
        "from the narratives. "
        "Use the submit_refined_resume tool to submit the refined resume and changes.\n\n"
        f"{ADD_NOTHING}"
    )

    result = call_model(
        "refine",
        model=PIPELINE_MODEL,
        # 8192: refined full-resume output; 4096 truncated under the
        # claude-sonnet-5 tokenizer (observed stop_reason=max_tokens)
        max_tokens=8192,
        system=cached_system(system_prompt),
        messages=[{"role": "user", "content": split_for_cache(posting, user_message)}],
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
    if isinstance(result["refined_content"], str):
        result["refined_content"] = keep_role_dates(draft, result["refined_content"])

    return cast(RefinementOutput, result)
