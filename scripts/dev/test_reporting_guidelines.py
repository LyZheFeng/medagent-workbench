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

COMPLETE_CARE = """\
# 病例报告:一例罕见的药物性肝损伤

患者,男,54 岁,因乏力两周就诊。既往史无特殊,查体见轻度黄疸。
实验室检查提示转氨酶升高,影像学除外胆道梗阻。
予停用可疑药物并保肝治疗,两周后随访转氨酶恢复正常。
已获得患者知情同意。伦理审批号 2024-118。
已按 CARE 要求去标识,并提供时间轴。
Limitations: single case.
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

    def test_accepted_wording_for_concealment_and_blinding(self):
        # Prose an author actually writes; the earlier patterns wanted the exact
        # "allocation conceal" / "blinding" strings and called this text missing.
        text = ("Allocation was concealed by central web randomisation. "
                "Outcome assessors were blinded.")
        consort = {item.id: item for item in cr.CONSORT}
        self.assertTrue(cr.present(text, consort["allocation"]))
        self.assertTrue(cr.present(text, consort["blinding"]))
        self.assertFalse(cr.present("The trial was randomised, nothing else.",
                                    consort["blinding"]))

    def test_the_printed_block_survives_a_non_utf8_console(self):
        # The block quotes text from the manuscript, and a Chinese Windows console
        # (cp936) cannot encode every character it might contain: ² and ⚠ both raise.
        d = tempfile.mkdtemp()
        p = write(d, "review.md", "A systematic review of trials.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cr.main([p]), 0)
        buf.getvalue().encode("gbk")


# Every finding cites an official checklist item, and a citation only means
# something if the number carries the meaning the gate reads into it. Each anchor
# is a phrase from the official wording behind that number — the phrase, not the
# number, is what a reader checks against the checklist they downloaded.
ANCHORS = {
    ("strobe", "1a"): "title or the abstract",
    ("strobe", "4"): "study design early",
    ("strobe", "5"): "setting, locations, and relevant dates",
    ("strobe", "6a"): "eligibility criteria",
    ("strobe", "7"): "outcomes, exposures, predictors",
    ("strobe", "12a"): "statistical methods",
    ("strobe", "12c"): "missing data",
    ("strobe", "13a"): "numbers of individuals at each stage",
    ("strobe", "16a"): "confounder-adjusted estimates",
    ("strobe", "19"): "Discuss limitations",
    ("strobe", "22"): "source of funding",
    ("consort2025", "2"): "trial registry",
    ("consort2025", "4"): "de-identified participant data",
    ("consort2025", "5a"): "Sources of funding",
    ("consort2025", "5b"): "conflicts of interest",
    ("consort2025", "9"): "type of trial",
    ("consort2025", "14"): "Pre-specified primary and secondary outcomes",
    ("consort2025", "16a"): "How sample size was determined",
    ("consort2025", "17a"): "random allocation sequence",
    ("consort2025", "18"): "conceal the sequence",
    ("consort2025", "20a"): "blinded after assignment",
    ("consort2025", "21b"): "included in each analysis",
    ("consort2025", "22a"): "numbers of participants who were randomly",
    ("consort2025", "26"): "estimated effect size and its precision",
    ("consort2025", "27"): "harms or unintended events",
    ("consort2025", "30"): "Trial limitations",
    ("consort2010", "3a"): "Description of trial design",
    ("consort2010", "6a"): "primary and secondary outcome measures",
    ("consort2010", "7a"): "How sample size was determined",
    ("consort2010", "8a"): "random allocation sequence",
    ("consort2010", "9"): "conceal the sequence",
    ("consort2010", "11a"): "blinded after assignment",
    ("consort2010", "13a"): "numbers of participants who were randomly",
    ("consort2010", "16"): "included in each analysis",
    ("consort2010", "17a"): "estimated effect size and its precision",
    ("consort2010", "19"): "harms or unintended effects",
    ("consort2010", "20"): "Trial limitations",
    ("consort2010", "23"): "Registration number and name of trial registry",
    ("consort2010", "25"): "Sources of funding",
    ("care", "5a"): "De-identified patient",
    ("care", "5c"): "psycho-social history",
    ("care", "7"): "organized as a timeline",
    ("care", "8a"): "Diagnostic testing",
    ("care", "9a"): "Types of therapeutic intervention",
    ("care", "10a"): "Clinician and patient-assessed outcomes",
    ("care", "10b"): "follow-up diagnostic",
    ("care", "11a"): "strengths AND limitations",
    ("care", "13"): "informed consent",
    ("stard", "10a"): "Index test",
    ("stard", "10b"): "Reference standard",
    ("stard", "12a"): "test positivity cut-offs",
    ("stard", "13a"): "readers of the index test",
    ("stard", "15"): "indeterminate",
    ("stard", "19"): "Flow of participants",
    ("stard", "22"): "Time interval",
    ("stard", "23"): "Cross tabulation",
    ("stard", "24"): "diagnostic accuracy and their precision",
    ("stard", "26"): "Study limitations",
    ("stard", "30"): "Sources of funding",
    ("prisma", "5"): "inclusion and exclusion criteria",
    ("prisma", "6"): "databases, registers, websites",
    ("prisma", "7"): "full search strategies",
    ("prisma", "11"): "risk of bias in the included studies",
    ("prisma", "13d"): "statistical heterogeneity",
    ("prisma", "14"): "due to missing results",
    ("prisma", "16a"): "flow diagram",
    ("prisma", "20b"): "summary estimate",
    ("prisma", "21"): "due to missing results",
    ("prisma", "23b"): "limitations of the evidence",
    ("prisma", "24a"): "registration information",
    ("prisma", "24b"): "review protocol can be accessed",
    ("prisma", "25"): "financial or non-financial support",
    ("prisma", "26"): "competing interests",
    ("prisma", "27"): "publicly available",
}

# Numbered items in the whole official checklist, from the same documents the
# sources name. A transcribed list missing an item fails here.
TOTALS = {"strobe": 22, "consort2025": 30, "consort2010": 25,
          "care": 13, "stard": 30, "prisma": 27}


class Citations(unittest.TestCase):
    def test_every_cited_item_is_anchored_to_the_official_wording(self):
        used = set()
        for design, items in cr.DESIGNS.items():
            for item in cr.COMMON + items:
                for checklist_id, number in item.cites:
                    used.add((checklist_id, number))
                    self.assertIn(
                        (checklist_id, number), ANCHORS,
                        f"{item.id} cites {checklist_id} {number} with no anchor; "
                        "check that number against the official checklist first")
        # The anchor table must not carry numbers nothing cites: a stale entry
        # would be a claim nobody checks.
        self.assertEqual(used, set(ANCHORS), used ^ set(ANCHORS))

    def test_each_number_carries_the_wording_the_gate_relies_on(self):
        for (checklist_id, number), anchor in ANCHORS.items():
            text = cr.CHECKLISTS[checklist_id].items.get(number, "")
            self.assertTrue(text, f"{checklist_id} {number} is not transcribed")
            self.assertIn(anchor.lower(), text.lower(),
                          f"{checklist_id} item {number} does not read like {anchor!r}")

    def test_checklist_totals_and_sources(self):
        for checklist_id, total in TOTALS.items():
            checklist = cr.CHECKLISTS[checklist_id]
            self.assertEqual(checklist.total, total, checklist_id)
            self.assertTrue(checklist.source.startswith("https://"),
                            f"{checklist_id} must name where it came from")

    def test_a_design_uses_only_its_own_checklist_numbers(self):
        # A CARE finding must not cite STROBE: the sentence an author reads is the
        # one they check against their own journal's checklist.
        for design, items in cr.DESIGNS.items():
            for item in cr.COMMON + items:
                for citation in cr.citations(item, design):
                    checklist = next(c for c in cr.CHECKLISTS.values()
                                     if c.label == citation.checklist)
                    self.assertEqual(checklist.design, design,
                                     f"{design}/{item.id} cites {citation.checklist}")

    def test_every_cross_cutting_item_answers_for_every_design(self):
        # An item checked on a design whose checklist has no such item must say
        # what the rule is instead of citing a number that does not exist.
        for design in cr.DESIGNS:
            for item in cr.COMMON:
                self.assertTrue(cr.basis(item, design), f"{design}/{item.id}")

    def test_a_finding_names_the_item_it_comes_from(self):
        d = tempfile.mkdtemp()
        p = write(d, "cohort.md", COMPLETE_STROBE.replace(
            "Limitations: single-region cohort, residual confounding likely.", ""))
        result = cr.run([p], None)
        limitations = [f for f in result["findings"]
                       if f["tag"] == "reporting · strobe · limitations"]
        self.assertEqual(len(limitations), 1)
        self.assertIn("STROBE 2007 item 19", limitations[0]["evidence"])

    def test_consort_findings_carry_both_numbering_systems(self):
        d = tempfile.mkdtemp()
        p = write(d, "trial.md", COMPLETE_CONSORT.replace(
            "Analysis: intention-to-treat, with a per-protocol sensitivity analysis.", ""))
        result = cr.run([p], None)
        itt = [f for f in result["findings"] if f["tag"] == "reporting · consort · itt"]
        self.assertEqual(len(itt), 1)
        self.assertIn("CONSORT 2025 item 21b", itt[0]["evidence"])
        self.assertIn("CONSORT 2010 item 16", itt[0]["evidence"])

    def test_a_case_report_gets_the_no_item_answer(self):
        # CARE 2013 has no conflicts-of-interest and no data-availability item;
        # inventing a number there would be the failure this gate exists to avoid.
        d = tempfile.mkdtemp()
        p = write(d, "case.md", COMPLETE_CARE)
        result = cr.run([p], None)
        found = {f["tag"]: f for f in result["findings"]}
        self.assertIn("journal requirement",
                      found["reporting · care · conflicts"]["evidence"])
        self.assertNotIn("CARE 2013 item",
                         found["reporting · care · data-availability"]["evidence"])

    def test_the_listing_prints_the_official_wording_and_its_source(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cr.listing("stard"), 0)
        out = buf.getvalue()
        self.assertIn("STARD 2015", out)
        self.assertIn("europepmc", out)
        self.assertIn("STARD 2015 item 24:", out)
        self.assertIn("precision", out)
        self.assertIn("section: results", out)

    def test_the_listing_names_each_designs_version(self):
        for design, label in cr.DESIGN_LABEL.items():
            self.assertRegex(label, r"\d{4}", design)
            self.assertIn(design, label.lower())


class Sections(unittest.TestCase):
    def test_headings_are_recognised_and_sub_headings_stay_in_place(self):
        text = """\
