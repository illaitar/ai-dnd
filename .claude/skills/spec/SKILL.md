---
name: spec
description: >-
  Author or review a design spec to this repo's house standard. Every spec MUST carry a Mermaid
  block-scheme of the system and at least one fully-worked example traced end-to-end with concrete
  numbers/attributes. Use when writing a design spec to docs/superpowers/specs/ (after brainstorming
  settles the approach), or to review/upgrade an existing spec against the standard. Triggers:
  "write the spec", "spec this", "to our spec standard", "check this spec", "does this spec follow
  the standard".
---

# Spec (house standard)

Author and review design specs to this repo's standard. The full standard — principles, the required
section anatomy, the two mandatory elements, the review checklist, the copy-paste skeleton, and a
complete worked example — lives in **[spec-standard.md](spec-standard.md)** next to this file.

**Announce at start:** "I'm using the spec skill — writing to our spec standard."

## Before you start

1. **Read `spec-standard.md` in full.** It is the contract; this file is just the workflow around it.
2. **The approach must already be settled.** Specs are the *written artifact*, not the place to explore
   options — that is `brainstorming`'s job. If the approach isn't decided yet, stop and brainstorm
   first. If it is, proceed.

## Authoring a spec

1. Copy the **template skeleton** (spec-standard.md §6) and fill every section (§3 defines each).
2. **Ground it in real code.** Name seams as `file.py:123`. If you're unsure a seam exists, go read it
   — a spec built on guessed function names is worse than no spec.
3. **Draw the block-scheme** (§4a): a Mermaid `flowchart`, edges labelled with the transformation,
   *new* work marked distinctly from what already exists, every box mapping to a named seam.
4. **Trace at least one worked example** (§4b): named concrete inputs → a step table naming the
   function/rule and the value at each step → the final observable output → at least one boundary or
   failure case. Real, internally-consistent numbers.
5. **Run the review checklist** (§5) on your own draft; fix inline.
6. **Save** to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and commit (no Claude co-author).
7. **Hand to the user for review** before moving on: "Spec written to `<path>` — please review before
   we turn it into an implementation plan."

## Reviewing an existing spec

Given a spec (a path, or the current draft), check it against the §5 checklist and report gaps
specifically — quote the vague sentence, name the missing block-scheme or the example that has no
numbers, point at the placeholder. Offer to fix. Do not pass a spec that lacks a faithful block-scheme
or a fully-traced worked example — those are the two hard gates (§2).

## Where it sits in the flow

```
brainstorming        →   spec (this)        →   writing-plans        →   subagent-driven-development
(discover & decide)      (the written           (the implementation      (build it)
                          contract, to             plan derived from
                          this standard)           the spec)
```

`brainstorming` decides *what and why*; this skill fixes *how it's written down*, concretely enough
that `writing-plans` can turn it into tasks mechanically. Do not use this skill to make design
decisions — bring them in already made.

## Hard rules (from the standard)

- **Concrete over abstract** — real values, never "based on X." A sentence true of ten implementations
  is too vague.
- **Block-scheme mandatory** — ≥1 Mermaid flowchart of the system's data/control flow.
- **Worked example mandatory** — ≥1 case traced end-to-end with concrete numbers + a boundary/failure case.
- **No placeholders** — no `TBD`/`etc.`/`handle appropriately` in normative sections.
- **Name the seams; state non-goals; honor project constraints verbatim.**
