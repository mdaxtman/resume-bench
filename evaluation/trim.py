"""Selectivity: does a shorter resume, made only by removing bullets, score better?

Every document either arm has produced is ~1,000–1,100 words and ~30 bullets.
Length has never been varied, and readability has never scored above 7, so
"the top of the scale is unreachable for documents of this class" and "the top
of the scale is unreachable at this length" have not been told apart.

Trimming here is verbatim. Bullets are removed, never reworded, so a change in
score is attributable to selection and length rather than to wording. Role
headers always stay, so the timeline a judge reads is unchanged; a project
header goes only when its last bullet does.

What gets removed first is decided by three things, in order: a per-bullet
relevance rating from a call that sees only the JD and the bullets; how much
literal keyword coverage the bullet alone is carrying; and age. The most recent
role always keeps at least one bullet.

The ordering is computed once per document and each budget takes a prefix of
it, so the conditions differ only in how far down one ordering they go.
"""

import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import JUDGE_MODEL, PROMPTS_DIR, RUNS_DIR
from corpus import load_jd
from evaluation.keywords import Keyword, cached_keywords, coverage, term_present
from evaluation.report import gate_record, gated
from evaluation.rescore import strip_leading_title
from evaluation.sweep import score_document
from pipeline.anthropic_utils import call_model, dict_items
from telemetry import tracing

_TOOL = "submit_ratings"
MAX_RATING = 3

_EXPERIENCE = re.compile(r"^##\s+.*experience", re.IGNORECASE)
_SECTION = re.compile(r"^##(?!#)")
_BULLET = re.compile(r"^[-*]\s+(.*\S)\s*$")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


@dataclass(frozen=True)
class Bullet:
    index: int  # position among Experience bullets, 0-based
    line: int  # line number in the document
    text: str
    role: int  # 0 is the most recent role
    context: str  # the role header, stripped of markup
    header: int | None  # line number of the project header above it, if any


def _is_role_header(line: str) -> bool:
    """`### Company — Title (dates)` in control documents, and
    `**Title** at Company (dates)` in pipeline ones. Project headers carry no
    dates — the generator is told not to give them any."""
    return line.startswith("###") or bool(_YEAR.search(line))


def experience_bullets(md: str) -> list[Bullet]:
    bullets: list[Bullet] = []
    in_experience = False
    role, context, header = -1, "", None
    previous = ""  # the last non-blank line, if it was a header rather than a bullet
    for n, line in enumerate(md.split("\n")):
        if _SECTION.match(line):
            in_experience = bool(_EXPERIENCE.match(line))
            continue
        if not in_experience or not line.strip():
            continue
        bullet = _BULLET.match(line)
        if bullet:
            bullets.append(Bullet(len(bullets), n, bullet.group(1), max(role, 0), context, header))
            previous = ""
        elif _is_role_header(line):
            # `**Employer — Title**` then `*dates*` on the next line: the dated
            # line marks the role, and the undated one above it names it.
            role, context, header = role + 1, _plain(f"{previous} {line}"), None
            previous = ""
        else:
            header, previous = n, line
    return bullets


def _plain(text: str) -> str:
    return " ".join(text.replace("*", "").replace("#", "").split())


def remove_bullets(md: str, drop: set[int]) -> str:
    """The document without the bullets indexed in `drop`, and without any
    project header left with nothing under it. Everything else is untouched."""
    if not drop:
        return md
    bullets = experience_bullets(md)
    gone = {b.line for b in bullets if b.index in drop}
    for header in {b.header for b in bullets if b.header is not None}:
        under = [b for b in bullets if b.header == header]
        if all(b.index in drop for b in under):
            gone.add(header)
    kept = [line for n, line in enumerate(md.split("\n")) if n not in gone]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept))


def word_count(md: str) -> int:
    return len(md.split())


def _coverage_cost(before: str, after: str, keywords: list[Keyword]) -> tuple[int, int]:
    """(required, preferred) terms present before a removal and absent after."""
    lost = [k for k in keywords if term_present(before, k) and not term_present(after, k)]
    return sum(k.required for k in lost), sum(not k.required for k in lost)


