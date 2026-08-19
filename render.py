"""Rendering structured generator output to markdown.

The generator returns structured data rather than prose so the screener and
refinement stages can reason about sections; this is where it becomes the
document a judge actually reads.
"""

from typing import Any


def build_resume_markdown(resume_data: dict[str, Any]) -> str:
    """Convert structured resume data to markdown format.

    Builds a markdown resume from the structured data returned by Claude,
    including summary, experience, and skills sections with proper formatting.

    Args:
        resume_data: Structured resume containing summary, experience, skills, contact

    Returns:
        Markdown-formatted resume string
    """
    lines = []

    # Contact info header (if available)
    contact = resume_data.get("contact", {})
    if isinstance(contact, dict) and contact:
        contact_parts = []
        if contact.get("email"):
            contact_parts.append(contact["email"])
        if contact.get("phone"):
            contact_parts.append(contact["phone"])
        if contact.get("location"):
            contact_parts.append(contact["location"])
        if contact.get("linkedin"):
            contact_parts.append(contact["linkedin"])
        if contact.get("github"):
            contact_parts.append(contact["github"])
        if contact.get("website"):
            contact_parts.append(contact["website"])

        if contact_parts:
            lines.append(" | ".join(contact_parts))
            lines.append("")

    # Summary section
    summary = resume_data.get("summary", "")
    if summary:
        lines.append("## Summary")
        lines.append(summary)
        lines.append("")

    # Experience section
    experience = resume_data.get("experience", [])
    if experience:
        lines.append("## Experience")
        for exp in experience:
            company = exp.get("company", "")
            title = exp.get("title", "")
            dates = exp.get("dates", "")

            # Company / Title header
            if company and title:
                lines.append(f"### {title} at {company}")
            elif company or title:
                lines.append(f"### {company or title}")

            if dates:
                lines.append(f"_{dates}_")

            # Projects
            projects = exp.get("projects", [])
            for project in projects:
                project_name = project.get("name", "")
                project_dates = project.get("dates", "")
                bullets = project.get("bullets", [])

                if project_name:
                    lines.append(f"**{project_name}**")
                    if project_dates:
                        lines.append(f"_{project_dates}_")

                for bullet in bullets:
                    lines.append(f"- {bullet}")

            lines.append("")

    # Skills section
    skills = resume_data.get("skills", [])
    if skills:
        lines.append("## Skills")
        lines.append(", ".join(skills))
        lines.append("")

    return "\n".join(lines).strip()


