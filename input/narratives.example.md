# Candidate Narratives

Ground truth. Every claim in every generated resume is checked against this
file by the authenticity judge, so it needs to be honest rather than flattering
— including the parts that make you look ordinary. A narrative that inflates
your scope produces resumes that inflate your scope and an authenticity score
that says they didn't.

Write in plain prose, not bullets. Say what the situation was, what you
personally did, what you did not do, and what happened. Ownership language
matters: "extended" and "architected" are different claims and an interviewer
will know which one is true.

Replace everything below with your own history and keep this file out of git.

---

## Career Overview

Twelve years building web applications, mostly frontend with periodic backend
work. Two stints at large companies and two at small ones. Strongest in design
systems and build tooling; weakest in data engineering, which I have touched
only through adjacent work.

---

## Example Corp — Senior Engineer (2021–2024)

**Component library consolidation**

Three product teams maintained three button implementations with different
accessibility behaviour. I proposed consolidating them, wrote the RFC, and got
agreement from the three tech leads over about six weeks of design review.

I built the new primitives — button, input, select, modal — and wrote the
codemod that migrated 140 call sites. Two other engineers migrated their own
teams' surfaces using it. I did not design the visual language; that came from
a designer who had already specced it before I joined.

Outcome: one implementation, keyboard and screen-reader behaviour tested once
instead of three times. I did not measure adoption beyond confirming the old
components were deleted.

**Build migration**

Inherited a Webpack 4 config nobody understood. Migrated to Vite over a quarter,
alongside feature work. Cold start went from roughly 90 seconds to under 10 —
measured on my own machine, not benchmarked properly across the team. The
migration broke SSR twice in staging and once in production for about 20
minutes.

---

## Additional Background (not employment — do not list as roles)

Self-directed projects, open source contributions, community work. Keep these
separate: the generator treats this section as supplemental and must not render
it as a job.