def removal_order(md: str, ratings: dict[int, int], keywords: list[Keyword]) -> list[int]:
    """Greedy order in which bullets are removed, cheapest first.

    Cost is (relevance rating, required terms only this bullet carries,
    preferred terms only it carries, recency, position). Coverage is recomputed
    against the document as it stands, because a term carried by two bullets
    is free to lose once and expensive to lose twice.
    """
    bullets = experience_bullets(md)
    every = {b.index for b in bullets}
    recent = {b.index for b in bullets if b.role == 0}
    kept = set(every)
    order: list[int] = []
    while True:
        candidates = [
            b
            for b in bullets
            if b.index in kept and not (b.index in recent and len(kept & recent) == 1)
        ]
        if not candidates:
            return order
        current = remove_bullets(md, every - kept)

        def cost(b: Bullet) -> tuple[int, int, int, int, int]:
            without = remove_bullets(md, (every - kept) | {b.index})
            required, preferred = _coverage_cost(current, without, keywords)
            return (ratings[b.index], required, preferred, -b.role, -b.index)

        victim = min(candidates, key=cost)
        order.append(victim.index)
        kept.discard(victim.index)


def trim_to_budget(md: str, order: list[int], budget: int) -> tuple[str, list[int]]:
    """The shortest prefix of `order` that brings the document within budget.

    If the order runs out first, the floor is returned: everything removable
    has been removed and the caller can see the budget was not met.
    """
    if word_count(md) <= budget:
        return md, []
    for k in range(1, len(order) + 1):
        doc = remove_bullets(md, set(order[:k]))
        if word_count(doc) <= budget:
            return doc, order[:k]
    return remove_bullets(md, set(order)), list(order)


@dataclass(frozen=True)
class BulletRelevanceInput:
    """The JD and the bullets, each labelled with its role. No narratives: this
    is a selection step reading a document, not a candidate."""

    jd: str
    bullets: tuple[Bullet, ...]


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ratings"],
    "properties": {
        "ratings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "rating"],
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "rating": {"type": "integer", "minimum": 0, "maximum": MAX_RATING},
                },
            },
        }
    },
}


def build_relevance_request(inp: BulletRelevanceInput) -> dict[str, Any]:
    listing = "\n".join(f"[{b.index}] ({b.context}) {b.text}" for b in inp.bullets)
    return {
        "model": JUDGE_MODEL,
        "max_tokens": 2048,
        "system": (PROMPTS_DIR / "bullet_relevance.md").read_text(),
        "messages": [
            {
                "role": "user",
                "content": f"<job_description>\n{inp.jd}\n</job_description>\n\n"
                f"<bullets>\n{listing}\n</bullets>\n\n"
                f"Rate every bullet using the {_TOOL} tool.",
            }
        ],
        "tools": [{"name": _TOOL, "description": "Submit bullet ratings", "input_schema": _SCHEMA}],
        "tool_choice": {"type": "tool", "name": _TOOL},
    }


def _parsed_ratings(result: dict[str, Any]) -> dict[int, int]:
    return {int(item["index"]): int(item["rating"]) for item in dict_items(result.get("ratings"))}


def ratings_complete(result: dict[str, Any], count: int) -> bool:
    """Exactly one in-range rating per bullet. A missing bullet would otherwise
    have no cost, and be removed first by default rather than by judgement."""
    try:
        ratings = _parsed_ratings(result)
    except (KeyError, TypeError, ValueError):
        return False
    return set(ratings) == set(range(count)) and all(0 <= r <= MAX_RATING for r in ratings.values())


def rate_bullets(inp: BulletRelevanceInput) -> dict[int, int]:
    result = call_model(
        "bullet_relevance",
        validate=lambda r: ratings_complete(r, len(inp.bullets)),
        attempts=3,
        **build_relevance_request(inp),
    )
    return _parsed_ratings(result)


def condition_name(arm: str, budget: int | None) -> str:
    return f"{arm}-{'full' if budget is None else budget}"


