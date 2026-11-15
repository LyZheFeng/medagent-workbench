#!/usr/bin/env python3
"""Tests for the diagnostic-accuracy helper (runtime/skills/core/medical-stats).

Run: python scripts/dev/test_diag_stats.py
Stdlib unittest only.

The interval expectations were computed by hand from the formulas, so the test
fails if the implementation drifts — not if the formula changes deliberately.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_MOD = (
    Path(__file__).resolve().parents[2]
    / "runtime/skills/core/medical-stats/diag_stats.py"
)
_spec = importlib.util.spec_from_file_location("diag_stats", _MOD)
assert _spec and _spec.loader
ds = importlib.util.module_from_spec(_spec)
sys.modules["diag_stats"] = ds
_spec.loader.exec_module(ds)


def row(tp, fp, tn, fn):
    return {"tp": str(tp), "fp": str(fp), "tn": str(tn), "fn": str(fn)}


class Proportions(unittest.TestCase):
    def test_wilson_matches_its_closed_form(self):
        p, lo, hi = ds.wilson(79, 83)
        self.assertAlmostEqual(p, 79 / 83, places=6)
        self.assertTrue(0 <= lo < p < hi <= 1)
        # Known value for 79/83 (the diagnostic-diagnostics example's sensitivity).
        self.assertAlmostEqual(lo, 0.883, places=3)
        self.assertAlmostEqual(hi, 0.981, places=3)

    def test_clopper_pearson_is_wider_than_wilson_at_small_n(self):
        # 0/5 is the clearest case: both start at zero, the exact upper bound is
        # higher because the normal approximation is optimistic there.
        _, cp_lo, cp_hi = ds.clopper_pearson(0, 5)
        _, w_lo, w_hi = ds.wilson(0, 5)
        self.assertEqual(cp_lo, 0.0)
        self.assertEqual(w_lo, 0.0)
        self.assertAlmostEqual(cp_hi, 0.5218, places=4)
        self.assertAlmostEqual(w_hi, 0.4345, places=4)
        self.assertGreater(cp_hi, w_hi)

        # 4/5: the exact upper bound is below 1 (only k == n reaches 1).
        _, cp_lo, cp_hi = ds.clopper_pearson(4, 5)
        self.assertLess(cp_lo, 0.8)
        self.assertAlmostEqual(cp_hi, 0.9949, places=4)

    def test_clopper_pearson_edges(self):
        # No events: the interval starts at zero and its upper bound is 1-0.025^(1/n).
        _, lo, hi = ds.clopper_pearson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 10), places=4)
        # All events: symmetric case.
        _, lo, hi = ds.clopper_pearson(10, 10)
        self.assertAlmostEqual(lo, 0.025 ** (1 / 10), places=4)
        self.assertEqual(hi, 1.0)

    def test_zero_denominator_is_nan_not_a_crash(self):
        p, lo, hi = ds.wilson(0, 0)
        self.assertTrue(p != p and lo != lo and hi != hi)  # all NaN


class LikelihoodRatios(unittest.TestCase):
    def test_lr_and_intervals_for_the_reference_table(self):
        r = ds.analyze(row(79, 45, 72, 4))
        # Point estimates: sens 0.9518, spec 0.6154 → LR+ 2.474, LR- 0.0783.
        self.assertAlmostEqual(r["lr_positive"], 2.474, places=2)
        self.assertAlmostEqual(r["lr_negative"], 0.0783, places=3)
        # Log-scale delta intervals, computed by hand from Simel (1991).
        lo, hi = r["lr_positive_ci"]
        self.assertAlmostEqual(lo, 1.957, places=2)
        self.assertAlmostEqual(hi, 3.127, places=2)
        lo, hi = r["lr_negative_ci"]
        self.assertAlmostEqual(lo, 0.0298, places=3)
        self.assertAlmostEqual(hi, 0.206, places=3)

    def test_the_interval_is_asymmetric_on_the_ratio_scale(self):
        r = ds.analyze(row(79, 45, 72, 4))
        lo, hi = r["lr_positive_ci"]
        point = r["lr_positive"]
        self.assertGreater(point - lo, 0)
        # A symmetric interval would make these equal; LR intervals must not be.
        self.assertNotAlmostEqual(point - lo, hi - point, places=2)
        self.assertLess(lo, point)
        self.assertLess(point, hi)

    def test_zero_cell_leaves_the_ratio_undefined_with_a_warning(self):
        r = ds.analyze(row(0, 10, 10, 0))
        self.assertIsNone(r["lr_positive_ci"])
        self.assertIsNone(r["lr_negative_ci"])
        self.assertTrue(any("likelihood-ratio CIs undefined" in w for w in r["warnings"]))

    def test_perfect_separation_does_not_divide_by_zero(self):
        # spec == 1 → LR+ is infinite rather than a ZeroDivisionError.
        r = ds.analyze(row(10, 0, 10, 0))
        self.assertIsNone(r["lr_positive"])
        self.assertIsNone(r["lr_positive_ci"])


class Output(unittest.TestCase):
    def run_main(self, body, *flags):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "table.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ds.main([*flags, path])
        out = buf.getvalue()
        block = out.split("```review")[1].split("```")[0]
        return code, json.loads(block), out

    def test_one_row_per_cutoff_and_the_review_contract(self):
        body = "tp,fp,tn,fn\n79,45,72,4\n70,30,87,13\n"
        code, payload, out = self.run_main(body)
        self.assertEqual(code, 0)
        self.assertEqual(payload["gate"], "medical-stats/diag_stats")
        self.assertEqual(len(payload["rows"]), 2)
        for r in payload["rows"]:
            self.assertIn("lr_positive_ci", r)
            self.assertIn("interval_method", r)
            self.assertEqual(r["interval_method"], "wilson")
        self.assertIn("LR+", out)

    def test_exact_flag_switches_the_method(self):
        code, payload, _ = self.run_main("tp,fp,tn,fn\n4,1,1,0\n", "--exact")
        self.assertEqual(code, 0)
        self.assertEqual(payload["rows"][0]["interval_method"], "clopper-pearson")

    def test_small_cell_warns_towards_the_exact_interval(self):
        _, payload, _ = self.run_main("tp,fp,tn,fn\n79,45,72,4\n")
        warnings = " ".join(payload["rows"][0]["warnings"])
        self.assertIn("--exact", warnings)

    def test_the_exact_run_does_not_tell_you_to_rerun_with_exact(self):
        # Found by running the demo: the advice was unconditional, so a caller who
        # had already passed --exact was told to pass --exact.
        _, payload, _ = self.run_main("tp,fp,tn,fn\n4,1,1,0\n", "--exact")
        warnings = " ".join(payload["rows"][0]["warnings"])
        self.assertNotIn("--exact", warnings)
        self.assertIn("exact (Clopper-Pearson)", warnings)

    def test_usage_error_returns_two(self):
        self.assertEqual(ds.main([]), 2)

    def test_the_printed_output_survives_a_non_utf8_console(self):
        # The script prints warnings, and a Chinese Windows console (cp936) cannot
        # encode every character: the warning marker "⚠" once turned a finished
        # analysis into a UnicodeEncodeError traceback. stdlib encode is the check.
        _, _, out = self.run_main("tp,fp,tn,fn\n79,45,72,4\n")
        out.encode("gbk")  # raises UnicodeEncodeError for any unprintable char
        self.assertIn("warning:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)