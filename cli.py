"""Command line entry point.

    uv run python -m cli sweep --all --samples 3
    uv run python -m cli report

A sweep is deliberately not reachable over HTTP. It is minutes of wall clock
and real API spend per invocation, its audience is whoever is tuning prompts
rather than anyone the resumes are for, and an endpoint that triggers arbitrary
batch model spend is a surface worth not creating.
"""

import argparse
import io
import json
import pathlib
import sys
from datetime import datetime
from typing import Any

from config import INPUT_DIR, JOBS_DIR
from corpus import list_slugs, load_jd
from evaluation import report as report_mod
from evaluation.keywords import cached_keywords, coverage
from evaluation.reliability import interpret, reliability_report
from evaluation.rescore import discover, load_slug_map, rescore_one
from evaluation.sweep import ARMS, read_metadata, run_sample, write_metadata
from evaluation.trim import load_trim, render_trim, run_trim


def _load_narratives() -> str:
    path = INPUT_DIR / "narratives.md"
    if not path.is_file():
        raise SystemExit(
            f"No narratives at {path}. Copy input/narratives.example.md and fill it in "
            "with your own career history."
        )
    return path.read_text()


def _load_contact() -> dict[str, Any] | None:
    path = INPUT_DIR / "contact.json"
    return dict(json.loads(path.read_text())) if path.is_file() else None


def cmd_sweep(args: argparse.Namespace) -> int:
    slugs = args.jd or list_slugs()
    unknown = set(slugs) - set(list_slugs())
    if unknown:
        raise SystemExit(f"Unknown JD slug(s): {', '.join(sorted(unknown))}")

    narratives = _load_narratives()
    contact = _load_contact()
    sweep_id = args.sweep_id or datetime.now().strftime("%Y-%m-%dT%H%M%S")

    arms = tuple(args.arms) if args.arms else ARMS
    total = len(slugs) * len(arms) * args.samples
    meta = write_metadata(sweep_id)
    print(
        f"sweep {sweep_id}: {len(slugs)} JDs x {len(arms)} arms x {args.samples} samples "
        f"= {total} documents"
    )
    print("prompts: " + "  ".join(f"{k}={v}" for k, v in meta["prompts"].items()) + "\n")

    done = 0
    for slug in slugs:
        for arm in arms:
            for i in range(1, args.samples + 1):
                done += 1
                label = f"[{done}/{total}] {slug} {arm} #{i}"
                try:
                    scores = run_sample(sweep_id, slug, arm, i, narratives, contact)
                    print(f"{label:<58} composite {scores['composite']:.2f}")
                except Exception as exc:  # one bad sample must not kill the sweep
                    print(f"{label:<58} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nDone. Results in runs/{sweep_id}/")
    print(f"Report with: uv run python -m cli report --sweep-id {sweep_id}")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """Score an archive of previously generated resumes with the current judges."""
    source = pathlib.Path(args.source).expanduser()
    if not source.is_dir():
        raise SystemExit(f"No such archive directory: {source}")

    mapping = load_slug_map(JOBS_DIR / "INDEX.local.md")
    items = discover(source, mapping)
    if not items:
        raise SystemExit(f"No <slug>/runs/<date>/*_resume.md documents found under {source}")

    unmapped = sorted({i["slug"] for i in items if i["slug"].startswith("unmapped-")})
    print(f"rescore {args.sweep_id}: {len(items)} documents from {source}")
    print("  documents are anonymised before scoring: any leading H1 is dropped")
    if unmapped:
        print(f"  {len(unmapped)} slug(s) had no redaction mapping and were hashed")
    if args.dry_run:
        for i in items:
            print(f"    {i['slug']:26} {i['arm']:9} sample-{i['sample']:<3} <- {i['source_run']}")
        return 0

    narratives = _load_narratives()
    print(
        "  NOTE: authenticity is scored against CURRENT narratives; these documents\n"
        "        predate them, so these scores are not comparable to a fresh sweep.\n"
    )

    for n, item in enumerate(items, start=1):
        label = f"[{n}/{len(items)}] {item['slug']} {item['arm']} #{item['sample']}"
        try:
            scores = rescore_one(args.sweep_id, item, narratives)
            print(f"{label:<58} composite {scores['composite']:.2f}")
        except Exception as exc:
            print(f"{label:<58} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nDone. uv run python -m cli report --sweep-id {args.sweep_id}")
    return 0


