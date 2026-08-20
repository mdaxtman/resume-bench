"""Does a judge axis measure the document, or does it measure nothing?

An axis whose scores barely spread across documents is ambiguous: the judge may
be unable to discriminate, or the documents may genuinely be alike. Re-scoring
the same document separates them. Variation that persists when the input is held
fixed is measurement error; variation that only appears between documents is
signal.

ICC — between-document variance over total variance — puts a number on it. An
axis near 0 cannot detect a prompt change no matter how large the change is,
which makes this the precondition for tuning anything against that axis.
"""

import statistics
from typing import Any


def _components(repeats: dict[str, list[float]]) -> tuple[float, float]:
    """Return (between-document variance, within-document variance)."""
    if len(repeats) < 2:
        raise ValueError("ICC needs at least two documents")
    if any(len(v) < 2 for v in repeats.values()):
        raise ValueError("ICC needs at least two scores per document")

    means = [statistics.mean(v) for v in repeats.values()]
    between = statistics.pvariance(means)
    within = statistics.mean([statistics.pvariance(v) for v in repeats.values()])
    return between, within


def icc(repeats: dict[str, list[float]]) -> float:
    between, within = _components(repeats)
    total = between + within
    return 0.0 if total == 0 else between / total


def reliability_report(repeats: dict[str, list[float]]) -> dict[str, Any]:
    between, within = _components(repeats)
    return {
        "documents": len(repeats),
        "repeats": min(len(v) for v in repeats.values()),
        "between_sd": round(between**0.5, 3),
        "within_sd": round(within**0.5, 3),
        "icc": round(icc(repeats), 3),
    }


def interpret(value: float) -> str:
    if value >= 0.75:
        return "reliable — differences between documents are real"
    if value >= 0.5:
        return "moderate — usable, but small effects will be hard to see"
    if value >= 0.2:
        return "weak — only large differences are detectable"
    return "no document-level signal — this axis cannot detect a prompt change"
