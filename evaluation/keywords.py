"""Literal keyword coverage against a job description.

Every other axis in this harness is a model's judgement and carries the variance
that implies. This one is arithmetic: a term is present or it is not, and the
answer is identical every time it is computed.

It measures a different thing from `jd_alignment`, which asks a judge whether a
resume *addresses* the requirements. Addressing a requirement is what persuades
a recruiter who is already reading. Containing the term is what causes the
resume to be returned by the search that gets it read at all.

Extraction sees only the JD — the input type has no field for a resume — so one
list is applied to both arms and cannot be fitted to either.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from config import JUDGE_MODEL, PROMPTS_DIR, RUNS_DIR
from pipeline.anthropic_utils import call_model, dict_items

_TOOL = "submit_keywords"


@dataclass(frozen=True)
class KeywordExtractionInput:
    """The JD, and nothing else. No resume, no arm, no prior coverage result."""

    jd: str


@dataclass(frozen=True)
class Keyword:
    term: str
    required: bool = True
    variants: list[str] = field(default_factory=list)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["keywords"],
    "properties": {
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["term", "required", "variants"],
                "properties": {
                    "term": {"type": "string"},
                    "required": {"type": "boolean"},
                    "variants": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


def _pattern(term: str) -> re.Pattern[str]:
    """Delimit by non-alphanumerics rather than \\b.

    `\\b` is defined against word characters, so it cannot delimit a term that
    ends in punctuation — `\\bC\\+\\+\\b` never matches "C++". Lookarounds for an
    adjacent alphanumeric give the property actually wanted: "React" matches
    inside "React.js" but "Java" does not match inside "JavaScript".
    """
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(term.strip())}(?![A-Za-z0-9])", re.IGNORECASE
    )


def term_present(text: str, keyword: Keyword) -> bool:
    return any(_pattern(t).search(text) for t in (keyword.term, *keyword.variants) if t.strip())


def coverage(resume: str, keywords: list[Keyword]) -> dict[str, Any]:
    required = [k for k in keywords if k.required]
    preferred = [k for k in keywords if not k.required]
    found_req = [k for k in required if term_present(resume, k)]
    found_pref = [k for k in preferred if term_present(resume, k)]
    return {
        "required_total": len(required),
        "required_found": len(found_req),
        "required_coverage": (len(found_req) / len(required)) if required else None,
        "preferred_total": len(preferred),
        "preferred_found": len(found_pref),
        "missing_required": [k.term for k in required if k not in found_req],
    }


def _keywords_valid(result: dict[str, Any]) -> bool:
    return len(dict_items(result.get("keywords"))) >= 5


def extract_keywords(inp: KeywordExtractionInput) -> list[Keyword]:
    result = call_model(
        "keyword_extraction",
        validate=_keywords_valid,
        attempts=3,
        model=JUDGE_MODEL,
        max_tokens=2048,
        system=(PROMPTS_DIR / "keyword_extraction.md").read_text(),
        messages=[{"role": "user", "content": f"<job_description>\n{inp.jd}\n</job_description>"}],
        tools=[{"name": _TOOL, "description": "Submit searchable terms", "input_schema": _SCHEMA}],
        tool_choice={"type": "tool", "name": _TOOL},
    )
    return [
        Keyword(
            term=str(item.get("term", "")).strip(),
            required=bool(item.get("required", True)),
            variants=[str(v) for v in (item.get("variants") or []) if str(v).strip()],
        )
        for item in dict_items(result.get("keywords"))
        if str(item.get("term", "")).strip()
    ]


def cached_keywords(slug: str, jd: str) -> list[Keyword]:
    """Extract once per JD and reuse. The list must not vary between arms."""
    path = RUNS_DIR / "keywords" / f"{slug}.json"
    if path.is_file():
        return [Keyword(**k) for k in json.loads(path.read_text())]
    keywords = extract_keywords(KeywordExtractionInput(jd=jd))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([k.__dict__ for k in keywords], indent=2))
    return keywords
