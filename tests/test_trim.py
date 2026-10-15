"""Verbatim trimming: removing bullets from a resume without rewording any.

The experiment this serves asks whether a shorter, more selective resume scores
better. That is only answerable if trimming changes nothing *but* selection —
a reworded bullet would confound length with wording — so the property most of
these tests pin is that whatever survives is byte-identical to the source.
"""

import re
from typing import Any

import pytest

from evaluation.keywords import Keyword
from evaluation.trim import (
    BulletRelevanceInput,
    build_relevance_request,
    experience_bullets,
    mean_ci,
    paired_deltas,
    ratings_complete,
    removal_order,
    remove_bullets,
    trim_to_budget,
    word_count,
)

PIPELINE_DOC = """## Summary
Frontend engineer with 11 years.

## Experience

**Senior Engineer** at Tesla (May 2026 – present)

**Scheduling Platform**

- Sole frontend engineer owning a React SPA.

- Introduced TanStack Query for server state.

**Frontend Engineer L5** at Amazon (May 2020 – May 2026)

**Control Tower Console**

- Built a dynamic wizard from composable hooks.

**Service Catalog Console**

- Migrated the console to Cloudscape v3.

## Skills
React, TypeScript
"""

CONTROL_DOC = """## Summary
Frontend engineer.

## Experience

### Tesla — Senior Engineer (May 2026 – present)

**Scheduling Platform**
- Sole frontend engineer owning a React SPA.
- Introduced TanStack Query for server state.

### Ekko Media — Frontend Developer (March 2015 – December 2015)

- Built marketing sites with jQuery.

## Skills
React
"""


def test_bullets_are_found_only_inside_experience() -> None:
    texts = [b.text for b in experience_bullets(PIPELINE_DOC)]
    assert texts == [
        "Sole frontend engineer owning a React SPA.",
        "Introduced TanStack Query for server state.",
        "Built a dynamic wizard from composable hooks.",
        "Migrated the console to Cloudscape v3.",
    ]


def test_roles_are_numbered_from_most_recent_in_both_formats() -> None:
    assert [b.role for b in experience_bullets(PIPELINE_DOC)] == [0, 0, 1, 1]
    assert [b.role for b in experience_bullets(CONTROL_DOC)] == [0, 0, 1]


def test_each_bullet_carries_its_role_as_context() -> None:
    bullets = experience_bullets(CONTROL_DOC)
    assert "Tesla" in bullets[0].context and "Ekko" in bullets[2].context


SPLIT_DATE_DOC = """## Experience

**Tesla — Senior Engineer**
*May 2026 – present*

*Scheduling Platform*
- Sole frontend engineer owning a React SPA.

**Amazon — Frontend Engineer L5**
*May 2020 – May 2026*

- Built a dynamic wizard.
"""


def test_a_role_whose_dates_sit_on_their_own_line_keeps_its_name() -> None:
    """Observed in the corpus: the employer line carries no year and the date
    follows on the next line. Without joining them, the rater sees a bullet
    labelled only "May 2026 – present"."""
    bullets = experience_bullets(SPLIT_DATE_DOC)
    assert [b.role for b in bullets] == [0, 1]
    assert "Tesla" in bullets[0].context and "2026" in bullets[0].context
    assert "Amazon" in bullets[1].context


def test_the_employer_line_of_a_split_role_header_is_never_removed() -> None:
    out = remove_bullets(SPLIT_DATE_DOC, {1})
    assert "**Amazon — Frontend Engineer L5**" in out and "*May 2020 – May 2026*" in out


def test_surviving_text_is_byte_identical() -> None:
    out = remove_bullets(PIPELINE_DOC, {1})
    for b in experience_bullets(PIPELINE_DOC):
        if b.index != 1:
            assert f"- {b.text}" in out
    assert "TanStack" not in out


def test_a_project_header_goes_with_its_last_bullet() -> None:
    out = remove_bullets(PIPELINE_DOC, {2})
    assert "**Control Tower Console**" not in out
    assert "**Service Catalog Console**" in out


def test_a_role_header_stays_when_all_its_bullets_go() -> None:
    """Dropping a role outright would open a gap in the timeline, which a
    judge reads as a fact about the candidate rather than about selection."""
    out = remove_bullets(CONTROL_DOC, {2})
    assert "### Ekko Media — Frontend Developer (March 2015 – December 2015)" in out
    assert "jQuery" not in out


def test_sections_outside_experience_are_untouched() -> None:
    out = remove_bullets(PIPELINE_DOC, {0, 1, 2, 3})
    assert out.startswith("## Summary\nFrontend engineer with 11 years.\n")
    assert out.rstrip().endswith("## Skills\nReact, TypeScript")


def test_removal_leaves_no_runs_of_blank_lines() -> None:
    assert "\n\n\n" not in remove_bullets(PIPELINE_DOC, {1, 2})


def _ratings(*values: int) -> dict[int, int]:
    return dict(enumerate(values))


def test_lowest_rated_bullet_goes_first() -> None:
    order = removal_order(PIPELINE_DOC, _ratings(3, 3, 0, 3), keywords=[])
    assert order[0] == 2