# Title

## Abstract

## Methods

### Study population

Eligibility: adults.

## Results

## Discussion

## 方法

## 结果
"""
        sections, order = cr.scan_sections(text)
        self.assertIn("methods", sections)
        self.assertIn("Eligibility: adults.", sections["methods"],
                      "a sub-heading's body belongs to its parent section")
        self.assertIn("results", sections)
        self.assertIn("discussion", sections)
        self.assertEqual(order, ("title", "abstract", "methods", "results",
                                 "discussion"))

    def test_an_item_in_the_wrong_section_warns_without_also_being_missing(self):
        # STROBE item 12c belongs in Methods; this manuscript says it only in the
        # Discussion, which is exactly the mistake --sections exists to catch.
        body = """\
# Cohort study of readmission

## Methods

We performed a retrospective cohort study in two hospitals, conducted between
January 2019 and December 2021. Eligibility: adults admitted with heart failure;
exclusion: prior transplant. Outcome: 30-day readmission. Exposure: discharge on
a weekend. Statistical methods were as described. Ethics approval: IRB 2019-042.
Informed consent was waived.

## Results

410 patients were screened; the adjusted OR was 1.31 (95% CI 1.04 to 1.66),
adjusted for age and comorbidity. The participant flow diagram is in Figure 1.

