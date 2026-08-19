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
WEIGHTS = {
    "jd_alignment": 0.4,
    "recruiter_readability": 0.2,
    "authenticity": 0.4,
}


def get_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key
