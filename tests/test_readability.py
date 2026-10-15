"""Readability as four scored parts rather than one holistic number.

The holistic axis sat at 6.0 for 80% of documents while reproducing its own
score to within 0.18, so the compression was real rather than noise — but a
single number could not say which property of a document held it there. Parts
make a score diagnosable, and the arithmetic that combines them stays in Python
where it is deterministic, the same policy as authenticity.
"""

import pytest

from evaluation.contracts import ColdReadInput
from evaluation.judges import READABILITY_PARTS, build_cold_read_request, readability_score


def test_readability_is_the_mean_of_its_parts() -> None:
    parts = {"opening": 8.0, "scannability": 6.0, "economy": 5.0, "structure": 7.0}
    assert readability_score(parts) == 6.5


def test_a_missing_part_is_an_error_not_a_smaller_mean() -> None:
    """Averaging whatever arrived would score a three-part response on a
    different scale from a four-part one without anyone noticing."""
    with pytest.raises(ValueError, match="economy"):
        readability_score({"opening": 8.0, "scannability": 6.0, "structure": 7.0})


def test_an_out_of_range_part_is_rejected() -> None:
    parts = {"opening": 8.0, "scannability": 6.0, "economy": 12.0, "structure": 7.0}
    with pytest.raises(ValueError, match="economy"):
        readability_score(parts)


def test_the_judge_is_asked_for_parts_and_not_for_a_holistic_score() -> None:
    """If the schema still offered a holistic field, the judge could fill it and
    the parts would become decoration."""
    schema = build_cold_read_request(ColdReadInput(jd="jd", resume="resume"))["tools"][0][
        "input_schema"
    ]
    fields = set(schema["properties"])
    assert {f"readability_{p}" for p in READABILITY_PARTS} <= fields
    assert "recruiter_readability" not in fields
    assert set(schema["required"]) >= {f"readability_{p}" for p in READABILITY_PARTS}
