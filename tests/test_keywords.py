"""Literal keyword coverage — the one axis with no measurement variance.

`jd_alignment` asks a judge whether a resume *addresses* the requirements. That
is a recruiter reading for meaning. It is not what makes a candidate findable:
a recruiter running a boolean search over parsed records gets nothing back for
`Kubernetes` from a resume that eloquently addresses container orchestration
without using the word.

Extraction runs once per JD and sees only the JD — never a resume, never an arm
label — so the same list is applied to both arms and cannot favour either. The
matching step is pure, deterministic, and repeatable to the character.
"""

import pytest

from evaluation.keywords import Keyword, KeywordExtractionInput, coverage, term_present


def kw(term: str, required: bool = True, variants: list[str] | None = None) -> Keyword:
    return Keyword(term=term, required=required, variants=variants or [])


def test_a_plain_term_is_found_case_insensitively() -> None:
    assert term_present("Built REACT components", kw("React"))
    assert term_present("built react components", kw("React"))


def test_a_substring_of_a_longer_word_is_not_a_match() -> None:
    """The canonical false positive: Java must not match JavaScript."""
    assert not term_present("10 years of JavaScript", kw("Java"))


def test_punctuation_delimits_a_match() -> None:
    """React.js contains React as a real occurrence, not a substring accident."""
    assert term_present("Built with React.js and Vite", kw("React"))


def test_a_term_containing_punctuation_still_matches() -> None:
    """\\b fails on C++; the matcher must not."""
    assert term_present("Wrote C++ and Python", kw("C++"))
    assert not term_present("Graded C++plus", kw("C++"))


def test_multi_word_terms_match_across_whitespace() -> None:
    assert term_present("Owned the Design Systems team", kw("design systems"))


def test_variants_count_as_the_same_term() -> None:
    k = kw("Kubernetes", variants=["k8s"])
    assert term_present("Deployed to k8s clusters", k)


def test_a_missing_term_is_missing() -> None:
    assert not term_present("Built React components", kw("Kubernetes"))


def test_coverage_reports_required_and_preferred_separately() -> None:
    """A missed required term is not the same event as a missed nice-to-have."""
    keywords = [kw("React"), kw("Kubernetes"), kw("GraphQL", required=False)]
    result = coverage("Built React and GraphQL services", keywords)
    assert result["required_total"] == 2
    assert result["required_found"] == 1
    assert result["preferred_total"] == 1
    assert result["preferred_found"] == 1
    assert result["missing_required"] == ["Kubernetes"]


def test_coverage_ratio_is_over_required_terms() -> None:
    result = coverage("React", [kw("React"), kw("Kubernetes")])
    assert result["required_coverage"] == 0.5


def test_coverage_with_no_required_terms_does_not_divide_by_zero() -> None:
    result = coverage("anything", [kw("GraphQL", required=False)])
    assert result["required_coverage"] is None


def test_extraction_input_cannot_carry_a_resume() -> None:
    """Extraction must not see a document, or the list could be fitted to it."""
    with pytest.raises(TypeError):
        KeywordExtractionInput(jd="...", resume="...")  # type: ignore[call-arg]