## Discussion

Missing data were handled by complete-case analysis.

Limitations: single-region cohort, residual confounding likely.

## Other information

Funding: none. Conflicts of interest: none declared. Data availability: on request.
"""
        d = tempfile.mkdtemp()
        p = write(d, "moved.md", body)
        result = cr.run([p], None, strict=True)
        by_tag = {f["tag"]: f for f in result["findings"]}
        self.assertIn("reporting · strobe · missing-data · section", by_tag)
        self.assertEqual(by_tag["reporting · strobe · missing-data · section"]["level"],
                         "warn")
        self.assertNotIn("reporting · strobe · missing-data", by_tag,
                         "an item that appears in the wrong section is not also "
                         "reported as missing")
        self.assertIn("Methods",
                      by_tag["reporting · strobe · missing-data · section"]["title"])
        self.assertIn("Section positions were checked", result["note"])

    def test_a_well_placed_report_gets_no_section_finding(self):
        body = """\
# Cohort study of readmission

## Methods

We performed a retrospective cohort study in two hospitals, conducted between
January 2019 and December 2021. Eligibility: adults admitted with heart failure;
exclusion: prior transplant. Outcome: 30-day readmission. Exposure: discharge on
a weekend. Missing data were handled by complete-case analysis. Statistical
methods were as described. Ethics approval: IRB 2019-042. Informed consent was
waived.

## Results

410 patients were screened; the adjusted OR was 1.31 (95% CI 1.04 to 1.66),
adjusted for age and comorbidity. The participant flow diagram is in Figure 1.

## Discussion

Limitations: single-region cohort, residual confounding likely.

## Other information

Funding: none. Conflicts of interest: none declared. Data availability: on request.
"""
        d = tempfile.mkdtemp()
        p = write(d, "placed.md", body)
        result = cr.run([p], None, strict=True)
        self.assertEqual(
            [f for f in result["findings"] if f["tag"].endswith(" · section")], [])
        self.assertIn("Section positions were checked", result["note"])

    def test_a_leading_h1_is_the_title_line(self):
        # A manuscript's first "# ..." line is its title, not a heading without a
        # section; a trial-registration number in the title is still in the title.
        text = """\
# Early mobilisation in the ICU (NCT01234567)

## Methods

Adults were eligible.
"""
        sections, order = cr.scan_sections(text)
        self.assertEqual(order, ("title", "methods"))
        self.assertIn("NCT01234567", sections["title"])
        self.assertIn("Adults were eligible.", sections["methods"])

    def test_no_recognised_heading_says_so_instead_of_guessing(self):
        d = tempfile.mkdtemp()
        p = write(d, "plain.md",
                  "A retrospective cohort study. Ethics approval: IRB 2019-042.\n")
        result = cr.run([p], None, strict=True)
        self.assertEqual(
            [f for f in result["findings"] if f["tag"].endswith(" · section")], [])
        self.assertIn("no Methods/Results heading was recognised", result["note"])

    def test_sections_defaults_off(self):
        d = tempfile.mkdtemp()
        p = write(d, "flat.md", "A cohort study. Missing data were handled.\n")
        without = cr.run([p], None)
        self.assertNotIn("Section positions", without["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)