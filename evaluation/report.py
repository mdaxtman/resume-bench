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

from config import AUTHENTICITY_GATE, CLAIM_COST, RUNS_DIR
from evaluation.judges import unsupported_claims
from evaluation.sweep import net_composite, passes_gate

AXES = (
    "jd_alignment",
    "recruiter_readability",
    "authenticity",
    "hire_intent",
    "composite",
    "unsupported",
    "net_composite",
)


def with_claims(row: dict[str, Any]) -> dict[str, Any]:
    """The row with its unsupported claims counted and its net composite.

    Both are derived from the raw findings every scores.json keeps, so any
    sweep on disk can be read this way.
    """
    unsupported = unsupported_claims(
        len(row.get("untraceable") or []), len(row.get("overstatements") or [])
    )
    return {
        **row,
        "unsupported": unsupported,
        "net_composite": net_composite(float(row["composite"]), unsupported),
    }


_LABELS = {
    "hire_intent": "hire intent *",
    "unsupported": "unsupported claims †",
    "net_composite": "net composite †",
}


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


def gated(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Documents that clear the authenticity gate — the ones that would be sent."""
    return [r for r in rows if passes_gate(float(r["authenticity"]))]


def gate_record(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """(passed, total) per arm. A rejection rate is a result in its own right."""
    return {
        arm: (len(gated([r for r in rows if r["arm"] == arm])), sum(r["arm"] == arm for r in rows))
        for arm in sorted({r["arm"] for r in rows})
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, tuple[float, float]]]:
    """Mean and spread per axis per arm, over documents that pass the gate."""
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for arm in sorted({r["arm"] for r in rows}):
        arm_rows = [with_claims(r) for r in gated([r for r in rows if r["arm"] == arm])]
        out[arm] = {axis: _stats([float(r[axis]) for r in arm_rows]) for axis in AXES}
    return out


def per_jd_record(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Wins/losses/ties by mean composite per JD. A per-sample record would
    overstate confidence by treating correlated samples as independent trials."""
    wins = losses = ties = 0
    rows = gated(rows)
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
    both = "pipeline" in summary and "control" in summary
    for axis in AXES:
        label = _LABELS.get(axis, axis.replace("_", " "))
        cells = []
        for arm in ("pipeline", "control"):
            mean, sd = summary.get(arm, {}).get(axis, (0.0, 0.0))
            cells.append(f"{mean:.2f} ± {sd:.2f}" if arm in summary else "—")
        # A single-arm sweep (`--arms pipeline`) has nothing to subtract from.
        delta = summary["pipeline"][axis][0] - summary["control"][axis][0] if both else None
        lines.append(
            f"{label:<24}{cells[0]:>18}{cells[1]:>18}"
            + (f"{delta:>+12.2f}" if delta is not None else f"{'—':>12}")
        )

    gate = gate_record(rows)
    lines += [
        "─" * 78,
        f"Authenticity gate (>= {AUTHENTICITY_GATE}): "
        + "   ".join(f"{arm} {passed}/{total}" for arm, (passed, total) in gate.items())
        + " passed; means are over passing documents",
    ]
    if both:
        wins, losses, ties = per_jd_record(rows)
        lines.append(
            f"Per-JD record (pipeline): {wins}W-{losses}L-{ties}T   "
            f"(a JD is a tie when |delta| <= 0.1)"
        )
    lines.append("* hire intent is reported, not folded into the composite.")
    lines.append(
        "† untraceable claims count twice, overstatements once; "
        f"net composite is composite less {CLAIM_COST} per unsupported claim."
    )
    return "\n".join(lines)


def load_and_render(sweep_id: str | None = None) -> str:
    sid = sweep_id or latest_sweep_id()
    return render(sid, load_sweep(sid))


def sweep_ids() -> list[str]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted(d.name for d in RUNS_DIR.iterdir() if d.is_dir())


__all__ = [
    "gate_record",
    "gated",
    "load_and_render",
    "load_sweep",
    "per_jd_record",
    "render",
    "summarise",
    "sweep_ids",
]