def test_the_only_carrier_of_a_required_term_outlasts_an_equal_rated_bullet() -> None:
    """Coverage is the one axis the pipeline measurably wins on; selection
    must not throw it away when an equally relevant bullet costs nothing."""
    keywords = [Keyword(term="Cloudscape", required=True)]
    order = removal_order(PIPELINE_DOC, _ratings(3, 3, 1, 1), keywords=keywords)
    assert order.index(2) < order.index(3)


def test_older_roles_go_first_among_equals() -> None:
    order = removal_order(CONTROL_DOC, _ratings(1, 1, 1), keywords=[])
    assert order[0] == 2


def test_the_most_recent_role_always_keeps_a_bullet() -> None:
    order = removal_order(PIPELINE_DOC, _ratings(0, 0, 3, 3), keywords=[])
    assert len(order) == 3
    survivor = ({0, 1, 2, 3} - set(order)).pop()
    assert survivor in {0, 1}


def test_trimming_stops_at_the_first_prefix_under_budget() -> None:
    order = removal_order(PIPELINE_DOC, _ratings(3, 2, 1, 0), keywords=[])
    full = word_count(PIPELINE_DOC)
    doc, dropped = trim_to_budget(PIPELINE_DOC, order, budget=full - 1)
    assert dropped == order[:1]
    assert word_count(doc) <= full - 1


def test_a_budget_already_met_removes_nothing() -> None:
    order = removal_order(PIPELINE_DOC, _ratings(3, 2, 1, 0), keywords=[])
    doc, dropped = trim_to_budget(PIPELINE_DOC, order, budget=10_000)
    assert doc == PIPELINE_DOC and dropped == []


def test_budgets_nest() -> None:
    """A tighter budget removes a superset of what a looser one did, so the
    conditions differ only in how far down one ordering they go."""
    order = removal_order(PIPELINE_DOC, _ratings(3, 2, 1, 0), keywords=[])
    full = word_count(PIPELINE_DOC)
    _, loose = trim_to_budget(PIPELINE_DOC, order, budget=full - 1)
    _, tight = trim_to_budget(PIPELINE_DOC, order, budget=full - 12)
    assert set(loose) <= set(tight)


def test_relevance_rater_cannot_carry_narratives() -> None:
    with pytest.raises(TypeError):
        BulletRelevanceInput(jd="jd", bullets=(), narratives="x")  # type: ignore[call-arg]


def test_relevance_payload_contains_only_the_jd_and_bullets() -> None:
    bullets = experience_bullets(PIPELINE_DOC)
    payload = build_relevance_request(BulletRelevanceInput(jd="JD-TEXT", bullets=tuple(bullets)))
    message = payload["messages"][0]["content"]
    assert set(re.findall(r"<([a-z_]+)>", message)) == {"job_description", "bullets"}
    assert "[3]" in message and "Cloudscape" in message


def _rated(*pairs: tuple[int, int]) -> dict[str, Any]:
    return {"ratings": [{"index": i, "rating": r} for i, r in pairs]}


def test_ratings_must_cover_every_bullet() -> None:
    assert ratings_complete(_rated((0, 3), (1, 2)), 2)
    assert not ratings_complete(_rated((0, 3)), 2)
    assert not ratings_complete(_rated((0, 3), (1, 7)), 2)


def _scored_row(
    slug: str, budget: int | None, readability: float, auth: float = 9.5
) -> dict[str, Any]:
    return {
        "slug": slug,
        "arm": f"pipeline-{budget or 'full'}",
        "source_arm": "pipeline",
        "budget": budget,
        "recruiter_readability": readability,
        "authenticity": auth,
    }


def test_deltas_are_paired_within_job() -> None:
    """Job a is easy and job b is hard; a between-job comparison would see that
    spread, a within-job one sees only the change trimming caused."""
    rows = [
        _scored_row("a", None, 8.0),
        _scored_row("a", 600, 9.0),
        _scored_row("b", None, 4.0),
        _scored_row("b", 600, 5.0),
    ]
    assert paired_deltas(rows, "recruiter_readability", 600, {"pipeline"}) == [1.0, 1.0]


def test_a_job_missing_either_condition_is_left_out() -> None:
    rows = [_scored_row("a", None, 8.0), _scored_row("b", 600, 5.0)]
    assert paired_deltas(rows, "recruiter_readability", 600, {"pipeline"}) == []


def test_documents_failing_the_gate_do_not_enter_a_delta() -> None:
    rows = [
        _scored_row("a", None, 8.0),
        _scored_row("a", 600, 9.0),
        _scored_row("a", 600, 1.0, auth=3.0),
    ]
    assert paired_deltas(rows, "recruiter_readability", 600, {"pipeline"}) == [1.0]


def test_confidence_interval_uses_t_not_z_at_small_n() -> None:
    mean, lo, hi = mean_ci([1.0, 2.0, 3.0])
    assert mean == 2.0
    assert hi - mean == pytest.approx(4.303 * 1.0 / 3**0.5, rel=1e-3)
    assert mean - lo == pytest.approx(hi - mean)
