"""Judge isolation — the load-bearing property of the whole harness.

If a cold-read judge ever sees the candidate narratives, it stops scoring the
resume and starts scoring the candidate, and every number the harness produces
becomes meaningless without producing a single error. Convention cannot hold
this line across refactors, so the contracts are shaped to make contamination a
construction failure rather than a silent one.

The production change these tests exist to catch: someone giving the two judge
inputs a shared base class, or adding `narratives: str | None = None` to the
cold-read input so one helper can serve both judges.
"""

import json
import re

import pytest

from evaluation.contracts import AuthenticityInput, ColdReadInput
from evaluation.judges import build_authenticity_request, build_cold_read_request

NARRATIVES = "GROUND-TRUTH-SENTINEL: candidate led the 2019 platform migration."
JD = "Staff Software Engineer. Requires distributed systems experience."
RESUME_A = "PIPELINE-ARM-SENTINEL: Staff Engineer, platform migration."
RESUME_B = "CONTROL-ARM-SENTINEL: Senior Engineer, various projects."


def test_cold_read_input_cannot_carry_narratives() -> None:
    """There must be no field for ground truth on the blind judge's input."""
    with pytest.raises(TypeError):
        ColdReadInput(jd=JD, resume=RESUME_A, narratives=NARRATIVES)  # type: ignore[call-arg]


def test_cold_read_request_excludes_narratives() -> None:
    """Nothing traceable to ground truth may reach the blind judge's payload."""
    payload = json.dumps(build_cold_read_request(ColdReadInput(jd=JD, resume=RESUME_A)))
    assert "GROUND-TRUTH-SENTINEL" not in payload
    assert "PIPELINE-ARM-SENTINEL" in payload


def test_cold_read_request_excludes_the_other_arm() -> None:
    """Each arm is scored on an absolute scale, never against its competitor."""
    payload = json.dumps(build_cold_read_request(ColdReadInput(jd=JD, resume=RESUME_A)))
    assert "CONTROL-ARM-SENTINEL" not in payload


def test_authenticity_request_includes_narratives() -> None:
    """Positive control: the exclusion tests above would be vacuous if the
    sentinel could never appear in a payload at all."""
    payload = json.dumps(
        build_authenticity_request(AuthenticityInput(resume=RESUME_A, narratives=NARRATIVES))
    )
    assert "GROUND-TRUTH-SENTINEL" in payload


def test_authenticity_input_cannot_carry_the_jd() -> None:
    """Authenticity is a fact-check against ground truth, not a fit judgement.
    Letting the JD in invites the judge to reward relevance over traceability."""
    with pytest.raises(TypeError):
        AuthenticityInput(resume=RESUME_A, narratives=NARRATIVES, jd=JD)  # type: ignore[call-arg]


def test_judge_inputs_share_no_base_class() -> None:
    """A shared base is how the narratives field gets reintroduced by accident."""
    common = set(ColdReadInput.__mro__) & set(AuthenticityInput.__mro__) - {object}
    assert not common, f"judge inputs share ancestry: {common}"


def test_cold_read_payload_contains_only_allowed_sections() -> None:
    """Allowlist, not denylist. A denylist here fails open: it only catches the
    contaminating section someone thought to forbid, and the realistic leak
    arrives under a friendly name like `<candidate_context>`. Enumerating what
    is permitted means any new section fails the test by default."""
    allowed = {"job_description", "resume"}
    payload = build_cold_read_request(ColdReadInput(jd=JD, resume=RESUME_A))
    message = payload["messages"][0]["content"]
    found = set(re.findall(r"<([a-z_]+)>", message))
    assert found == allowed, f"unexpected sections in blind judge payload: {found - allowed}"
