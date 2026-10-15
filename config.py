"""Runtime configuration, sourced from the environment.

The web app this pipeline came from read prompts and secrets from Postgres.
Here everything is files and environment variables: there is no database, no
request context, and no user scoping — a sweep is one operator on one machine.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
PROMPTS_DIR = ROOT / "prompts"
JOBS_DIR = ROOT / "jobs"
INPUT_DIR = ROOT / "input"
RUNS_DIR = ROOT / "runs"

# Stages and judges are versioned independently: a judge is deliberately allowed
# to be a different (usually stronger) model than the pipeline it scores.
PIPELINE_MODEL = os.environ.get("PIPELINE_MODEL", "claude-sonnet-5")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-sonnet-5")

# Composite weights. Hire intent is deliberately excluded: it answers "would I
# call this person", which is a different question from "does this document do
# its job", and folding it in would let one noisy gut-check axis dominate.
#
# Authenticity is excluded too, and enforced as a gate instead. It held 0.4 of
# the weight while carrying almost no document-level signal (ICC 0.31; 87% of
# documents at 9.5), because it measures something that should almost never
# vary: whether the resume fabricates. A guardrail earns its keep by rarely
# firing and a quality axis by spreading, and one number cannot do both. The
# remaining two axes keep the 0.4 : 0.2 ratio they were originally given.
WEIGHTS = {
    "jd_alignment": 2 / 3,
    "recruiter_readability": 1 / 3,
}

# A document scoring below this is rejected rather than averaged: it would not
# be sent, so it should not move an arm's quality means. 75 of 76 documents in
# the first full sweep cleared it. How often an arm is rejected is reported.
AUTHENTICITY_GATE = 8.5


def get_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key
