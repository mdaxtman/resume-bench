"""Loads stage prompts from `prompts/*.md`.

The web app kept prompts in Postgres so they could be versioned and swapped
without a redeploy. Here they are files, versioned by git — which is strictly
better for the harness's purpose: a sweep result is only interpretable if you
can name the exact prompt text that produced it, and a commit SHA does that.
"""

from datetime import date

from config import PROMPTS_DIR

_KNOWN = ("fit_assessment", "generator", "resume_screener", "refinement")


def load_prompt(stage: str) -> str:
    """Load a stage prompt, substituting today's date for `{today}`.

    The judges were given the date first (`evaluation.judges._prompt`). The
    screener, without it, read the current role's recent start as a future
    date and flagged it as a typo in 4 of 39 documents, and refinement moved
    the date back a year or two in exactly those four.
    """
    path = PROMPTS_DIR / f"{stage}.md"
    if not path.is_file():
        raise ValueError(f"No prompt file for stage {stage!r} (looked for {path}). Known: {_KNOWN}")
    return path.read_text().replace("{today}", date.today().isoformat())
