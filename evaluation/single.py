"""The single-call arm: the generator's rules in one call, with no fit report.

Against the control, the pipeline's one lasting advantage is honesty: about 1.6
fewer unsupported claims a document, under both judges, at a lower composite.
But the control's prompt has one sentence about grounding, and the generator's
carries every rule this harness has found to matter: the summary held to the
candidate's own work, skills held to the narratives, gaps named at their true
depth, ownership verbs, the bullet budget. The advantage may be the rules, not
the staging. No measurement here has separated the two.

This arm gives one call those rules. `prompts/generator_single.md` is the
generator's prompt with each reference to the fit report replaced by the
comparison the fit stage would have made, and nothing else changed. The call
reads the narratives and the posting and is held to the same bullet budget,
and the same code sorts its roles. There is no fit assessment, screener, or
refinement.

The `draft` arm scores the pipeline's own draft, before the screener and
refinement, from the pipeline sample with the same index. It generates
nothing. Between them the four arms attribute any difference: the fit stage
(`single` against `draft`), the screener and refinement (`draft` against
`pipeline`), and the prompt (`single` against `control`).

The rule, fixed before the run. Paired by job against the pipeline in the same
sweep, `single` is kept, and the staging is reported as adding nothing
measurable over one call, unless any of these holds:

- its net composite is demonstrably lower (the 95% interval lies below zero)
  under the committed judge, or under the verdict judge
- its composite is demonstrably lower
- fewer of its 39 documents pass the authenticity gate than the pipeline's

If any holds, the staging has earned its three extra calls, and the arm is
reverted.

None held, and the arm is kept (single-01). Against the pipeline every
difference is inside noise under both judges, at a quarter of the calls. See
the README, *Does the staging beat one call with the same rules?*
"""

import json
from typing import Any, cast

from config import PIPELINE_MODEL, RUNS_DIR
from pipeline.anthropic_utils import cached_system, call_model, split_for_cache
from pipeline.generator import (
    _GENERATOR_SCHEMA,
    _TOOL_NAME,
    BULLET_BUDGET,
    _format_contact_info,
    draft_is_usable,
    order_roles,
)
from pipeline.prompts import load_prompt
from render import build_resume_markdown


def run_single(jd: str, narratives_text: str, contact_info: dict[str, Any] | None) -> str:
    """One call with the generator's rules. Returns markdown.

    The request is the generator's with the fit assessment left out and its
    closing instruction pointed at the posting instead.
    """
    stable = f"<candidate_background>\n{narratives_text}\n</candidate_background>\n\n"
    user_message = f"<job_description>\n{jd}\n</job_description>\n\n"
    contact_text = _format_contact_info(contact_info)
    if contact_text:
        user_message += f"<contact_info>\n{contact_text}\n</contact_info>\n\n"
    user_message += (
        "Create a focused, strategic resume that highlights strengths matching the role. "
        "Compare the posting with the narratives to guide emphasis, handle gaps "
        "appropriately, and use the exact terminology from the JD. "
        "Include your contact information in the contact field if provided. "
        "Use the submit_resume_draft tool to submit your output.\n\n"
        f"Hard limit: at most {BULLET_BUDGET} bullets in total across every role and project. "
        "Count them before you submit."
    )
    draft = call_model(
        "single",
        validate=draft_is_usable,
        attempts=3,
        model=PIPELINE_MODEL,
        max_tokens=8192,
        system=cached_system(load_prompt("generator_single")),
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
    return build_resume_markdown(order_roles(draft))


def pipeline_draft(sweep_id: str, slug: str, index: int) -> str:
    """The draft the pipeline sample with this index handed to its screener."""
    path = RUNS_DIR / sweep_id / slug / "pipeline" / f"sample-{index}" / "artefacts.json"
    if not path.is_file():
        raise ValueError(f"no pipeline sample {index} for {slug} to take the draft from")
    return str(json.loads(path.read_text())["draft"])
