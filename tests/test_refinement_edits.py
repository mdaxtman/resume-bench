"""Refinement as edits applied in code.

Refinement was told it may not add claims and added 1.3 overstatements a
document anyway; every untraceable claim in 78 refined documents entered there.
The edit-list variant makes the rules that matter checkable: an edit replaces
one exact span on one line, may not grow it past a few words, and a
substitution must quote a sentence that is in the narratives.
"""

import json
from typing import Any
from unittest.mock import patch

from pipeline import refinement
from pipeline.refinement import MAX_GROWTH, apply_edits

NARRATIVES = """## Amazon
I built the **Git Catalog** console feature, syncing product templates from
customer repositories, and wrote the integration tests for it."""

DRAFT = """## Experience
### Engineer at Amazon
_2020 – 2026_
- Built Git sync for product templates in the console
- Wrote integration tests for the sync flow
## Skills
React, TypeScript"""

EVIDENCE = "I built the Git Catalog console feature, syncing product templates"


def _sub(before: str, after: str, evidence: str | None = EVIDENCE) -> dict[str, Any]:
    edit: dict[str, Any] = {"type": "substitute", "before": before, "after": after}
    if evidence is not None:
        edit["narrative_evidence"] = evidence
    return edit


def test_a_substitution_with_verbatim_evidence_applies() -> None:
    text, applied, rejected = apply_edits(
        DRAFT, [_sub("Git sync for product templates", "Git Catalog template sync")], NARRATIVES
    )
    assert "- Built Git Catalog template sync in the console" in text
    assert len(applied) == 1 and not rejected


def test_evidence_matches_across_markdown_typography_and_wrapping() -> None:
    """The narrative bolds "Git Catalog" and wraps the line; a faithful quote
    still matches."""
    quote = "syncing product templates from customer repositories, and wrote the"
    _, applied, _ = apply_edits(DRAFT, [_sub("Git sync", "Git Catalog sync", quote)], NARRATIVES)
    assert applied


def test_evidence_that_is_not_in_the_narratives_is_rejected() -> None:
    edit = _sub(
        "Git sync", "GitOps pipeline", "I designed the GitOps deployment pipeline end to end"
    )
    text, applied, rejected = apply_edits(DRAFT, [edit], NARRATIVES)
    assert text == DRAFT and not applied
    assert rejected[0]["rejected"] == "evidence not in narratives"


def test_a_substitution_without_evidence_is_rejected() -> None:
    for evidence in (None, "", "I built it"):
        _, applied, rejected = apply_edits(
            DRAFT, [_sub("Git sync", "Git Catalog sync", evidence)], NARRATIVES
        )
        assert not applied and rejected[0]["rejected"] == "substitution without evidence"


def test_an_appended_clause_is_rejected_as_an_addition() -> None:
    """The keyword clauses refinement used to append: '…, strengthening X'."""
    before = "Wrote integration tests for the sync flow"
    after = before + ", establishing test-driven development across the team"
    _, applied, rejected = apply_edits(
        DRAFT, [{"type": "hygiene", "before": before, "after": after}], NARRATIVES
    )
    assert not applied and rejected[0]["rejected"].startswith("adds")


def test_growth_up_to_the_cap_is_allowed() -> None:
    before = "integration tests"
    after = " ".join([before] + ["x"] * MAX_GROWTH["tighten"])
    _, applied, _ = apply_edits(
        DRAFT, [{"type": "tighten", "before": before, "after": after}], NARRATIVES
    )
    assert applied


def test_an_edit_cannot_change_the_layout() -> None:
    edit = {
        "type": "hygiene",
        "before": "### Engineer at Amazon\n_2020 – 2026_",
        "after": "**Engineer** at Amazon",
    }
    text, applied, rejected = apply_edits(DRAFT, [edit], NARRATIVES)
    assert text == DRAFT and rejected[0]["rejected"] == "spans more than one line"


def test_an_ambiguous_or_missing_span_is_rejected() -> None:
    for before, count in (("the", 2), ("Kubernetes", 0)):
        edit = {"type": "tighten", "before": before, "after": "a"}
        _, applied, rejected = apply_edits(DRAFT, [edit], NARRATIVES)
        assert not applied and rejected[0]["rejected"] == f"before occurs {count} times"


def test_tightening_needs_no_evidence() -> None:
    edit = {"type": "tighten", "before": "Built Git sync", "after": "Contributed to Git sync"}
    _, applied, _ = apply_edits(DRAFT, [edit], NARRATIVES)
    assert applied


def test_edits_apply_to_the_text_earlier_edits_left() -> None:
    first = {"type": "tighten", "before": "Wrote integration tests", "after": "Wrote tests"}
    second = {
        "type": "tighten",
        "before": "Wrote tests for the sync flow",
        "after": "Tested the sync flow",
    }
    text, applied, _ = apply_edits(DRAFT, [first, second], NARRATIVES)
    assert "- Tested the sync flow" in text and len(applied) == 2


def _run(result: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    with patch.object(refinement, "call_model", return_value=result) as call:
        out = refinement.run_refinement_edits(DRAFT, {}, NARRATIVES, "jd")
    return out, call


def test_the_edit_list_is_recovered_when_it_arrives_as_a_json_string() -> None:
    edits = [{"type": "tighten", "before": "Built Git sync", "after": "Built a Git sync"}]
    out, _ = _run({"edits": json.dumps({"edits": edits})})
    assert "- Built a Git sync" in out["refined_content"]


def test_no_edits_returns_the_draft_unchanged() -> None:
    out, _ = _run({"edits": []})
    assert out["refined_content"] == DRAFT


def test_both_variants_end_on_the_add_nothing_rule() -> None:
    _, call = _run({"edits": []})
    assert call.call_args.kwargs["messages"][0]["content"].rstrip().endswith(refinement.ADD_NOTHING)
    with patch.object(refinement, "call_model", return_value={"refined_content": ""}) as call:
        refinement.run_refinement(DRAFT, {}, NARRATIVES, "jd")
    assert call.call_args.kwargs["messages"][0]["content"].rstrip().endswith(refinement.ADD_NOTHING)
