#!/usr/bin/env python3
"""Tests for the reporting-guideline gate (runtime/skills/core/reporting-guidelines).

Run: python scripts/dev/test_reporting_guidelines.py
Stdlib unittest only. Each case is a sentence-level fixture: the point of the gate
is that the same text produces the same findings twice, so the fixtures are
written to be boring rather than realistic.
"""
import importlib.util
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_MOD = (
    Path(__file__).resolve().parents[2]
    / "runtime/skills/core/reporting-guidelines/check_report.py"
)
_spec = importlib.util.spec_from_file_location("check_report", _MOD)
assert _spec and _spec.loader
cr = importlib.util.module_from_spec(_spec)
sys.modules["check_report"] = cr
_spec.loader.exec_module(cr)


def write(d, name, body):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    return p


def tags(result):
    return {f["tag"] for f in result["findings"]}


def levels(result):
    return {f["level"] for f in result["findings"]}


COMPLETE_STROBE = """\
# Cohort study of readmission after discharge

We performed a retrospective cohort study in two hospitals, conducted between
January 2019 and December 2021 (setting and study period).

Eligibility: adults admitted with heart failure; exclusion: prior transplant.
Outcome: 30-day readmission. Exposure: discharge on a weekend. We adjusted for
age, sex and comorbidity with multivariable logistic regression.
Missing data were handled by complete-case analysis.
Effect: adjusted OR 1.31 (95% CI 1.04 to 1.66) — see the participant flow diagram.
Ethics approval: the institutional review board of Hospital A approved the study
(IRB 2019-042). Informed consent was waived for this retrospective review.
Funding: none. Conflicts of interest: none declared. Data availability: the
analysis dataset is available from the corresponding author on request.
Limitations: single-region cohort, residual confounding likely.
"""

COMPLETE_CONSORT = """\
# Randomised controlled trial of early mobilisation (NCT01234567)

Design: parallel-group randomised controlled trial, 1:1 allocation.
Randomisation: computer-generated sequence in blocks, allocation concealment by
central randomisation. Blinding: outcome assessors were blinded (single-blind).
Sample size calculation targeted 220 participants for 80% power.
Primary outcome: ICU length of stay. Secondary outcome: 28-day mortality.
Participant flow: 410 screened, 220 assigned to the intervention or control group.
Analysis: intention-to-treat, with a per-protocol sensitivity analysis.
Harms: adverse events were recorded in both arms and did not differ.
Effect: HR 0.82 (95% CI 0.66 to 1.02). Ethics approval: hospital ethics committee
(2020/17). Informed consent: written consent from each participant or their proxy.
Funding: a national grant. Conflicts of interest: none. Data availability: on
request. Limitations: single centre, unblinded intervention delivery.
"""


class Detection(unittest.TestCase):
    def test_designs_are_detected_from_the_text(self):
        cases = [
            ("This systematic review followed PRISMA.", "prisma"),
            ("A randomised controlled trial of two drugs.", "consort"),
            ("We describe a case report of a rare tumour.", "care"),
            ("A diagnostic accuracy study of a novel index test.", "stard"),
            ("A retrospective cohort study of readmission.", "strobe"),
            ("", "strobe"),
        ]
        for text, expected in cases:
            self.assertEqual(cr.detect_design(text), expected, text)


class Findings(unittest.TestCase):
    def test_a_complete_cohort_report_passes(self):
        d = tempfile.mkdtemp()
        p = write(d, "cohort.md", COMPLETE_STROBE)
        result = cr.run([p], None)
        self.assertEqual(result["findings"], [], tags(result))

    def test_a_complete_trial_report_passes(self):
        d = tempfile.mkdtemp()
        p = write(d, "trial.md", COMPLETE_CONSORT)
        result = cr.run([p], None)
        self.assertEqual(result["findings"], [], tags(result))

    def test_missing_ethics_consent_and_intervals_are_errors(self):
        d = tempfile.mkdtemp()
        body = """\
A retrospective cohort study of readmission in one hospital, 2019 to 2021.
Eligibility: adults; exclusion: none. Outcome: readmission. We used multivariable
logistic regression and complete-case analysis for missing data.
The adjusted OR was 1.31 for weekend discharge.
"""
        p = write(d, "thin.md", body)
        result = cr.run([p], None)
        found = tags(result)
        self.assertIn("reporting · strobe · ethics", found)
        self.assertIn("reporting · strobe · consent", found)
        self.assertNotIn("reporting · strobe · design", found,
                         "the fixture does name the design (cohort)")
        errors = {f["tag"] for f in result["findings"] if f["level"] == "error"}
        self.assertIn("reporting · strobe · ethics", errors)
        self.assertIn("reporting · strobe · ci", errors,
                      "no confidence interval anywhere in the text")

    def test_chinese_case_report_is_checked(self):
        d = tempfile.mkdtemp()
        body = """\
# 病例报告:一例罕见的药物性肝损伤

患者,男,54 岁,因乏力两周就诊。既往史无特殊,查体见轻度黄疸。
实验室检查提示转氨酶升高,影像学除外胆道梗阻。
予停用可疑药物并保肝治疗,两周后随访转氨酶恢复正常。
已获得患者知情同意。伦理审批号 2024-118。
"""
        p = write(d, "case.md", body)
        result = cr.run([p], None)
        found = tags(result)
        self.assertIn("reporting · care · deidentification", found,
                      "Chinese case report without de-identification must be flagged")
        self.assertNotIn("reporting · care · consent", found)
        self.assertNotIn("reporting · care · demographics", found)

    def test_forced_design_overrides_detection(self):
        d = tempfile.mkdtemp()
        p = write(d, "cohort.md", COMPLETE_STROBE)
        result = cr.run([p], "prisma")
        self.assertTrue(result["findings"], "a cohort report judged as PRISMA must fail")
        self.assertTrue(all("prisma" in f["tag"] or f["tag"] == "reporting · ci"
                            for f in result["findings"]), tags(result))

    def test_output_contract(self):
        d = tempfile.mkdtemp()
        p = write(d, "thin.md", "A cohort study with nothing else in it.\n")
        result = cr.run([p], None)
        self.assertIn("note", result)
        self.assertIsInstance(result["findings"], list)
        for finding in result["findings"]:
            self.assertEqual(set(finding), {"level", "tag", "title", "evidence"})
            self.assertIn(finding["level"], {"error", "warn", "ok"})
            self.assertTrue(finding["title"])
            self.assertTrue(finding["evidence"])
        # The note must never read as a pass.
        self.assertIn("not a compliance verdict", result["note"])

    def test_errors_sort_before_warnings(self):
        d = tempfile.mkdtemp()
        p = write(d, "thin.md", "A cohort study.\n")
        result = cr.run([p], None)
        seen_warn = False
        for finding in result["findings"]:
            if finding["level"] == "warn":
                seen_warn = True
            elif seen_warn:
                self.fail("an error finding came after a warning")

    def test_unreadable_file_is_a_finding(self):
        report = cr.check(Path(tempfile.mkdtemp()) / "missing.md", None)
        self.assertTrue(report.findings)
        self.assertEqual(report.findings[0].level, "error")
        self.assertIn("could not read", report.findings[0].title)

    def test_the_printed_block_survives_a_non_utf8_console(self):
        # The block quotes the manuscript, and a Chinese Windows console (cp936)
        # cannot encode every character it might contain: ² and ⚠ both raise.
        d = tempfile.mkdtemp()
        p = write(d, "review.md", "A systematic review of trials.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cr.main([p]), 0)
        buf.getvalue().encode("gbk")


if __name__ == "__main__":
    unittest.main(verbosity=2)