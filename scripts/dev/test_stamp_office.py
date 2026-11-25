#!/usr/bin/env python3
"""Tests for the docx/xlsx compliance-footer stamper.

Run: python scripts/dev/test_stamp_office.py

python-docx and openpyxl are needed to build and inspect the fixtures; the
suites skip themselves on a machine without them (the gates CI installs
nothing). The byte-identical second-run checks are the contract: stamping an
already-stamped file must not rewrite it.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_ROOT = Path(__file__).resolve().parents[2]
_MOD = _ROOT / "runtime/skills/core/document-footer/stamp_office.py"
_spec = importlib.util.spec_from_file_location("stamp_office", _MOD)
assert _spec and _spec.loader
st = importlib.util.module_from_spec(_spec)
sys.modules["stamp_office"] = st
_spec.loader.exec_module(st)


def _have(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


HAVE_DOCX = _have("docx")
HAVE_XLSX = _have("openpyxl")


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = st.main(argv)
    return code, out.getvalue(), err.getvalue()


def review_of(stdout: str) -> dict:
    return json.loads(stdout.split("```review")[1].split("```")[0])


def file_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_docx(path: str, footer: str | None = None) -> str:
    from docx import Document
    document = Document()
    document.add_paragraph("A case report body.")
    if footer:
        document.sections[0].footer.paragraphs[0].text = footer
    document.save(path)
    return path


def docx_footer(path: str) -> str:
    from docx import Document
    document = Document(path)
    return " | ".join(p.text for s in document.sections
                      for p in s.footer.paragraphs)


def write_xlsx(path: str, sheets: int = 1, footer: str | None = None) -> str:
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active["A1"] = "value"
    for index in range(1, sheets):
        workbook.create_sheet(f"sheet{index + 1}")
    if footer:
        for sheet in workbook.worksheets:
            sheet.oddFooter.center.text = footer
    workbook.save(path)
    return path


def xlsx_footers(path: str) -> list[str]:
    from openpyxl import load_workbook
    return [(ws.oddFooter.center.text or "") for ws in load_workbook(path).worksheets]


class DocxFooter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_both_languages_reach_the_footer(self):
        path = write_docx(os.path.join(self.dir, "case.docx"))
        code, stdout, err = run_main([path])
        self.assertEqual(code, 0, err)
        text = docx_footer(path)
        self.assertIn("For research and teaching only", text)
        self.assertIn("仅供科研与教学使用", text)
        payload = review_of(stdout)
        self.assertEqual(payload["gate"], "document-footer/stamp")
        self.assertEqual(payload["files"][0]["action"], "stamped")
        self.assertEqual(payload["files"][0]["footers"], 1)

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_second_run_leaves_the_file_byte_identical(self):
        path = write_docx(os.path.join(self.dir, "case.docx"))
        self.assertEqual(run_main([path])[0], 0)
        before = file_hash(path)
        code, stdout, _ = run_main([path])
        self.assertEqual(code, 0)
        self.assertEqual(review_of(stdout)["files"][0]["action"], "already")
        self.assertEqual(file_hash(path), before)

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_an_existing_footer_is_kept(self):
        path = write_docx(os.path.join(self.dir, "case.docx"), footer="CONFIDENTIAL")
        self.assertEqual(run_main([path])[0], 0)
        text = docx_footer(path)
        self.assertIn("CONFIDENTIAL", text)
        self.assertIn("not a medical device", text.lower())

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_check_writes_nothing(self):
        path = write_docx(os.path.join(self.dir, "case.docx"))
        before = file_hash(path)
        code, stdout, _ = run_main([path, "--check"])
        self.assertEqual(code, 0)
        payload = review_of(stdout)
        self.assertEqual(payload["files"][0]["action"], "would-stamp")
        self.assertEqual(file_hash(path), before)
        self.assertEqual(docx_footer(path), "")

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_out_writes_a_copy_and_leaves_the_original(self):
        path = write_docx(os.path.join(self.dir, "case.docx"))
        before = file_hash(path)
        out = os.path.join(self.dir, "stamped")
        code, stdout, err = run_main([path, "--out", out])
        self.assertEqual(code, 0, err)
        copy = os.path.join(out, "case.docx")
        self.assertTrue(os.path.isfile(copy))
        self.assertIn("not a medical device", docx_footer(copy).lower())
        self.assertEqual(file_hash(path), before)


class XlsxFooter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    @unittest.skipUnless(HAVE_XLSX, "openpyxl not installed")
    def test_every_sheet_gets_the_footer(self):
        path = write_xlsx(os.path.join(self.dir, "data.xlsx"), sheets=2)
        code, stdout, err = run_main([path])
        self.assertEqual(code, 0, err)
        footers = xlsx_footers(path)
        self.assertEqual(len(footers), 2)
        for text in footers:
            self.assertIn("Research/teaching only", text)
            self.assertIn("不构成诊疗建议", text)
        self.assertEqual(review_of(stdout)["files"][0]["sheets"], 2)

    @unittest.skipUnless(HAVE_XLSX, "openpyxl not installed")
    def test_second_run_leaves_the_file_byte_identical(self):
        path = write_xlsx(os.path.join(self.dir, "data.xlsx"))
        self.assertEqual(run_main([path])[0], 0)
        before = file_hash(path)
        code, stdout, _ = run_main([path])
        self.assertEqual(code, 0)
        self.assertEqual(review_of(stdout)["files"][0]["action"], "already")
        self.assertEqual(file_hash(path), before)

    @unittest.skipUnless(HAVE_XLSX, "openpyxl not installed")
    def test_an_existing_footer_is_kept(self):
        path = write_xlsx(os.path.join(self.dir, "data.xlsx"), footer="Page &P")
        self.assertEqual(run_main([path])[0], 0)
        self.assertIn("Page &P", xlsx_footers(path)[0])


class CliContract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_unknown_extension_is_refused_not_ignored(self):
        path = os.path.join(self.dir, "notes.txt")
        Path(path).write_text("x", encoding="utf-8")
        code, stdout, err = run_main([path])
        self.assertEqual(code, 1)
        self.assertIn("only .docx and .xlsx", err)
        self.assertEqual(review_of(stdout)["files"][0]["action"], "error")

    def test_missing_file_is_an_error(self):
        code, _, err = run_main([os.path.join(self.dir, "nope.docx")])
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)

    def test_no_files_is_a_usage_error(self):
        self.assertEqual(run_main([])[0], 2)

    def test_check_and_out_together_are_refused(self):
        code, _, err = run_main(["x.docx", "--check", "--out", "somewhere"])
        self.assertEqual(code, 2)
        self.assertIn("--check writes nothing", err)

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_missing_python_docx_is_exit_three(self):
        path = write_docx(os.path.join(self.dir, "case.docx"))
        with mock.patch.object(st, "_import_docx", return_value=(None, None)):
            code, _, err = run_main([path])
        self.assertEqual(code, 3)
        self.assertIn("python-docx is required", err)

    @unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
    def test_printed_output_survives_a_gbk_console(self):
        path = write_docx(os.path.join(self.dir, "case.docx"))
        code, stdout, stderr = run_main([path])
        (stdout + stderr).encode("gbk")


if __name__ == "__main__":
    unittest.main(verbosity=2)