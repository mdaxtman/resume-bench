# resume-bench

[![check](https://github.com/mdaxtman/resume-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/mdaxtman/resume-bench/actions/workflows/ci.yml)

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
emphasizing matches and omitting hard gaps. A screener scores the draft from an
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

Composite is `2/3 x jd_alignment + 1/3 x recruiter_readability`, each axis
0–10. **Hire intent is measured and reported but excluded from the composite** —
"would I call this person" is a different question from "does this document do
its job", and it is the noisiest axis.

**Authenticity is a gate, not a term.** A document scoring below 8.5 is rejected
rather than averaged — it would not be sent, so it does not move an arm's quality
means — and how many documents each arm loses to the gate is reported alongside
them. Authenticity used to carry 0.4 of the composite; the reliability results
below are why it no longer does. The two remaining axes keep the 2:1 ratio they
had before.

**Unsupported claims are reported beside the composite, with a net composite.**
Each report counts a document's unsupported claims (an untraceable claim twice,
an overstatement once: the authenticity score's weights, not divided by length)
and prints a net composite, which is the composite less `CLAIM_COST` (0.5) per unsupported
claim. Both are derived at report time from the raw findings, as the gate is, so
any sweep on disk reads this way. The composite itself is unchanged. *What if an
unsupported claim cost something?* says why both are needed.

**Readability is scored in four parts** — opening, scannability, economy,
structure — and is their mean, computed in Python. The judge never reports a
holistic readability number. The single number it replaced sat at 6.0 for 80%
of documents, and nothing could say which property of a document held it there.

Results reported before *Does a shorter resume score better?* were produced under
the earlier scoring — `0.4 x jd_alignment + 0.2 x readability + 0.4 x
authenticity`, with holistic readability — and are not comparable with
numbers produced under this one.

Authenticity is length-normalised. The judge reports counts — claims checked,
untraceable claims, overstatements — and the score is computed in Python, so
the arithmetic is deterministic and the raw findings survive for analysis. The
rubric this replaced deducted a flat 2 points per untraceable claim from a
starting 10 with no relation to document length, which meant a longer resume
was penalised for being longer: a roughly 95%-accurate control resume took -11
and floored at 0, making the composite gap uninterpretable. The rate has the
opposite tilt, smaller: cutting well-supported bullets lowers it with nothing new
wrong, because the summary and skills keep their claims — about −0.13 at 800
words.

`n = 3` samples per arm per JD by default. LLM judges vary by roughly half a
point per axis on an identical document, so a single-sample delta between two
configs is not a result. Every mean in the report is printed with its spread.

## Results

The arm comparison below rests on two experiments, 126 scored documents, `n = 3`
samples per arm per job. Six later ones change it. The trim experiment — 304
documents — is under *Does a shorter resume score better?*; a fresh re-run of
both arms, after a fix that gave the generator inputs it had never received,
is under *Does the generator get what the fit stage found?*, and finds no
pipeline advantage at all; a bullet budget in the generator, under *Does a
bullet budget in the generator help?*, raises readability and restores a small,
unresolved lead. *What does the refinement stage do?* finds that lead is all
refinement's, that refinement gives a single prompt the same gain, and that
the gain carries a cost in unsupported claims. *Can refinement stop adding
claims?* finds the cost was the gain: refinement that adds no claims moves no
score, and without the claims the pipeline trails a single prompt. *Why does
the generator say less than a single prompt?* finds that the generator never
sees the posting and omits whatever the fit report files as a gap. Showing it
the posting, lifting its cap on skills and naming lighter work at its true
depth, all together, closes the gap to the single prompt, but adds unsupported
claims in 2 of 39 documents and is not kept. The gain turns out to be the
summary's comparison of the candidate to the employer's product: hold the
summary to the candidate's own work and the gain goes with it. *What if an
unsupported claim cost something?* re-ranks every version with a price on each
claim the narratives do not support. At that price the order reverses: every
version of the current pipeline and generator scores above the single prompt,
seven of the nine with an interval clear of zero. *Does the own-work generator
pass at a price per claim?* holds its skills list to what the narratives show.
It passes a rule fixed in advance by a margin of 0.004 and is now the
generator, but a fresh run puts it level with the old one. *The whole pipeline
with the new generator* finds the new pipeline level with the previous one and
ahead of the single prompt at a price per claim. *Does the claim count depend
on how the judge is asked?* finds that it does: every output format tried
changed what the authenticity judge counts. A second judge confirms that the
single prompt carries more unsupported claims than the pipeline, but not any
difference between two versions of the generator.

**Fresh sweep** — 13 job descriptions run end to end through both arms, 76
documents. **Archive re-score** — 50 previously generated documents, byte
identical to ones an earlier scoring pass had already graded, re-judged under
the length-normalised rubric. The second exists because a fresh sweep varies the documents
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

That is **85% of the measured advantage gone**, on documents that did not change
by a byte — the difference was entirely in how they were scored.

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

### Does redacting the corpus bias the comparison?

The job descriptions here have company and product names replaced. The pipeline
has a stage that exploits company identity — its fit assessment emits a
`product_connection` naming a parallel between the candidate's work and what the
company builds, and the generator is meant to write the summary's "why this
person here" sentence from it — though, as the correction below records, it
never received it. The control has no equivalent. So redaction plausibly removes a
pipeline-only capability and understates its advantage, particularly on hire
intent, which scores whether a document is specific and memorable.

Tested directly: four postings through both arms against their original
un-redacted text, prompts reverted by fingerprint to the state that produced the
main sweep, so redaction was the only variable.

```
un-redacted, 4 postings, n = 2      pipeline        control    delta
jd alignment                     8.12 ± 0.60    7.88 ± 0.78    +0.25
recruiter readability            6.12 ± 0.33    6.00 ± 0.50    +0.12
authenticity                     9.28 ± 0.15    9.36 ± 0.12    -0.08
hire intent                      7.38 ± 0.70    7.75 ± 0.66    -0.38
composite                        8.19 ± 0.24    8.10 ± 0.39    +0.09
```

Against the redacted run on the same four postings, the pipeline's hire-intent
delta moved from +0.25 to −0.38, and it moved in that direction on all four. The
fit stage did produce the field: `product_connection` was populated in 5 of 8
un-redacted runs against 4 of 12 redacted ones. It did not reach the generator.

**What this supports:** redaction is not costing the pipeline an advantage. The
worry was reasonable and the effect runs the other way on every posting tested.

**What it does not support:** any confident account of *why*. Sixteen documents
at two samples per cell, on integer-valued scores, is thin. The hire-intent gap
traces largely to one row — a control sample scoring 9.0 against its own
arm-mate's 8.0 — and dropping it halves the effect. One of the four per-posting
shifts was −0.17, inside the noise of a coarse scale.

There is a readable explanation in the documents, offered as a hypothesis rather
than a result: with the company named, the control's summary reorganised around
what that company does, leading with the candidate's agentic orchestration work
for an AI-tooling role, which the judge called "exactly the profile they are
hunting for". The pipeline's summary follows a fixed structure — who the
candidate is, the product connection, a recurring situation type — so
`product_connection` buys it one company-specific sentence while the control can
restructure the whole document. If that is right, the structure that makes the
pipeline consistent is also what caps it where being memorable is what scores.
Confirming it needs more postings, not more samples.

**Correction.** The generator never received `product_connection`, nor the fit
report's cultural signals, in this experiment or in any other run reported
before *Does the generator get what the fit stage found?*. `_format_fit_report`
forwarded matches, gaps and terminology only — a gap present since the first
commit. So the capability this experiment set out to protect was not operating.
The measurement stands as a description of the pipeline as it ran. The
explanation in the paragraph above does not: the pipeline's summary was never
written from a product connection, so it cannot have been capped at one
company-specific sentence by it. With the input now connected, the original
worry is live again — redaction may now remove something the pipeline uses —
and this experiment needs re-running.

### Is the instrument any good?

Every number above depends on judges that are themselves models. Re-scoring the
same document repeatedly separates two situations the aggregate cannot: a judge
that fails to discriminate, and documents that genuinely do not differ. ICC is
between-document variance over total variance — near 1 the axis measures the
document, near 0 it measures nothing.

Six documents, four repeats each:

```
axis                    between sd   within sd     ICC
jd alignment                  1.13        0.25    0.95
hire intent                   0.74        0.18    0.95
recruiter readability         0.37        0.18    0.81
authenticity                  0.18        0.27    0.31
```

This overturned a conclusion. Readability sat at 6.0 for 80% of documents, which
reads as a miscalibrated rubric — three of its ten points doing all the work. The
judge in fact reproduces its own score with a within-document sd of **0.18**, and
returned the identical value four times out of four on five of the six documents.
The compression is a property of the documents, not the rubric. Rewriting the
rubric would have manufactured spread and hidden a real finding about the
generator.

**Authenticity is the axis in trouble.** Its within-document variation (0.27)
exceeds its between-document variation (0.18), so it carries almost no
document-level signal — while holding 0.4 of the composite weight. The likely
explanation is benign: it was added to catch fabrication, and it sits at 9.5 for
87% of documents because fabrication is not happening. That is what a working
guardrail looks like. But a guardrail earns its keep by rarely firing and a
quality axis earns its keep by spreading, and one number cannot do both. It
belongs as a gate — reject below ~8.5, which 75 of 76 documents clear — rather
than as weight.

One known artefact, quantified rather than guessed at: **58% of documents draw an
explicit "typo" or "date error" complaint** for a current employment date the
judge reads as a future typo, one note proposing it was "possibly meant to be
2024". The penalty is small (−0.14 readability) and lands on both arms almost
equally (57% vs 59%), so no comparison here is distorted by it. The fix is to
state the current date in the judge prompt; the harness assumed a judge knows
when "now" is.

### What moved when the generator was tuned

Bullets averaged **28.8 words, under the stated 30-word cap**, and the judge
described them at every score level as "packed with multiple clauses each
covering architecture, tools, and impact simultaneously". The prompt constrained
words; the judge penalised clauses, and word count cannot distinguish a 28-word
bullet carrying one clause from a 28-word bullet carrying three. Obeying the cap
therefore bought nothing.

Four changes, each traceable to a complaint repeated across 76 documents: one
clause of mechanism per bullet; a 55-word summary cap, with a note that "2–3
sentences" is not a length constraint because three 35-word sentences reads as a
wall; expand internal shorthand or drop it; group the skills list.

Five job descriptions, three samples, pipeline arm only, same postings as the
baseline:

```
axis                        before         after    delta       t
recruiter readability   6.07 ± 0.44   6.60 ± 0.49    +0.53    3.13
hire intent (holdout)   7.33 ± 0.70   7.40 ± 0.71    +0.07    0.26
authenticity (guard)    9.40 ± 0.25   9.36 ± 0.27    -0.04   -0.43
composite               8.09 ± 0.31   8.16 ± 0.34    +0.06    0.54
```

Structurally the documents changed as instructed: summaries fell from 100 to 71
words, and bullets over the cap from 40% to 19%. The skills grouping had no
effect at all, for a structural reason rather than a prompt one — the generator's
output contract renders skills as a single joined string, so there is nowhere to
put a group.

**The holdout is the result.** Readability rose by half a point and hire intent
did not move. Hire intent is deliberately excluded from the composite and was not
tuned for, which makes it the check on whether an improvement generalises. It
says this one did not: the documents became measurably more scannable and no more
likely to earn a phone screen.

That is the intervention working as designed and being correctly bounded, not a
failure. Scannability and persuasiveness are different properties, and only one
of them was changed. The practical conclusion is that formatting is not the lever
for hire intent — worth knowing before spending further iterations on it.

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

Readability was **5.9 on both arms** before the generator change — "readable but
verbose" on this rubric — and the tuning result above is a before/after on the
pipeline arm alone, over 5 of the 13 postings. It is not a pipeline-versus-control
comparison and should not be read as one.

Every number reported here was produced before the judge prompts were given the
current date. That change removes a measured artefact and therefore makes future
runs incomparable with these; `compare` will report the prompt hashes as differing,
which is the intended behaviour rather than a defect.

The ICC figures come from six documents spanning readability 5.0 to 6.0. ICC is
sensitive to the range it is computed over, so these are lower bounds for axes
whose documents happen to cluster; nothing in the corpus scores above 7.0 on
readability, so the top of that scale is untested.

### Does a shorter resume score better?

Every document either arm had produced was 950–1,450 words with about 30
bullets. Length had never been varied, so the readability ceiling above could as
easily have been a property of the length as of the documents. `trim` tests
that directly: each of the 76 full-sweep documents is scored untrimmed and cut
to 800, 600 and 450 words by removing whole bullets — lowest-relevance first,
never rewording one. Wording is held fixed; selection and length vary. 304
documents, scored with readability in parts and authenticity as a gate. All 304
passed the gate.

```
both arms, delta vs untrimmed, paired by job (13), mean [95% CI]
                    800 words (-31%)      600 words (-48%)      450 words (-62%)
jd alignment       -0.04 [-0.21,+0.13]   -0.20 [-0.38,-0.02]   -0.54 [-0.73,-0.35]
readability        +0.20 [+0.09,+0.31]   +0.14 [-0.03,+0.31]   -0.27 [-0.46,-0.08]
  economy          +0.48 [+0.34,+0.62]   +0.76 [+0.58,+0.95]   +0.62 [+0.37,+0.86]
  scannability     +0.14 [+0.04,+0.24]   +0.10 [-0.09,+0.29]   -0.14 [-0.32,+0.04]
  structure        -0.04 [-0.23,+0.14]   -0.36 [-0.59,-0.14]   -1.25 [-1.53,-0.97]
hire intent        -0.01 [-0.17,+0.15]   -0.34 [-0.56,-0.12]   -0.86 [-1.12,-0.60]
keyword coverage   -0.6pp                -0.9pp                -2.6pp
composite          +0.04 [-0.10,+0.18]   -0.09 [-0.25,+0.08]   -0.45 [-0.63,-0.27]
```

**A third of every resume is free to cut, and nothing past that is.** At 800
words — thirteen fewer bullets — jd alignment and hire intent do not move, and
readability rises by a fifth of a point. Below that the cost appears and grows:
hire intent falls on 10 of 13 jobs at 600 words, and at 450 on 11 while rising
on none. The judges name the cause. Notes citing thin evidence go from 3 of 76
documents untrimmed to 8 at 600 words and 27 at 450. Both arms trace the same
shape separately.

**The peak is too flat to search for.** The best condition beats the untrimmed
document by +0.04 composite, inside an interval that spans zero. A search that
prunes bullets until a score peaks would be climbing a plateau: the only slope
this experiment can resolve points down.

**Readability's ceiling is the bullets, not the length.** Economy — whether every
bullet earns its place — is the part trimming is built to move, and it moves
most (+0.76 at 600 words). Untrimmed, the two lowest parts are economy (5.74)
and scannability (5.76) — whether each bullet reads at a glance. Trimming lifts
the first and cannot reach the second, because no bullet is reworded:
scannability stays between 5.6 and 5.9 in every condition, and at 800 and 600
words it is the lowest part. That is where the remaining headroom is, and it is
a writing problem rather than a selection one. For scale, the generator change
that targeted bullet shape moved readability +0.53 on the earlier ruler, more
than any length did here.

**The control part caught the judge's overall impression.** Removing bullets
should not raise scannability. The trim removed *shorter* bullets than it kept
(24.5 against 30.2 words), so a real change would run the other way — yet it rose
+0.14 at 800 words, on 7 of 13 jobs and down on none. Part of the readability
gain at 800 words is therefore the judge's impression of a shorter document
rather than a property of it. The economy gain is the part with a mechanism
behind it.

**What this does not show.** The trim keeps every role's dated header so the
timeline is intact, which leaves two or three roles per document with a header
and no bullets. Judges remark on that in 16 of 76 documents at 800 words and 29
at 450. A real 450-word resume would fold its oldest roles into one line, so part
of the structure decline at 600 and 450 words belongs to the method rather than
to length. The hire-intent and alignment declines do not — those notes cite
missing evidence. The relevance rater and the judges are the same model, which if
anything favours trimming. The sources are the full sweep's documents, generated
before the generator was tuned, and their ~100-word summaries are never trimmed.
One judgement per document.

**The readability parts are reliable.** Eight documents, four repeats each:
readability ICC 0.97 with a within-document sd of 0.13, against 0.81 and 0.18 for
the holistic score it replaced; each part 0.92–0.94. These documents span
readability 4.5–6.8, wider than the earlier 5.0–6.0, and ICC rises with range, so
the within-document sd is the fairer comparison.

**The arm comparison survives the new scoring.** The untrimmed condition is the
full sweep re-scored under the gate and readability parts. Pipeline minus
control, paired by job: composite +0.09 [−0.24, +0.41], keyword coverage +5.3pp
[−0.2, +10.9]. The same small, unresolved advantage as before, measured with
authenticity out of the composite rather than holding 40% of it. These are the
original documents; a fresh generation after the fit fix below finds none.

### Does the generator get what the fit stage found?

It did not, until this was written. The fit stage produces cultural signals and
a `product_connection`, and the generator prompt has a section for each — find a
real experience for every cultural signal; take the summary's second sentence
from the product connection. `_format_fit_report` forwarded matches, gaps and
terminology only, so both sections acted on inputs that never arrived, from the
first commit until this fix. Nothing failed: a missing section reads to the
model as an assessment that found none. The product repository carries the same
formatter and had the same gap.

With the inputs connected they visibly arrive: 26 of 39 fit reports carried a
product connection, and summaries now draw on it — for a defense-tech lead role,
"a close architectural parallel to a command-and-control (C2) interface". What
they do not do is move a score.

```
pipeline arm, before vs after the fix — 13 jobs, n = 3, paired by job
                    before    after    delta [95% CI]
hire intent           7.05     7.15    +0.10 [-0.19, +0.39]
jd alignment          7.64     7.59    -0.05 [-0.28, +0.18]
readability           6.35     6.26    -0.10 [-0.33, +0.13]
  scannability        5.97     5.77    -0.21 [-0.40, -0.01]
keyword coverage     60.4%    59.9%    -0.5pp
composite             7.21     7.15    -0.07 [-0.27, +0.14]
```

Hire intent — the axis a company-specific "why this person here" sentence is
aimed at — moved a tenth of a point inside an interval of ±0.3. Thirteen jobs
cannot see an effect smaller than that, so the honest statement is that the
mechanism is worth less than a third of a point if it is worth anything. That
fits what the job-level variance already showed: most of hire intent is the fit
between candidate and posting, which no sentence in the summary changes.

**The arm comparison, re-run from scratch.** With the fix in, both arms were
generated fresh and scored under the gate and readability parts.

```
fresh sweep, pipeline minus control — 13 jobs, n = 3, paired by job
composite           -0.02 [-0.15, +0.12]   record 5W-5L-3T
jd alignment        +0.03 [-0.15, +0.20]
hire intent         -0.10 [-0.31, +0.11]
  opening           -0.28 [-0.42, -0.14]   pipeline lower on 9 jobs, higher on none
  structure         -0.26 [-0.42, -0.09]   pipeline lower on 9 jobs, higher on 1
keyword coverage    +4.8pp [-2.5, +12.0]
```

The small composite lead every earlier comparison found is gone, and two
readability parts now favour the control. Both have candidate mechanisms in the
documents, offered as hypotheses rather than results. The control's summaries
run 90 words to the pipeline's 73, and opening is scored on the summary. And
the refinement stage rewrites the generator's `###` role headings as bold lines
in 36 of 39 documents, while all 39 control documents keep their headings;
structure is scored on how findable the roles and dates are.

Refinement also adds 72 words to the average document (range −22 to +221),
mostly trailing keyword clauses — "…, strengthening WCAG compliance" — on
bullets the generator was told to keep to one clause. That is plausibly where
the pipeline's keyword-coverage edge comes from, and plausibly part of what it
costs. The refinement stage is the next thing to test on its own.

### Does a bullet budget in the generator help?

The trim found a third of every resume free to cut, but it cut from outside,
verbatim, and left roles as empty headers. A shorter resume should come from the
generator. Two pilots showed it does not keep a length rule stated in its system
prompt: an 800-word cap moved drafts from 954 words to 891, and "at most 18
bullets" produced 25–28. What went in is a budget rule in the system prompt —
spend bullets by relevance, oldest roles get one, every role keeps one — with the
number restated as the last line of the request, the placement a three-call
probe found the generator mostly follows. The decision rule was fixed before the
sweep: keep it if readability rises while jd alignment and hire intent hold;
revert it if either falls.

```
pipeline arm, 18-bullet budget vs none — 13 jobs, n = 3, paired by job
                    none   budget    delta [95% CI]         jobs up/down
words               1032      822    -208
bullets             29.1     21.5    -7.6
jd alignment        7.59     7.63    +0.03 [-0.24, +0.29]    4/3
hire intent         7.15     7.24    +0.08 [-0.20, +0.35]    5/4
readability         6.26     6.49    +0.22 [+0.03, +0.42]    9/2
  opening           6.90     7.24    +0.33 [+0.10, +0.57]   10/2
  scannability      5.77     5.95    +0.18 [-0.05, +0.41]    8/2
  economy           5.77     6.13    +0.35 [+0.08, +0.61]   10/2
  structure         6.59     6.63    +0.03 [-0.24, +0.29]    5/4
keyword coverage   59.9%    58.6%    -2.2pp [-6.0, +1.7]
authenticity        9.60     9.46    -0.15 [-0.25, -0.05]    2/11
composite           7.15     7.25    +0.09 [-0.14, +0.32]    9/4
```

**It passes the rule, and the budget stays.** A fifth of every document goes,
readability rises by about what the 800-word trim found, and neither jd
alignment nor hire intent moves. Structure holds, as it did in the trim at this
length, and no role is left as an empty header.

**The budget works as pressure, not as a limit.** Only 4 of 39 drafts kept to
18 bullets. They average 20.4, against 26.6 without the budget, at the same 25
words a bullet. Refinement then adds about one more, where it added 2.5 without
the budget. A stricter number, or a check that returns an over-budget draft, is
the lever if a shorter document is wanted; nothing here says one is.

**Part of the readability gain is the judge's impression.** Economy has a
mechanism — fewer, more relevant bullets — and rose as it did under trimming.
Opening rose +0.33 with summaries the same length (73 words both ways), and the
trim moved opening +0.13 and +0.31 in its two arms without touching a summary.
The judge scores the opening partly on the document behind it. Read the gain as
economy plus the same halo the trim found.

**Authenticity falls, and most of the fall is arithmetic.** The score is a rate
— penalties over claims checked — and the summary and skills, which carry a
steady share of the overstatements, keep their length while bullets go.
Verbatim trimming to 800 words cannot introduce an overstatement and lowers the
score by the same amount: −0.13 in each arm, down on 12 and 11 of 13 jobs. What
remains is small. Overstatements of scope — "led", "sole", "owned", often where
the narrative says the team did it — rise +0.69 a document [+0.09, +1.29], on
10 of 13 jobs, but not in the generator's drafts: scored before refinement, the
budgeted drafts show +0.21 [−0.34, +0.75] and no change in overstatements
overall. The rise appears in refinement, which is where the next section finds
unsupported claims entering. Untraceable claims do not move (0.13 a document
either way). One document fell below the gate, at 8.42, and it holds four of
the sweep's five untraceable claims.

**Against the control, a lead reappears and stays unresolved.** The control
does not use the generator, so the budgeted pipeline pairs against the fresh
sweep's control directly: composite +0.07 [−0.16, +0.31], record 7W-4L-2T,
against −0.02 and 5W-5L-3T without the budget. The opening deficit is gone
(+0.05), partly through the same halo; economy now favours the pipeline by
+0.50 [+0.15, +0.85]. Structure still trails, −0.23 [−0.53, +0.07], which
leaves refinement's heading rewrite as the open suspect — confirmed in the next
section. The budgeted pipeline is 360 words shorter than the control.

### What does the refinement stage do?

Every pipeline sample keeps the generator's rendered draft and the screener's
report, so refinement can be removed or changed with the draft held fixed. Three
conditions on the budgeted sweep's 39 drafts, each paired with the same
document: the **draft** scored as is, with no screener or refinement; the
pipeline as it ran, **refined**; and **refined (fixed input)**, refinement re-run on the same
draft and screener report but given the rendered draft instead of its own
reformatting of the structured one. The pre-budget sweep's drafts were also
scored, as a replication of draft against refined. Decision rules, fixed
first: drop refinement if the draft holds composite, jd alignment, hire intent
and the gate; adopt the fixed input if it beats both other conditions.

```
draft -> refined, paired by job (13), mean [95% CI]
                     budgeted drafts         pre-budget drafts
jd alignment        +0.49 [+0.18, +0.79]    +0.74 [+0.40, +1.08]
hire intent         +0.31 [+0.05, +0.56]    +0.49 [+0.14, +0.83]
readability         -0.14 [-0.34, +0.06]    +0.00 [-0.15, +0.15]
  structure         -0.44 [-0.63, -0.25]    -0.18 [-0.28, -0.07]
keyword coverage    +12.6pp                 +13.0pp
words               +77                     +72
authenticity        -0.17 [-0.24, -0.10]    -0.09 [-0.17, -0.02]
composite           +0.28 [+0.04, +0.52]    +0.50 [+0.26, +0.73]
```

**Refinement is the pipeline's advantage — all of it.** Without it the pipeline
loses to the single-prompt control: the draft trails on jd alignment −0.44
[−0.74, −0.14], hire intent −0.33 [−0.64, −0.03] and keyword coverage −10pp,
for a record of 3W-9L-1T. The fit-guided generator writes a resume with fewer
of the posting's terms than one prompt does, and refinement more than makes up
the difference. The effect is the largest any experiment here has measured, and
it replicates on drafts written before the budget.

**It works by adding the posting's terms, and some of what it adds is not
true.** Coverage rises 12.6 points and the document 77 words. Refinement's
prompt forbids new claims and audits every ownership verb, yet it adds 1.31
overstatements a document [+0.88, +1.73]. The 78 drafts, across both sweeps,
carry no untraceable claim at all; every one in the refined documents entered
at refinement. They are of
two kinds: JD terms appended to the skills list ("AWS S3", "A/B testing",
"design component libraries") where the narrative mentions the thing only in
passing or not at all, and summary sentences that draw a parallel to the
target's product beyond what the narratives support. The scope overstatements
the budget section found rising also appear here and not in the drafts.

**The heading rewrite was the code, not the model.** Refinement received
`_format_resume_for_screener`'s reformatting of the structured draft, which
wrote each role as a bold line in the same weight as a project name, and it
copied that layout into all 38 documents whose draft had role headings. Given
the rendered draft instead, 38 of 39 keep them:

```
refined (fixed input) - refined, paired by job (13)
structure           +0.33 [+0.10, +0.57]   up on 7 jobs, down on none
composite           +0.09 [-0.14, +0.31]
jd alignment        +0.09     hire intent  +0.03     authenticity  -0.05
untraceable claims  +0.26 [-0.04, +0.55]   documents with any: 2 -> 7
```

Structure recovers; nothing else moves. Against the draft it wins on composite,
+0.37 [+0.21, +0.52]; against the original refinement, only on the structure
it was meant to fix. It is adopted as a fix rather than as an improvement:
refinement now edits the document the screener read. Untraceable claims are the
thing to watch. The rise is inside its interval, and two documents carry most of
it, but it points the same way as everything else refinement adds.

**Refinement works on any resume, and with it on both arms they tie.** The same
screener and refinement, applied to the 39 control documents:

```
paired by job (13)          control+refinement - control   pipeline - control+refinement
jd alignment                +0.31 [+0.05, +0.56]           -0.17 [-0.56, +0.22]
hire intent                 -0.10 [-0.31, +0.11]           +0.10 [-0.21, +0.42]
readability                 -0.10 [-0.23, +0.03]           +0.29 [+0.03, +0.56]
keyword coverage            +9.1pp                         -6.3pp
composite                   +0.17 [-0.02, +0.36]           -0.01 [-0.34, +0.31]
record                                                     5W-7L-1T
```

The control starts with more of the posting's terms (55% coverage against the
draft's 45%), so refinement has less to add, and adds it: +0.31 jd alignment.
Then the full pipeline and a single prompt plus refinement are indistinguishable
on composite, jd alignment and hire intent. The pipeline's one remaining edge is
readability, and that comes from the bullet budget, a rule in the generator's
prompt that the control prompt could carry as easily. By the rule fixed before
this ran, the fit assessment and the fit-guided generator do not earn their two
calls: the measurable value is a keyword pass that any draft can be given — and
the next section finds that the pass's value was the claims it added.

**What this does not show.** jd alignment is scored by a model reading the
posting, which is the axis most open to a document that repeats the posting's
terms; whether a recruiter rewards the added clauses as the judge does is not
measured here. The authenticity cost is measured, and in use it is the part an
interviewer would find. The control comparisons pair documents from two sweeps
generated under the same conditions, not from one. One judgement per document.

### Can refinement stop adding claims?

Refinement's prompt already said it "may not add experience, capabilities, or
claims". Its own change logs show how claims got in anyway, each entry noting
"no new claim": a posting's term attached to adjacent work, new skills and
category labels, new summary sentences, clauses that tie a bullet to a concern
of the posting. Many of the mappings come from the screener, which cannot see
the narratives and marks adjacent work as equivalent at confidence 0.8 or
higher — "an AI-generated DSL parsed into an AST" as "prompt engineering".

Two variants, run on the same 39 drafts and screener reports. The **strict
prompt** replaces refinement's instructions with a closed list of edits:
substitute a term only with a narrative sentence quoted as evidence, tighten
overstated claims, fix hygiene. The screener's mappings become suggestions to
check, everything else is ruled out, and the rule is restated as the last line
of the request. The **edit list** has refinement submit edits instead of a
resume, and code applies them, rejecting any that span lines, match more or
fewer than one place, grow their span by more than a few words, or quote
evidence that is not in the narratives. The rule, fixed first: a variant stops
adding claims if at most 1 of 39 documents carries an untraceable claim, its
overstatements are not demonstrably above the draft's, and all 39 pass the
gate. Of those that pass, the higher composite is kept, and on a tie the simpler.

```
same 39 drafts      overstatements   documents with an   gated   jd alignment vs draft   hire    composite
                    a document       untraceable claim
draft                    2.31               0              0       —                       —       —
previous prompt          3.46               7              2      +0.59 [+0.35, +0.82]    +0.36   +0.38
strict prompt            2.31               1              0      +0.00 [-0.22, +0.22]    +0.05   -0.03
edit list                2.13               2              0      -0.15 [-0.33, +0.02]    -0.03   -0.13
```

**The strict prompt stops it, and is kept.** Its overstatements match the
draft's exactly, one document in 39 carries an untraceable claim, and the gate
holds. It still edits — about four changes a document, 134 of 137 citing a
narrative sentence. The edit list misses the rule on untraceable documents,
trails the strict prompt on jd alignment and composite, and is the larger
change; it is in the history (`f1927fe`), not the code.

**With the claims gone, so is the gain.** Against the drafts it edits, the
strict prompt moves jd alignment +0.00, hire intent +0.05, composite −0.03.
Every point refinement added to jd alignment and hire intent arrived with the
claims it added. That is what the cold-read judge should do with them: it reads
the resume against the posting and, by design, never sees the narratives, so an
unsupported claim of a required skill reads to it as the skill. The authenticity
gate is the only check, and at 8.5 it passed 37 of the 39 documents that carried
the claims.

**The honest pipeline trails a single prompt.** With refinement adding nothing,
the pipeline scores as its draft does:

```
pipeline (strict refinement) - control, paired by job (13)
jd alignment        -0.44 [-0.73, -0.15]
hire intent         -0.28 [-0.58, +0.01]
composite           -0.24 [-0.46, -0.01]
```

The control is not winning the same way. Its overstatements per claim match the
draft's (7.1% against 7.5%); it makes more claims — 51 a document against 31 —
in a longer document, and covers more of the posting (55% of required keywords
against 45%). The fit-guided generator says less about the candidate than a
single prompt does. Why is a question for the generator, which is now where any
advantage would have to come from: screener and refinement cost two calls and,
made honest, move nothing measurable.

### Why does the generator say less than a single prompt?

Across the 13 postings there are 143 required keywords. Taking one sample of
each posting, the control has 20 of them that the budgeted draft does not.
Eleven of those 20 are terms that appear in the narratives *and* in the fit report's matches: the
generator was handed them and dropped them. HTML, CSS, REST and GraphQL are
typical, and the control carries each of them only in its skills list, which
runs to 53 items against the generator's "5-10 key skills". Most of the rest
are gaps. The fit stage is written to score fit strictly, and by a rough
count about half of its 204 gaps describe lighter work that is real. "Deep
GraphQL experience" is filed as a gap where the narratives describe support
work on an existing GraphQL layer. The generator omits every gap. The bullet budget is not the
cause: drafts covered 46.9% of required keywords before it and 45.1% after.
Some of the control's lead is stretching the generator refuses to do:
"Next.js-adjacent", "A/B-test-ready" and "GCP-adjacent" make three of its 39
documents untraceable.

Underneath both, the generator never saw the posting. It knew the posting
only through the fit report's paraphrase, while its request asked for "the
exact terminology from the JD". (It now reads the posting; see *Does the
own-work generator pass at a price per claim?*)

Three changes, each made alone and then all together, on the same 39 saved
fit reports. **jd**: the generator reads the posting. **skills**: the skills
list covers what the narratives show the candidate using that a reader of this
posting would look for, instead of 5–10 items. **gaps**: lighter-but-real work
is named at the depth the narratives give it, and only absent work is omitted.
The keep rule was fixed first: at most 1 of 39 documents with an untraceable
claim, overstatements per claim not demonstrably higher, 39/39 through the
gate, a jd-alignment gain whose CI excludes zero, and readability not
demonstrably lower. Each change is compared with a re-run of the unchanged
generator from the same session. That re-run lands within noise of the
original drafts (jd −0.13 [−0.46, +0.21]), and the verdict is the same against
either.

```
vs unchanged generator   jd alignment            hire     composite               coverage   documents with an
(paired by job, 13)                                                                          untraceable claim
unchanged (re-run)       —                       —        —                       —          1
jd                       +0.23 [-0.03, +0.50]    +0.08    +0.21 [+0.01, +0.42]    +3.4       5
skills                   -0.15 [-0.38, +0.07]    -0.08    -0.11 [-0.28, +0.06]    +2.3       0
gaps                     +0.03 [-0.23, +0.28]    +0.00    +0.01 [-0.18, +0.21]    +3.5       0
all three                +0.49 [+0.22, +0.76]    +0.38    +0.37 [+0.17, +0.58]    +5.5       2
```

**Together they close the gap to the single prompt; no one of them does.** All
three together raise jd alignment for 9 postings and lower it for none. Against
the control they leave jd alignment at −0.08 [−0.22, +0.07] and composite at
+0.04, with readability +0.28 [+0.14, +0.41], 16 fewer claims a document and one
fewer overstatement. The interaction has a plain reading. The skills and gap
changes both ask for what "a reader of this posting would look for", which a
paraphrase of the posting cannot answer, so they pay only once the generator
can see it.

**None is kept.** All three together carry 2 documents with an untraceable
claim against a limit of 1. Both are summary sentences built from the fit
report's `product_connection` ("closely paralleling Go's agent builder"), which
the current generator also receives. The posting alone does worse, with 5: the
posting's technologies written in as skills ("S3", "REST API design") and an
endpoint credited to the wrong stack. The skills change's wording, what "the
narratives show the candidate using", appears to be what keeps the posting's
terms out of the claims once all three run together. The experiment is in the
history (`ab130d1`, reverted in `f6a8396`).

**The gain was the comparison.** The current prompt asks the summary's second
sentence to name the employer's product and "the architectural parallel" to
the candidate's work, and with the posting in hand the generator names it from
there. One more condition ran all three changes with that sentence describing
only the candidate's own work, under the same rule. No summary compared, against
21 of 39 in all three, and nothing else differed: no draft needed a retry.

```
own work only, paired by job (13)   jd alignment            composite               overstatements a document
vs all three                        -0.36 [-0.57, -0.15]    -0.26 [-0.46, -0.07]    -0.67 [-1.18, -0.15]
vs current drafts                   +0.00 [-0.33, +0.33]    -0.02 [-0.30, +0.26]    -0.44 [-0.79, -0.08]
vs control                          -0.44 [-0.66, -0.21]    -0.22 [-0.40, -0.04]    -1.72 [-2.24, -1.20]
```

jd alignment falls for 10 postings and rises for 1, and the whole gain of the
three changes goes. The two judges disagree about the comparison. The cold-read
judge sees only the posting and the resume, has no way to check it, and
rewards it. The authenticity judge sees the narratives and often lists it as
an overstatement ("an interpretive stretch not grounded in the narrative"):
11 of all three's 99 overstatements are comparisons with the employer's work,
and none of this condition's 73. Without the comparison the
generator is more honest than the current one (overstatements per claim
−1.86 [−3.03, −0.70]) and scores no better. It still fails the rule, with 2 of
39 documents untraceable, both posting terms written into skills for one
posting: "AWS S3", which the narratives mention once as product behaviour, and
"Test-Driven Development", which they never mention. That makes three findings
of one kind. Refinement's gain was the claims it added, the control's lead
includes "-adjacent" stretching, and most of the generator's missing jd
alignment is a claim about the employer's product. The experiment is in the history
(`a8854d2`, reverted in `1dfcf78`).

**A draft whose tool call folded into its summary.** Five of 234 budgeted
drafts across six runs, and 4 of 39 before the bullet budget, arrived with the
rest of the tool call serialised into `summary`: `</summary>`, then
`<parameter name="experience">`, then the roles as raw JSON. The rendered resume had no role headings or no Skills section. The
schema requires both fields, but a tool's input schema is advisory. The
cold-read judge scored one of these 9.0 on jd alignment, and refinement repairs
the shape before the final resume is scored, so no sweep showed it. The
generator now rejects such a draft and retries, as the fit stage already did
(`23dd851`).

### What if an unsupported claim cost something?

Three results above have the same shape. Refinement's gain was the claims it
added. Part of the control's lead is "-adjacent" stretching. Most of the
generator's missing jd alignment is a comparison with the employer's product.
In each, jd alignment rose by saying things the narratives do not support. The
cold-read judge cannot tell, because it never sees the narratives. The
authenticity judge can, but its score is a gate at 8.5, and 3 of the 546
documents scored under the current judges have fallen below it, all from the
previous refinement prompt. Any other unsupported claim costs nothing in the
composite.

Where a version changed only its unsupported claims, the composite says what
each claim bought. Refinement's previous prompt against the strict one gains
+0.31 composite for 1.46 more unsupported claims a document, 0.21 a claim. All
three generator changes against the same changes with the summary held to the
candidate's own work gain +0.26 for 0.67 more, 0.39 a claim. Below that price a
benchmark prefers the bolder resume. `CLAIM_COST` is set at 0.5, above every
price measured, so no way of adding claims seen so far pays. Re-ranking needs
no new calls, because every scores.json keeps the findings. These are the
main versions scored under the current judges, 39 documents each, with the
three below the gate included:

```
version                              claims   unsupported   jd      composite   net composite
control (single prompt)               50.6       3.90       7.56      7.16          5.21
control + previous refinement         53.4       5.13       7.87      7.34          4.77
pipeline, previous refinement         34.2       3.87       7.62      7.24          5.30
pipeline, strict refinement (current) 30.6       2.41       7.13      6.93          5.72
draft, current generator              30.6       2.31       7.13      6.96          5.80
generator, all three changes          34.4       2.64       7.49      7.20          5.88
generator, own work only              32.7       1.97       7.13      6.94          5.95
```

```
paired by job (13), minus the control   composite               net composite           price that breaks even
pipeline, strict refinement (current)   -0.24 [-0.46, -0.01]    +0.51 [+0.05, +0.97]    0.16 a claim
generator, own work only                -0.22 [-0.40, -0.04]    +0.74 [+0.30, +1.18]    0.12
generator, all three changes            +0.04 [-0.07, +0.15]    +0.67 [+0.22, +1.12]    any price
pipeline, previous refinement           +0.07 [-0.16, +0.31]    +0.09 [-0.51, +0.68]    —
```

**Above about 0.16 a claim, the order reverses.** On the composite, the single
prompt beats the current pipeline. On the net composite at 0.5 a claim, the
current pipeline beats it, and so does every version of the current pipeline
and generator. Seven of those nine clear zero, including the current
generator's draft at +0.59 [+0.15, +1.03]. All three generator changes need no
price at all: against the control they match the composite and carry 1.26
fewer unsupported claims a document. The pipeline with the previous refinement prompt claimed as freely
as the control and is level with it either way.

**What the net composite does not settle.** At 0.5 a claim the penalty term
varies 1.75 times as much as the jd term, so the net composite is mostly a
count of unsupported claims. Its intervals are about twice as wide as the
composite's. The price itself is a judgement about how much a claim a
candidate cannot back up should cost. The table shows where each comparison
turns, so a different price can be read off it.

**How consistently the judge counts.** The reliability run above covered the
authenticity *score*, not the count the net composite charges. Ten documents
spanning the range of unsupported claims, drawn from the control, the current
draft, the own-work generator and the current pipeline, were each judged four
more times. Nine returned nearly the same count every time: within-document sd
0.20 claims, ICC 0.95. The tenth returned 6, 3, 2 and 8. The judge could not
settle whether one skills-list entry was untraceable, overstated or fine. That
entry was a cloud service the narratives mention only as where a product stored
its files. In one repeat the judge also listed the same bullet as both untraceable
and overstated. Across all ten documents the ICC is 0.68 and the within-document sd
is 0.78 claims. That is 0.39 of net composite on one document and 0.06 on a
version's mean of 39 documents, small beside the gaps between versions. The current
generator's 2.31 claims against the control's 3.90 go the same way on 12 postings
of 13.

**The judge also counts claims it has cleared.** Of the 1,568 findings on the
546 documents scored under the current judges, 7% carry the judge's own verdict
that the claim is fine: "not an overstatement", "excluded", "included here only
to confirm it was checked". The schema gives a claim that was checked and found
supported nowhere to go except `claims_checked`, so some of those claims end up
in the findings and are counted. The control carries the most, 0.26 a document
against the current pipeline's 0.13. With them matched by phrase and removed,
the generator's leads hold. The current pipeline's lead touches zero:

```
net composite minus the control     as counted              cleared findings removed
pipeline, strict refinement         +0.51 [+0.05, +0.97]    +0.44 [-0.01, +0.90]
generator, own work only            +0.74 [+0.30, +1.18]    +0.68 [+0.29, +1.06]
generator, all three changes        +0.67 [+0.22, +1.12]    +0.66 [+0.21, +1.11]
draft, current generator            +0.59 [+0.15, +1.03]    +0.56 [+0.15, +0.98]
```

Removing them makes the count less consistent, not more. On the repeats, the
judge lists the same doubtful claim every time and only sometimes adds that it
is fine. On the nine steady documents the within-document sd rises from 0.20 to
0.38 claims when the cleared ones are removed. Giving each finding a verdict
in the judge's output was tried next. It changed what the judge counts, not
only how it records it; see *Does the claim count depend on how the judge is
asked?*

The trim experiment reads differently under the net composite. Cutting the
control's resume to 600 words lowers its composite by −0.08 [−0.27, +0.12] but
removes 1.08 unsupported claims a document [0.80, 1.35], 13 postings of 13, and
raises its net composite +0.46 [+0.22, +0.70]. Cutting the pipeline's document
to 600 words removes a third as many, −0.35 [−0.87, +0.17], and its net
composite does not move.

### Does the own-work generator pass at a price per claim?

The own-work generator ranks first above, but it failed its rule on two
counts: no jd-alignment gain, and 2 of 39 documents with an untraceable claim.
Both untraceable claims were skills-list entries, and the skills lists held 6
of its 75 findings. Among them were a practice the posting asked for that the
narratives never mention, a cloud service they name only as where a product
stored its files, and a technology they say the candidate has not worked
with. One more condition held the skills list to what the narratives show.
Each entry must be something the narratives show the candidate working with.
The posting asking for it is not evidence. Neither is a narrative naming it as
part of a product, a system or another team's work. Light work may be listed
at that depth ("GraphQL (exposure)").

The rule was fixed before the run (`37fcd7f`) and asks the question the net
composite now asks. It allows at most 1 of 39 documents with an untraceable
claim and requires all 39 to pass the gate. Against the current drafts, the
net composite gain must have an interval clear of zero, and jd alignment must
not be demonstrably lower.

```
skills held to the narratives,   jd alignment            composite               unsupported claims      net composite
paired by job (13)
vs current drafts                +0.10 [-0.28, +0.48]    +0.06 [-0.24, +0.36]    -0.56 [-0.95, -0.18]    +0.34 [+0.00, +0.68]
vs unchanged generator (re-run)  +0.23 [-0.15, +0.61]    +0.19 [-0.09, +0.46]    -0.67 [-1.09, -0.25]    +0.52 [+0.20, +0.83]
vs own work only                 +0.10 [-0.12, +0.33]    +0.07 [-0.12, +0.27]    -0.23 [-0.61, +0.15]    +0.19 [-0.06, +0.44]
vs control                       -0.33 [-0.57, -0.10]    -0.15 [-0.31, +0.02]    -2.15 [-2.79, -1.52]    +0.93 [+0.57, +1.29]
```

**It passes, with almost nothing to spare.** Against the current drafts, the
lower bound of the net composite gain is +0.004. One document of 39 has an
untraceable claim: the same cloud-service entry, for the same posting, that the
judge could not settle when it judged one document four times. None falls below
the gate, and no summary compares the candidate with the employer. A slightly
different count would have failed it. With the findings the judge itself cleared
removed, the lower bound is −0.02, and the net composite rises for 8 postings
and falls for 4. Against the re-run of the unchanged generator the gain is
clear, +0.52 [+0.20, +0.83]. Against the single prompt the net composite is
higher on all 13 postings.

**Under the rule, it is now the generator.** The prompt changes are in
`prompts/generator.md`, the generator requires the posting, and the sweep
passes it. In the sections above, "current generator" means the version before
this one.

**Its advantage did not replicate.** It was adopted at the edge of its rule,
so a fresh run should be expected to fall back, and it did. A full pipeline
sweep generated 39 new drafts with it, from new fit reports (*The whole
pipeline with the new generator*). Against the previous generator's drafts,
the new drafts' net composite is +0.05 [−0.32, +0.43]. Against the run that
passed the rule it is −0.29 [−0.49, −0.08]. Under a second authenticity judge,
the run that passed carries no fewer unsupported claims than the previous
drafts: +0.13 [−0.80, +1.06]. The new generator is level with the old one, not
better. It stays because the whole-pipeline rule keeps it unless it is
demonstrably worse.

There is one side effect. The prompt's example, "GraphQL (exposure)", now
appears in 38 of 39 drafts. It appeared in 26 of 39 own-work drafts and 3 of 39
of the current drafts. The narratives support GraphQL at that depth, and no
finding concerns the skills entry. Still, the drafts are copying the example,
not choosing an entry for the posting.

### The whole pipeline with the new generator

A fresh sweep ran all 13 postings, 3 samples each, through the whole pipeline:
new fit reports, the new generator, then strict refinement. Its rule was fixed
before the run (`f5749f5`). The generator stays unless the new pipeline's net
composite is demonstrably below the previous pipeline's. Each new draft was
also scored before refinement.

```
paired by job (13)                   jd alignment            composite               unsupported claims      net composite
new pipeline vs previous pipeline    +0.10 [-0.24, +0.45]    +0.07 [-0.21, +0.35]    -0.10 [-0.53, +0.32]    +0.12 [-0.22, +0.46]
new pipeline vs control              -0.33 [-0.55, -0.12]    -0.17 [-0.33, -0.00]    -1.59 [-2.48, -0.70]    +0.63 [+0.14, +1.11]
refinement on the new drafts         +0.21 [-0.04, +0.45]    +0.14 [-0.05, +0.32]    +0.31 [+0.05, +0.56]    -0.01 [-0.18, +0.15]
```

**The new pipeline is level with the previous one, and the generator stays.**
Every difference between them is inside noise. Against the single prompt it
repeats the previous pipeline's result. Its composite is lower, −0.17. It
carries 1.59 fewer unsupported claims a document, on 12 postings of 13, and
its net composite is higher, +0.63 [+0.14, +1.11]. None of its 39 documents
fell below the gate.

**Refinement still buys its gain with claims.** On the new drafts it raises
jd alignment +0.21 and adds 0.31 unsupported claims a document. Its net
composite does not move. The strict refinement prompt was written to add no
claims (*Can refinement stop adding claims?*), and on the previous drafts it
added none that could be measured: +0.10 [−0.19, +0.39]. On these drafts it
adds them for 7 postings and removes them for 1.

### Does the claim count depend on how the judge is asked?

The authenticity judge's output has two lists, untraceable and overstated, and
7% of what it writes into them are claims it then clears in the same entry.
Three other output formats were tried on the ten documents from the
consistency check, each judged four times:

- a third list, `cleared`, after the two counted ones
- a `review` of every doubtful claim, written before the counted lists
- each finding carrying a verdict (untraceable, overstated or supported),
  written after its reason, with `supported` not counted

```
ten documents, four repeats       unsupported a document    control   others   within sd   ICC    r with the
                                                                                                  committed judge
committed: two lists              2.42                      3.50      2.16     0.78        0.68   —
two lists and `cleared`           1.90                      3.00      1.62     0.39        0.77   +0.67
`review` first                    2.65                      2.38      2.72     0.58        0.57   -0.33
a verdict on each finding         3.52                      4.12      3.38     0.94        0.35   +0.05
```

**Each format changed what the judge counts, not only how it records it.**
Wherever a cleared claim had somewhere to go, the judge used it as a worklog:
the verdict format withdrew 25 claims a document, and up to 40. That turns a
search for problems into a claim-by-claim audit, which judges differently.

- With a `cleared` list after the counted ones, the judge still wrote
  "retracted — see cleared" into the counted lists, 6 of 75 entries.
- Written first, the review cleared claims on a control document that the
  committed judge flagged on all four repeats. One of them it described as
  "could overstate scope", then left out of both lists. Across the ten
  documents its counts run against the committed judge's (r −0.33).
- The verdict format is the least consistent of the four.

The judges agree little document by document. The verdict judge's
counts correlate +0.38 with the committed judge's over 195 documents. So the
scoring judge was not changed, and every count on disk stays comparable.

**The verdict judge was kept as a second instrument instead.** It re-judged
the control, the previous drafts, the strict pipeline, the drafts that passed
the generator rule, and the new pipeline. The rule, fixed first (`f5749f5`):
unless the control carries demonstrably more unsupported claims than both
pipelines under it too, the net composite's lead over the single prompt is not
reported as a result.

```
control minus, paired by job (13)    unsupported claims, committed    unsupported claims, second judge
previous pipeline (strict)           +1.49 [+0.63, +2.34]             +1.62 [+0.56, +2.67]
new pipeline                         +1.59 [+0.70, +2.48]             +1.51 [+0.37, +2.66]
previous drafts                      +1.59 [+0.80, +2.38]             +1.46 [+0.22, +2.70]
drafts that passed the rule          +2.15 [+1.52, +2.79]             +1.33 [+0.26, +2.40]
```

**That the control carries more unsupported claims holds under both judges.**
The intervals clear zero under each, so the rule is met. The net composite's
lead is weaker under the second judge, because that judge is noisier. The new
pipeline's lead is +0.59 [−0.01, +1.18], and the previous pipeline's is +0.57
[−0.02, +1.17]. A difference between two versions of the generator does not
survive the change of judge. Any result that rests on one judge's claim count
should be checked against the other before it is acted on.

## Decisions this measurement implies

The results above changed what the scoring design should be. The first two
below have since been implemented (see *Scoring*); the rest have not. All are
recorded because the evidence for each is in the numbers, and because forgetting
why a change was warranted is how a harness drifts back toward measuring the
wrong thing.

**Authenticity belongs as a gate, not as 40% of a quality score.**
*Implemented.* Its ICC is 0.31 — within-document variation exceeds
between-document variation, so it carries almost no document-level signal —
while it holds the joint-largest weight in the composite. The likely explanation
is benign: it was added to catch fabrication, and it sits at 9.5 for 87% of
documents because fabrication is not happening. That is a working guardrail. But
a guardrail earns its keep by rarely firing and a quality axis earns its keep by
spreading, and one number cannot do both. As a gate it would reject below ~8.5,
which 75 of 76 documents clear.

**The composite is jd_alignment wearing a coat.** Variance contributed by each
weighted term: jd alignment 0.396, authenticity 0.108, readability 0.084. The
first is 4.7x the last. Every composite figure reported here is substantially a
jd_alignment figure, and the weights imply a balance the axes do not deliver.
Dropping authenticity and renormalising was tested arithmetically and moved the
t-statistic from 1.60 to 1.75 — marginally more sensitive, not decisive, because
removing a near-constant term rescales the delta and its error together.

**Readability may have a ceiling rather than a noise problem.** *Decomposition
implemented; the trim experiment locates the ceiling in bullet scannability, not
length.* The obvious inference from 80% of documents scoring 6.0 was a
miscalibrated rubric, and the reliability measurement contradicted it: the judge
reproduces its own score to within 0.18. So the compression is real. But nothing
in either corpus has ever scored above 7.0, so the top two bands are untested
and may be unreachable for documents of this class. Decomposing the single
holistic judgement into sub-criteria — opening strength, bullet uniformity,
section structure, time-to-key-fact — would produce spread arithmetically and
make a score diagnosable rather than merely reportable. What it must not do is
instruct the judge to "use the full range", which manufactures spread without
adding information.

**Resolving the composite comparison needs roughly 40 postings, not more
samples.** Between-job variation (sd 0.32) is more than twice the effect (+0.14).
`n = 3` already pins each posting's mean down well; the noise is between jobs.

**Three variables have never been varied.** `JUDGE_MODEL` is a separate setting
from `PIPELINE_MODEL` precisely so a judge can be a stronger model, and it has
only ever been run at parity. `call_model` disables extended thinking by default,
inherited from an interactive application where it made sense, and a judge
fact-checking every claim against 22k tokens of ground truth is exactly where it
might matter. And the narratives are 67% of every sweep's input tokens, identical
across all 351 calls of a full run — the shape prompt caching exists for, and
unused, because the code came from an application that ran one request at a time.

**A jd-alignment gain needs its overstatements read beside it.** The cold-read
judge cannot see the narratives — that isolation is the point of it — so a stage
that claims a required skill without support scores as if the candidate had it.
Refinement bought +0.38 composite that way, and the gate passed 37 of 39 of its
documents. Any change that raises jd alignment should be reported with its
paired change in overstatements and untraceable claims, and a gain that arrives
with more of either is unproven until a version without them keeps it.
*Implemented:* every report prints unsupported claims and a net composite, at
0.5 a claim, beside the composite (*What if an unsupported claim cost
something?*).

**A document's shape is checked in code, not by a judge.** The cold-read judge
read a resume whose summary held every role as raw JSON, with no role headings
below it, and gave it 9.0 on jd alignment and 7.0 on readability with no
mention of the markup. It reads for content. Whether a stage's output has the
fields and form it should is a validator's job, at the stage that produced it,
with a retry.

**A claim count needs a second judge before it decides anything.** The
authenticity judge counts claims it has itself cleared: 7% of its findings.
Giving each finding a verdict was tried in three formats. Each changed what the
judge counts, and the two judges agree on little at the level of one
document (*Does the claim count depend on how the judge is asked?*). The
scoring judge was left as it is. The verdict judge is kept as a second
instrument. Between the control and the pipeline, both judges agree. Between
two versions of the generator they do not, so a decision between close
versions should not rest on either judge's count alone. The verdict judge
lives outside the harness for now. It would need to become a command, so that
any comparison can be re-judged with it.

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
cp .env.example .env                                  # add ANTHROPIC_API_KEY
cp input/narratives.example.md input/narratives.md    # then write your own history
```

`ANTHROPIC_API_KEY` is the only required variable. `PIPELINE_MODEL` and
`JUDGE_MODEL` default to the same model and are separate on purpose — a judge is
allowed to be a different, usually stronger, model than the pipeline it scores.

### Generating and scoring

```bash
uv run python -m cli list                             # JD slugs and existing sweeps
uv run python -m cli sweep --all --samples 3          # both arms, whole corpus
uv run python -m cli sweep --arms pipeline --jd staff-swe-devtools-01 --samples 3
uv run python -m cli report --sweep-id <id>
```

`--arms` restricts a run to one arm, which is what makes a before/after on a
prompt change affordable: the control is unchanged, so there is no reason to pay
to regenerate it.

A sweep is minutes to hours of wall clock and real API spend, which is why it is
a CLI and not an HTTP endpoint. Its audience is whoever is tuning prompts, and an
endpoint that triggers arbitrary batch model spend is a surface worth not
creating. Samples are idempotent — rerunning the same `--sweep-id` skips anything
already scored, so an interrupted sweep resumes rather than restarts.

### Asking whether a result is real

```bash
uv run python -m cli compare <baseline-id> <candidate-id>
uv run python -m cli reliability --sweep-id <id> --documents 6 --repeats 4 [--authenticity]
uv run python -m cli coverage --sweep-id <id>
uv run python -m cli rescore --source <archive-dir> [--dry-run]
```

**`compare`** prints both sweeps and then states what differed between them —
prompts, models, or weights. When nothing differed it says so, which makes any
score movement run-to-run variance rather than a result.

**`reliability`** re-scores the same documents repeatedly and reports ICC per
axis. Run this before tuning anything: an axis whose within-document variation
rivals its between-document variation cannot detect a prompt change however large
the change is. With `--authenticity` it also re-runs the authenticity judge
and reports both the score and the count of unsupported claims the net
composite charges.

**`coverage`** computes literal keyword coverage over documents already on disk.
Terms are extracted once per posting, cached, and applied identically to both
arms. Only the extraction costs anything; the matching is pure.

**`trim`** takes the documents of an existing sweep and scores each untrimmed
and at several word budgets, removing whole bullets verbatim and never rewording
one — so selection and length vary while wording does not. `trim-report` prints
each condition and its delta against the untrimmed original, paired by job.

```bash
uv run python -m cli trim --source full-01 --sweep-id trim-01 --budgets 800 600 450
uv run python -m cli trim-report --sweep-id trim-01
```

**`rescore`** scores an existing archive of resumes under the current judges,
holding the documents fixed so that only the ruler varies. Documents are
anonymised first — any leading heading is stripped, because an archived baseline
that opens with its own arm label is not something a blind judge can be blind to.

### What a run leaves behind

```
runs/<sweep>/meta.json                    prompt hashes, models, weights, git state
runs/<sweep>/<jd>/<arm>/sample-<n>/
    resume.md          the scored document
    scores.json        per-axis scores and raw authenticity findings
    coverage.json      keyword coverage, if computed
    artefacts.json     fit report, screener report, pre-refinement draft
    trace.jsonl        every model call: tokens, latency, stop reason, full envelope

runs/<trim>/<jd>/<arm>-<budget>/sample-<n>/
    trim.json          budget, words, and every bullet removed with its rating
    relevance.json     per-bullet relevance ratings (untrimmed condition only)
```

The trace is what made a reproducible tool-call failure diagnosable at all. A
score tells you a run got worse; the envelope tells you why.

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
