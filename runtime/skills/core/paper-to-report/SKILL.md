---
name: paper-to-report
description: Use when the user adds a published paper (PDF) and asks for a summary, critical appraisal, journal-club write-up, or a plain-language report of it — extracts the paper, reconstructs its study design and results, appraises it against the design-appropriate reporting checklist, and writes a structured report citing the source. Distinguishes clearly between what the paper shows and appraisal/commentary.
---

# Paper → structured report

Turn an added paper (PDF in the workspace) into a critical appraisal report —
not a paraphrase. The deliverable is `reports/<paper-name>.report.md`.

## 1. Extract

Extract text (and tables) from the PDF into `reports/<name>.extract.md` with
page anchors. Record: title, authors, journal, year, DOI/PMID, funding
statement, and whether a protocol/registration (ClinicalTrials.gov NCT, PROSPERO)
exists — link it.

## 2. Reconstruct the study

One short section answering, from the paper itself:

- **Design & registration** — RCT / cohort / case-control / cross-sectional /
  case-report / systematic-review; preregistered? matches what was done?
- **PICO** of the paper
- **Primary endpoint** — exactly as pre-specified; note endpoint switching
- **Sample size** — planned vs analyzed; attrition
- **Key results** — effect sizes + 95% CIs for the primary endpoint, and the
  safety/secondary results the abstract led with

## 3. Appraise (design-appropriate checklist)

- RCT → CONSORT: randomization/allocation concealment, blinding, ITT vs
  per-protocol, CONSORT flow numbers sum
- Observational → STROBE: confounding handling, selection/information bias,
  missing data
- Systematic review → PRISMA: protocol, search reproducibility, risk-of-bias
  tool, heterogeneity
- Diagnostic accuracy → STARD: indeterminate results, spectrum of patients,
  blinded index test
- Case report → CARE: consent, de-identification, timeline

Grade the headline claim's evidence (CEBM level + GRADE with reasons). State
**funding/conflict posture** explicitly.

## 4. Report structure

`reports/<name>.report.md`: 摘要 (5 lines) → study reconstruction → appraisal
findings (numbered, each anchored to the extract with page) → bottom line
("this paper shows X at Y evidence strength; it does NOT show Z") → plain-
language paragraph when asked. Quote figures with page anchors; never invent a
number the extract does not contain.

## Boundaries

- The report separates **what the paper reports** from **your appraisal** —
  two clearly marked voices
- Statistics quoted must match the paper exactly (check CIs digit by digit)
- 批判性结论需要引用具体页码/章节,不使用"作者可能"式模糊表述
