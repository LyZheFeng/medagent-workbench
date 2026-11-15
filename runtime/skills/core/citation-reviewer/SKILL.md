---
name: citation-reviewer
description: Use when checking the citations of a medical manuscript, report, or review — verifying each reference exists and supports the claim it is attached to, detecting citation–claim mismatches, retracted papers, and fabricated DOIs/PMIDs. Ships citation_check.py, which resolves DOIs/PMIDs through Crossref and PubMed and reads retraction, expression-of-concern and erratum notices; the claim-support judgement stays with the model, which emits the findings list and never silently fixes references.
---

# Citation review (medical)

Medical reviews propagate: one mis-cited trial becomes ten downstream
"confirmed" claims. This check verifies each reference **against the claim it
supports**, not merely that it exists. The two halves are separate on purpose:
a script answers "does the record exist, and is it retracted?"; you answer "does
it support the sentence?".

## Run the script first

`citation_check.py` (next to this file, stdlib only) resolves every DOI/PMID
through Crossref and PubMed, reads PubMed's editorial notices, and writes one
```review``` block plus the annotated list.

```bash
python "$XDG_CONFIG_HOME/opencode/skills/citation-reviewer/citation_check.py" \
  --manuscript draft.md --out review/citation-check.md
python ... --refs refs.json                    # [{doi|pmid, label, claim}, ...]
python ... --doi 10.1016/S0140-6736(97)11096-0 --pmid 9500320
python ... --offline                           # cached lookups only
```

- `--refs` accepts a JSON list (or `{"references": [...]}`) or a `.txt` with one
  identifier per line (`doi:10.x`, `10.x`, `PMID: 123`, `123`).
- `--manuscript` scans a Markdown/plain-text draft for DOIs and **labelled**
  PMIDs (`PMID: 123`), keeping the line and heading. A DOI and a PMID on one
  line are checked separately and merge only if they resolve to the same record
  — prose often cites two papers in one sentence. Convert `.docx`/PDF to text
  first; there is no document parser here.
- Cache: `.openscience/citations/cache.json`, 7-day TTL, atomic replace;
  `--refresh` and `--max-age-days` change it. `--offline` reads only the cache
  and never opens a socket; a missing entry is `offline-miss`, not `ok`.
- Pacing: NCBI anonymous at 3 req/s (`NCBI_API_KEY` in the environment raises it
  to 10); Crossref at 1 req/s, or the polite pool with `--mailto` /
  `CROSSREF_MAILTO`. The key and the address never reach the cache, the review
  block or the Markdown file.
- `--strict` exits 1 when any finding is an error; exit 2 is bad input.

Statuses: `ok`, `retracted`, `concern`, `corrected`, `notice` (the identifier is
itself a retraction/erratum notice), `retraction-unknown` (DOI resolved but no
PMID, so PubMed's notices could not be read — **not** a pass), `unresolved`,
`offline-miss`, `lookup-failed` (transport error: unverified, not absent).

## Per-citation checks

For every citation in the document:

1. **Resolves?** The script: Crossref for the DOI, PubMed esearch
   (`10.xxxx[doi]`) for the PMID, EFetch for the record. A DOI that already has
   a PMID is cross-checked; a disagreement is an error, not a preference.
2. **Retracted or corrected?** The script, from PubMed's own fields
   (`Retracted Publication`, `RetractionIn`, `ExpressionOfConcernIn`,
   `ErratumIn`, `Retraction of Publication`, …). Crossref's `updated-by` is a
   cross-check only; an empty Crossref update list does not mean clean.
3. **Supports the claim?** You, reading the abstract (and the full text where
   it matters). Compare direction and population with the abstract's actual
   findings: swapped direction (trial showed harm, text says benefit), wrong
   population (adult RCT cited for a pediatric claim), wrong outcome, secondary
   finding promoted to headline. Each is a `mismatch` finding with the quoted
   claim and the abstract's sentence; abstract-only stays `needs-fulltext`.
4. **Appropriate class?** A narrative review cited where an RCT/meta-analysis
   exists and is retrievable is `upgrade-suggested`, not an error.

## Output

The script's ```review``` JSON is the machine contract (`refs`, `findings`,
`summary`, `note`, `warnings`) and `review/citation-check.md` is the readable
list. Add your own `mismatch` / `needs-fulltext` / `upgrade-suggested` findings to
that list, per citation: `[status] Author Year — finding — evidence`. Do not
present the script's `ok` as "supports the claim": it only says the record
resolved and no editorial notice was attached.

## Boundaries

- **The script is not the review.** It checks existence and editorial notices;
  whether the source supports the sentence, and whether it is the right study to
  cite, is yours. Say which references you read beyond the abstract, and mark
  the rest `needs-fulltext` rather than implying a pass.
- **A missing PMID is `retraction-unknown`.** PubMed is where the notices live;
  if the DOI resolves but no PMID does, the retraction status was not checked.
  Report it that way, never as clean.
- **Crossref is not the retraction authority.** Wakefield's DOI had an empty
  `update-to` in Crossref while PubMed carried both `Retracted Publication` and
  `RetractionIn` — this is why the script reads PubMed for status.
- The script compares Crossref and PubMed metadata; it cannot know what title the
  manuscript claims. A DOI resolving to a different paper is only caught when
  PMID and DOI disagree.
- Never rewrite a citation to make it fit; propose the correct replacement
  source and let the user decide.
- Do not run unprompted on ordinary analysis; it is a review-stage skill (used
  by traceability-review and the reviewer agent).