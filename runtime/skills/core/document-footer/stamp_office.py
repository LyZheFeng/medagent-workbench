#!/usr/bin/env python3
"""Write the medical boundary into generated .docx / .xlsx files, stdlib CLI.

The app's own exports already carry the boundary; files an agent generates do
not. This script stamps the same statement into the document itself, so the
file still says what it is after it leaves the workspace. It is deliberately
mechanical: append the footer, write a copy or the file in place, and print one
```review block with the hashes before and after.

Usage:
    python stamp_office.py report.docx
    python stamp_office.py report.docx data.xlsx --check
    python stamp_office.py report.docx --out stamped/
    python stamp_office.py review/*.docx

Formats: .docx (footer of every section that has its own) and .xlsx (the
print footer of every sheet). Runs twice are a no-op: the marker sentence is
detected and the file is left byte-identical. PDF and .pptx are not covered;
images and DICOM are not documents and are out of scope.

Exit codes: 0 stamped or already stamped; 1 at least one file failed;
2 bad usage; 3 python-docx / openpyxl is missing.

(Console text is ASCII; the footer text itself is bilingual.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

GATE = "document-footer/stamp"
# Present in both the long docx text and the short xlsx footer; compared
# case-insensitively so a second run changes nothing.
MARKER = "not a medical device"
TEXT_EN = (
    "For research and teaching only - not a medical device, and not diagnosis "
    "or treatment advice for any individual patient. Every conclusion needs "
    "review by a qualified researcher."
)
TEXT_ZH = (
    "仅供科研与教学使用 - 不构成诊疗建议，也不是医疗器械；"
    "所有结论需由具备资质的研究者复核。"
)
SHORT = (
    "Research/teaching only. Not a medical device; no diagnosis or treatment "
    "advice. 仅供科研与教学，不构成诊疗建议。"
)
MAX_XLSX_FOOTER = 255


class StampError(Exception):
    """Input this script cannot stamp (unknown extension, unreadable file)."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_save(save, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=target.parent, suffix=target.suffix)
    os.close(handle)
    try:
        save(temp)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _import_docx():
    try:
        import docx
        from docx.shared import Pt
        return docx, Pt
    except ImportError:
        return None, None


def _import_openpyxl():
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        return None


def _write_docx_footer(footer, Pt) -> None:
    paragraphs = footer.paragraphs
    for text in (TEXT_EN, TEXT_ZH):
        paragraph = paragraphs[0] if (text == TEXT_EN and paragraphs
                                      and not paragraphs[0].text.strip()) \
            else footer.add_paragraph()
        run = paragraph.add_run(text)
        run.font.size = Pt(7.5)


def stamp_docx(docx_mod, Pt, source: Path, target: Path,
               check: bool) -> tuple[str, int, list[str]]:
    document = docx_mod.Document(str(source))
    warnings: list[str] = []
    changed = 0
    for index, section in enumerate(document.sections):
        footer = section.footer
        if index and footer.is_linked_to_previous:
            continue
        if any(MARKER in p.text.lower() for p in footer.paragraphs):
            continue
        _write_docx_footer(footer, Pt)
        changed += 1
    if not changed:
        return "already", 0, warnings
    if check:
        return "would-stamp", changed, warnings
    _atomic_save(lambda temp: document.save(temp), target)
    return "stamped", changed, warnings


def stamp_xlsx(openpyxl_mod, source: Path, target: Path,
               check: bool) -> tuple[str, int, list[str]]:
    workbook = openpyxl_mod.load_workbook(str(source))
    warnings: list[str] = []
    changed = 0
    for sheet in workbook.worksheets:
        existing = (sheet.oddFooter.center.text or "").strip()
        if MARKER in existing.lower():
            continue
        if existing:
            combined = f"{existing} | {SHORT}"
            if len(combined) > MAX_XLSX_FOOTER:
                warnings.append(
                    f"sheet {sheet.title!r}: the existing footer plus the "
                    f"boundary exceeds Excel's {MAX_XLSX_FOOTER}-character cap, "
                    "so the footer was replaced")
                combined = SHORT
            sheet.oddFooter.center.text = combined
        else:
            sheet.oddFooter.center.text = SHORT
        changed += 1
    if not changed:
        return "already", 0, warnings
    if check:
        return "would-stamp", changed, warnings
    _atomic_save(lambda temp: workbook.save(temp), target)
    return "stamped", changed, warnings


def process(path: Path, out_dir: Path | None, check: bool) -> dict:
    suffix = path.suffix.lower()
    if suffix not in {".docx", ".xlsx"}:
        raise StampError(f"{path.name}: only .docx and .xlsx are supported")
    if not path.is_file():
        raise StampError(f"{path.name}: no such file")
    target = (out_dir / path.name) if out_dir else path
    before = sha256(path)
    entry = {"path": str(path), "output": str(target),
             "kind": suffix.lstrip("."), "sha256_before": before}
    if suffix == ".docx":
        docx_mod, Pt = _import_docx()
        if docx_mod is None:
            raise StampError("python-docx is required (pip install python-docx)")
        action, count, warnings = stamp_docx(docx_mod, Pt, path, target, check)
        entry["footers"] = count
    else:
        openpyxl_mod = _import_openpyxl()
        if openpyxl_mod is None:
            raise StampError("openpyxl is required (pip install openpyxl)")
        action, count, warnings = stamp_xlsx(openpyxl_mod, path, target, check)
        entry["sheets"] = count
    entry["action"] = action
    entry["warnings"] = warnings
    entry["sha256_after"] = sha256(target) if not check else before
    return entry


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(
        prog="stamp_office.py",
        description="Append the medical boundary to .docx footers and .xlsx "
                    "print footers. Idempotent.")
    parser.add_argument("files", nargs="+", help=".docx / .xlsx files")
    parser.add_argument("--check", action="store_true",
                        help="report what would change; write nothing")
    parser.add_argument("--out", help="write stamped copies into this directory")
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code) if isinstance(exit_.code, int) else 2
    if ns.check and ns.out:
        print("error: --check writes nothing, so --out makes no sense with it",
              file=sys.stderr)
        return 2
    out_dir = Path(ns.out) if ns.out else None
    entries = []
    failed = False
    missing = False
    for name in ns.files:
        try:
            entry = process(Path(name), out_dir, ns.check)
        except (StampError, OSError) as e:
            failed = True
            if "required (pip install" in str(e):
                missing = True
            entries.append({"path": name, "action": "error", "error": str(e)})
            print(f"error: {e}", file=sys.stderr)
            continue
        entries.append(entry)
        detail = (f"{entry.get('footers', 0)} footer(s)" if "footers" in entry
                  else f"{entry.get('sheets', 0)} sheet(s)")
        print(f"{entry['action']}: {name} ({entry['kind']}, {detail})")
        for warning in entry["warnings"]:
            print(f"  warning: {warning}")
    print("```review")
    print(json.dumps({"gate": GATE, "check": ns.check, "files": entries},
                     ensure_ascii=False, indent=1))
    print("```")
    if missing:
        return 3
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))