"""What produced a sweep.

A score is only comparable to another score if you know whether anything
changed between them. Prompts are files that get edited between commits, so a
git SHA is not sufficient evidence — it identifies the last commit, not the
bytes that were actually sent. Content hashes are.

Recorded once per sweep, since prompts do not change mid-run.
"""

import hashlib
import subprocess
from typing import Any

from config import JUDGE_MODEL, PIPELINE_MODEL, PROMPTS_DIR, WEIGHTS


def prompt_fingerprints() -> dict[str, str]:
    """Short content hash per prompt file, keyed by stage name."""
    return {
        path.stem: hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        for path in sorted(PROMPTS_DIR.glob("*.md"))
    }


def _git_state() -> dict[str, str]:
    """Commit and dirty flag, best effort. Absent outside a repo."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return {}
    return {"commit": sha, "worktree": "dirty" if dirty else "clean"}


def sweep_metadata() -> dict[str, Any]:
    return {
        "pipeline_model": PIPELINE_MODEL,
        "judge_model": JUDGE_MODEL,
        "weights": dict(WEIGHTS),
        "prompts": prompt_fingerprints(),
        "git": _git_state(),
    }


def diff_metadata(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Human-readable differences between two sweeps' conditions."""
    out: list[str] = []
    for key in ("pipeline_model", "judge_model"):
        if a.get(key) != b.get(key):
            out.append(f"{key}: {a.get(key)} -> {b.get(key)}")
    if a.get("weights") != b.get("weights"):
        out.append(f"weights: {a.get('weights')} -> {b.get('weights')}")
    pa, pb = a.get("prompts", {}), b.get("prompts", {})
    for stage in sorted(set(pa) | set(pb)):
        if pa.get(stage) != pb.get(stage):
            out.append(f"prompt {stage}: {pa.get(stage, 'absent')} -> {pb.get(stage, 'absent')}")
    return out
