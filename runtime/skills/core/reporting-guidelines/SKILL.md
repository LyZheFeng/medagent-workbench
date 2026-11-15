---
name: reporting-guidelines
description: Use when a medical manuscript, report or study write-up is being finished or reviewed — STROBE (observational), CONSORT (randomised trials), CARE (case reports), STARD (diagnostic accuracy) or PRISMA (systematic reviews). Runs a deterministic presence check for the items a submission cannot pass without (ethics approval, informed consent, registration numbers, confidence intervals, missing data, de-identification, participant flow, harms), names the official item number and checklist version behind each finding, and optionally checks that an item sits in the section the checklist puts it in. It reports which items the text does not mention; it never certifies compliance.
---

# Reporting-guideline check

Reporting checklists fail in one specific way: the study is fine and the write-up
silently omits the item the reviewer will ask for — no ethics statement, no
interval on the headline estimate, a flow diagram with no numbers in it. A model
asked to "check STROBE compliance" answers differently each time and invents
findings; a fixed list of patterns gives the same answer twice.

The gate answers **"does the text mention this item at all?"** — nothing more.
That is deliberately small, and it is the part that can be checked by machine.

## Run it

```bash
# The design is detected from the text (case report / trial / accuracy study /
# review / observational); force one when the text is ambiguous or in another
# language.
python "$XDG_CONFIG_HOME/opencode/skills/reporting-guidelines/check_report.py" report.md
python "$XDG_CONFIG_HOME/opencode/skills/reporting-guidelines/check_report.py" --design stard report.md
python "$XDG_CONFIG_HOME/opencode/skills/reporting-guidelines/check_report.py" --design consort manuscript.md supplement.md

# The checklist itself, for the "what is still missing" conversation.
python "$XDG_CONFIG_HOME/opencode/skills/reporting-guidelines/check_report.py" --list stard

# Also ask whether each item sits in the section its checklist puts it in
# (Methods, Results, …). A warning, and only when headings are recognised.
python "$XDG_CONFIG_HOME/opencode/skills/reporting-guidelines/check_report.py" --sections manuscript.md
```

It prints exactly one ` ```review ` fenced JSON block, the same contract the
reviewer agent uses: `level` (`error` for a required item, `warn` for a
recommended one), `tag` (`reporting · <design> · <item>`), `title`, `evidence`,
plus a `note` that says what was checked and what it does not prove.

## Which checklist, which number

Every finding names the official item behind it, with the version, because the
numbers move between versions: this gate cites **STROBE 2007**, **CONSORT 2025**
(with the CONSORT 2010 number beside it, which many journals' checklists still
use), **CARE 2013**, **STARD 2015** and **PRISMA 2020**. `--list <design>` prints
the official wording behind each cited number, so "which item is missing" and
"what does that item ask for" are one answer instead of two.

Three consequences worth knowing:

- A finding cites only the checklist of the design being checked. A CARE report
  gets CARE numbers, never STROBE ones.
- Where a checklist has no item for a check — CARE 2013 has no funding,
  conflicts-of-interest or data-availability item, STROBE 2007 predates the last
  two — the finding says it is a journal requirement instead of inventing a
  number that does not exist.
- The item numbers were checked against each checklist as published, and the
  gate's tests pin number, official wording and the checklist's item count
  together, so a renumbering cannot pass unnoticed. If a journal supplies its own
  checklist (a CONSORT extension, a Chinese translation), cite that one in the
  reply as well.

## What it checks

Common to every design: ethics approval or a waiver, informed consent,
confidence intervals on the estimates, limitations, funding, conflicts of
interest, data availability.

Per design — STROBE: design, setting with dates, eligibility, variables and
confounders, statistics, missing-data handling, participant flow, adjustment.
CONSORT: registration number, design, sequence generation, allocation
concealment, blinding, sample-size calculation, primary/secondary outcomes,
participant flow, ITT, harms. CARE: de-identification, demographics, history,
assessment, intervention, follow-up and outcome, timeline. STARD: reference
standard, index test and cutoff, the 2×2 table, **indeterminate results**,
sensitivity/specificity, ROC/AUC, flow, blinded readers, test interval. PRISMA:
protocol registration, databases with dates, full search strategy, eligibility
criteria, selection counts, risk of bias, heterogeneity, publication bias, flow
diagram.

Both languages are covered: a Chinese manuscript's 「伦理审批」「知情同意」「去标识」
satisfy the corresponding items, and mixed-language drafts are fine.

## Working the findings

1. A `missing` finding for an item that **is** in the submission but not in this
   file (a checklist, a supplement, a registered protocol) is correctly absent
   from this file and nothing needs writing — say so in the reply instead of
   padding the manuscript.
2. Otherwise add the item at the place a journal expects it: methods for ethics
   and consent, results for flow and intervals, a declarations block for funding
   and conflicts.
3. A `· section` warning (from `--sections`) means the sentence exists but sits in
   the wrong place — move it rather than writing a second one.
4. Re-run the gate; the finding disappears only when the text says the thing.

## Hard boundaries

- **Never report a pass.** The note already says a presence check is not a
  compliance verdict; do not contradict it with "the manuscript complies with
  STROBE". Report items that are missing, and items a human should verify.
- **It does not read tables well.** A 2×2 table written as a markdown table may
  or may not match `TP`/`FP`; a missing-cell finding there needs your eyes.
- **It cannot judge quality.** "We adjusted for confounders" satisfies the item
  and may still be wrong; hand that judgment to `stats-integrity` /
  `domain-check` and the reviewer agent.
- **`--sections` reads headings, not structure.** A manuscript with no recognised
  Methods/Results heading is existence-checked only, and the note says so. A
  section warning is a placement claim, never a completeness one.
- Do not run it on a papers-you-read (a published PDF); it is for manuscripts
  being written or audited, where "missing" is actionable.
- Never edit a finding's severity to make a document look finished.