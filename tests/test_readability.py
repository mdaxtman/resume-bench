"""Readability as four scored parts rather than one holistic number.

The holistic axis sat at 6.0 for 80% of documents while reproducing its own
score to within 0.18, so the compression was real rather than noise — but a
single number could not say which property of a document held it there. Parts
make a score diagnosable, and the arithmetic that combines them stays in Python
where it is deterministic, the same policy as authenticity.
"""

import pytest

from evaluation.contracts import ColdReadInput
from evaluation.judges import (
    READABILITY_PARTS,
    build_cold_read_request,
    cold_read_valid,
    readability_score,
)


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


def _valid() -> dict[str, object]:
    return {
        "jd_alignment": 8,
        "readability_opening": 6,
        "readability_scannability": 6,
        "readability_economy": 5,
        "readability_structure": 7,
        "hire_intent": 7,
        "notes": {},
    }


def test_a_well_formed_cold_read_is_accepted() -> None:
    assert cold_read_valid(_valid())


def test_note_text_in_a_score_field_is_rejected() -> None:
    """Observed live in trim-01: the judge flattened its notes into the top
    level, putting prose where `hire_intent` belonged and dropping the number.
    Rejecting it lets the call retry instead of failing the document."""
    flattened = _valid() | {"hire_intent": "The depth of ownership (sole frontend engineer..."}
    assert not cold_read_valid(flattened)


def test_a_missing_or_out_of_range_score_is_rejected() -> None:
    missing = {k: v for k, v in _valid().items() if k != "readability_economy"}
    assert not cold_read_valid(missing)
    assert not cold_read_valid(_valid() | {"jd_alignment": 11})
