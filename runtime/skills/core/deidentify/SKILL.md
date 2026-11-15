---
name: deidentify
description: Use before writing or sharing a case report, case series, or any clinical text that carries patient details — replaces labelled names, record numbers, national IDs, phone numbers, emails, addresses and institutions with stable tokens, and shifts every date by one consistent offset. Runs a deterministic stdlib script and emits the app's review block. A rule-based first pass, not a guarantee of anonymity; images and DICOM metadata are not covered.
---

# De-identification (clinical text)

Direct identifiers in a case report are the one mistake that cannot be undone by
an erratum. This gate does the mechanical part — the part that can be done the
same way twice — and says plainly what is left for a human.

## Run it

```bash
python "$XDG_CONFIG_HOME/opencode/skills/deidentify/deidentify.py" case.md
# -> case.deid.md (work from this copy) + one ```review block with counts only

# Keep the mapping where patient data belongs — never in the workspace or an
# export. The copy and the mapping are different files; share only the copy.
python "$XDG_CONFIG_HOME/opencode/skills/deidentify/deidentify.py" draft.md \
  --out clean.md --mapping ~/private/case-map.json

# Report only, write nothing (for a draft you are not yet copying).
python "$XDG_CONFIG_HOME/opencode/skills/deidentify/deidentify.py" --check draft.md

# A fixed offset when you need the same shift across documents.
python "$XDG_CONFIG_HOME/opencode/skills/deidentify/deidentify.py" draft.md --shift-days 30
```

## What it replaces

- **Unlabelled:** 18/15-digit mainland ID numbers, mobile numbers, email
  addresses
- **Labelled** (the label is kept, the value becomes a token): 姓名, 姓名：
  张三, 患者：张三, 患者张三，男, `Name:`, `Patient John Doe`, 住院号 / 门诊号 /
  病历号 / 登记号 / MRN, 电话 / Tel / Phone, 住址 / Address
- **Institutions:** Chinese hospital / medical-school / CDC names, and English
  `… Hospital`, `… Medical School`, `… Institute`, `… Clinic`
- **Ages ≥ 90** become `≥90` (the CARE / journal convention)
- **Dates** all shift by one offset (`YYYY-MM-DD`, `YYYY/MM/DD`, `YYYY年M月D日`,
  `YYYY年M月`), so intervals inside the document are preserved. The offset is
  derived from the file's hash unless `--shift-days` is given.

The same value always gets the same token (`[NAME-1]`) within a document, and
the whole pass is deterministic: re-running it on the same file gives the same
copy and the same offset.

## What it cannot do

- **Not an anonymity guarantee.** An unlabelled name, a rare occupation, a
  distinctive tattoo or a combination of quasi-identifiers can still identify a
  patient. Read the copy before it leaves your hands.
- **It does not read images.** Burned-in identifiers and DICOM metadata must be
  removed with an imaging tool; the gate only sees text.
- **It does not judge consent.** Whether a case may be published is a separate
  question, answered on the title page (`[CONSENT-PENDING]` until it is).

## Output

Exactly one ` ```review ` fenced JSON block, the app's reviewer contract:
`findings` (one per identifier kind, with counts and token names — never the
identifiers themselves), and a `note` that says what was done and what it does
not prove. The copy itself is the deliverable.

## Working rules

- Work from the de-identified copy, not the original; keep the original where
  patient data belongs.
- Never put the mapping file in the workspace, an export, or a message. Losing
  it means the copy can no longer be re-identified — that is the safer failure.
- Images and DICOM are yours to clean; do not claim the document is
  de-identified on the strength of this gate alone.
- The gate replaces what it matches; it does not decide what *should* be
  published.