"""Coercion of tool-result fields that do not match their declared schema.

A tool's `input_schema` is advisory: the API guarantees a well-formed tool call,
not that nested structures match their declared types. Observed in a real fit
run, with `stop_reason=tool_use` and nothing truncated — the model returned each
array field as a JSON *string* wrapping the array in a single-key object:

    "matches": "{\"matches\": [{...}, {...}]}"

The previous coercion rejected anything that was not a list and returned `[]`,
so ten matches, eight gaps and three cultural signals were discarded in silence
and the generator ran with no fit guidance at all. The stage still "succeeded".
"""

import json

import pytest

from evaluation.sweep import require_usable_fit
from pipeline.anthropic_utils import dict_items

ITEMS = [{"requirement": "React", "priority": "required", "notes": "9 years"}]


def test_a_well_formed_list_passes_through() -> None:
    assert dict_items(ITEMS) == ITEMS


def test_non_dict_items_are_dropped() -> None:
    assert dict_items([*ITEMS, "stray string", 42]) == ITEMS


def test_json_string_wrapping_a_single_key_object_is_recovered() -> None:
    """The observed real failure."""
    assert dict_items(json.dumps({"matches": ITEMS})) == ITEMS


def test_json_string_of_a_bare_array_is_recovered() -> None:
    assert dict_items(json.dumps(ITEMS)) == ITEMS


def test_leading_whitespace_does_not_defeat_recovery() -> None:
    assert dict_items("\n" + json.dumps({"gaps": ITEMS}) + "\n") == ITEMS


def test_a_multi_key_object_is_not_guessed_at() -> None:
    """Two candidate arrays means no unambiguous answer. Do not pick one."""
    assert dict_items(json.dumps({"matches": ITEMS, "gaps": ITEMS})) == []


def test_prose_is_not_coerced() -> None:
    assert dict_items("the candidate matches on React and TypeScript") == []


def test_non_list_non_string_is_empty() -> None:
    assert dict_items(None) == [] and dict_items(42) == []


def test_a_fit_report_with_no_matches_is_rejected() -> None:
    """The load-bearing guard. A pipeline arm whose fit report is empty is not
    a pipeline arm — it is a control arm with extra edit passes — and must not
    be recorded as a successful sample."""
    with pytest.raises(ValueError, match="unusable"):
        require_usable_fit({"matches": [], "gaps": [], "overall_score": 0.4})


def test_a_populated_fit_report_is_accepted() -> None:
    require_usable_fit({"matches": ITEMS, "gaps": [], "overall_score": 0.4})
