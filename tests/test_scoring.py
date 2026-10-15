"""Scoring arithmetic. Pure functions, no API calls.

The authenticity rule these cover replaced a flat "start at 10, -2 per
untraceable claim" rubric that had no relation to document length.
"""

import pytest

from config import AUTHENTICITY_GATE, WEIGHTS
from evaluation.judges import authenticity_score
from evaluation.report import per_jd_record
from evaluation.sweep import composite, passes_gate


def test_a_clean_resume_scores_ten() -> None:
    assert authenticity_score(claims_checked=40, untraceable=0, overstatements=0) == 10.0


def test_mostly_accurate_long_resume_does_not_floor() -> None:
    """The regression this exists for: under the old flat rubric a control
    resume that was roughly 95% accurate accumulated -11 and floored at 0,
    which made the composite gap uninterpretable even though the ranking was
    right. Length must not be its own penalty."""
    score = authenticity_score(claims_checked=40, untraceable=5, overstatements=1)
    assert score > 8.0, f"a ~95%-accurate resume scored {score}"


def test_short_and_long_resumes_with_equal_accuracy_score_equally() -> None:
    """Same proportion of unsupported claims, different lengths."""
    short = authenticity_score(claims_checked=10, untraceable=1, overstatements=0)
    long_ = authenticity_score(claims_checked=40, untraceable=4, overstatements=0)
    assert short == long_


def test_overstatement_is_penalised_less_than_fabrication() -> None:
    overstated = authenticity_score(claims_checked=20, untraceable=0, overstatements=4)
    fabricated = authenticity_score(claims_checked=20, untraceable=4, overstatements=0)
    assert overstated > fabricated


def test_score_floors_at_zero_not_below() -> None:
    assert authenticity_score(claims_checked=5, untraceable=5, overstatements=5) == 0.0


def test_zero_claims_is_an_error_not_a_silent_ten() -> None:
    """A judge that checked nothing must not read as a perfect document."""
    with pytest.raises(ValueError):
        authenticity_score(claims_checked=0, untraceable=0, overstatements=0)


def test_composite_excludes_hire_intent_and_authenticity() -> None:
    assert composite(10.0, 10.0) == 10.0
    assert composite(10.0, 0.0) == 6.667  # readability carries a third


def test_removing_authenticity_preserves_the_original_two_to_one_ratio() -> None:
    """Authenticity left the composite because its ICC was 0.31; the two axes
    that remain keep the 0.4 : 0.2 balance they were given originally."""
    assert WEIGHTS["jd_alignment"] == pytest.approx(2 * WEIGHTS["recruiter_readability"])
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_the_gate_is_inclusive_at_its_threshold() -> None:
    assert passes_gate(AUTHENTICITY_GATE)
    assert not passes_gate(AUTHENTICITY_GATE - 0.01)


def _row(slug: str, arm: str, comp: float) -> dict[str, object]:
    return {"slug": slug, "arm": arm, "composite": comp, "authenticity": 9.5}


def test_per_jd_record_counts_by_jd_not_by_sample() -> None:
    """Three correlated samples of one JD are one trial, not three."""
    rows = [_row("a", "pipeline", 9.0) for _ in range(3)]
    rows += [_row("a", "control", 7.0) for _ in range(3)]
    assert per_jd_record(rows) == (1, 0, 0)


def test_per_jd_record_treats_small_deltas_as_ties() -> None:
    rows = [_row("a", "pipeline", 8.05), _row("a", "control", 8.0)]
    assert per_jd_record(rows) == (0, 0, 1)


def test_per_jd_record_skips_jds_missing_an_arm() -> None:
    rows = [_row("a", "pipeline", 9.0)]
    assert per_jd_record(rows) == (0, 0, 0)


def test_report_renders_without_a_real_sweep() -> None:
    """Proves the table formats before a sweep is paid for."""
    from evaluation.report import render

    rows = []
    for slug in ("a", "b"):
        for i in (1, 2):
            rows.append(
                {
                    "slug": slug,
                    "arm": "pipeline",
                    "sample": i,
                    "jd_alignment": 9.0,
                    "recruiter_readability": 8.5,
                    "authenticity": 9.5,
                    "hire_intent": 8.0,
                    "composite": 9.1,
                }
            )
            rows.append(
                {
                    "slug": slug,
                    "arm": "control",
                    "sample": i,
                    "jd_alignment": 7.0,
                    "recruiter_readability": 7.5,
                    "authenticity": 9.0,
                    "hire_intent": 6.5,
                    "composite": 7.5,
                }
            )
    out = render("test-sweep", rows)
    assert "2 JDs, n=2 per arm" in out
    assert "hire intent *" in out
    assert "2W-0L-0T" in out


def _scored(arm: str, authenticity: float, readability: float) -> dict[str, object]:
    return {
        "slug": "a",
        "arm": arm,
        "sample": 1,
        "jd_alignment": 8.0,
        "recruiter_readability": readability,
        "authenticity": authenticity,
        "hire_intent": 7.0,
        "composite": 8.0,
    }


def test_a_document_that_fails_the_gate_is_counted_but_not_averaged() -> None:
    """A gate rejects; it does not deduct. A fabricated resume would not be
    sent, so it must not pull an arm's quality means down — but how often an
    arm fails is a result in its own right and has to be visible."""
    from evaluation.report import gate_record, summarise

    rows = [_scored("pipeline", 9.5, 6.0), _scored("pipeline", 5.0, 2.0)]
    assert gate_record(rows) == {"pipeline": (1, 2)}
    assert summarise(rows)["pipeline"]["recruiter_readability"] == (6.0, 0.0)


def test_the_report_states_gate_failures() -> None:
    from evaluation.report import render

    rows = [_scored("pipeline", 9.5, 6.0), _scored("control", 5.0, 6.0)]
    rows.append(_scored("control", 9.5, 6.0))
    out = render("gate-sweep", rows)
    assert "1/1" in out and "1/2" in out


def test_a_single_arm_sweep_does_not_report_a_delta_against_nothing() -> None:
    """`--arms pipeline` is the documented way to run a before/after. Its report
    printed the absent control as 0.00 and the pipeline's own mean as a delta."""
    from evaluation.report import render

    out = render("one-arm", [_scored("pipeline", 9.5, 6.0)])
    assert "0.00 ± 0.00" not in out
    assert "+6.00" not in out and "+8.00" not in out
    assert "Per-JD record" not in out
