# resume-bench

A multi-stage resume tailoring pipeline, and the offline harness that measures
whether the staging actually helps.

The interesting part is not the pipeline. It is that the pipeline is scored
against a control, by judges that cannot see what would bias them, across a
corpus, with variance reported — so "did that prompt change help?" has an
answer other than an impression.

## The measurement

Every job description is run through two arms:

**Pipeline** — four staged model calls. A fit assessment reads the JD against
the candidate's ground-truth narratives and produces matches, gaps, and
terminology mappings. A generator writes a resume guided by that assessment,
emphasising matches and omitting hard gaps. A screener scores the draft from an
ATS perspective, seeing only the resume and the JD. A refinement pass acts on
the screener's findings without introducing claims the draft didn't make.

**Control** — one call. Same model, same narratives, same JD, same "write the
best resume you can" instruction, none of the staging. This is a genuinely hard
baseline; a strong single prompt is not a straw man, and a pipeline that cannot
beat one has not been shown to do anything.

Both arms are then scored by three judges.

### Judge isolation

Isolation is the load-bearing property, so it is enforced by types rather than
by care at the call site:

| Judge | Sees | Never sees |
|---|---|---|
| Cold read (per arm) | JD, one resume | the narratives, the other arm's resume |
| Authenticity | one resume, the narratives | the JD |

A cold-read judge that saw the narratives would stop scoring the document and
start scoring the candidate. One that saw both resumes would rank rather than
score, letting a weak control flatter the pipeline. An authenticity judge that
saw the JD would reward relevance, which the other judges already measure.

`ColdReadInput` and `AuthenticityInput` share no base class and have no field
for the thing they must not see, so contaminating either is a construction
error. `tests/test_judge_isolation.py` fails on a realistic contamination
refactor, including one that hides the leak inside a friendly-looking
`<candidate_context>` section — the payload test is an allowlist of permitted
sections, because a denylist only catches the leak someone thought to forbid.

### Scoring

Composite is `0.4 x jd_alignment + 0.2 x recruiter_readability + 0.4 x
authenticity`, each axis 0–10. **Hire intent is measured and reported but
excluded from the composite** — "would I call this person" is a different
question from "does this document do its job", and it is the noisiest axis.

Authenticity is length-normalised. The judge reports counts — claims checked,
untraceable claims, overstatements — and the score is computed in Python, so
the arithmetic is deterministic and the raw findings survive for analysis. The
rubric this replaced deducted a flat 2 points per untraceable claim from a
starting 10 with no relation to document length, which meant a longer resume
was penalised for being longer: a roughly 95%-accurate control resume took -11
and floored at 0, making the composite gap uninterpretable.

`n = 3` samples per arm per JD by default. LLM judges vary by roughly half a
point per axis on an identical document, so a single-sample delta between two
configs is not a result. Every mean in the report is printed with its spread.

## Results

<!-- TODO: populate from the first full sweep. Report aggregate only:
     N JDs, n per arm, per-axis mean +/- sd for both arms, per-JD W-L-T.
     Do not break results out per JD. -->

_Pending the first sweep under this harness._ Earlier scored runs exist but were
produced by a model executing the rubric by hand rather than by this code, and
are not reported here for that reason.

## A worked example: an input shape that broke a stage

One JD failed the fit assessment reproducibly. The stage returned a well-formed
tool call whose `terminology` array contained bare strings where the schema
declared objects, and the stage crashed reading `.get()` on a string.

The single variable was YAML frontmatter left on the front of the document by a
browser clipper. Zero of two runs succeeded with it; two of two succeeded
without. Two things came out of that:

**A tool's `input_schema` is advisory.** The API guarantees a well-formed tool
call, not that nested structures match their declared types. Anything reading
into a tool result needs to coerce rather than trust — see `dict_items` in
`pipeline/anthropic_utils.py`.

**Fix at the boundary, not at the read site.** Frontmatter is not job
description prose, so it is removed when a JD enters the corpus rather than
defended against at every stage that consumes one.

## Running it

```bash
cp .env.example .env                      # add your ANTHROPIC_API_KEY
cp input/narratives.example.md input/narratives.md   # then write your own history

uv run python -m cli list                 # JD slugs and existing sweeps
uv run python -m cli sweep --all --samples 3
uv run python -m cli report
uv run python -m cli compare <baseline-sweep> <candidate-sweep>
```

`compare` prints both sweeps and then states what differed between them —
prompts, models, or weights. When nothing differed it says so, because that
makes any score movement run-to-run variance rather than a result.

A sweep is minutes of wall clock and real API spend. It is a CLI and not an
HTTP endpoint on purpose: its audience is whoever is tuning prompts, and an
endpoint that triggers arbitrary batch model spend is a surface worth not
creating. Samples are idempotent — rerunning the same `--sweep-id` skips
anything already scored, so an interrupted sweep resumes.

Per-call traces land in `runs/<sweep>/<jd>/<arm>/sample-<n>/trace.jsonl`:
model, tokens, latency, stop reason, and the full request/response envelope.
A score tells you a run got worse; the envelope tells you why.

## Corpus and privacy

`jobs/` holds real job postings with company and product names redacted and
slugs reduced to seniority and discipline. The JD text is public; which
postings a particular candidate ran is not, and directory names alone disclose
it. Redaction defeats grep and casual browsing — it does not defeat someone in
the industry recognising a company from its own boilerplate.

`input/narratives.md` is gitignored and must stay that way. It is personal
career history, and it is also the ground truth the authenticity judge checks
against — which is why the corpus can be synthetic but the narratives cannot.
Replacing them with invented history does not make the harness less useful, it
makes every number it produces meaningless while still printing.

## Layout

```
config.py          models, paths, composite weights
corpus.py          JD loading
render.py          structured generator output -> markdown
telemetry.py       per-call JSONL tracing
pipeline/          the four stages
evaluation/        judges, control arm, sweep runner, report
prompts/           every prompt, versioned in git
jobs/              redacted JD corpus
input/             narratives (gitignored) + example
```

Prompts are files rather than database rows because a sweep result is only
interpretable if you can name the exact prompt text that produced it. Each
sweep records a content hash of every prompt in `runs/<sweep>/meta.json`,
alongside the models and composite weights. A commit SHA is not enough on its
own — prompts get edited between commits, and a SHA identifies the last commit
rather than the bytes that were sent.
