"""Refinement stage — improve resume while preserving voice."""

import re
from typing import Any, NotRequired, TypedDict, cast

from config import PIPELINE_MODEL
from pipeline.anthropic_utils import call_model, dict_items
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
# it ignored inside its system prompt. The system prompt already forbade new
# claims, and refinement added 1.3 overstatements a document regardless.
ADD_NOTHING = (
    "Change the draft only by substituting a term (with a verbatim narrative sentence "
    "as evidence), tightening, or hygiene. Add nothing: no bullets, no clauses, no "
    "skills, no summary sentences."
)

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

    user_message = (
        f"<job_description>\n{jd_content}\n</job_description>\n\n"
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


# --- Edit-list refinement -------------------------------------------------
#
# The variant above asks the model to return a rewritten resume and trusts it
# to add nothing. This one asks for a list of edits and applies them in code,
# so the rules that matter are enforced rather than requested: nothing can be
# inserted, the layout cannot change, and a substitution must quote a sentence
# that is really in the narratives.

_EDITS_TOOL_NAME = "submit_resume_edits"
EDIT_TYPES = ("substitute", "tighten", "hygiene")

# Words an edit may add to the span it replaces. A substitution swaps a term
# for the JD's term, which can run a few words longer; anything past that is
# a clause, and clauses are where unsupported claims entered.
MAX_GROWTH = {"substitute": 3, "tighten": 2, "hygiene": 2}

# Shorter quotes are too generic to tie a term to a specific piece of work.
MIN_EVIDENCE_WORDS = 5

_EDITS_SCHEMA = {
    "type": "object",
    "required": ["edits"],
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "before", "after"],
                "properties": {
                    "type": {"type": "string", "enum": list(EDIT_TYPES)},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "narrative_evidence": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "remaining_gaps": _REFINEMENT_SCHEMA["properties"]["remaining_gaps"],  # type: ignore[index]
    },
}

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-", "–": "-"})


def _normalise(text: str) -> str:
    """Compare quotes on words, not on markdown, typography, or line wrapping."""
    text = text.translate(_QUOTES).lower()
    text = re.sub(r"[*_`#>]", "", text)
    return " ".join(text.split())


def edit_rejection(text: str, edit: dict[str, Any], narratives: str) -> str | None:
    """Why `edit` cannot be applied to `text`, or None if it can."""
    kind, before, after = edit.get("type"), edit.get("before"), edit.get("after")
    if kind not in EDIT_TYPES:
        return f"unknown type {kind!r}"
    if not isinstance(before, str) or not isinstance(after, str) or not before.strip():
        return "missing before/after"
    if "\n" in before or "\n" in after:
        return "spans more than one line"
    occurrences = text.count(before)
    if occurrences != 1:
        return f"before occurs {occurrences} times"
    if len(after.split()) - len(before.split()) > MAX_GROWTH[kind]:
        return f"adds {len(after.split()) - len(before.split())} words"
    if kind == "substitute":
        evidence = edit.get("narrative_evidence")
        if not isinstance(evidence, str) or len(evidence.split()) < MIN_EVIDENCE_WORDS:
            return "substitution without evidence"
        if _normalise(evidence) not in _normalise(narratives):
            return "evidence not in narratives"
    return None


def apply_edits(
    draft: str, edits: list[dict[str, Any]], narratives: str
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the edits that pass `edit_rejection`, in order.

    Returns (text, applied, rejected); each rejected edit carries its reason.
    Edits apply to the text as earlier edits left it, so a later edit's
    `before` must match the updated text.
    """
    text = draft
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for edit in edits:
        reason = edit_rejection(text, edit, narratives)
        if reason:
            rejected.append({**edit, "rejected": reason})
            continue
        text = text.replace(edit["before"], edit["after"], 1)
        applied.append(edit)
    return text, applied, rejected


def run_refinement_edits(
    draft: str,
    screener_report: dict[str, Any],
    narratives_text: str,
    jd_content: str,
) -> dict[str, Any]:
    """Refinement as a list of edits applied in code. Same inputs as `run_refinement`.

    Returns {refined_content, edits_applied, edits_rejected, remaining_gaps}.
    """
    user_message = (
        f"<job_description>\n{jd_content}\n</job_description>\n\n"
        f"<generated_resume>\n{draft}\n</generated_resume>\n\n"
        f"<screener_feedback>\n{screener_report}\n</screener_feedback>\n\n"
        f"<candidate_narratives>\n{narratives_text}\n</candidate_narratives>\n\n"
        f"Submit your edits to the draft with the {_EDITS_TOOL_NAME} tool.\n\n"
        f"{ADD_NOTHING}"
    )
    result = call_model(
        "refine",
        model=PIPELINE_MODEL,
        max_tokens=8192,
        system=load_prompt("refinement_edits"),
        messages=[{"role": "user", "content": user_message}],
        tools=cast(
            Any,
            [
                {
                    "name": _EDITS_TOOL_NAME,
                    "description": "Submit edits to the resume draft",
                    "input_schema": _EDITS_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _EDITS_TOOL_NAME},
    )
    text, applied, rejected = apply_edits(draft, dict_items(result.get("edits")), narratives_text)
    return {
        "refined_content": text,
        "edits_applied": applied,
        "edits_rejected": rejected,
        "remaining_gaps": dict_items(result.get("remaining_gaps")),
    }
