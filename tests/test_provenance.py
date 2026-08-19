"""Sweep provenance. Pure functions plus one filesystem property."""

from config import PROMPTS_DIR
from provenance import diff_metadata, prompt_fingerprints, sweep_metadata


def test_fingerprints_cover_every_prompt() -> None:
    """The production change this catches: adding a prompt file and forgetting
    it, so a sweep silently varies on an input nothing recorded."""
    assert set(prompt_fingerprints()) == {p.stem for p in PROMPTS_DIR.glob("*.md")}


def test_a_new_prompt_appears_in_the_fingerprint() -> None:
    probe = PROMPTS_DIR / "__probe__.md"
    probe.write_text("temporary")
    try:
        assert "__probe__" in prompt_fingerprints()
    finally:
        probe.unlink()
    assert "__probe__" not in prompt_fingerprints()


def test_fingerprints_are_content_addressed() -> None:
    probe = PROMPTS_DIR / "__probe__.md"
    probe.write_text("one")
    try:
        first = prompt_fingerprints()["__probe__"]
        probe.write_text("two")
        assert prompt_fingerprints()["__probe__"] != first
    finally:
        probe.unlink()


def test_identical_conditions_diff_to_nothing() -> None:
    meta = sweep_metadata()
    assert diff_metadata(meta, meta) == []


def test_a_changed_prompt_is_reported() -> None:
    a = {"prompts": {"generator": "aaaaaaaaaaaa"}}
    b = {"prompts": {"generator": "bbbbbbbbbbbb"}}
    assert diff_metadata(a, b) == ["prompt generator: aaaaaaaaaaaa -> bbbbbbbbbbbb"]


def test_model_and_weight_changes_are_reported() -> None:
    a = {"pipeline_model": "claude-sonnet-5", "weights": {"jd_alignment": 0.4}}
    b = {"pipeline_model": "claude-opus-5", "weights": {"jd_alignment": 0.5}}
    changes = diff_metadata(a, b)
    assert any("pipeline_model" in c for c in changes)
    assert any("weights" in c for c in changes)
