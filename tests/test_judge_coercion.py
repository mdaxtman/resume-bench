"""Coercion of the authenticity judge's string-array fields.

`untraceable` and `overstatements` are declared as arrays of strings. When the
model delivers one as a bare string instead, iterating it yields CHARACTERS —
observed live as 868 untraceable claims and 2,994 overstatements against 55
claims checked, which floored the score at 0 and, because authenticity carries
0.4 of the composite, corrupted the aggregate and inflated its spread fourfold.

A count of findings that exceeds the number of claims checked is arithmetically
impossible, so it is treated as a malformed response rather than scored.
"""

import json

import pytest

from evaluation.judges import authenticity_findings
from pipeline.anthropic_utils import str_items

ITEMS = ["claimed to have architected X", "overstated team size"]


def test_a_well_formed_list_passes_through() -> None:
    assert str_items(ITEMS) == ITEMS


def test_a_bare_string_is_not_split_into_characters() -> None:
    """The live failure. Must never yield 868 items from one sentence."""
    result = str_items("claimed to have architected X")
    assert result != list("claimed to have architected X")
    assert len(result) <= 1


def test_json_string_wrapping_a_single_key_object_is_recovered() -> None:
    assert str_items(json.dumps({"untraceable": ITEMS})) == ITEMS


def test_json_string_of_a_bare_array_is_recovered() -> None:
    assert str_items(json.dumps(ITEMS)) == ITEMS


def test_non_string_items_are_coerced_not_dropped() -> None:
    """A finding rendered as an object still counts as a finding."""
    assert len(str_items([{"claim": "x"}, "y"])) == 2


def test_none_and_missing_are_empty() -> None:
    assert str_items(None) == [] and str_items([]) == []


def test_findings_cannot_exceed_claims_checked() -> None:
    with pytest.raises(ValueError, match="impossible"):
        authenticity_findings({"claims_checked": 5, "untraceable": ITEMS * 4, "overstatements": []})


def test_a_plausible_result_is_accepted() -> None:
    claims, untraceable, overstatements = authenticity_findings(
        {"claims_checked": 40, "untraceable": ITEMS, "overstatements": ["a"]}
    )
    assert (claims, len(untraceable), len(overstatements)) == (40, 2, 1)


def test_claims_checked_must_be_positive() -> None:
    with pytest.raises(ValueError):
        authenticity_findings({"claims_checked": 0, "untraceable": [], "overstatements": []})
