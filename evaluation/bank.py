"""A master resume, written once and chosen from for each posting.

The generator rewrites a resume from 12.5k words of narratives for every
posting, so the wording, the choice of material and every claim are made again
each time, and each time is a chance to overstate. Trimming the single prompt's
resume to 600 words removed about one unsupported claim a document on every
posting: choosing less had paid better than rewording.

Here the writing happens once, with no posting in view. `build_bank` asks for
everything the narratives support, one fact a bullet, and every bullet, skill
and positioning statement carries the passage of the narratives it rests on.
`verify_bank` discards an item whose passage is not in the narratives verbatim,
so what can reach a resume has been checked once, mechanically, and not by the
judge that later scores it.

For each posting nothing is written. A rater scores every item's relevance to
the posting, the least relevant bullets are removed until the document fits a
word budget, and what remains renders exactly as the bank wrote it. The
`bank-summary` condition differs in one thing: its summary is written for the
posting from the chosen document, so the cost of a summary that was not
tailored can be read off the pair.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from config import PIPELINE_MODEL, RUNS_DIR
from corpus import load_jd
from evaluation.keywords import Keyword, cached_keywords, coverage, term_present
from evaluation.sweep import score_document
from pipeline.anthropic_utils import cached_system, call_model, dict_items, split_for_cache
from pipeline.prompts import load_prompt
from render import build_resume_markdown
from telemetry import tracing

CONDITIONS = ("bank", "bank-summary")
MAX_RATING = 3
# A skill goes on the resume when a reader of the posting would look for it or
# it strengthens the case; see prompts/bank_selection.md.
SKILL_THRESHOLD = 2
# Most bullets a project keeps: the generator's own rule, "3-4 bullets" for the
# projects that carry the role's requirements.
PROJECT_CAP = 4
# An evidence passage shorter than this matches too much of the narratives to
# show anything: "React" is in them whether or not the candidate built with it.
MIN_EVIDENCE_WORDS = 5

_BANK_TOOL = "submit_master_resume"
_SELECTION_TOOL = "submit_selection"
_SUMMARY_TOOL = "submit_summary"

_ITEM = {
    "type": "object",
    "required": ["text", "evidence"],
    "properties": {"text": {"type": "string"}, "evidence": {"type": "string"}},
}
_BANK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["roles", "skills", "summaries"],
    "properties": {
        "roles": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["company", "title", "dates", "projects"],
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "dates": {"type": "string"},
                    "projects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "bullets"],
                            "properties": {
                                "name": {"type": "string"},
                                "bullets": {"type": "array", "items": _ITEM},
                            },
                        },
                    },
                },
            },
        },
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "evidence"],
                "properties": {"name": {"type": "string"}, "evidence": {"type": "string"}},
            },
        },
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "evidence"],
                "properties": {
                    "text": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def bank_is_usable(result: dict[str, Any]) -> bool:
    """Roles with bullets, skills, and more than one statement to choose from.

    The same failure the generator's draft check guards against applies here:
    a tool call whose fields arrive serialised inside another field.
    """
    roles = dict_items(result.get("roles"))
    bullets = [
        b
        for r in roles
        for p in dict_items(r.get("projects"))
        for b in dict_items(p.get("bullets"))
    ]
    return (
        bool(bullets)
        and bool(dict_items(result.get("skills")))
        and len(dict_items(result.get("summaries"))) >= 2
        and "<parameter name=" not in json.dumps(result)
    )


def build_bank(narratives: str) -> dict[str, Any]:
    """Every bullet, skill and positioning statement the narratives support."""
    stable = f"<candidate_background>\n{narratives}\n</candidate_background>\n\n"
    instruction = (
        "Write the master resume: every bullet, skill, and positioning statement the "
        "narratives support, each with its evidence copied exactly from the narratives. "
        f"Use the {_BANK_TOOL} tool."
    )
    return call_model(
        "bank",
        validate=bank_is_usable,
        attempts=3,
        model=PIPELINE_MODEL,
        # The largest output in the harness: the pilot ran out at 20k tokens
        # on all three attempts. Above 20k `call_model` streams.
        max_tokens=64000,
        system=cached_system(load_prompt("bank")),
        messages=[{"role": "user", "content": split_for_cache(stable, instruction)}],
        tools=cast(
            Any,
            [
                {
                    "name": _BANK_TOOL,
                    "description": "Submit the master resume",
                    "input_schema": _BANK_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _BANK_TOOL},
    )


_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_ELISION = re.compile(r"\.\.\.|…")
_EDGE = " .,;:'\"-"


def _normalise(text: str) -> str:
    """Case, quote and dash style, markdown emphasis and spacing are not content."""
    text = re.sub(r"[*_`]", "", text.translate(_TYPOGRAPHY).lower())
    return " ".join(text.split())


def evidence_found(passage: str, source: str) -> bool:
    """The passage is in the source verbatim, once both are normalised.

    An ellipsis marks an elision, so each side of one must be found on its own;
    a passage stitched from two places is not one passage.
    """
    parts = [p.strip(_EDGE) for p in _ELISION.split(_normalise(passage))]
    parts = [p for p in parts if p]
    text = _normalise(source)
    return sum(len(p.split()) for p in parts) >= MIN_EVIDENCE_WORDS and all(
        p in text for p in parts
    )


def _passages(evidence: object) -> list[str]:
    if isinstance(evidence, str):
        return [evidence]
    if isinstance(evidence, list):
        return [e for e in evidence if isinstance(e, str)]
    return []


def verify_bank(raw: dict[str, Any], narratives: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The bank without any item whose evidence is not in the narratives.

    Returns the verified bank and a record of what was discarded. A project left
    with no bullets goes too. A role left with none stays, so the timeline is
    intact, and the record names it.
    """
    discarded: list[dict[str, Any]] = []
    counts: dict[str, list[int]] = {"bullets": [0, 0], "skills": [0, 0], "summaries": [0, 0]}

    def keep(kind: str, item: dict[str, Any], text: str) -> bool:
        passages = _passages(item.get("evidence"))
        ok = bool(passages) and all(evidence_found(p, narratives) for p in passages)
        counts[kind][1] += 1
        counts[kind][0] += ok
        if not ok:
            discarded.append({"kind": kind, "text": text, "evidence": item.get("evidence")})
        return ok

    roles = []
    for role in dict_items(raw.get("roles")):
        projects = []
        for project in dict_items(role.get("projects")):
            bullets = [
                {"text": str(b["text"]).strip(), "evidence": b.get("evidence")}
                for b in dict_items(project.get("bullets"))
                if str(b.get("text", "")).strip() and keep("bullets", b, str(b["text"]))
            ]
            if bullets:
                projects.append({"name": str(project.get("name", "")), "bullets": bullets})
        roles.append(
            {
                "company": str(role.get("company", "")),
                "title": str(role.get("title", "")),
                "dates": str(role.get("dates", "")),
                "projects": projects,
            }
        )
    skills = [
        {"name": str(s["name"]).strip(), "evidence": s.get("evidence")}
        for s in dict_items(raw.get("skills"))
        if str(s.get("name", "")).strip() and keep("skills", s, str(s["name"]))
    ]
    summaries = [
        {"text": str(s["text"]).strip(), "evidence": s.get("evidence")}
        for s in dict_items(raw.get("summaries"))
        if str(s.get("text", "")).strip() and keep("summaries", s, str(s["text"]))
    ]
    bank = {"roles": roles, "skills": skills, "summaries": summaries}
    record = {
        "kept": {kind: kept for kind, (kept, _) in counts.items()},
        "total": {kind: total for kind, (_, total) in counts.items()},
        "roles_without_bullets": [r["company"] for r in roles if not r["projects"]],
        "discarded": discarded,
    }
    return bank, record