def cmd_trim(args: argparse.Namespace) -> int:
    """Score existing documents untrimmed and at each word budget.

    Holds wording fixed and varies only selection: bullets are removed verbatim,
    never rewritten. The untrimmed original is re-scored alongside, so every
    condition is measured by the same ruler in the same run.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    root = pathlib.Path("runs") / args.source
    docs = sorted(
        p
        for p in root.glob("*/*/sample-*/resume.md")
        if p.parts[-3] in args.arms and (not args.jd or p.parts[-4] in args.jd)
    )
    if not docs:
        raise SystemExit(f"No {'/'.join(args.arms)} documents under {root}")

    budgets = sorted(args.budgets, reverse=True)
    meta = write_metadata(args.sweep_id)
    print(
        f"trim {args.sweep_id}: {len(docs)} documents from {args.source} x "
        f"{len(budgets) + 1} conditions (full, {', '.join(map(str, budgets))} words)"
    )
    print("prompts: " + "  ".join(f"{k}={v}" for k, v in meta["prompts"].items()) + "\n")

    narratives = _load_narratives()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for doc in docs:
            slug, arm, sample = doc.parts[-4], doc.parts[-3], int(doc.parts[-2].split("-")[1])
            future = pool.submit(
                run_trim, args.sweep_id, doc, slug, arm, sample, budgets, narratives
            )
            futures[future] = f"{slug} {arm} #{sample}"
        for done, future in enumerate(as_completed(futures), start=1):
            label = f"[{done}/{len(futures)}] {futures[future]}"
            try:
                summary = "  ".join(
                    f"{r['words']}w rr {r['recruiter_readability']:.2f}" for r in future.result()
                )
                print(f"{label:<52} {summary}")
            except Exception as exc:  # one bad document must not kill the run
                print(f"{label:<52} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nDone. uv run python -m cli trim-report --sweep-id {args.sweep_id}")
    return 0


def cmd_trim_report(args: argparse.Namespace) -> int:
    print(render_trim(args.sweep_id, load_trim(args.sweep_id)))
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """Literal keyword coverage for every document in an existing sweep.

    Runs against documents already on disk. The only model calls are one
    extraction per JD, cached, and identical for both arms.
    """
    root = pathlib.Path("runs") / args.sweep_id
    if not root.is_dir():
        raise SystemExit(f"No sweep at {root}")

    samples = sorted(root.glob("*/*/sample-*/resume.md"))
    slugs = sorted({p.parts[-4] for p in samples})
    print(f"coverage {args.sweep_id}: {len(samples)} documents across {len(slugs)} JDs")

    keywords = {}
    for slug in slugs:
        try:
            keywords[slug] = cached_keywords(slug, load_jd(slug))
        except Exception as exc:
            print(f"  {slug}: extraction FAILED ({exc})", file=sys.stderr)
    print(f"  keyword lists ready for {len(keywords)}/{len(slugs)} JDs\n")

    for doc in samples:
        slug = doc.parts[-4]
        if slug not in keywords:
            continue
        result = coverage(doc.read_text(), keywords[slug])
        (doc.parent / "coverage.json").write_text(json.dumps(result, indent=2))

    print(f"Done. Wrote coverage.json beside {len(samples)} documents.")
    return 0


def cmd_reliability(args: argparse.Namespace) -> int:
    """Re-score the same documents repeatedly to separate signal from error."""
    from collections import defaultdict

    from evaluation.contracts import AuthenticityInput, ColdReadInput
    from evaluation.judges import run_authenticity, run_cold_read

    root = pathlib.Path("runs") / args.sweep_id
    samples = sorted(root.glob("*/*/sample-*/resume.md"))
    if not samples:
        raise SystemExit(f"No documents under {root}")

    # Span the observed readability range rather than sampling at random: an
    # axis can be reliable in one region and flat in another.
    scored = []
    for doc in samples:
        s = json.loads((doc.parent / "scores.json").read_text())
        scored.append((s["recruiter_readability"], s["composite"], doc, s["slug"]))
    scored.sort()
    step = max(1, len(scored) // args.documents)
    chosen = scored[::step][: args.documents]

    print(f"reliability: {len(chosen)} documents x {args.repeats} repeats")
    print(f"  spanning readability {chosen[0][0]:.1f} to {chosen[-1][0]:.1f}\n")

    axes: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    narratives = _load_narratives() if args.authenticity else ""
    for readability, _, doc, slug in chosen:
        key = f"{slug}/{doc.parent.parent.name}/{doc.parent.name}"
        jd = load_jd(slug)
        resume = doc.read_text()
        for trial in range(args.repeats):
            cold = run_cold_read(ColdReadInput(jd=jd, resume=resume))
            axes["jd_alignment"][key].append(cold.jd_alignment)
            axes["recruiter_readability"][key].append(cold.recruiter_readability)
            for part, value in cold.readability_parts.items():
                axes[f"  {part}"][key].append(value)
            axes["hire_intent"][key].append(cold.hire_intent)
            if args.authenticity:
                auth = run_authenticity(AuthenticityInput(resume=resume, narratives=narratives))
                axes["authenticity"][key].append(auth.authenticity)
        got = [axes[a][key] for a in ("recruiter_readability",)][0]
        print(f"  {key:52} readability {got}")

    print(f"\n{'axis':<24}{'between sd':>12}{'within sd':>11}{'ICC':>7}   interpretation")
    for axis, repeats in axes.items():
        r = reliability_report(dict(repeats))
        print(
            f"{axis.replace('_', ' '):<24}{r['between_sd']:>12.2f}{r['within_sd']:>11.2f}"
            f"{r['icc']:>7.2f}   {interpret(r['icc'])}"
        )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print(report_mod.load_and_render(args.sweep_id))
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    print("JDs:")
    for slug in list_slugs():
        print(f"  {slug}")
    sweeps = report_mod.sweep_ids()
    print("\nSweeps:" if sweeps else "\nSweeps: (none yet)")
    for s in sweeps:
        print(f"  {s}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Answer "did that change help" with the conditions stated."""
    from provenance import diff_metadata

    for sweep_id in (args.baseline, args.candidate):
        print(report_mod.load_and_render(sweep_id))
        print()
    changes = diff_metadata(read_metadata(args.baseline), read_metadata(args.candidate))
    if changes:
        print("What changed between them:")
        for line in changes:
            print(f"  {line}")
    else:
        print("Nothing changed between them. Any score movement is run-to-run variance.")
    return 0


