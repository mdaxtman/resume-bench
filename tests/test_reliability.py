"""Judge reliability: can an axis tell two documents apart at all?

A low spread across documents has two explanations that look identical in the
aggregate — a judge that cannot discriminate, and documents that genuinely do
not differ. They are separated by re-scoring the SAME document repeatedly. If
the variation within one document is as large as the variation between
documents, the axis carries no document-level information regardless of which
explanation holds.

This is the ratio ICC reports: between-document variance over total variance.
Near 1, the axis is measuring the document. Near 0, it is measuring nothing.
"""

import pytest

from evaluation.reliability import icc, reliability_report


def test_a_perfectly_consistent_judge_scores_one() -> None:
    """Same document, same score every time; different documents differ."""
    assert icc({"a": [5.0, 5.0, 5.0], "b": [8.0, 8.0, 8.0]}) == pytest.approx(1.0)


def test_a_judge_that_ignores_the_document_scores_zero() -> None:
    """Identical spread within each document, no separation between them."""
    value = icc({"a": [5.0, 8.0], "b": [5.0, 8.0]})
    assert value == pytest.approx(0.0, abs=0.01)


def test_a_realistically_noisy_judge_lands_between() -> None:
    value = icc({"a": [5.0, 5.5, 6.0], "b": [7.0, 7.5, 8.0]})
    assert 0.5 < value < 1.0


def test_icc_needs_at_least_two_documents() -> None:
    with pytest.raises(ValueError):
        icc({"a": [5.0, 6.0]})


def test_icc_needs_repeats() -> None:
    with pytest.raises(ValueError):
        icc({"a": [5.0], "b": [7.0]})


def test_report_carries_both_variance_components() -> None:
    r = reliability_report({"a": [5.0, 5.5], "b": [7.0, 7.5]})
    assert r["within_sd"] < r["between_sd"]
    assert r["documents"] == 2 and r["repeats"] == 2
    assert 0.0 <= r["icc"] <= 1.0


def test_a_constant_axis_is_reported_not_crashed() -> None:
    """Authenticity sits at 9.5 for most documents; that must not divide by zero."""
    r = reliability_report({"a": [9.5, 9.5], "b": [9.5, 9.5]})
    assert r["icc"] == 0.0
    assert r["between_sd"] == 0.0
