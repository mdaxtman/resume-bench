"""Prompt-cache prefix construction.

The narratives are 22k tokens and byte-identical across every call in a sweep —
the shape prompt caching exists for. But a cache prefix must match from the very
start of the request, so the saving is only available where the stable content
comes first. Where the job description precedes the narratives, the prefix is
shared by one posting's samples, which a sweep runs back to back.

These tests pin the structure, not the saving; whether the cache is actually hit
is a fact about a live run and is recorded in the trace as cache_read tokens.
"""

from typing import Any
from unittest.mock import patch

import pytest

from evaluation.contracts import ColdReadInput
from evaluation.judges import build_cold_read_request
from pipeline import fit_assessment, refinement, screener
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


POSTING = "<job_description>\nthis posting\n</job_description>\n\n"


def _request(module: Any, run: Any) -> dict[str, Any]:
    ret = {"matches": [{"requirement": "r"}], "refined_content": ""}
    with patch.object(module, "call_model", return_value=ret) as call:
        run()
    return dict(call.call_args.kwargs)


def test_fit_caches_the_posting_and_the_narratives() -> None:
    """Everything but the closing instruction repeats for each sample of a posting."""
    request = _request(
        fit_assessment, lambda: fit_assessment.run_fit_assessment("this posting", "my history")
    )
    cached, tail = request["messages"][0]["content"]
    assert cached["cache_control"] == {"type": "ephemeral"}
    assert cached["text"].startswith(POSTING)
    assert "my history" in cached["text"] and "my history" not in tail["text"]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize(
    "request_",
    [
        lambda: _request(screener, lambda: screener.run_screener("this posting", "a resume")),
        lambda: _request(
            refinement, lambda: refinement.run_refinement("a resume", {}, "hist", "this posting")
        ),
        lambda: build_cold_read_request(ColdReadInput(jd="this posting", resume="a resume")),
    ],
    ids=["screener", "refinement", "cold read"],
)
def test_stages_that_open_with_the_posting_cache_only_the_posting(request_: Any) -> None:
    """The resume varies by sample, so the cached prefix stops before it."""
    request = request_()
    cached, tail = request["messages"][0]["content"]
    assert cached == {"type": "text", "text": POSTING, "cache_control": {"type": "ephemeral"}}
    assert tail["text"].startswith("<resume>") or tail["text"].startswith("<generated_resume>")
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