def run_trim(
    trim_id: str,
    source: Path,
    slug: str,
    arm: str,
    sample: int,
    budgets: list[int],
    narratives: str,
) -> list[dict[str, Any]]:
    """Score one source document untrimmed and at every budget.

    Laid out as runs/<trim_id>/<slug>/<arm>-<budget>/sample-<n>/, the same depth
    as a sweep, so `reliability` and `coverage` run against it unchanged.
    Idempotent per condition, like a sweep sample.
    """
    jd = load_jd(slug)
    md = strip_leading_title(source.read_text())
    keywords = cached_keywords(slug, jd)
    bullets = experience_bullets(md)

    full_dir = RUNS_DIR / trim_id / slug / condition_name(arm, None) / f"sample-{sample}"
    full_dir.mkdir(parents=True, exist_ok=True)
    ratings_path = full_dir / "relevance.json"
    if ratings_path.is_file():
        ratings = {int(k): int(v) for k, v in json.loads(ratings_path.read_text()).items()}
    else:
        with tracing(full_dir / "trace.jsonl"):
            ratings = rate_bullets(BulletRelevanceInput(jd=jd, bullets=tuple(bullets)))
        ratings_path.write_text(json.dumps(ratings, indent=2))
    order = removal_order(md, ratings, keywords)

    results = []
    for budget in (None, *budgets):
        out = RUNS_DIR / trim_id / slug / condition_name(arm, budget) / f"sample-{sample}"
        scores_path = out / "scores.json"
        if scores_path.is_file():
            results.append(dict(json.loads(scores_path.read_text())))
            continue

        doc, dropped = (md, []) if budget is None else trim_to_budget(md, order, budget)
        out.mkdir(parents=True, exist_ok=True)
        (out / "resume.md").write_text(doc)
        (out / "coverage.json").write_text(json.dumps(coverage(doc, keywords), indent=2))
        (out / "trim.json").write_text(
            json.dumps(
                {
                    "source": str(source),
                    "budget": budget,
                    "words_before": word_count(md),
                    "words": word_count(doc),
                    "floor_reached": budget is not None and word_count(doc) > budget,
                    "bullets_before": len(bullets),
                    "dropped": [
                        {"index": i, "rating": ratings[i], "text": bullets[i].text} for i in dropped
                    ],
                },
                indent=2,
            )
        )
        with tracing(out / "trace.jsonl"):
            scored = score_document(jd, doc, narratives)
        scores = {
            "slug": slug,
            "arm": condition_name(arm, budget),
            "source_arm": arm,
            "budget": budget,
            "sample": sample,
            "words": word_count(doc),
            **scored,
        }
        scores_path.write_text(json.dumps(scores, indent=2))
        results.append(scores)
    return results


# Two-sided 95% critical values of Student's t. Thirteen jobs is 12 degrees of
# freedom, where z would understate an interval by about a tenth.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306}
_T95 |= {9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131}
_T95 |= {16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}


def _t95(df: int) -> float:
    if df > 30:
        return 1.96
    return _T95[max(k for k in _T95 if k <= df)]


def mean_ci(values: list[float]) -> tuple[float, float, float]:
    """(mean, low, high) of a 95% t interval."""
    mean = statistics.mean(values)
    if len(values) < 2:
        return mean, mean, mean
    half = _t95(len(values) - 1) * statistics.stdev(values) / len(values) ** 0.5
    return mean, mean - half, mean + half


def metric(row: dict[str, Any], name: str) -> float:
    parts = row.get("readability_parts") or {}
    return float(parts[name] if name in parts else row[name])


def paired_deltas(
    rows: list[dict[str, Any]], name: str, budget: int, arms: set[str]
) -> list[float]:
    """Per-job (mean at budget) - (mean untrimmed), over gated documents.

    The job is the unit of independence: three samples of one posting are not
    three trials, and between-job spread is larger than any effect here.
    """
    rows = [r for r in gated(rows) if r["source_arm"] in arms]
    deltas = []
    for slug in sorted({r["slug"] for r in rows}):
        trimmed = [metric(r, name) for r in rows if r["slug"] == slug and r["budget"] == budget]
        full = [metric(r, name) for r in rows if r["slug"] == slug and r["budget"] is None]
        if trimmed and full:
            deltas.append(statistics.mean(trimmed) - statistics.mean(full))
    return deltas


