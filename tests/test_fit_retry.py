"""Selecting a usable tool_use block, and retrying when none is usable.

Two real fit responses, both `stop_reason=tool_use`, neither truncated:

  run 1: every array field arrived as a JSON string wrapping a single-key object
  run 2: `<parameter name="...">` function-call syntax leaked into a parameter
         VALUE, nested objects flattened to top-level keys, and a SECOND
         tool_use block appended carrying empty arrays and reasoning
         "placeholder"

The first block is not reliably the good one, so the response has to be searched
rather than indexed, and a response with no usable block has to be retried
rather than recorded.
"""

import pytest

from pipeline.anthropic_utils import select_tool_input
from pipeline.fit_assessment import fit_is_usable

GOOD = {"matches": [{"requirement": "React", "priority": "required", "notes": "9y"}]}
FLATTENED = {"matches": "\n<parameter name=\"requirement\">React", "priority": "required"}
EMPTY = {"matches": [], "gaps": [], "reasoning": "placeholder"}


def test_the_only_block_is_used() -> None:
    assert select_tool_input([GOOD], fit_is_usable) == GOOD


def test_a_later_block_is_chosen_when_the_first_is_unusable() -> None:
    """Indexing [0] is what made run 2 invisible."""
    assert select_tool_input([FLATTENED, GOOD], fit_is_usable) == GOOD


def test_the_first_usable_block_wins() -> None:
    other = {"matches": [{"requirement": "TS", "priority": "required", "notes": "5y"}]}
    assert select_tool_input([GOOD, other], fit_is_usable) == GOOD


def test_no_usable_block_raises() -> None:
    with pytest.raises(ValueError, match="no usable"):
        select_tool_input([FLATTENED, EMPTY], fit_is_usable)


def test_no_blocks_at_all_raises() -> None:
    with pytest.raises(ValueError):
        select_tool_input([], fit_is_usable)


def test_without_a_validator_the_first_block_is_returned() -> None:
    """Stages with no shape to check keep the old behaviour."""
    assert select_tool_input([FLATTENED, GOOD], None) == FLATTENED


def test_fit_usability_requires_recoverable_matches() -> None:
    assert fit_is_usable(GOOD)
    assert not fit_is_usable(FLATTENED)
    assert not fit_is_usable(EMPTY)


def test_fit_usability_accepts_the_json_string_shape() -> None:
    """Run 1's malformation is recoverable, so it counts as usable."""
    import json
    assert fit_is_usable({"matches": json.dumps({"matches": GOOD["matches"]})})
