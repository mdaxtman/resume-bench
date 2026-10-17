"""Summary written last: does a summary written after the rest of the resume,
and checked against the narratives, beat the one the generator writes first?

The generator writes the summary before anything else, alongside bullets it has
not finished choosing, and refinement may not add a summary sentence. A summary
written for the posting from a finished document was the largest single effect
the bench has measured (*Does a master resume beat writing for each posting?*),
but that one could not see the narratives, and one judge charged it with the
claims it made. This writes the summary last, from the finished document, with
the narratives in view and an instruction to check every statement against
them.

Everything but the summary is held fixed. Each source document runs under three
conditions, laid out as runs/<id>/<slug>/<condition>/sample-<n>/ so `coverage`
and `reliability` run against it unchanged:

- `full`: the document as the pipeline finished it, re-scored in the same run,
  so every condition is measured by the same ruler.
- `none`: the summary removed, which is what the summary is worth.
- `last`: the summary rewritten last.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from config import PIPELINE_MODEL, PROMPTS_DIR, RUNS_DIR
from corpus import load_jd
from evaluation.keywords import cached_keywords, coverage
from evaluation.sweep import score_document
from pipeline.anthropic_utils import cached_system, call_model, split_for_cache
from pipeline.generator import _format_fit_report
from telemetry import tracing

_TOOL = "submit_summary"
CONDITIONS = ("full", "none", "last")

_SUMMARY = re.compile(r"^##\s+summary\s*$", re.IGNORECASE)
_SECTION = re.compile(r"^##(?!#)")


def _summary_span(md: str) -> tuple[int, int]:
    """Line range of the summary section: its heading through the line before
    the next `##` heading."""
    lines = md.split("\n")
    start = next((i for i, line in enumerate(lines) if _SUMMARY.match(line)), None)
    if start is None:
        raise ValueError("no ## Summary section")
    end = next((i for i in range(start + 1, len(lines)) if _SECTION.match(lines[i])), len(lines))
    return start, end


def summary_text(md: str) -> str:
    start, end = _summary_span(md)
    return "\n".join(md.split("\n")[start + 1 : end]).strip()


def remove_summary(md: str) -> str:
    """The document with its summary section gone and every other line kept."""
    start, end = _summary_span(md)
    lines = md.split("\n")
    return "\n".join(lines[:start] + lines[end:])


def replace_summary(md: str, text: str) -> str:
    """The document with only the summary paragraph changed."""
    start, end = _summary_span(md)
    lines = md.split("\n")
    return "\n".join([*lines[: start + 1], text.strip(), "", *lines[end:]])


@dataclass(frozen=True)
class SummaryInput:
    """The resume arrives without its summary: the writer never sees the one it
    replaces, so the condition is a summary written last, not a revision."""

    jd: str
    narratives: str
    product_connection: str | None
    resume: str


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}

# Restated last in the request, as the generator's bullet budget is: a pilot's
# three summaries ran 63-78 words with the cap stated only in the prompt.
SUMMARY_WORDS = 55


def build_summary_request(inp: SummaryInput) -> dict[str, Any]:
    fit = _format_fit_report({"product_connection": inp.product_connection})
    # Narratives lead, so they sit in the cached prefix. See split_for_cache.
    stable = f"<candidate_background>\n{inp.narratives}\n</candidate_background>\n\n"
    variable = f"<job_description>\n{inp.jd}\n</job_description>\n\n"
    if fit:
        variable += f"<fit_assessment>\n{fit}\n</fit_assessment>\n\n"
    variable += (
        f"<resume>\n{inp.resume}\n</resume>\n\n"
        f"Write the summary for this resume, check it, and submit it using the {_TOOL} tool.\n\n"
        f"Hard limit: at most {SUMMARY_WORDS} words. Count them before you submit."
    )
    return {
        "model": PIPELINE_MODEL,
        "max_tokens": 2048,
        "system": cached_system((PROMPTS_DIR / "summary_last.md").read_text()),
        "messages": [{"role": "user", "content": split_for_cache(stable, variable)}],
        "tools": [
            {"name": _TOOL, "description": "Submit the resume summary", "input_schema": _SCHEMA}
        ],
        "tool_choice": {"type": "tool", "name": _TOOL},
    }


def summary_usable(result: dict[str, Any]) -> bool:
    """One paragraph of prose: no heading, and none of the tool-call markup that
    has leaked into a generator's summary before."""
    text = result.get("summary")
    return (
        isinstance(text, str)
        and bool(text.strip())
        and not re.search(r"^#", text.strip(), re.MULTILINE)
        and "<parameter" not in text
        and "</" not in text
    )


def write_summary(inp: SummaryInput) -> str:
    result = call_model(
        "summary_last", validate=summary_usable, attempts=3, **build_summary_request(inp)
    )
    return " ".join(cast(str, result["summary"]).split())


def run_summary(
    sweep_id: str, source: Path, slug: str, sample: int, narratives: str
) -> list[dict[str, Any]]:
    """Score one finished pipeline document under every condition.

    `source` is the sample directory: its resume.md is the document, and its
    artefacts.json holds the fit stage's product connection, which the
    generator's summary rule refers to. Idempotent per condition.
    """
    jd = load_jd(slug)
    md = (source / "resume.md").read_text()
    keywords = cached_keywords(slug, jd)
    fit = json.loads((source / "artefacts.json").read_text()).get("fit") or {}
    connection = fit.get("product_connection")
    without = remove_summary(md)

    results = []
    for condition in CONDITIONS:
        out = RUNS_DIR / sweep_id / slug / condition / f"sample-{sample}"
        scores_path = out / "scores.json"
        if scores_path.is_file():
            results.append(dict(json.loads(scores_path.read_text())))
            continue
        out.mkdir(parents=True, exist_ok=True)

        with tracing(out / "trace.jsonl"):
            if condition == "full":
                doc, text = md, summary_text(md)
            elif condition == "none":
                doc, text = without, ""
            else:
                text = write_summary(
                    SummaryInput(
                        jd=jd,
                        narratives=narratives,
                        product_connection=connection if isinstance(connection, str) else None,
                        resume=without,
                    )
                )
                doc = replace_summary(md, text)
            (out / "resume.md").write_text(doc)
            (out / "coverage.json").write_text(json.dumps(coverage(doc, keywords), indent=2))
            (out / "summary.json").write_text(
                json.dumps(
                    {
                        "source": str(source),
                        "original": summary_text(md),
                        "summary": text,
                        "words": len(text.split()),
                    },
                    indent=2,
                )
            )
            scored = score_document(jd, doc, narratives)

        scores = {
            "slug": slug,
            "arm": condition,
            "sample": sample,
            "summary_words": len(text.split()),
            "words": len(doc.split()),
            **scored,
        }
        scores_path.write_text(json.dumps(scores, indent=2))
        results.append(scores)
    return results
