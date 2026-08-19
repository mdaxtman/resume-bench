"""Typed inputs and outputs for the three judges.

These types exist to make judge isolation structural. `ColdReadInput` has no
field for the narratives and `AuthenticityInput` has no field for the JD, so
contaminating either is a construction error rather than a silently wrong
number. They deliberately share no base class — a shared base is exactly how
the forbidden field gets reintroduced during a refactor.

See tests/test_judge_isolation.py.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColdReadInput:
    """What a blind recruiter judge sees: the JD and exactly one resume.

    Never the narratives (it would score the candidate, not the document) and
    never the competing arm's resume (each arm is scored on an absolute scale,
    so a weak control cannot flatter the pipeline by comparison).
    """

    jd: str
    resume: str


@dataclass(frozen=True)
class AuthenticityInput:
    """What the authenticity judge sees: one resume and the ground truth.

    Not the JD. Authenticity asks only "is this traceable?" — showing it the
    role invites it to reward relevance, which the other two judges already
    measure.
    """

    resume: str
    narratives: str


@dataclass(frozen=True)
class ColdReadScores:
    jd_alignment: float
    recruiter_readability: float
    hire_intent: float
    notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthenticityScores:
    """Raw findings plus the score derived from them.

    The judge reports counts; `authenticity` is computed in Python (see
    `evaluation.judges.authenticity_score`). Keeping the arithmetic out of the
    model makes it deterministic and auditable, and keeping the raw counts
    means the normalisation policy can change without re-running a sweep.
    """

    claims_checked: int
    untraceable: list[str]
    overstatements: list[str]
    authenticity: float