@dataclass(frozen=True)
class BankBullet:
    index: int  # position among all the bank's bullets, 0-based
    role: int  # 0 is the most recent role
    project: str
    text: str
    context: str  # "Company, Title / Project", as the rater sees it


def bank_bullets(bank: dict[str, Any]) -> list[BankBullet]:
    out: list[BankBullet] = []
    for r, role in enumerate(bank["roles"]):
        for project in role["projects"]:
            context = f"{role['company']}, {role['title']} / {project['name']}"
            for bullet in project["bullets"]:
                out.append(BankBullet(len(out), r, project["name"], bullet["text"], context))
    return out


@dataclass(frozen=True)
class SelectionInput:
    """The posting and the bank. Not the narratives: choosing reads a document,
    not a candidate, and the bank's evidence stays out of view with them."""

    jd: str
    bullets: tuple[BankBullet, ...]
    skills: tuple[str, ...]
    summaries: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    bullets: dict[int, int]
    skills: dict[int, int]
    summary: int


def selection_input(jd: str, bank: dict[str, Any]) -> SelectionInput:
    return SelectionInput(
        jd=jd,
        bullets=tuple(bank_bullets(bank)),
        skills=tuple(s["name"] for s in bank["skills"]),
        summaries=tuple(s["text"] for s in bank["summaries"]),
    )


