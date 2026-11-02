---
name: clinical-evidence
description: Use when the user asks a clinical question, requests evidence for a diagnosis/treatment/prognosis question, asks for a PICO-framed literature search, or wants an evidence table or evidence grading (Oxford CEBM / GRADE). Searches PubMed/biomcp connectors, frames the question as PICO, grades evidence, and produces a structured evidence table with citations. Never gives individual-patient treatment advice; outputs are research evidence summaries only.
---

# Clinical evidence synthesis

Turn a clinical research question into a **graded, citation-backed evidence
table**. This skill is for research and evidence synthesis — it is not a
clinical decision support tool, and its output must never be presented as
advice for an individual patient.

## Step 1 — Frame the question as PICO

Restate the request as PICO before searching anything:

- **P** — Population/Patient (disease, setting, demographics)
- **I** — Intervention (drug, procedure, test, exposure)
- **C** — Comparator (placebo, standard care, another test)
- **O** — Outcome (mortality, sensitivity/specificity, adverse events, QoL)

State the PICO to the user in one line; if any element is genuinely ambiguous,
ask one clarifying question before searching. Add a study-design filter when
implied by the question: therapy → RCT/systematic review; diagnosis →
cross-sectional accuracy studies; prognosis → cohort; harm → cohort/case-control.

## Step 2 — Search

Use the literature connectors in this order:

1. **biomcp** (if enabled) — PubMed articles, ClinicalTrials.gov trials,
   ClinVar/MyVariant variants. Best first pass for clinical questions.
2. **paper-search** — PubMed/medRxiv for preprints and broader coverage.
3. **pubmedmcp** — direct E-utils abstract retrieval for MeSH-aware queries.

Search both free-text and MeSH terms. Record the exact query strings and date
bounds in the output — the search must be reproducible. Prefer:

- Systematic reviews/meta-analyses (Cochrane when available)
- RCTs for therapy questions
- n-of-1 over narrative review when the question is narrow

## Step 3 — Grade the evidence

For each source record, assign an Oxford CEBM level (1–5) and, when a claim
will carry weight in the conclusion, a GRADE rating (High/Moderate/Low/Very
low) with the downgrading reasons spelled out (risk of bias, imprecision,
inconsistency, indirectness, publication bias).

## Step 4 — Produce the evidence table

Write `evidence/evidence-table.md` in the workspace:

| Citation (PMID/DOI) | Design & N | Population | Intervention/Comparator | Key outcome (effect size + 95% CI) | CEBM level | GRADE | Limitations |
|---|---|---|---|---|---|---|---|

Follow with a **Bottom line** paragraph: what the evidence supports, at what
strength, and what remains uncertain. Every number in the bottom line must
appear in the table and trace to a cited source.

## Hard boundaries

- **No individual-patient recommendations.** Phrase conclusions as "the
  evidence suggests…", never "you should…".
- **Never fabricate a citation.** If a claim has no retrieved source, say so.
- Dose, drug interactions, and guideline currency change — flag that the
  synthesis has a retrieval date and may go stale.
- Chinese output when the user writes Chinese; keep citation titles in their
  original language.
