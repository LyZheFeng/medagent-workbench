---
name: literature-review
description: Use when the user asks for a literature review, survey of a medical topic, scoping review, or "what does the literature say about X" — searches PubMed/biomcp/paper-search connectors, screens studies through a PRISMA-style funnel, extracts data into a structured corpus, and writes a synthesis with an evidence table and PRISMA flow counts. Produces artifacts (corpus.csv, PRISMA counts, review.md), not just chat replies.
---

# Medical literature review

A reproducible mini-review: **search → screen → extract → synthesize**, with
every stage dropping an inspectable artifact in the workspace.

## 1. Protocol (before searching)

Write `review/protocol.md`: the PICO question, inclusion/exclusion criteria
(population, intervention, study designs, languages, date range), databases to
search, and the planned synthesis form (narrative / evidence table /
meta-analysis-feasible). Changing criteria mid-review goes into the protocol
changelog, not silently.

## 2. Search

Run each database via the connectors (biomcp, paper-search, pubmedmcp):

- Record for every source: exact query string, filters, date run, hit count →
  `review/search-log.md`
- Deduplicate by DOI/PMID (fuzzy title match as fallback, flagged for manual
  check)

## 3. Screening (PRISMA-style funnel)

Two stages, both logged to `review/screening.csv`
(`pmid,title,stage,decision,reason`):

1. Title/abstract screen against inclusion criteria
2. Full-text screen with a per-exclusion reason (wrong population, wrong
   design, no comparator, …)

Produce the PRISMA counts: identified → deduplicated → screened → full-text →
included. State clearly that screening was single-reviewer (agent) and
flag borderline decisions for the user.

## 4. Extraction

`review/corpus.csv`, one row per included study: citation (PMID/DOI), year,
country, design, N, population, intervention/comparator, outcomes with effect
sizes + 95% CIs, funding/conflict note, CEBM level. **Never estimate a number
"from memory" — every cell comes from the retrieved abstract/paper, or stays
empty with `?`.**

## 5. Synthesis

`review/review.md`: structured narrative organized by question sub-themes, the
evidence table, PRISMA flow numbers, heterogeneity notes, and limitations
(single-reviewer screening, language bias, publication risk). End with the
bottom-line answer to the PICO and its evidence strength.

## Boundaries

- Claims cite PMIDs; an uncitable claim is cut or marked as inference
- No meta-analysis pooling without checking heterogeneity and stating the
  model; when in doubt, present the table and stop