_RATINGS: dict[str, Any] = {
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
_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["bullets", "skills", "summary"],
    "properties": {
        "bullets": _RATINGS,
        "skills": _RATINGS,
        "summary": {"type": "integer", "minimum": 0},
    },
}


def build_selection_request(inp: SelectionInput) -> dict[str, Any]:
    bullets = "\n".join(f"[{b.index}] ({b.context}) {b.text}" for b in inp.bullets)
    skills = "\n".join(f"[{i}] {s}" for i, s in enumerate(inp.skills))
    summaries = "\n".join(f"[{i}] {s}" for i, s in enumerate(inp.summaries))
    return {
        "model": PIPELINE_MODEL,
        "max_tokens": 8192,
        "system": load_prompt("bank_selection"),
        "messages": [
            {
                "role": "user",
                "content": f"<job_description>\n{inp.jd}\n</job_description>\n\n"
                f"<bullets>\n{bullets}\n</bullets>\n\n"
                f"<skills>\n{skills}\n</skills>\n\n"
                f"<positioning_statements>\n{summaries}\n</positioning_statements>\n\n"
                f"Rate every bullet and every skill, and choose one positioning statement, "
                f"using the {_SELECTION_TOOL} tool.",
            }
        ],
        "tools": [
            {
                "name": _SELECTION_TOOL,
                "description": "Submit the selection",
                "input_schema": _SELECTION_SCHEMA,
            }
        ],
        "tool_choice": {"type": "tool", "name": _SELECTION_TOOL},
    }


def _ratings(value: object) -> dict[int, int]:
    return {int(item["index"]): int(item["rating"]) for item in dict_items(value)}


def parse_selection(result: dict[str, Any]) -> Selection:
    return Selection(
        bullets=_ratings(result.get("bullets")),
        skills=_ratings(result.get("skills")),
        summary=int(result["summary"]),
    )


def selection_complete(result: dict[str, Any], inp: SelectionInput) -> bool:
    """One in-range rating per bullet and per skill, and a statement that exists.

    A bullet without a rating would have no cost and be removed first by
    default rather than by judgement.
    """
    try:
        sel = parse_selection(result)
    except (KeyError, TypeError, ValueError):
        return False
    return (
        set(sel.bullets) == set(range(len(inp.bullets)))
        and set(sel.skills) == set(range(len(inp.skills)))
        and all(0 <= r <= MAX_RATING for r in (*sel.bullets.values(), *sel.skills.values()))
        and 0 <= sel.summary < len(inp.summaries)
    )


def rate_bank(inp: SelectionInput) -> Selection:
    result = call_model(
        "bank_selection",
        validate=lambda r: selection_complete(r, inp),
        attempts=3,
        **build_selection_request(inp),
    )
    return parse_selection(result)


def chosen_skills(bank: dict[str, Any], selection: Selection) -> list[str]:
    """Skills rated at or above the threshold, most relevant first, bank order within."""
    rated = [(-selection.skills[i], i) for i in range(len(bank["skills"]))]
    return [bank["skills"][i]["name"] for neg, i in sorted(rated) if -neg >= SKILL_THRESHOLD]


