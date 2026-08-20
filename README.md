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

Two experiments, 126 scored documents, `n = 3` samples per arm per job.

**Fresh sweep** — 13 job descriptions run end to end through both arms, 76
documents. **Archive re-score** — 50 previously generated documents, byte
identical to ones an earlier scoring pass had already graded, re-judged under
the current rubric. The second exists because a fresh sweep varies the documents
*and* the ruler at once and so cannot attribute a change to either.

### The measured advantage is small and not significant

```
fresh sweep            pipeline        control      delta
jd alignment        7.70 ± 1.08    7.49 ± 0.91      +0.21
recruiter readability 5.95 ± 0.40  5.77 ± 0.43      +0.18
authenticity        9.43 ± 0.21    9.41 ± 0.33      +0.02
hire intent *       7.27 ± 0.80    7.21 ± 0.73      +0.06
composite           8.04 ± 0.44    7.91 ± 0.44      +0.13
```

Paired by job — the unit of independence, since three samples of one posting are
not three trials — the composite delta is **+0.14, 95% CI [−0.03, +0.32]**,
positive on 8 of 13 jobs. The interval crosses zero. The honest statement is
*underpowered*, not *disproven*: between-job variation (sd 0.32) is more than
twice the effect. Resolving it needs roughly 40 postings, and more samples per
posting would not help, because the noise is between jobs rather than within
them.

### Most of the original advantage was the ruler, not the pipeline

An earlier scoring pass over 25 runs recorded a composite gap of **+0.93**.
Re-judging those same 50 documents under the current rubric gives **+0.14**.

```
                    old ruler   new ruler     swing
jd alignment            +0.39       +0.24     -0.15
recruiter readability   +0.52       +0.60     +0.08
hire intent             +0.60       +0.36     -0.24
authenticity            +1.78       -0.20     -1.98
composite               +0.93       +0.14     -0.79
```

Almost the entire collapse is one axis, and the absolute means locate it
precisely: the pipeline arm's authenticity barely moved (9.50 → 9.13) while the
control arm's rose **+1.61** (7.72 → 9.33).

The old rubric was not inflating the pipeline. It was penalising the control,
for two independent reasons that happened to point the same way. Deductions were
not normalised by document length while control resumes averaged 29% longer, so
a longer document accrued more deductions mechanically. And every archived
control resume opened with the literal line `# Control Resume`, so a judge
instructed to score blind could read the arm off line one.

Both are fixed here: authenticity is normalised against claims checked, judge
isolation is carried by types rather than instructions, and any leading heading
is stripped before a document reaches a judge.

### Where the advantage is real: literal keyword coverage

Every axis above is a model's judgement. This one is arithmetic — a term appears
in the document or it does not, and the answer is identical every time it is
computed. Terms are extracted once per posting by a call that sees only the
posting, then matched against both arms.

```
                   pipeline   control   per-JD delta        95% CI
fresh sweep (76)      61.0%     55.9%         +5.3pp   [-0.2, +10.9]
archive     (50)      59.4%     56.2%         +4.7pp   [+0.4,  +9.1]
```

The archive interval **excludes zero** (t = 2.36, 12 df). Two independent
document sets agree on direction and magnitude, and the effect is larger
relative to its noise than the composite the harness was originally built to
report.

This is the axis the pipeline is actually designed to move: its fit stage emits
terminology mappings above a confidence threshold and its generator is
instructed to use them, while the control prompt says nothing of the kind. It
was also the axis nothing was scoring. The screener stage computed keyword
coverage and discarded it, and the control arm never ran through the screener at
all.

### What these numbers do not show

The **delta** in keyword coverage is sound, because both arms are scored against
one identical extracted list. The **~60% absolute level** is not a finding: it is
bounded by extraction quality. Frequently missed terms fall into two groups —
ones the candidate narratives genuinely do not support, which no pipeline can
produce, and artefacts like `Frontend Software Engineer`, which is a title
rather than a searchable skill and counts as missing for both arms.

Keyword coverage is a proxy for one real mechanism: whether a document surfaces
in a recruiter's search over parsed records. It is not evidence about automated
rejection, which is rarer than commonly claimed, and it says nothing about parse
fidelity, which is the other way documents disappear.

The archive documents were generated against earlier prompts and earlier source
narratives, and their authenticity is judged against the current narratives. Both
arms are affected identically, which is what the comparison requires, but their
absolute scores are not comparable with the fresh sweep's.

Readability is **5.9 on both arms** — "readable but verbose" on this rubric. That
is not a finding about the pipeline; it is a finding about both, and the largest
quality gap either arm has.

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
