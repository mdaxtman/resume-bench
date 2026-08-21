"""Aggregation across a sweep.

Reports mean and standard deviation per axis per arm, plus a per-JD win record.
Spread is printed everywhere a mean is, because the interesting claim about a
staged pipeline is usually not that it scores higher but that it scores more
consistently — a baseline that occasionally produces something excellent and
occasionally produces something unusable has a mean that hides the risk.
"""

import json
import statistics
from typing import Any

from config import RUNS_DIR

AXES = ("jd_alignment", "recruiter_readability", "authenticity", "hire_intent", "composite")


def load_sweep(sweep_id: str) -> list[dict[str, Any]]:
    root = RUNS_DIR / sweep_id
    if not root.is_dir():
        raise ValueError(f"No sweep at {root}")
    return [json.loads(p.read_text()) for p in sorted(root.glob("*/*/sample-*/scores.json"))]


def latest_sweep_id() -> str:
    if not RUNS_DIR.is_dir():
        raise ValueError(f"No sweeps yet ({RUNS_DIR} does not exist)")
    sweeps = sorted(d.name for d in RUNS_DIR.iterdir() if d.is_dir())
    if not sweeps:
        raise ValueError(f"No sweeps yet in {RUNS_DIR}")
    return sweeps[-1]


def _stats(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    spread = statistics.stdev(values) if len(values) > 1 else 0.0
    return (round(statistics.mean(values), 2), round(spread, 2))


def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, tuple[float, float]]]:
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for arm in sorted({r["arm"] for r in rows}):
        arm_rows = [r for r in rows if r["arm"] == arm]
        out[arm] = {axis: _stats([float(r[axis]) for r in arm_rows]) for axis in AXES}
    return out


def per_jd_record(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Wins/losses/ties by mean composite per JD. A per-sample record would
    overstate confidence by treating correlated samples as independent trials."""
    wins = losses = ties = 0
    for slug in sorted({r["slug"] for r in rows}):
        by_arm = {
            arm: [float(r["composite"]) for r in rows if r["slug"] == slug and r["arm"] == arm]
            for arm in ("pipeline", "control")
        }
        if not by_arm["pipeline"] or not by_arm["control"]:
            continue
        delta = statistics.mean(by_arm["pipeline"]) - statistics.mean(by_arm["control"])
        if delta > 0.1:
            wins += 1
        elif delta < -0.1:
            losses += 1
        else:
            ties += 1
    return wins, losses, ties


def render(sweep_id: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"{sweep_id}: no samples found."

    summary = summarise(rows)
    jds = len({r["slug"] for r in rows})
    per_arm = len(rows) // max(1, len(summary) * jds)
    lines = [
        f"{sweep_id}  —  {jds} JDs, n={per_arm} per arm, {len(rows)} scored documents",
        "─" * 78,
        f"{'Axis':<24}{'Pipeline':>18}{'Control':>18}{'Delta':>12}",
    ]
    for axis in AXES:
        p_mean, p_sd = summary.get("pipeline", {}).get(axis, (0.0, 0.0))
        c_mean, c_sd = summary.get("control", {}).get(axis, (0.0, 0.0))
        label = axis.replace("_", " ")
        if axis == "hire_intent":
            label += " *"
        lines.append(
            f"{label:<24}{f'{p_mean:.2f} ± {p_sd:.2f}':>18}"
            f"{f'{c_mean:.2f} ± {c_sd:.2f}':>18}{p_mean - c_mean:>+12.2f}"
        )

    wins, losses, ties = per_jd_record(rows)
    lines += [
        "─" * 78,
        f"Per-JD record (pipeline): {wins}W-{losses}L-{ties}T   "
        f"(a JD is a tie when |delta| <= 0.1)",
        "* hire intent is reported, not folded into the composite.",
    ]
    return "\n".join(lines)


def load_and_render(sweep_id: str | None = None) -> str:
    sid = sweep_id or latest_sweep_id()
    return render(sid, load_sweep(sid))


def sweep_ids() -> list[str]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted(d.name for d in RUNS_DIR.iterdir() if d.is_dir())


__all__ = ["load_and_render", "load_sweep", "render", "summarise", "per_jd_record", "sweep_ids"]
