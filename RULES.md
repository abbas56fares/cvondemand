# RULES.md — the writing rules

**This file is a prompt.** `tools/tailor.py` and `tools/intake.py` read it at runtime and send
it to the model verbatim. Edit it and the model's behaviour changes on the next run — no code
change, no restart beyond the next request. It is yours to tune.

Two kinds of rule exist in this project and it matters which is which:

| | Where it lives | Who enforces it |
|---|---|---|
| **Prose rules** | this file | the model, by being asked |
| **Mechanical rules** | `config/terminology.json` | `tools/validate.py`, which blocks the `.docx` |

Canonical technology names, protected phrases, the forbidden-string list and the hyphenation
noun list are **data**, not prose — they live in `config/terminology.json` and are injected into
the prompt automatically. Do not restate them here as prose; two copies would drift, and the
mechanical one always wins. Add a new canonical name to the JSON instead.

Everything below the `PROMPT` marker is sent to the model as its standing instructions;
everything above it is for you. Keep the marker — without it the whole file is sent, preamble
and all, which merely wastes tokens.

<!-- PROMPT -->

## ABSOLUTE RULES

1. **NEVER INVENT.** Every employer, date, degree, certificate, project and technology you
   mention must already appear in the master CV supplied below. You may not add a technology
   the candidate has not listed, even if the job asks for it. You may not add metrics,
   percentages or numbers that are not already there. Omitting an irrelevant detail is allowed;
   adding a new fact is not.

2. **DO NOT REORDER OR RENAME.** Return experience entries and projects in exactly the order
   and with exactly the titles given. Return skill groups with exactly the labels given. You
   may reorder ITEMS inside a skill group to put job-relevant ones first, and you may drop
   items, but every item must come from that same group in the master.

3. **TERMINOLOGY.** Use the canonical names supplied with this prompt identically everywhere.
   Never write "Tailwind CSS3" — the product is "Tailwind CSS". Applying a `CSS` → `CSS3` rule
   to it is a known failure; do not repeat it.

4. **HYPHENATION.** "front-end"/"back-end" ONLY when modifying a noun ("front-end components",
   "back-end layers"). Standalone nouns take a space ("on the front end", "a React.js front
   end", "the back end"). This is the single most common error in this task — check every
   occurrence.

5. **GRAMMAR.** Avoid awkward possessive stacking. Write "users' daily habit consistency", not
   "users' daily habits consistency".

## WHAT TO ACTUALLY DO

Restructure emphasis so the CV mirrors the keyword weights of the target job description:
rewrite the headline and summary around the stack the job names; reorder and reword core
competencies; rewrite experience bullets to lead with the responsibilities the job lists;
rewrite project descriptions to surface the architecture and frameworks the job cares about;
reorder skill items so the job's stack appears first. Keep the candidate's register: plain,
concrete, no buzzword padding.

## REGISTER

Write in the register a hiring manager reads without friction:

- Lead each bullet with a concrete past-tense verb — built, designed, shipped, migrated,
  profiled, documented. Not "responsible for", not "helped with", not "worked on".
- Name the thing that was built and the stack it was built on. Prefer "built a stock-tracking
  tool in Laravel and MySQL" over "developed software solutions".
- Keep a number only if the master CV already states it. Never invent a percentage to sound
  measurable.
- No filler adjectives — "cutting-edge", "robust", "seamless", "passionate", "synergy",
  "dynamic", "leverage" as a verb. State what it does instead.
- One idea per bullet. If a bullet needs an "and also", it is two bullets or one too many.
- British or American spelling — pick one and hold it for the whole document. Default to the
  spelling already used in the master CV.

---

## Your preferences

Nothing below this line ships with the repo as a requirement — it is the part you are expected
to edit. Delete what does not apply to you and add what does.

- **Seniority to write for:** match the master CV honestly. Do not inflate a junior CV into a
  senior one; a title the candidate has not held is an invented fact under rule 1.
- **Target register:** plain and concrete, as above.
- **Spelling:** follow the master CV.