def removal_order(
    bank: dict[str, Any], ratings: dict[int, int], keywords: list[Keyword], fixed: str
) -> list[int]:
    """Greedy order in which bullets are removed, cheapest first.

    The cost is the trim experiment's: (relevance, required terms only this
    bullet carries, preferred terms only it carries, recency, position).
    `fixed` is the text that stays whatever is removed (summary, skills, role
    headers), so a term it holds costs nothing to lose from a bullet. A
    project's name counts as carried by each of its bullets, since it goes
    with the last of them. Every role keeps one bullet: an employer with
    nothing under it reads as an omission.

    No project keeps more than `PROJECT_CAP`: while one holds more, only its
    bullets are candidates. The generator is told the same, because a reader
    who sees seven bullets on one project reads none of them, and the bank
    puts every bullet a project supports under it.
    """
    bullets = bank_bullets(bank)
    base = {k for k, kw in enumerate(keywords) if term_present(fixed, kw)}
    carried = {
        b.index: {
            k
            for k, kw in enumerate(keywords)
            if k not in base and term_present(f"{b.project} {b.text}", kw)
        }
        for b in bullets
    }
    kept = {b.index for b in bullets}
    order: list[int] = []
    while True:
        per_role = Counter(bullets[i].role for i in kept)
        per_project = Counter((bullets[i].role, bullets[i].project) for i in kept)
        holders = Counter(k for i in kept for k in carried[i])
        candidates = [bullets[i] for i in sorted(kept) if per_role[bullets[i].role] > 1]
        crowded = [b for b in candidates if per_project[(b.role, b.project)] > PROJECT_CAP]
        candidates = crowded or candidates
        if not candidates:
            return order

        def cost(b: BankBullet) -> tuple[int, int, int, int, int]:
            alone = [k for k in carried[b.index] if holders[k] == 1]
            required = sum(keywords[k].required for k in alone)
            return (ratings[b.index], required, len(alone) - required, -b.role, -b.index)

        victim = min(candidates, key=cost)
        order.append(victim.index)
        kept.discard(victim.index)


def resume_data(
    bank: dict[str, Any], drop: set[int], skills: list[str], summary: str
) -> dict[str, Any]:
    """The bank's roles less the dropped bullets, in the bank's order and words.
    A project left with nothing goes with its last bullet."""
    experience = []
    n = 0
    for role in bank["roles"]:
        projects = []
        for project in role["projects"]:
            kept = []
            for bullet in project["bullets"]:
                if n not in drop:
                    kept.append(bullet["text"])
                n += 1
            if kept:
                projects.append({"name": project["name"], "bullets": kept})
        experience.append(
            {
                "company": role["company"],
                "title": role["title"],
                "dates": role["dates"],
                "projects": projects,
            }
        )
    return {"summary": summary, "experience": experience, "skills": skills}


def word_count(md: str) -> int:
    return len(md.split())


def select(
    bank: dict[str, Any], selection: Selection, keywords: list[Keyword], budget: int
) -> tuple[dict[str, Any], list[int]]:
    """The resume for one posting, and the bullets removed to make it.

    Skills rated at or above the threshold, the chosen positioning statement,
    and the bank's bullets less the shortest prefix of the removal order that
    brings the rendered document within `budget` words. If the order runs out
    first, the floor is returned: one bullet a role.
    """
    skills = chosen_skills(bank, selection)
    summary = bank["summaries"][selection.summary]["text"]
    headers = " ".join(f"{r['company']} {r['title']}" for r in bank["roles"])
    order = removal_order(
        bank, selection.bullets, keywords, f"{summary} {', '.join(skills)} {headers}"
    )
    for k in range(len(order) + 1):
        data = resume_data(bank, set(order[:k]), skills, summary)
        if word_count(build_resume_markdown(data)) <= budget:
            return data, order[:k]
    return data, order


_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}


def write_summary(jd: str, resume: str) -> str:
    """A summary for this posting, written from the chosen document alone.

    It sees no narratives, so it can only restate what the bank already holds.
    """
    result = call_model(
        "bank_summary",
        validate=lambda r: isinstance(r.get("summary"), str) and bool(r["summary"].strip()),
        attempts=3,
        model=PIPELINE_MODEL,
        max_tokens=1024,
        system=load_prompt("bank_summary"),
        messages=[
            {
                "role": "user",
                "content": f"<job_description>\n{jd}\n</job_description>\n\n"
                f"<resume>\n{resume}\n</resume>\n\n"
                f"Write the summary using the {_SUMMARY_TOOL} tool.",
            }
        ],
        tools=cast(
            Any,
            [
                {
                    "name": _SUMMARY_TOOL,
                    "description": "Submit the summary",
                    "input_schema": _SUMMARY_SCHEMA,
                }
            ],
        ),
        tool_choice={"type": "tool", "name": _SUMMARY_TOOL},
    )
    return str(result["summary"]).strip()


