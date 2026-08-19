"""Command line entry point.

    uv run python -m cli sweep --all --samples 3
    uv run python -m cli report

A sweep is deliberately not reachable over HTTP. It is minutes of wall clock
and real API spend per invocation, its audience is whoever is tuning prompts
rather than anyone the resumes are for, and an endpoint that triggers arbitrary
batch model spend is a surface worth not creating.
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from config import INPUT_DIR
from corpus import list_slugs
from evaluation import report as report_mod
from evaluation.sweep import ARMS, read_metadata, run_sample, write_metadata


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

    meta = write_metadata(sweep_id)
    total = len(slugs) * len(ARMS) * args.samples
    print(f"sweep {sweep_id}: {len(slugs)} JDs x {len(ARMS)} arms x {args.samples} samples "
          f"= {total} documents")
    print("prompts: " + "  ".join(f"{k}={v}" for k, v in meta["prompts"].items()) + "\n")

    done = 0
    for slug in slugs:
        for arm in ARMS:
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
    parser = argparse.ArgumentParser(prog="cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sweep = sub.add_parser("sweep", help="generate and score both arms across the corpus")
    p_sweep.add_argument("--all", action="store_true", help="every JD in the corpus (default)")
    p_sweep.add_argument("--jd", nargs="*", help="specific JD slugs")
    p_sweep.add_argument("--samples", type=int, default=3,
                         help="samples per arm per JD; below 3 the spread is not meaningful")
    p_sweep.add_argument("--sweep-id", help="resume or name a sweep (default: timestamp)")
    p_sweep.set_defaults(func=cmd_sweep)

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
