"""Generator stage — produce tailored resume draft guided by fit assessment."""

from typing import Any, cast

from config import PIPELINE_MODEL
from pipeline.anthropic_utils import cached_system, call_model, dict_items, split_for_cache
from pipeline.prompts import load_prompt

# Tool schema for Claude tool_use
_TOOL_NAME = "submit_resume_draft"

_GENERATOR_SCHEMA = {
    "type": "object",
    "required": ["experience", "skills"],
    "properties": {
        "summary": {"type": "string"},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["company", "title", "dates", "projects"],
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "dates": {"type": "string"},
                    "projects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "bullets"],
                            "properties": {
                                "name": {"type": "string"},
                                "dates": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "contact": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "location": {"type": "string"},
                "linkedin": {"type": "string"},
                "github": {"type": "string"},
                "website": {"type": "string"},
            },
        },
    },
}


def _format_note(notes: str | None) -> str:
    """Format optional notes as suffix string."""
    return f" ({notes})" if notes else ""


_OVERVIEW_CATEGORY = "career_overview"
_SUPPLEMENTAL_CATEGORY = "supplemental"


def _section(heading: str, rows: list[dict[str, Any]]) -> str:
    """Render one narrative group under a Markdown heading."""
    return f"{heading}\n" + "\n\n".join(f"### {n['title']}\n{n['content']}" for n in rows)


def _format_narratives(narrative_rows: list[dict[str, Any]]) -> str:
    """Format narratives into Markdown sections grouped by category.

    Supplemental narratives (side projects, community work) are kept out of the
    role section so the generator does not render them as employment. Any other
    category is treated as a role, so adding a new category never silently drops
    a narrative from the prompt.
    """
    if not narrative_rows:
        return "No candidate background narratives available."

    overview = [n for n in narrative_rows if n.get("category") == _OVERVIEW_CATEGORY]
    supplemental = [n for n in narrative_rows if n.get("category") == _SUPPLEMENTAL_CATEGORY]
    roles = [
        n
        for n in narrative_rows
        if n.get("category") not in (_OVERVIEW_CATEGORY, _SUPPLEMENTAL_CATEGORY)
    ]

    sections: list[str] = []
    if overview:
        sections.append(_section("## Career Overview", overview))
    if roles:
        sections.append(_section("## Role Narratives", roles))
    if supplemental:
        sections.append(
            _section(
                "## Additional Background (not employment — do not list as roles)",
                supplemental,
            )
        )

    return "\n\n".join(sections)


def _format_fit_report(fit_report: dict[str, Any]) -> str:
    """Format fit report into structured guidance for the generator.

    Converts the pre-computed fit assessment into readable sections showing:
    - What requirements are clearly matched
    - What gaps exist and how to handle them
    - Which terminology should be used
    """
    lines = []

    # dict_items: tool input_schema is advisory, so scalar items can appear
    # where objects were declared. See tests/test_tool_result_validation.py.

    # MATCHES section
    matches = dict_items(fit_report.get("matches"))
    if matches:
        lines.append("MATCHES — requirements you clearly meet (emphasize these):")
        for match in matches:
            priority = match.get("priority", "required").upper()
            req = match.get("requirement", "")
            notes = match.get("notes", "")
            notes_str = _format_note(notes)
            lines.append(f"  - [{priority}] {req}{notes_str}")

    # GAPS section (separated by type)
    gaps = dict_items(fit_report.get("gaps"))
    soft_gaps = [g for g in gaps if g.get("type") == "soft"]
    hard_gaps = [g for g in gaps if g.get("type") == "hard"]

    if soft_gaps:
        lines.append("\nGAPS — soft (position adjacent strengths if relevant):")
        for gap in soft_gaps:
            req = gap.get("requirement", "")
            notes = gap.get("notes", "")
            notes_str = _format_note(notes)
            lines.append(f"  - [SOFT] {req}{notes_str}")

    if hard_gaps:
        lines.append("\nGAPS — hard (leave as gap, do not bridge):")
        for gap in hard_gaps:
            req = gap.get("requirement", "")
            notes = gap.get("notes", "")
            notes_str = _format_note(notes)
            lines.append(f"  - [HARD] {req}{notes_str}")

    # TERMINOLOGY section
    terminology = fit_report.get("terminology", [])
    if terminology:
        lines.append("\nTERMINOLOGY — use JD's exact terms where experience matches:")
        for term in terminology:
            my_term = term.get("my_term", "")
            jd_term = term.get("jd_term", "")
            lines.append(f"  - {my_term} → {jd_term}")

    return "\n".join(lines)


def _format_contact_info(contact_info: dict[str, Any] | None) -> str:
    """Format contact info into readable text for generator prompt."""
    if not contact_info:
        return ""

    lines = []
    if contact_info.get("email"):
        lines.append(f"Email: {contact_info['email']}")
    if contact_info.get("phone"):
        lines.append(f"Phone: {contact_info['phone']}")
    if contact_info.get("location"):
        lines.append(f"Location: {contact_info['location']}")
    if contact_info.get("linkedin"):
        lines.append(f"LinkedIn: {contact_info['linkedin']}")
    if contact_info.get("github"):
        lines.append(f"GitHub: {contact_info['github']}")
    if contact_info.get("website"):
        lines.append(f"Website: {contact_info['website']}")

    return "\n".join(lines)


def run_generator(
    narratives_text: str,
    fit_report: dict[str, Any],
    contact_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """Step 1: Generator perspective — create strategic resume guided by fit assessment.

    Receives pre-computed fit report (matches/gaps/terminology) to inform strategic choices:
    - Emphasize matched requirements
    - Handle soft gaps by positioning adjacent strengths
    - Omit hard gaps entirely
    - Use exact terminology from the JD where applicable

    Args:
        narratives_text: Formatted candidate narratives
        fit_report: Pre-computed fit assessment
        contact_info: Optional contact information (email, phone, location,
            linkedin, github, website)

    Returns:
        Structured resume data: {summary, experience, skills, contact, ...}

    Raises:
        RuntimeError: If API call fails or no tool response found
    """
    system_prompt = load_prompt("generator")
    fit_guidance = _format_fit_report(fit_report)
    contact_text = _format_contact_info(contact_info)

    # Narratives lead, so they sit in the cached prefix. See split_for_cache.
    stable = f"<candidate_background>\n{narratives_text}\n</candidate_background>\n\n"
    user_message = f"<fit_assessment>\n{fit_guidance}\n</fit_assessment>\n\n"

    if contact_text:
        user_message += f"<contact_info>\n{contact_text}\n</contact_info>\n\n"

    user_message += (
        "Create a focused, strategic resume that highlights strengths matching the role. "
        "Use the fit assessment above to guide emphasis, handle gaps appropriately, and use the "
        "exact terminology from the JD. "
        "Include your contact information in the contact field if provided. "
        "Use the submit_resume_draft tool to submit your output."
    )

    # cast needed: Anthropic SDK requires Any type for tools parameter despite static type hints
    return call_model(
        "generate",
        model=PIPELINE_MODEL,
        # 8192: full-resume output; same shape as refinement, which truncated
        # at 4096 under the claude-sonnet-5 tokenizer (stop_reason=max_tokens)
        max_tokens=8192,
        system=cached_system(system_prompt),
        messages=[{"role": "user", "content": split_for_cache(stable, user_message)}],
        tools=cast(
            Any,
            [
                {
                    "name": _TOOL_NAME,
                    "description": "Submit the generated resume draft",
                    "input_schema": _GENERATOR_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )
