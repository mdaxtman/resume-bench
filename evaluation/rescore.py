"""Re-score previously generated resumes under the current judges.

Holds the documents fixed and varies only the ruler. A fresh sweep cannot
separate "the pipeline changed" from "the measurement changed"; this can,
because the documents are byte-identical to the ones the old scoring saw.

Two things have to be normalised first. Every archived control resume opens with
`# Control Resume`, so a judge told to score blind could read the arm off line
one. And several pipeline resumes open with the candidate's name, which appears
on that side only. Any leading H1 is therefore dropped, rather than a blocklist
of the labels that happen to be in this archive.

Caveat worth stating wherever these numbers appear: the archived documents were
generated against earlier narratives and earlier prompts. Authenticity is scored
against the *current* narratives, so a claim that was traceable when written can
read as untraceable now. That is acceptable for the question being asked — both
arms are affected identically — but it makes these scores non-comparable with a
fresh sweep's.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from config import RUNS_DIR
from evaluation.contracts import AuthenticityInput, ColdReadInput
from evaluation.judges import run_authenticity, run_cold_read
from evaluation.sweep import composite
from telemetry import tracing

_LEADING_H1 = re.compile(r"\A\s*#(?!#)[^\n]*\n?")

ARM_FILES = {"pipeline": "refined_resume.md", "control": "control_resume.md"}


def strip_leading_title(text: str) -> str:
    """Drop a leading H1 so neither arm announces itself to the judge."""
    return _LEADING_H1.sub("", text, count=1).lstrip("\n")


def load_slug_map(index_path: Path) -> dict[str, str]:
    """Parse `- \\`<redacted>\\` <- <original>` lines into original -> redacted."""
    if not index_path.is_file():
        return {}
    pairs = re.findall(r"^- `([^`]+)` <- (.+)$", index_path.read_text(), re.MULTILINE)
    return {original.strip(): redacted for redacted, original in pairs}


def redacted_slug(original: str, mapping: dict[str, str]) -> str:
    """Never let a real employer slug reach a report that might be published."""
    if original in mapping:
        return mapping[original]
    return "unmapped-" + hashlib.sha256(original.encode()).hexdigest()[:8]


def discover(source_root: Path, mapping: dict[str, str]) -> list[dict[str, Any]]:
    """Find every (run, arm) pair in an archive laid out as <slug>/runs/<date>/."""
    found: list[dict[str, Any]] = []
    for job_dir in sorted(p for p in source_root.iterdir() if p.is_dir()):
        jd_path = job_dir / "jd.md"
        runs = sorted(p for p in (job_dir / "runs").glob("*") if p.is_dir()) if (
            job_dir / "runs"
        ).is_dir() else []
        if not jd_path.is_file() or not runs:
            continue
        slug = redacted_slug(job_dir.name, mapping)
        for index, run_dir in enumerate(runs, start=1):
            for arm, filename in ARM_FILES.items():
                doc = run_dir / filename
                if doc.is_file():
                    found.append(
                        {
                            "slug": slug,
                            "arm": arm,
                            "sample": index,
                            "source_run": run_dir.name,
                            "doc": doc,
                            "jd": jd_path,
                        }
                    )
    return found


def rescore_one(sweep_id: str, item: dict[str, Any], narratives: str) -> dict[str, Any]:
    out = RUNS_DIR / sweep_id / item["slug"] / item["arm"] / f"sample-{item['sample']}"
    scores_path = out / "scores.json"
    if scores_path.is_file():
        return dict(json.loads(scores_path.read_text()))

    out.mkdir(parents=True, exist_ok=True)
    resume = strip_leading_title(Path(item["doc"]).read_text())
    jd = Path(item["jd"]).read_text()
    (out / "resume.md").write_text(resume)

    with tracing(out / "trace.jsonl"):
        cold = run_cold_read(ColdReadInput(jd=jd, resume=resume))
        auth = run_authenticity(AuthenticityInput(resume=resume, narratives=narratives))

    scores = {
        "slug": item["slug"],
        "arm": item["arm"],
        "sample": item["sample"],
        "source_run": item["source_run"],
        "jd_alignment": cold.jd_alignment,
        "recruiter_readability": cold.recruiter_readability,
        "hire_intent": cold.hire_intent,
        "authenticity": auth.authenticity,
        "claims_checked": auth.claims_checked,
        "untraceable": auth.untraceable,
        "overstatements": auth.overstatements,
        "composite": composite(cold.jd_alignment, cold.recruiter_readability, auth.authenticity),
        "notes": cold.notes,
    }
    scores_path.write_text(json.dumps(scores, indent=2))
    return scores
