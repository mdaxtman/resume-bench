"""Loads stage prompts from `prompts/*.md`.

The web app kept prompts in Postgres so they could be versioned and swapped
without a redeploy. Here they are files, versioned by git — which is strictly
better for the harness's purpose: a sweep result is only interpretable if you
can name the exact prompt text that produced it, and a commit SHA does that.
"""

from config import PROMPTS_DIR

_KNOWN = ("fit_assessment", "generator", "resume_screener", "refinement")


def load_prompt(stage: str) -> str:
    path = PROMPTS_DIR / f"{stage}.md"
    if not path.is_file():
        raise ValueError(f"No prompt file for stage {stage!r} (looked for {path}). Known: {_KNOWN}")
    return path.read_text()
