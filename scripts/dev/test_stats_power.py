#!/usr/bin/env python3
"""Tests for the sample-size / power helper (runtime/skills/core/medical-stats).

Run: python scripts/dev/test_stats_power.py

Stdlib unittest. Every pinned number is a hand-checked textbook value; the
formulas are the ones the medical-stats skill names (Fleiss, Schoenfeld,
Buderer), so a change in the formula must change these tests too.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_ROOT = Path(__file__).resolve().parents[2]
_MOD = _ROOT / "runtime/skills/core/medical-stats/stats_power.py"
_spec = importlib.util.spec_from_file_location("stats_power", _MOD)
assert _spec and _spec.loader
sp = importlib.util.module_from_spec(_spec)
sys.modules["stats_power"] = sp
_spec.loader.exec_module(sp)


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sp.main(argv)
    return code, out.getvalue(), err.getvalue()


def review_of(stdout: str) -> dict:
    return json.loads(stdout.split("```review")[1].split("```")[0])


class TwoProportions(unittest.TestCase):
    def test_fleiss_example_is_93_per_group(self):
        result = sp._two_proportions(0.5, 0.3, 0.05, 0.8, 1.0)
        self.assertEqual(result["n1"], 93)
        self.assertEqual(result["n2"], 93)
        self.assertEqual(result["total"], 186)
        self.assertGreaterEqual(result["achieved_power"], 0.8 - 1e-9)

    def test_power_90_needs_more_than_power_80(self):
        eighty = sp._two_proportions(0.5, 0.3, 0.05, 0.8, 1.0)["n1"]
        ninety = sp._two_proportions(0.5, 0.3, 0.05, 0.9, 1.0)["n1"]
        self.assertGreater(ninety, eighty)

    def test_allocation_ratio_two_gives_69_and_138(self):
        result = sp._two_proportions(0.5, 0.3, 0.05, 0.8, 2.0)
        self.assertEqual(result["n1"], 69)
        self.assertEqual(result["n2"], 138)


class NonInferiority(unittest.TestCase):
    def test_margin_ten_points_is_393_per_group(self):
        result = sp._non_inferiority(0.5, 0.5, 0.1, 0.05, 0.8)
        self.assertEqual(result["n1"], 393)
        self.assertEqual(result["total"], 786)
        self.assertGreaterEqual(result["achieved_power"], 0.8 - 1e-9)

    def test_margin_must_exceed_the_expected_difference(self):
        with self.assertRaises(sp.PowerError):
            sp._non_inferiority(0.6, 0.4, 0.1, 0.05, 0.8)


class Means(unittest.TestCase):
    def test_delta_five_sd_ten_is_63_per_group(self):
        result = sp._means(5.0, 10.0, 0.05, 0.8, 1.0)
        self.assertEqual(result["n1"], 63)
        self.assertEqual(result["n2"], 63)
        self.assertGreaterEqual(result["achieved_power"], 0.8 - 1e-9)


class Accuracy(unittest.TestCase):
    def test_buderer_precision_example(self):
        result, warnings = sp._accuracy(0.9, 0.85, 0.05, 0.3, 0.05)
        self.assertEqual(result["n_diseased"], 139)
        self.assertEqual(result["n_non_diseased"], 196)
        self.assertEqual(result["n_for_sensitivity"], 464)
        self.assertEqual(result["n_for_specificity"], 280)
        self.assertEqual(result["total"], 464)
        self.assertEqual(result["binding"], "sensitivity")
        self.assertEqual(warnings, [])

    def test_small_groups_are_flagged(self):
        _, warnings = sp._accuracy(0.95, 0.95, 0.1, 0.5, 0.05)
        self.assertTrue(any("normal approximation" in w for w in warnings))


class Survival(unittest.TestCase):
    def test_schoenfeld_events_and_total(self):
        result = sp._survival(0.7, 0.6, 0.05, 0.8, 1.0)
        self.assertEqual(result["events"], 247)
        self.assertEqual(result["total"], 412)
        self.assertGreaterEqual(result["achieved_power"], 0.8 - 1e-9)

    def test_hr_of_one_is_refused(self):
        with self.assertRaises(sp.PowerError):
            sp._survival(1.0, 0.6, 0.05, 0.8, 1.0)


class CliContract(unittest.TestCase):
    def test_two_proportions_review_block(self):
        code, stdout, _ = run_main(["two-proportions", "--p1", "0.5",
                                    "--p2", "0.3"])
        self.assertEqual(code, 0)
        payload = review_of(stdout)
        self.assertEqual(payload["gate"], "medical-stats/stats_power")
        self.assertEqual(payload["design"], "two-proportions")
        self.assertEqual(payload["result"]["n1"], 93)
        self.assertTrue(payload["method"])
        self.assertEqual(payload["inputs"]["alpha"], 0.05)

    def test_dropout_inflates_the_size(self):
        code, stdout, _ = run_main(["two-proportions", "--p1", "0.5",
                                    "--p2", "0.3", "--dropout", "0.1"])
        self.assertEqual(code, 0)
        payload = review_of(stdout)
        self.assertEqual(payload["result"]["n1"], 104)
        self.assertEqual(payload["result"]["total"], 208)

    def test_validation_errors_exit_two(self):
        cases = [
            ["two-proportions", "--p1", "0.5", "--p2", "0.5"],
            ["two-proportions", "--p1", "1.2", "--p2", "0.3"],
            ["two-proportions", "--p1", "0.5", "--p2", "0.3", "--power", "1.5"],
            ["two-proportions", "--p1", "0.5", "--p2", "0.3", "--dropout", "1"],
            ["means", "--delta", "0", "--sd", "10"],
            ["means", "--delta", "5", "--sd", "-1"],
            ["accuracy", "--sensitivity", "0.9", "--specificity", "0.8",
             "--half-width", "0", "--prevalence", "0.3"],
            ["survival", "--hr", "1", "--event-rate", "0.6"],
            ["survival", "--hr", "0.7", "--event-rate", "0"],
            ["non-inferiority", "--p1", "0.5", "--p2", "0.5", "--margin", "0.1",
             "--ratio", "2"],
        ]
        for argv in cases:
            code, _, _ = run_main(argv)
            self.assertEqual(code, 2, argv)

    def test_missing_subcommand_is_two_not_a_traceback(self):
        self.assertEqual(run_main([])[0], 2)

    def test_small_group_warning_reaches_the_block(self):
        code, stdout, _ = run_main(["two-proportions", "--p1", "0.95",
                                    "--p2", "0.5"])
        self.assertEqual(code, 0)
        self.assertTrue(review_of(stdout)["warnings"])

    def test_accuracy_says_which_constraint_binds(self):
        code, stdout, _ = run_main(["accuracy", "--sensitivity", "0.9",
                                    "--specificity", "0.85",
                                    "--half-width", "0.05",
                                    "--prevalence", "0.3"])
        self.assertEqual(code, 0)
        payload = review_of(stdout)
        self.assertEqual(payload["result"]["binding"], "sensitivity")
        self.assertIsNone(payload["result"]["achieved_power"])

    def test_printed_output_survives_a_gbk_console(self):
        code, stdout, stderr = run_main(["survival", "--hr", "0.7",
                                         "--event-rate", "0.6"])
        (stdout + stderr).encode("gbk")


if __name__ == "__main__":
    unittest.main(verbosity=2)