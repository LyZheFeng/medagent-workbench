---
name: document-footer
description: Use after generating a .docx or .xlsx for the user - a case report, an exported table, a paper draft. Stamps the bilingual research/teaching boundary into the document's own footer (every .docx section that has one; every .xlsx sheet's print footer) with a stdlib script, and emits the app's review block. Idempotent - a second run leaves the file byte-identical. Does not cover PDF, .pptx, images or DICOM, and does not judge consent.
---

# Document footer (medical boundary)

The app's own exports carry the boundary; **files the agent generates do not**.
A case report handed to a colleague as `case.docx` must still say what it is
after it leaves the workspace, so the statement goes into the document itself
rather than into the chat around it.

## Run it

```bash
python "$XDG_CONFIG_HOME/opencode/skills/document-footer/stamp_office.py" report.docx
python ... report.docx data.xlsx
python ... review/*.docx --check          # report only, write nothing
python ... report.docx --out stamped/     # copies, original untouched
```

Use it **after** the document is final: rewording the footer afterwards is
possible, but the script's second run then leaves it alone only if the marker
sentence is still there.

## What it writes

- `.docx`: the footer of the first section and of every later section that has
  its own (a section linked to the previous one shares that footer). An existing
  footer is kept; the statement is appended below it.
- `.xlsx`: the centre section of each sheet's print footer. An existing print
  footer is kept and the statement appended, unless the combined text would
  exceed Excel's 255-character cap — then the footer is replaced and the script
  says so in `warnings`.

The text is bilingual on purpose: an exported document outlives the interface
language it was made in.

## What it refuses

- Anything that is not `.docx`/`.xlsx` (PDF and `.pptx` are not covered; a PDF
  needs a different tool and a `.pptx` footer is not a print footer).
- Exit `3` when `python-docx`/`openpyxl` is missing, with the pip line to fix
  it. The Windows installer bundles both.
- It does not decide whether the boundary is enough for a given journal or
  ethics board, and it does not touch consent or de-identification.

## Output contract

One ```review block:

```json
{"gate": "document-footer/stamp", "check": false,
 "files": [{"path": "report.docx", "output": "report.docx", "kind": "docx",
            "action": "stamped", "footers": 1,
            "sha256_before": "...", "sha256_after": "...", "warnings": []}]}
```

`action` is `stamped`, `already`, `would-stamp` (`--check`) or `error`. The
hashes are how a reviewer confirms that an `already` run changed nothing.