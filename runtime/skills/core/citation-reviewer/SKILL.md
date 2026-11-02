---
name: citation-reviewer
description: Use when checking the citations of a medical manuscript, report, or review — verifying each reference exists and supports the claim it is attached to, detecting citation–claim mismatches, retracted papers, and fabricated DOIs/PMIDs. Runs a deterministic per-citation check and emits a findings list; it never silently fixes references.
---

# Citation review (medical)

Medical reviews propagate: one mis-cited trial becomes ten downstream
"confirmed" claims. This check verifies each reference **against the claim it
supports**, not merely that it exists.

## Per-citation checks

For every citation in the document:

1. **Resolves?** DOI/PMID fetches via the connectors (pubmedmcp / paper-search /
   biomcp). An unresolvable DOI/PMID is a `critical` finding — likely fabricated.
2. **Retracted or corrected?** Check retraction status (PubMed retraction
   filters / editorial notes). A retracted source still cited as evidence is
   `critical`.
3. **Supports the claim?** Compare the claim's direction and population with
   the abstract's actual findings: swapped direction (trial showed harm, text
   says benefit), wrong population (adult RCT cited for pediatric claim),
   wrong outcome, secondary finding promoted to headline — each is a
   `mismatch` finding with the quoted claim and the abstract's sentence.
4. **Appropriate class?** A narrative review cited where an RCT/meta-analysis
   exists and is retrievable is an `upgrade-suggested` finding, not an error.

## Output

` ```review ` fenced JSON + a human-readable list, per citation:
`[status] Author Year — finding — evidence`. Statuses: `ok`, `mismatch`,
`unresolved`, `retracted`, `upgrade-suggested`. Summary counts at the end.
Write the full annotated list to `review/citation-check.md`.

## Boundaries

- Abstract-only judgment is provisional — mark claims needing full-text
  confirmation as `needs-fulltext` rather than passing them
- Never rewrite a citation to make it fit; propose the correct replacement
  source and let the user decide
- Do not run unprompted on ordinary analysis; it is a review-stage skill
  (used by traceability-review and the reviewer agent)
