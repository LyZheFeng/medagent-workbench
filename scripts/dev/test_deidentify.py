#!/usr/bin/env python3
"""Tests for the de-identification gate (runtime/skills/core/deidentify).

Run: python scripts/dev/test_deidentify.py
Stdlib unittest only. Every fixture is synthetic — no real patient data.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_MOD = (
    Path(__file__).resolve().parents[2]
    / "runtime/skills/core/deidentify/deidentify.py"
)
_spec = importlib.util.spec_from_file_location("deidentify", _MOD)
assert _spec and _spec.loader
dd = importlib.util.module_from_spec(_spec)
sys.modules["deidentify"] = dd
_spec.loader.exec_module(dd)


def write(directory, name, body, encoding="utf-8"):
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(body.encode(encoding))
    return path


def review_block(stdout):
    match = re.search(r"```review\n(.*?)\n```", stdout, re.S)
    assert match, f"no review block in: {stdout!r}"
    return json.loads(match.group(1))


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dd.main([str(a) for a in argv])
    return code, buf.getvalue()


class UnlabelledIdentifiers(unittest.TestCase):
    def test_id_phone_and_email_are_replaced(self):
        body = (
            "身份证 11010519491231002X，手机 13800138000，"
            "邮箱 zhang.san@example.org，旧号 130503670401001。\n"
        )
        result = dd.scan_text(body, 10)
        self.assertNotIn("11010519491231002X", result.text)
        self.assertNotIn("13800138000", result.text)
        self.assertNotIn("zhang.san@example.org", result.text)
        self.assertNotIn("130503670401001", result.text)
        self.assertIn("[ID-1]", result.text)
        self.assertIn("[ID-2]", result.text)
        self.assertIn("[PHONE-1]", result.text)
        self.assertIn("[EMAIL-1]", result.text)
        self.assertEqual(result.counts, {"ID": 2, "PHONE": 1, "EMAIL": 1})

    def test_a_date_inside_an_id_is_not_shifted(self):
        # The ID runs first, so its embedded birth date never reaches the date
        # rule and comes back as a shifted date.
        result = dd.scan_text("编号 11010519491231002X\n", 100)
        self.assertNotIn("1949", result.text)
        self.assertEqual(result.dates, {})


class LabelledFields(unittest.TestCase):
    def test_labels_survive_and_values_become_tokens(self):
        body = (
            "姓名：张三\n"
            "住院号：A123456\n"
            "电话：010-12345678\n"
            "地址：北京市朝阳区某路 1 号\n"
        )
        result = dd.scan_text(body, 10)
        self.assertIn("姓名：[NAME-1]", result.text)
        self.assertIn("住院号：[MRN-1]", result.text)
        self.assertIn("电话：[PHONE-1]", result.text)
        self.assertIn("地址：[ADDRESS-1]", result.text)
        for leaked in ("张三", "A123456", "010-12345678", "朝阳区"):
            self.assertNotIn(leaked, result.text)

    def test_one_value_one_token(self):
        result = dd.scan_text("姓名：张三\n患者姓名：张三\n", 10)
        self.assertEqual(result.text.count("[NAME-1]"), 2)
        self.assertEqual(result.counts["NAME"], 1)
        # Both occurrences were replaced: no original name is left.
        self.assertNotIn("张三", result.text)

    def test_patient_name_before_a_gender_marker(self):
        result = dd.scan_text("患者王五，男，52 岁，因乏力就诊。\n", 10)
        self.assertIn("患者[NAME-1]，男，52 岁", result.text)
        self.assertNotIn("王五", result.text)

    def test_a_clinical_word_is_not_taken_for_a_name(self):
        result = dd.scan_text("患者：男性，45 岁。\n", 10)
        self.assertIn("男性", result.text)
        self.assertNotIn("[NAME-1]", result.text)

    def test_english_names(self):
        result = dd.scan_text("Patient John Doe was seen by Dr. Alice Smith.\n", 10)
        self.assertNotIn("John Doe", result.text)
        self.assertNotIn("Alice Smith", result.text)
        self.assertEqual(result.counts["NAME"], 2)


class Institutions(unittest.TestCase):
    def test_chinese_hospital_keeps_the_verb_before_it(self):
        result = dd.scan_text("患者于2024年3月入住北京协和医院。\n", 10)
        self.assertIn("入住[INSTITUTION-1]", result.text)
        self.assertNotIn("北京协和医院", result.text)

    def test_hospital_at_the_start_of_a_sentence(self):
        result = dd.scan_text("北京大学人民医院收治了该患者。\n", 10)
        self.assertIn("[INSTITUTION-1]", result.text)
        self.assertNotIn("北京大学人民医院", result.text)

    def test_english_institution(self):
        result = dd.scan_text("Treated at Massachusetts General Hospital in 2023.\n", 10)
        self.assertIn("[INSTITUTION-1]", result.text)
        self.assertNotIn("Massachusetts General Hospital", result.text)


class Ages(unittest.TestCase):
    def test_over_89_is_grouped_and_younger_ages_are_kept(self):
        result = dd.scan_text("患者 92 岁，对照 45 岁，另一例 aged 93。\n", 10)
        self.assertIn("≥90 岁", result.text)
        self.assertIn("45 岁", result.text)
        self.assertIn("aged ≥90", result.text)
        self.assertEqual(result.ages, {"92": "≥90", "93": "≥90"})

    def test_age_boundary(self):
        result = dd.scan_text("89 岁与 90 岁。\n", 10)
        self.assertEqual(result.ages, {"90": "≥90"})
        self.assertIn("89 岁", result.text)


class Dates(unittest.TestCase):
    def test_three_formats_shift_by_the_same_offset(self):
        body = (
            "Admitted 2024-01-02, discharged 2024-01-05; visit 2024/01/20, "
            "随访 2024年1月30日。\n"
        )
        result = dd.scan_text(body, 10)
        self.assertIn("2024-01-12", result.text)
        self.assertIn("2024-01-15", result.text)
        self.assertIn("2024/01/30", result.text)
        self.assertIn("2024年2月9日", result.text)
        self.assertEqual(len(result.dates), 4)

    def test_a_repeated_date_gets_one_shifted_value(self):
        result = dd.scan_text("2024-01-02 入院，2024-01-02 复查。\n", 10)
        self.assertEqual(result.text.count("2024-01-12"), 2)
        self.assertEqual(result.dates, {"2024-01-02": "2024-01-12"})

    def test_year_month_keeps_its_granularity(self):
        result = dd.scan_text("2024年2月随访。\n", 10)
        self.assertIn("2024年2月", result.text)
        self.assertNotIn("日", result.text)

    def test_month_day_dates_shift_too(self):
        # A timeline names the year once: "3月12日入院，3月18日出院" must move
        # with the same offset, or the admission date shifts and the discharge
        # date does not.
        result = dd.scan_text("3月12日入院，3月18日出院。\n", 10)
        self.assertIn("3月22日", result.text)
        self.assertIn("3月28日", result.text)

    def test_month_day_crossing_a_month_boundary(self):
        result = dd.scan_text("12月28日复查。\n", 10)
        self.assertIn("1月7日", result.text)

    def test_full_date_and_month_day_keep_their_interval(self):
        body = "2024年3月12日入院，3月18日出院。\n"
        result = dd.scan_text(body, 10)
        self.assertIn("2024年3月22日", result.text)
        self.assertIn("3月28日", result.text)
        self.assertEqual(len(result.dates), 2)

    def test_the_default_shift_is_stable_per_file(self):
        raw = "2024-01-02\n".encode()
        first = dd._deterministic_shift(raw)
        self.assertEqual(first, dd._deterministic_shift(raw))
        self.assertGreaterEqual(abs(first), 1)
        self.assertLessEqual(abs(first), 364)


class Contract(unittest.TestCase):
    def test_no_findings_for_ordinary_prose(self):
        result = dd.scan_text(
            "The adjusted OR was 1.31 (95% CI 1.04 to 1.66); 120 participants.\n", 10
        )
        self.assertEqual(result.counts, {})
        self.assertEqual(result.dates, {})
        findings = dd.findings(result)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["level"], "ok")

    def test_review_block_never_repeats_an_identifier(self):
        d = tempfile.mkdtemp()
        p = write(
            d,
            "case.md",
            "姓名：张三\n患者于2024年1月2日入院。\n电话：13800138000\n",
        )
        code, stdout = run_main([p, "--shift-days", "10"])
        self.assertEqual(code, 0)
        data = review_block(stdout)
        self.assertTrue(data["findings"])
        for finding in data["findings"]:
            self.assertEqual(set(finding), {"level", "tag", "title", "evidence"})
            self.assertIn(finding["level"], {"warn", "ok"})
            self.assertTrue(finding["title"])
            self.assertTrue(finding["evidence"])
        self.assertIn("not a guarantee of anonymity", data["note"])
        for leaked in ("张三", "13800138000", "2024年1月2日"):
            self.assertNotIn(leaked, stdout)

        copy = Path(d) / "case.deid.md"
        self.assertTrue(copy.exists())
        text = copy.read_text(encoding="utf-8")
        self.assertIn("姓名：[NAME-1]", text)
        self.assertIn("[PHONE-1]", text)
        self.assertNotIn("2024年1月2日", text)
        self.assertIn("2024年1月12日", text)

    def test_mapping_is_opt_in_and_reidentifies(self):
        d = tempfile.mkdtemp()
        p = write(d, "case.md", "姓名：张三，住院号 A123456。\n")
        self.assertFalse((Path(d) / "case.deid.map.json").exists())
        mapping = Path(d) / "case-map.json"
        code, stdout = run_main([p, "--mapping", mapping])
        self.assertEqual(code, 0)
        self.assertTrue(mapping.exists())
        doc = json.loads(mapping.read_text(encoding="utf-8"))
        self.assertEqual(doc["tokens"]["[NAME-1]"], "张三")
        self.assertEqual(doc["tokens"]["[MRN-1]"], "A123456")
        self.assertIn("re-identifies", doc["notice"])
        self.assertIn("dateShiftDays", doc)
        self.assertNotIn("张三", stdout)

    def test_check_writes_nothing(self):
        d = tempfile.mkdtemp()
        p = write(d, "draft.md", "姓名：张三\n")
        code, stdout = run_main([p, "--check"])
        self.assertEqual(code, 0)
        self.assertFalse((Path(d) / "draft.deid.md").exists())
        self.assertIn("no file was written", review_block(stdout)["note"])

    def test_check_rejects_output_paths(self):
        d = tempfile.mkdtemp()
        p = write(d, "draft.md", "姓名：张三\n")
        self.assertEqual(run_main([p, "--check", "--out", p])[0], 2)

    def test_refuses_to_overwrite_the_source(self):
        d = tempfile.mkdtemp()
        p = write(d, "draft.md", "姓名：张三\n")
        code, _ = run_main([p, "--out", p])
        self.assertEqual(code, 2)
        self.assertIn("张三", Path(p).read_text(encoding="utf-8"))

    def test_gbk_input_is_decoded(self):
        d = tempfile.mkdtemp()
        p = write(d, "gbk.md", "姓名：张三\n患者于2024年1月2日入院。\n", encoding="gb18030")
        code, _ = run_main([p])
        self.assertEqual(code, 0)
        text = (Path(d) / "gbk.deid.md").read_text(encoding="utf-8")
        self.assertIn("姓名：[NAME-1]", text)
        self.assertNotIn("张三", text)

    def test_missing_file_is_a_usage_error(self):
        self.assertEqual(run_main([os.path.join(tempfile.mkdtemp(), "nope.md")])[0], 2)

    def test_the_printed_block_survives_a_non_utf8_console(self):
        # A Windows console is cp936; the block must degrade, not raise.
        d = tempfile.mkdtemp()
        p = write(d, "case.md", "患者 92 岁，姓名：张三。\n")
        code, stdout = run_main([p])
        self.assertEqual(code, 0)
        stdout.encode("gbk")


if __name__ == "__main__":
    unittest.main(verbosity=2)