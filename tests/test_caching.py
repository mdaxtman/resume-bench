"""Prompt-cache prefix construction.

The narratives are 22k tokens and byte-identical across every call in a sweep —
the shape prompt caching exists for. But a cache prefix must match from the very
start of the request, so the saving is only available where the stable content
comes first. Where the job description precedes the narratives, the prefix
differs per posting and nothing is cacheable.

These tests pin the structure, not the saving; whether the cache is actually hit
is a fact about a live run and is recorded in the trace as cache_read tokens.
"""

import pytest

from pipeline.anthropic_utils import cached_system, split_for_cache

STABLE = "<candidate_narratives>\nyears of history\n</candidate_narratives>\n\n"
VARIABLE = "<job_description>\nthis posting\n</job_description>"


def test_system_is_one_block_marked_for_caching() -> None:
    blocks = cached_system("You are a recruiter.")
    assert len(blocks) == 1
    assert blocks[0]["text"] == "You are a recruiter."
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_user_message_splits_into_cached_prefix_then_variable_tail() -> None:
    blocks = split_for_cache(STABLE, VARIABLE)
    assert [b["text"] for b in blocks] == [STABLE, VARIABLE]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_the_split_preserves_the_prompt_byte_for_byte() -> None:
    """A cache change must not become a prompt change. Concatenating the blocks
    has to reproduce exactly what a single-string message would have sent."""
    assert "".join(b["text"] for b in split_for_cache(STABLE, VARIABLE)) == STABLE + VARIABLE


def test_an_empty_variable_tail_is_omitted_rather_than_sent_blank() -> None:
    blocks = split_for_cache(STABLE, "")
    assert len(blocks) == 1 and blocks[0]["text"] == STABLE


def test_a_stable_prefix_must_not_be_empty() -> None:
    """An empty prefix would place a breakpoint with nothing before it."""
    with pytest.raises(ValueError):
        split_for_cache("", VARIABLE)
