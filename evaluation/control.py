"""The control arm: one-shot generation, no pipeline.

Same model, same narratives, same JD, same "write the best resume you can"
instruction — and none of the fit assessment, screening, or refinement. That
isolation is the whole point: a pipeline that beats no baseline has not been
shown to do anything, and a strong single prompt is a genuinely hard baseline
to beat. Every measured delta is attributable to the staged structure, because
the structure is the only variable.
"""

from config import PIPELINE_MODEL, PROMPTS_DIR
from pipeline.anthropic_utils import cached_system, call_model_text, split_for_cache


def run_control(jd_content: str, narratives_text: str) -> str:
    """Generate a baseline resume in a single call. Returns markdown."""
    return call_model_text(
        "control",
        model=PIPELINE_MODEL,
        max_tokens=4096,
        system=cached_system((PROMPTS_DIR / "control.md").read_text()),
        messages=[
            {
                "role": "user",
                "content": split_for_cache(
                    f"<candidate_narratives>\n{narratives_text}\n</candidate_narratives>\n\n",
                    f"<job_description>\n{jd_content}\n</job_description>\n\nWrite the resume.",
                ),
            }
        ],
    )
