---
name: case-report
description: Use when writing or structuring a clinical case report, case series, or CARE-guideline write-up — patient history, examination, diagnostics, treatment, follow-up, and discussion sections. Produces CARE-2021-aligned structure with de-identification checks and informed-consent reminders. Research writing aid only; never diagnoses or prescribes.
---

# Case report writing (CARE guidelines)

Structure and de-identification discipline for clinical case reports, following
the **CARE reporting checklist (2011/2021)**. The output is a research document,
not a clinical note.

## De-identification first

Before writing a word of clinical content, run the de-identification gate on
any draft that carries patient details (see the `deidentify` skill):

```bash
python "$XDG_CONFIG_HOME/opencode/skills/deidentify/deidentify.py" draft.md
```

Work from `draft.deid.md`; keep the mapping file (written only with
`--mapping`) where patient data belongs, never in the workspace. The gate is a
rule-based first pass, not an anonymity guarantee.

Then check what patterns cannot see:

- Unlabelled names, initials, rare occupations and distinctive details (a
  tattoo, a family business) — remove them yourself; the gate does not guess
- Prefer relative days ("day 3 of admission") when the calendar adds nothing;
  the gate's shift preserves intervals, but the dates are still false
- Images: remove or black out every identifier, including DICOM metadata burns;
  distinctive tattoos/birthmarks only with consent noted
- State the **informed-consent status** in the title-page footnote: written
  consent obtained / guardian consent / waived by IRB (with reference). No
  consent statement → the draft carries a `[CONSENT-PENDING]` marker that the
  traceability review will flag.

## CARE structure

Write into `case-report/report.md`:

1. **Title** — "XX: a case report" (the key diagnosis/symptom + design)
2. **Abstract** (structured: Why / What / How / Bottom line)
3. **Keywords**
4. **Introduction** — why this case is worth reporting (rarity, mechanism,
   clinical lesson); cite 2–3 recent reviews
5. **Patient information** — demographics, chief complaint, relevant history
6. **Clinical findings** — exam timeline
7. **Timeline** — a dated (relative-day) table of events, tests, interventions
8. **Diagnostic assessment** — differentials considered, workup, final
   diagnosis with supporting evidence
9. **Therapeutic intervention** — drugs (generic names, dose, route, duration),
   procedures, adverse effects
10. **Follow-up and outcomes** — visit intervals, objective outcomes
11. **Discussion** — mechanism, literature context (PubMed search documented
    with query + date), strengths/limitations, the **clinical lesson**
12. **Patient perspective** (when consented)
13. **Informed consent statement**

## Boundaries

- Every clinical claim in the discussion cites a retrievable source (PubMed
  connectors) — no textbook-memory assertions without a citation
- Treatment described is what happened, not a recommendation
- If the case is a series (n≥2), report per-patient then aggregate, per CARE