def main(argv: list[str] | None = None) -> int:
    # A sweep runs for hours and is usually piped to tee, where Python's default
    # block buffering makes progress invisible until the process exits. Line
    # buffering costs nothing and makes a long run observable while it runs.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(prog="cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sweep = sub.add_parser("sweep", help="generate and score both arms across the corpus")
    p_sweep.add_argument("--all", action="store_true", help="every JD in the corpus (default)")
    p_sweep.add_argument("--jd", nargs="*", help="specific JD slugs")
    p_sweep.add_argument(
        "--samples",
        type=int,
        default=3,
        help="samples per arm per JD; below 3 the spread is not meaningful",
    )
    p_sweep.add_argument("--sweep-id", help="resume or name a sweep (default: timestamp)")
    p_sweep.add_argument(
        "--arms", nargs="*", choices=list(ARMS), help="restrict to one arm (default: both)"
    )
    p_sweep.set_defaults(func=cmd_sweep)

    p_rescore = sub.add_parser(
        "rescore", help="score an archive of existing resumes with the current judges"
    )
    p_rescore.add_argument("--source", required=True, help="dir laid out as <slug>/runs/<date>/")
    p_rescore.add_argument("--sweep-id", default="rescore-01")
    p_rescore.add_argument("--dry-run", action="store_true", help="list documents, call nothing")
    p_rescore.set_defaults(func=cmd_rescore)

    p_cov = sub.add_parser("coverage", help="literal keyword coverage over an existing sweep")
    p_cov.add_argument("--sweep-id", required=True)
    p_cov.set_defaults(func=cmd_coverage)

    p_rel = sub.add_parser("reliability", help="re-score documents to measure judge noise")
    p_rel.add_argument("--sweep-id", required=True)
    p_rel.add_argument("--documents", type=int, default=6)
    p_rel.add_argument("--repeats", type=int, default=4)
    p_rel.add_argument("--authenticity", action="store_true", help="also re-run the costlier judge")
    p_rel.set_defaults(func=cmd_reliability)

    p_trim = sub.add_parser(
        "trim", help="re-score existing documents with bullets removed to word budgets"
    )
    p_trim.add_argument("--source", required=True, help="sweep whose documents are trimmed")
    p_trim.add_argument("--sweep-id", default="trim-01")
    p_trim.add_argument("--budgets", type=int, nargs="+", default=[800, 600, 450])
    p_trim.add_argument("--arms", nargs="+", choices=list(ARMS), default=list(ARMS))
    p_trim.add_argument("--jd", nargs="*", help="specific JD slugs (default: all in source)")
    p_trim.add_argument("--workers", type=int, default=4, help="documents scored concurrently")
    p_trim.set_defaults(func=cmd_trim)

    p_trim_report = sub.add_parser("trim-report", help="aggregate a trim experiment")
    p_trim_report.add_argument("--sweep-id", default="trim-01")
    p_trim_report.set_defaults(func=cmd_trim_report)

    p_report = sub.add_parser("report", help="aggregate a sweep")
    p_report.add_argument("--sweep-id", help="default: most recent")
    p_report.set_defaults(func=cmd_report)

    p_cmp = sub.add_parser("compare", help="two sweeps side by side, with what differed")
    p_cmp.add_argument("baseline")
    p_cmp.add_argument("candidate")
    p_cmp.set_defaults(func=cmd_compare)

    sub.add_parser("list", help="show JD slugs and existing sweeps").set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