def load_trim(trim_id: str) -> list[dict[str, Any]]:
    root = RUNS_DIR / trim_id
    if not root.is_dir():
        raise ValueError(f"No trim experiment at {root}")
    rows = []
    for path in sorted(root.glob("*/*/sample-*/scores.json")):
        row = dict(json.loads(path.read_text()))
        cov = json.loads((path.parent / "coverage.json").read_text())
        trim = json.loads((path.parent / "trim.json").read_text())
        row["coverage"] = 100 * float(cov["required_coverage"] or 0.0)
        row["bullets"] = trim["bullets_before"] - len(trim["dropped"])
        rows.append(row)
    return rows


_LEVELS = [
    ("words", "words"),
    ("bullets", "bullets"),
    ("jd_alignment", "jd alignment"),
    ("recruiter_readability", "readability"),
    ("opening", "  opening"),
    ("scannability", "  scannability *"),
    ("economy", "  economy"),
    ("structure", "  structure"),
    ("hire_intent", "hire intent"),
    ("coverage", "coverage (req, %)"),
    ("authenticity", "authenticity"),
    ("composite", "composite"),
]
_DELTAS = [k for k, _ in _LEVELS if k not in ("words", "bullets", "authenticity")]


def render_trim(trim_id: str, rows: list[dict[str, Any]]) -> str:
    budgets = sorted({r["budget"] for r in rows if r["budget"] is not None}, reverse=True)
    columns: list[int | None] = [None, *budgets]
    groups = [(a, {a}) for a in sorted({r["source_arm"] for r in rows})]
    if len(groups) > 1:
        groups.append(("both arms", {a for _, arms in groups for a in arms}))

    jobs = len({r["slug"] for r in rows})
    lines = [f"{trim_id} — {jobs} JDs, {len(rows)} scored documents", "=" * 78]
    gate = gate_record(rows)
    failed = {arm: f"{t - p}/{t}" for arm, (p, t) in gate.items() if p < t}
    lines.append(
        "Authenticity gate: all documents passed"
        if not failed
        else "Authenticity gate failures (excluded): "
        + ", ".join(f"{a} {f}" for a, f in failed.items())
    )

    head = f"{'':<22}" + "".join(f"{'full' if b is None else b:>10}" for b in columns)
    for name, arms in groups:
        passing = [r for r in gated(rows) if r["source_arm"] in arms]
        lines += ["", f"{name}: means over passing documents", head]
        for key, label in _LEVELS:
            cells = []
            for b in columns:
                values = [metric(r, key) for r in passing if r["budget"] == b]
                fmt = (
                    ".0f" if key in ("words", "bullets") else ".1f" if key == "coverage" else ".2f"
                )
                cells.append(f"{statistics.mean(values):>10{fmt}}" if values else f"{'—':>10}")
            lines.append(f"{label:<22}" + "".join(cells))

        lines += ["", f"{name}: delta vs full, paired by job — mean [95% CI] (jobs up/down)"]
        lines.append(f"{'':<22}" + "".join(f"{b:>28}" for b in budgets))
        for key in _DELTAS:
            label = dict(_LEVELS)[key]
            cells = []
            for b in budgets:
                deltas = paired_deltas(rows, key, b, arms)
                if not deltas:
                    cells.append(f"{'—':>28}")
                    continue
                mean, lo, hi = mean_ci(deltas)
                up = sum(d > 0 for d in deltas)
                down = sum(d < 0 for d in deltas)
                cells.append(f"{f'{mean:+.2f} [{lo:+.2f},{hi:+.2f}] ({up}/{down})':>28}")
            lines.append(f"{label:<22}" + "".join(cells))

    lines += [
        "",
        "* scannability is a negative control: trimming never rewords a bullet,",
        "  so a movement there is the judge's overall impression, not the bullets.",
    ]
    return "\n".join(lines)