def bank_path(sweep_id: str, index: int) -> Path:
    return RUNS_DIR / sweep_id / "_banks" / f"bank-{index}.json"


def ensure_bank(sweep_id: str, index: int, narratives: str) -> dict[str, Any]:
    """Build, verify and persist the bank for one sample index, once.

    Each sample index has its own bank, so the variance of writing one is in
    the arm's spread rather than fixed into every document.
    """
    path = bank_path(sweep_id, index)
    if path.is_file():
        return dict(json.loads(path.read_text()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with tracing(path.with_suffix(".trace.jsonl")):
        raw = build_bank(narratives)
    bank, record = verify_bank(raw, narratives)
    path.with_suffix(".raw.json").write_text(json.dumps(raw, indent=2))
    path.with_suffix(".verification.json").write_text(json.dumps(record, indent=2))
    whole = resume_data(
        bank, set(), [s["name"] for s in bank["skills"]], bank["summaries"][0]["text"]
    )
    path.with_suffix(".md").write_text(build_resume_markdown(whole))
    path.write_text(json.dumps(bank, indent=2))
    return bank


def _sample_dir(sweep_id: str, slug: str, condition: str, index: int) -> Path:
    return RUNS_DIR / sweep_id / slug / condition / f"sample-{index}"


def run_bank_sample(
    sweep_id: str, slug: str, index: int, narratives: str, budget: int
) -> list[dict[str, Any]]:
    """Choose from bank `index` for one posting and score both conditions.

    Laid out like a sweep (runs/<id>/<slug>/<condition>/sample-<n>/), so
    `report`, `coverage` and `reliability` read it unchanged. Idempotent per
    condition.
    """
    bank = ensure_bank(sweep_id, index, narratives)
    jd = load_jd(slug)
    keywords = cached_keywords(slug, jd)
    base = _sample_dir(sweep_id, slug, "bank", index)
    base.mkdir(parents=True, exist_ok=True)

    selection_path = base / "selection.json"
    if selection_path.is_file():
        saved = json.loads(selection_path.read_text())
        selection = Selection(
            bullets={int(k): v for k, v in saved["bullets"].items()},
            skills={int(k): v for k, v in saved["skills"].items()},
            summary=int(saved["summary"]),
        )
    else:
        with tracing(base / "selection.trace.jsonl"):
            selection = rate_bank(selection_input(jd, bank))
    data, dropped = select(bank, selection, keywords, budget)
    selection_path.write_text(
        json.dumps(
            {
                "bullets": selection.bullets,
                "skills": selection.skills,
                "summary": selection.summary,
                "budget": budget,
                "bank_bullets": len(bank_bullets(bank)),
                "dropped": len(dropped),
            },
            indent=2,
        )
    )

    results = []
    for condition in CONDITIONS:
        out = _sample_dir(sweep_id, slug, condition, index)
        scores_path = out / "scores.json"
        if scores_path.is_file():
            results.append(dict(json.loads(scores_path.read_text())))
            continue
        out.mkdir(parents=True, exist_ok=True)
        with tracing(out / "trace.jsonl"):
            doc_data = data
            if condition == "bank-summary":
                rest = build_resume_markdown({**data, "summary": ""})
                doc_data = {**data, "summary": write_summary(jd, rest)}
            resume = build_resume_markdown(doc_data)
            (out / "resume.json").write_text(json.dumps(doc_data, indent=2))
            (out / "resume.md").write_text(resume)
            (out / "coverage.json").write_text(json.dumps(coverage(resume, keywords), indent=2))
            scored = score_document(jd, resume, narratives)
        scores = {
            "slug": slug,
            "arm": condition,
            "sample": index,
            "words": word_count(resume),
            **scored,
        }
        scores_path.write_text(json.dumps(scores, indent=2))
        results.append(scores)
    return results
