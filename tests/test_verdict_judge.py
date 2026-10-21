"""The verdict judge: a second count of unsupported claims.

The authenticity judge counts 7% of findings it has itself cleared. Giving each
finding a verdict changed what the judge counts, so it was not adopted as the
scoring judge. It is kept as a second instrument: the two agree on the control
against the pipeline and disagree between close versions, so a claim count
that decides anything is checked against both.
"""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import cli
from evaluation import judges
from evaluation.contracts import AuthenticityInput
from evaluation.report import render, with_claims

INPUT = AuthenticityInput(resume="Built the console.", narratives="Built the console alone.")


def _finding(verdict: str, claim: str = "a claim") -> dict[str, str]:
    return {"claim": claim, "reason": "because", "verdict": verdict}


def test_findings_are_split_by_verdict_and_cleared_ones_are_not_counted() -> None:
    result = judges.verdict_findings(
        {
            "claims_checked": 10,
            "findings": [
                _finding("untraceable"),
                _finding("overstated"),
                _finding("overstated"),
                _finding("supported"),
            ],
        }
    )
    assert len(result["untraceable"]) == 1 and len(result["overstatements"]) == 2
    assert len(result["withdrawn"]) == 1
    assert result["unsupported"] == judges.unsupported_claims(1, 2) == 4.0


@pytest.mark.parametrize(
    "result",
    [
        {"claims_checked": 0, "findings": []},
        {"claims_checked": 5},
        {"claims_checked": 5, "findings": [_finding("untraceable"), "a bare string"]},
        {"claims_checked": 5, "findings": [_finding("probably fine")]},
        {"claims_checked": 1, "findings": [_finding("untraceable"), _finding("overstated")]},
    ],
    ids=["no claims", "no findings", "not an object", "unknown verdict", "impossible"],
)
def test_a_malformed_response_is_rejected_so_the_call_is_retried(result: dict[str, Any]) -> None:
    assert not judges.verdict_valid(result)


def test_it_reads_what_the_authenticity_judge_reads() -> None:
    """Only the prompt and the output format differ, so the two counts differ
    only in how the judge is asked."""
    first = judges.build_authenticity_request(INPUT)
    second = judges.build_verdict_request(INPUT)
    assert second["messages"] == first["messages"]
    assert second["tools"][0]["name"] == first["tools"][0]["name"]
    assert second["tools"][0]["input_schema"]["required"] == ["claims_checked", "findings"]
    system = second["system"][0]["text"]
    assert system != first["system"][0]["text"]
    assert date.today().isoformat() in system and "{today}" not in system


def test_the_report_shows_the_second_count_when_every_document_has_one() -> None:
    def row(arm: str, overstatements: int, second: float) -> dict[str, Any]:
        return {
            "slug": "a",
            "arm": arm,
            "sample": 1,
            "jd_alignment": 8.0,
            "recruiter_readability": 6.0,
            "authenticity": 9.5,
            "hire_intent": 7.0,
            "composite": 7.0,
            "overstatements": ["x"] * overstatements,
            "verdict": {"unsupported": second},
        }

    rows = [row("pipeline", 1, 3.0), row("control", 1, 1.0)]
    assert with_claims(rows[0])["net_composite_2"] == pytest.approx(7.0 - 3.0 * 0.5)
    out = render("both", rows)
    second = [line for line in out.splitlines() if line.startswith("  second judge")]
    assert [line.split()[-1] for line in second] == ["+2.00", "-1.00"]

    del rows[1]["verdict"]
    out = render("partial", rows)
    assert "  second judge" not in out
    assert "judged 1 of 2 documents" in out


def test_the_command_judges_each_document_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for n in (1, 2):
        sample = tmp_path / "runs" / "s" / "job" / "pipeline" / f"sample-{n}"
        sample.mkdir(parents=True)
        (sample / "resume.md").write_text(f"resume {n}")
    judged = tmp_path / "runs" / "s" / "job" / "pipeline" / "sample-1" / "verdict.json"
    judged.write_text(json.dumps({"unsupported": 9.0}))

    args = argparse.Namespace(sweep_id="s", arms=None, jd=None, workers=1)
    with (
        patch.object(cli, "_load_narratives", return_value="history"),
        patch.object(judges, "run_verdict", return_value={"unsupported": 2.0}) as run,
    ):
        assert cli.cmd_verdict(args) == 0
    assert run.call_count == 1
    assert run.call_args.args[0].resume == "resume 2"
    assert json.loads(judged.read_text()) == {"unsupported": 9.0}
    written = judged.parents[1] / "sample-2" / "verdict.json"
    assert json.loads(written.read_text()) == {"unsupported": 2.0}
