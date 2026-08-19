"""The control arm: one-shot generation, no pipeline.

Same model, same narratives, same JD, same "write the best resume you can"
instruction — and none of the fit assessment, screening, or refinement. That
isolation is the whole point: a pipeline that beats no baseline has not been
shown to do anything, and a strong single prompt is a genuinely hard baseline
to beat. Every measured delta is attributable to the staged structure, because
the structure is the only variable.
"""

import anthropic

from config import PIPELINE_MODEL, PROMPTS_DIR, get_anthropic_api_key

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client  # noqa: PLW0603
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_anthropic_api_key())
    return _client


def run_control(jd_content: str, narratives_text: str) -> str:
    """Generate a baseline resume in a single call. Returns markdown."""
    response = _get_client().messages.create(
        model=PIPELINE_MODEL,
        max_tokens=4096,
        thinking={"type": "disabled"},
        system=(PROMPTS_DIR / "control.md").read_text(),
        messages=[
            {
                "role": "user",
                "content": (
                    f"<candidate_narratives>\n{narratives_text}\n</candidate_narratives>\n\n"
                    f"<job_description>\n{jd_content}\n</job_description>\n\n"
                    "Write the resume."
                ),
            }
        ],
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()
