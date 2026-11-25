#!/usr/bin/env python3
"""Tests for the medical-figure generator (runtime/skills/core/med-figures).

Run: python scripts/dev/test_med_figures.py

Stdlib unittest. The statistics are stdlib, so they run everywhere; rendering
tests skip themselves when matplotlib is absent (gates CI installs nothing).
The reference numbers for the forest plot and the log-rank test were computed
independently with scipy and are pinned here with that provenance.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_ROOT = Path(__file__).resolve().parents[2]
_MOD = _ROOT / "runtime/skills/core/med-figures/med_figures.py"
_spec = importlib.util.spec_from_file_location("med_figures", _MOD)
assert _spec and _spec.loader
med = importlib.util.module_from_spec(_spec)
sys.modules["med_figures"] = med
_spec.loader.exec_module(med)


def _mpl_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


HAVE_MPL = _mpl_available()


def write_csv(directory: str, name: str, body: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(body)
    return path


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = med.main(argv)
    return code, out.getvalue(), err.getvalue()


def review_of(stdout: str) -> dict:
    return json.loads(stdout.split("```review")[1].split("```")[0])


def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG")
    return (int.from_bytes(head[16:20], "big"),
            int.from_bytes(head[20:24], "big"))


class Intervals(unittest.TestCase):
    def test_chi2_survival_matches_the_textbook_cutoffs(self):
        # 3.841459 / 5.991465 are the 95% points of chi-square with 1 / 2 df.
        self.assertAlmostEqual(med.chi2_sf(3.841458820694124, 1), 0.05, places=4)
        self.assertAlmostEqual(med.chi2_sf(5.991464547107979, 2), 0.05, places=4)
        self.assertEqual(med.chi2_sf(0.0, 3), 1.0)
        with self.assertRaises(med.FigureError):
            med.chi2_sf(1.0, 0)

    def test_matrix_inverse(self):
        inv = med._invert([[2.0, 1.0], [1.0, 2.0]])
        self.assertAlmostEqual(inv[0][0], 2 / 3)
        self.assertAlmostEqual(inv[0][1], -1 / 3)
        self.assertAlmostEqual(inv[1][0], -1 / 3)
        self.assertAlmostEqual(inv[1][1], 2 / 3)
        with self.assertRaises(med.FigureError):
            med._invert([[1.0, 2.0], [2.0, 4.0]])

    def test_wilson_matches_diag_stats(self):
        # Two skills ship the same interval; this fails the day one drifts.
        diag_path = _ROOT / "runtime/skills/core/medical-stats/diag_stats.py"
        spec = importlib.util.spec_from_file_location("diag_stats_for_crosscheck", diag_path)
        assert spec and spec.loader
        diag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(diag)
        for k, n in ((0, 5), (4, 5), (79, 83), (1, 1)):
            self.assertEqual(med.wilson(k, n), diag.wilson(k, n))


class RocMath(unittest.TestCase):
    def test_auc_is_the_mann_whitney_statistic(self):
        # Positives 3, 4 against negatives 1, 2: every pair is a win.
        self.assertEqual(med.auc([3.0, 4.0, 1.0, 2.0], [1, 1, 0, 0]), 1.0)
        self.assertEqual(med.auc([1.0, 2.0, 3.0, 4.0], [1, 1, 0, 0]), 0.0)
        # Positives 2, 4; negatives 2, 3: the 2-vs-2 pair is a tie (0.5),
        # 4 beats both -> (0.5 + 1 + 1) / 4.
        self.assertAlmostEqual(
            med.auc([2.0, 4.0, 2.0, 3.0], [1, 1, 0, 0]), 0.625
        )

    def test_one_class_is_an_error(self):
        with self.assertRaises(med.FigureError):
            med.auc([1.0, 2.0], [1, 1])

    def test_points_run_from_origin_to_the_top_right_corner(self):
        points = med.roc_points([1.0, 2.0, 3.0, 4.0], [0, 0, 1, 1])
        self.assertEqual((points[0]["fpr"], points[0]["tpr"]), (0.0, 0.0))
        self.assertEqual((points[-1]["fpr"], points[-1]["tpr"]), (1.0, 1.0))
        for earlier, later in zip(points, points[1:]):
            self.assertLessEqual(earlier["fpr"], later["fpr"])
            self.assertLessEqual(earlier["tpr"], later["tpr"])

    def test_analysis_interval_contains_the_estimate_and_is_repeatable(self):
        # Overlapping distributions, so the interval is not degenerate at 1.0.
        scores = ([round(0.02 * i, 2) for i in range(1, 21)] +
                  [round(0.02 * i + 0.2, 2) for i in range(1, 21)])
        labels = [0] * 20 + [1] * 20
        first = med.roc_analysis(scores, labels, boot=300, seed=7)
        second = med.roc_analysis(scores, labels, boot=300, seed=7)
        self.assertEqual(first["auc_ci"], second["auc_ci"])
        low, high = first["auc_ci"]
        self.assertLess(low, first["auc"])
        self.assertGreater(high, first["auc"])
        self.assertGreater(high - low, 0.0)

    def test_youden_point_and_a_given_cutoff(self):
        scores = [1.0, 2.0, 3.0, 4.0]
        labels = [0, 0, 1, 1]
        analysis = med.roc_analysis(scores, labels, boot=200)
        self.assertEqual(analysis["operating_source"], "youden")
        given = med.roc_analysis(scores, labels, cutoff=2.5, boot=200)
        self.assertEqual(given["operating_source"], "given")
        self.assertAlmostEqual(given["operating"]["tpr"], 1.0)
        self.assertAlmostEqual(given["operating"]["fpr"], 0.0)
        self.assertLessEqual(given["operating"]["sensitivity_ci"][0], 1.0)
        self.assertGreaterEqual(given["operating"]["specificity_ci"][1], 0.0)

    def test_cutoff_outside_the_data_is_flagged(self):
        analysis = med.roc_analysis([1.0, 2.0, 3.0, 4.0], [0, 0, 1, 1],
                                    cutoff=10.0, boot=200)
        self.assertTrue(any("outside the observed score range" in w
                            for w in analysis["warnings"]))


class ForestMath(unittest.TestCase):
    # Reference values computed with scipy.stats.chi2 on 2026-11-15 from the
    # same three log-scale inputs; the test pins the formulas, not a rerun.
    ROWS = [("A", 1.50, 1.20, 1.875),
            ("B", 2.00, 1.50, 2.667),
            ("C", 0.80, 0.60, 1.067)]

    def studies(self):
        return [med.Study(name, effect, low, high, 0.0, 0.0)
                for name, effect, low, high in self.ROWS]

    def test_fixed_and_random_pooling(self):
        analysis = med.forest_analysis(self.studies(), log_scale=True)
        self.assertAlmostEqual(analysis["fixed"]["effect"], 1.3668, places=3)
        self.assertAlmostEqual(analysis["fixed"]["ci"][0], 1.1760, places=3)
        self.assertAlmostEqual(analysis["fixed"]["ci"][1], 1.5886, places=3)
        self.assertAlmostEqual(analysis["random"]["effect"], 1.3412, places=3)
        self.assertAlmostEqual(analysis["random"]["ci"][0], 0.8198, places=3)
        self.assertAlmostEqual(analysis["random"]["ci"][1], 2.1942, places=3)
        self.assertAlmostEqual(analysis["q"], 20.6922, places=3)
        self.assertAlmostEqual(analysis["p_heterogeneity"], 3.2117e-05, places=6)
        self.assertAlmostEqual(analysis["i2"], 0.9033, places=3)
        self.assertAlmostEqual(analysis["tau2"], 0.1706, places=3)

    def test_weights_are_fractions_that_sum_to_one(self):
        analysis = med.forest_analysis(self.studies(), log_scale=True)
        self.assertAlmostEqual(sum(s.weight_fixed for s in analysis["studies"]), 1.0)
        self.assertAlmostEqual(sum(s.weight_random for s in analysis["studies"]), 1.0)
        # The tightest study (A) carries the most weight in both models.
        self.assertEqual(max(analysis["studies"], key=lambda s: s.weight_fixed).name, "A")
        self.assertEqual(max(analysis["studies"], key=lambda s: s.weight_random).name, "A")

    def test_mean_difference_uses_the_identity_scale(self):
        # Symmetric CIs, so both studies carry the same weight and the pooled
        # mean difference is the midpoint (1.5).
        rows = [med.Study("A", 1.0, 0.5, 1.5, 0.0, 0.0),
                med.Study("B", 2.0, 1.5, 2.5, 0.0, 0.0)]
        analysis = med.forest_analysis(rows, log_scale=False, model="fixed")
        self.assertAlmostEqual(analysis["fixed"]["effect"], 1.5, places=6)
        self.assertAlmostEqual(analysis["fixed"]["ci"][0], 1.1464, places=3)
        self.assertAlmostEqual(analysis["fixed"]["ci"][1], 1.8536, places=3)
        self.assertAlmostEqual(analysis["i2"], 0.8698, places=3)

    def test_bad_intervals_and_ratio_values_are_refused(self):
        with self.assertRaises(med.FigureError):
            med.forest_analysis([med.Study("A", 1.0, 1.2, 1.1, 0.0, 0.0)], True)
        with self.assertRaises(med.FigureError):
            med.forest_analysis([med.Study("A", 3.0, 1.0, 2.0, 0.0, 0.0)], True)
        with self.assertRaises(med.FigureError):
            med.forest_analysis([med.Study("A", 0.0, 0.0, 1.0, 0.0, 0.0)], True)

    def test_one_study_is_flagged_as_not_a_meta_analysis(self):
        analysis = med.forest_analysis([med.Study("A", 1.5, 1.2, 1.8, 0.0, 0.0)], True)
        self.assertTrue(any("one study" in w for w in analysis["warnings"]))


class KaplanMeierMath(unittest.TestCase):
    A = [(1, 1), (2, 1), (3, 0), (4, 1), (5, 0)]
    B = [(1, 0), (2, 1), (3, 0), (4, 1), (5, 0)]

    def test_survival_steps_and_censoring(self):
        curve = med.km_curve(self.A)
        by_time = {p["time"]: p["survival"] for p in curve}
        self.assertAlmostEqual(by_time[1], 0.8)
        self.assertAlmostEqual(by_time[2], 0.6)
        self.assertAlmostEqual(by_time[4], 0.3)
        self.assertNotIn(3, by_time)  # a censoring time does not step the curve

    def test_median_and_risk_table(self):
        analysis = med.km_analysis({"A": self.A, "B": self.B}, [0, 2, 4])
        self.assertEqual(analysis["medians"]["A"][0], 4)
        self.assertEqual(analysis["medians"]["B"][0], 4)
        self.assertEqual(analysis["risk"]["A"], [5, 4, 2])
        self.assertEqual(analysis["risk"]["B"], [5, 4, 2])

    def test_log_rank_matches_the_reference_computation(self):
        result = med.logrank({"A": self.A, "B": self.B})
        self.assertAlmostEqual(result["chi2"], 0.2470588, places=6)
        self.assertEqual(result["df"], 1)
        self.assertAlmostEqual(result["p"], 0.6191537, places=6)

    def test_no_events_is_reported_not_divided_by_zero(self):
        result = med.logrank({"A": [(1, 0)], "B": [(2, 0)]})
        self.assertIsNone(result["p"])
        analysis = med.km_analysis({"A": [(1, 0)], "B": [(2, 0)]}, [0])
        self.assertTrue(any("no events" in w for w in analysis["warnings"]))

    def test_median_not_reached(self):
        curve = med.km_curve([(1, 0), (2, 0), (3, 0)])
        self.assertIsNone(med.km_median(curve)[0])

    def test_one_group_is_an_error(self):
        with self.assertRaises(med.FigureError):
            med.logrank({"A": self.A})


class BlandAltmanMath(unittest.TestCase):
    def test_bias_and_limits_of_agreement(self):
        result = med.bland_altman_analysis([1.0, 2.0, 3.0], [1.1, 1.9, 3.2])
        self.assertAlmostEqual(result["bias"], -0.0666667, places=6)
        self.assertAlmostEqual(result["sd"], 0.1527525, places=6)
        self.assertAlmostEqual(result["loa"][0], -0.3661, places=3)
        self.assertAlmostEqual(result["loa"][1], 0.2328, places=3)

    def test_zero_spread_and_small_n_are_flagged(self):
        result = med.bland_altman_analysis([1.0, 2.0, 3.0], [2.0, 3.0, 4.0])
        self.assertEqual(result["sd"], 0.0)
        self.assertTrue(any("collapse onto the bias" in w for w in result["warnings"]))
        self.assertTrue(any("below 30" in w for w in result["warnings"]))

    def test_unpaired_lengths_are_refused(self):
        with self.assertRaises(med.FigureError):
            med.bland_altman_analysis([1.0, 2.0, 3.0], [1.0, 2.0])


class DiagnosticTableMath(unittest.TestCase):
    def test_measures_match_the_hand_computation(self):
        result = med.table_analysis(79, 45, 72, 4)
        self.assertEqual(result["n"], 200)
        self.assertAlmostEqual(result["prevalence"], 0.415, places=6)
        self.assertAlmostEqual(result["metrics"]["sensitivity"][0], 0.951807, places=6)
        self.assertAlmostEqual(result["metrics"]["specificity"][0], 0.615385, places=6)
        self.assertAlmostEqual(result["metrics"]["ppv"][0], 0.637097, places=6)
        self.assertAlmostEqual(result["metrics"]["npv"][0], 0.947368, places=6)
        self.assertAlmostEqual(result["metrics"]["accuracy"][0], 0.755, places=6)
        self.assertAlmostEqual(result["lr_positive"], 2.47470, places=4)
        self.assertAlmostEqual(result["lr_negative"], 0.078313, places=5)

    def test_intervals_are_wilson_and_ordered(self):
        result = med.table_analysis(79, 45, 72, 4)
        for key in ("sensitivity", "specificity", "ppv", "npv", "accuracy"):
            point, low, high = result["metrics"][key]
            self.assertLess(low, point)
            self.assertLess(point, high)

    def test_small_cell_is_flagged(self):
        result = med.table_analysis(79, 45, 72, 4)
        self.assertTrue(any("cell has <5 events" in w for w in result["warnings"]))

    def test_zero_cell_leaves_likelihood_ratios_undefined(self):
        result = med.table_analysis(10, 0, 10, 0)
        self.assertIsNone(result["lr_positive"])
        self.assertEqual(result["lr_negative"], 0.0)  # a perfect negative LR
        self.assertIsNone(result["lr_negative_ci"])
        self.assertTrue(any("likelihood-ratio" in w for w in result["warnings"]))

    def test_empty_and_negative_tables_are_refused(self):
        with self.assertRaises(med.FigureError):
            med.table_analysis(0, 0, 0, 0)
        with self.assertRaises(med.FigureError):
            med.table_analysis(5, -1, 5, 5)


class DiagnosticTableCli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write_2x2(self, body="tp,fp,tn,fn\n79,45,72,4\n", name="t.csv"):
        return write_csv(self.dir, name, body)

    def test_single_row_writes_a_table_png(self):
        out = os.path.join(self.dir, "table.png")
        code, stdout, err = run_main(["table", self.write_2x2(), "--out", out])
        self.assertEqual(code, 0 if HAVE_MPL else 3, err)
        payload = review_of(stdout)
        self.assertEqual(payload["gate"], "med-figures/table")
        self.assertEqual(payload["estimates"]["counts"],
                         {"tp": 79, "fp": 45, "tn": 72, "fn": 4})
        self.assertAlmostEqual(payload["estimates"]["sensitivity"][0], 0.9518)
        if HAVE_MPL:
            self.assertTrue(os.path.isfile(out))
            width, _ = png_size(out)
            self.assertGreater(width, 1700)  # 183 mm at 300 dpi is ~2161 px

    def test_a_table_with_no_positives_still_prints_valid_json(self):
        # Found by probing the installed app: tp=fn=0 leaves sensitivity as NaN,
        # which json.dumps writes and json.loads accepts, but is not JSON — a
        # strict consumer rejects the whole review block over one undefined
        # estimate. The warning already says the group is empty.
        path = self.write_2x2("tp,fp,tn,fn\n0,10,10,0\n", "no_positives.csv")
        out = os.path.join(self.dir, "no_positives.png")
        code, stdout, err = run_main(["table", path, "--out", out])
        self.assertEqual(code, 0 if HAVE_MPL else 3, err)

        def reject(constant):
            raise AssertionError(f"non-finite number in the review block: {constant}")

        payload = json.loads(stdout.split("```review")[1].split("```")[0],
                            parse_constant=reject)
        self.assertIsNone(payload["estimates"]["sensitivity"])
        self.assertIsNotNone(payload["estimates"]["specificity"])
        self.assertIn("sensitivity n/a", stdout)

    def test_columns_can_be_renamed(self):
        path = self.write_2x2("pos,neg,true_neg,false_neg\n10,2,20,1\n",
                              "renamed.csv")
        out = os.path.join(self.dir, "renamed.png")
        code, stdout, err = run_main(["table", path, "--tp", "pos", "--fp", "neg",
                                      "--tn", "true_neg", "--fn", "false_neg",
                                      "--out", out])
        self.assertIn(code, (0, 3), err)
        self.assertEqual(review_of(stdout)["estimates"]["counts"]["tn"], 20)

    def test_several_rows_are_refused_with_a_pointer_to_diag_stats(self):
        path = self.write_2x2("tp,fp,tn,fn\n10,2,20,1\n20,4,18,2\n", "multi.csv")
        code, _, err = run_main(["table", path])
        self.assertEqual(code, 2)
        self.assertIn("one 2x2 table", err)
        self.assertIn("diag_stats.py", err)

    def test_non_whole_and_negative_counts_are_refused(self):
        bad = self.write_2x2("tp,fp,tn,fn\n10.5,2,20,1\n", "fraction.csv")
        code, _, err = run_main(["table", bad])
        self.assertEqual(code, 2)
        self.assertIn("whole number", err)
        negative = self.write_2x2("tp,fp,tn,fn\n10,-2,20,1\n", "negative.csv")
        self.assertEqual(run_main(["table", negative])[0], 2)

    def test_out_cannot_overwrite_the_input(self):
        path = self.write_2x2()
        code, _, err = run_main(["table", path, "--out", path])
        self.assertEqual(code, 2)
        self.assertIn("overwrite the input", err)

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_missing_matplotlib_keeps_the_measures(self):
        path = self.write_2x2()
        out = os.path.join(self.dir, "table.png")
        with mock.patch.object(med, "_import_pyplot", return_value=None):
            code, stdout, _ = run_main(["table", path, "--out", out])
        self.assertEqual(code, 3)
        payload = review_of(stdout)
        self.assertFalse(payload["rendered"])
        self.assertAlmostEqual(payload["estimates"]["specificity"][0], 0.6154)
        self.assertFalse(os.path.exists(out))

    def test_the_printed_output_survives_a_gbk_console(self):
        code, stdout, stderr = run_main(
            ["table", self.write_2x2(), "--out",
             os.path.join(self.dir, "table.png")])
        (stdout + stderr).encode("gbk")


class CliContract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_missing_file_is_an_error_not_a_traceback(self):
        code, _, err = run_main(["roc", os.path.join(self.dir, "nope.csv")])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)

    def test_missing_column_lists_the_ones_found(self):
        path = write_csv(self.dir, "s.csv", "score,outcome\n1,0\n")
        code, _, err = run_main(["roc", path, "--label", "label"])
        self.assertEqual(code, 2)
        self.assertIn("missing column", err)
        self.assertIn("columns found", err)

    def test_non_numeric_value_names_the_line(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\nabc,1\n")
        code, _, err = run_main(["roc", path, "--out", os.path.join(self.dir, "x.png")])
        self.assertEqual(code, 2)
        self.assertIn("line 3", err)

    def test_empty_table_is_refused(self):
        path = write_csv(self.dir, "s.csv", "score,label\n")
        code, _, err = run_main(["roc", path])
        self.assertEqual(code, 2)
        self.assertIn("no data rows", err)

    def test_no_subcommand_returns_two(self):
        self.assertEqual(run_main([])[0], 2)

    def test_unknown_measure_returns_two(self):
        path = write_csv(self.dir, "f.csv", "study,effect,ci_low,ci_high\nA,1,0.5,2\n")
        code, _, _ = run_main(["forest", path, "--measure", "hrr"])
        self.assertEqual(code, 2)

    def test_default_output_sits_beside_the_input(self):
        self.assertEqual(med._default_out(r"C:\d\scores.csv", "roc"),
                         Path(r"C:\d\scores_roc.png"))

    def test_bom_csv_parses(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n")
        code, _, _ = run_main(["roc", path, "--boot", "100",
                               "--out", os.path.join(self.dir, "x.png")])
        self.assertEqual(code, 0 if HAVE_MPL else 3)

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_review_contract_and_sha256(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n4,0\n")
        code, out, _ = run_main(["roc", path, "--boot", "100",
                                 "--out", os.path.join(self.dir, "roc.png")])
        self.assertEqual(code, 0)
        payload = review_of(out)
        self.assertEqual(payload["gate"], "med-figures/roc")
        self.assertEqual(len(payload["input"]["sha256"]), 64)
        self.assertEqual(payload["input"]["rows"], 4)
        self.assertTrue(payload["rendered"])
        self.assertEqual(payload["style"], "openscience")
        self.assertTrue(os.path.isfile(payload["outputs"][0]["path"]))

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_out_parent_directory_is_created(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n")
        out = os.path.join(self.dir, "nested", "fig", "roc.png")
        code, _, _ = run_main(["roc", path, "--boot", "100", "--out", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(out))

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_vector_output_is_a_real_pdf(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n")
        out = os.path.join(self.dir, "roc.png")
        code, _, _ = run_main(["roc", path, "--boot", "100", "--out", out, "--vector"])
        self.assertEqual(code, 0)
        pdf = os.path.join(self.dir, "roc.pdf")
        with open(pdf, "rb") as fh:
            self.assertEqual(fh.read(4), b"%PDF")

    def test_out_cannot_overwrite_the_input(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n")
        code, _, err = run_main(["roc", path, "--out", path])
        self.assertEqual(code, 2)
        self.assertIn("overwrite the input", err)

    def test_non_positive_width_and_nan_cutoff_are_refused(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n")
        self.assertEqual(run_main(["roc", path, "--width-mm", "0"])[0], 2)
        code, _, err = run_main(["roc", path, "--cutoff", "nan",
                                 "--out", os.path.join(self.dir, "x.png")])
        self.assertEqual(code, 2)
        self.assertIn("finite", err)

    def test_the_printed_output_survives_a_gbk_console(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n")
        code, out, err = run_main(["roc", path, "--boot", "100",
                                   "--out", os.path.join(self.dir, "roc.png")])
        (out + err).encode("gbk")  # UnicodeEncodeError for anything cp936 lacks

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_missing_matplotlib_still_reports_the_numbers(self):
        path = write_csv(self.dir, "s.csv", "score,label\n1,0\n2,1\n3,1\n")
        out = os.path.join(self.dir, "roc.png")
        with mock.patch.object(med, "_import_pyplot", return_value=None):
            code, stdout, _ = run_main(["roc", path, "--boot", "100", "--out", out])
        self.assertEqual(code, 3)
        payload = review_of(stdout)
        self.assertFalse(payload["rendered"])
        self.assertTrue(any("matplotlib is not installed" in w
                            for w in payload["warnings"]))
        self.assertFalse(os.path.exists(out))


@unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
class Rendering(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def roc_fixture(self):
        return write_csv(self.dir, "roc.csv",
                         "score,label\n" + "\n".join(
                             f"{0.05 + 0.01 * i:.2f},{'1' if i > 10 else '0'}"
                             for i in range(20)))

    def test_roc_png_has_final_size_pixels(self):
        out = os.path.join(self.dir, "roc.png")
        code, out_text, err = run_main(["roc", self.roc_fixture(), "--boot", "100",
                                        "--out", out])
        self.assertEqual(code, 0, err)
        width, height = png_size(out)
        self.assertGreater(width, 900)   # 89 mm at 300 dpi is ~1051 px
        self.assertGreater(height, 900)
        self.assertGreater(os.path.getsize(out), 20000)

    def test_forest_png_is_a_double_column_figure(self):
        path = write_csv(self.dir, "forest.csv",
                         "study,effect,ci_low,ci_high\n"
                         "A,1.50,1.20,1.875\nB,2.00,1.50,2.667\n"
                         "C,0.80,0.60,1.067\n")
        out = os.path.join(self.dir, "forest.png")
        code, out_text, err = run_main(["forest", path, "--out", out])
        self.assertEqual(code, 0, err)
        width, _ = png_size(out)
        self.assertGreater(width, 1800)  # 183 mm at 300 dpi is ~2161 px
        payload = review_of(out_text)
        self.assertAlmostEqual(payload["estimates"]["heterogeneity"]["q"],
                               20.6922, places=3)

    def test_km_png_and_risk_table(self):
        path = write_csv(self.dir, "km.csv",
                         "group,time,event\n" + "\n".join(
                             f"{g},{t},{e}"
                             for g, rows in (("A", [(1, 1), (2, 1), (3, 0), (4, 1), (5, 0)]),
                                             ("B", [(1, 0), (2, 1), (3, 0), (4, 1), (5, 0)]))
                             for t, e in rows))
        out = os.path.join(self.dir, "km.png")
        code, out_text, err = run_main(["km", path, "--times", "0,2,4",
                                        "--time-unit", "months", "--out", out])
        self.assertEqual(code, 0, err)
        self.assertGreater(os.path.getsize(out), 15000)
        payload = review_of(out_text)
        self.assertEqual(payload["estimates"]["risk_times"], [0.0, 2.0, 4.0])

    def test_bland_altman_png(self):
        path = write_csv(self.dir, "ba.csv",
                         "a,b\n" + "\n".join(
                             f"{10 + i * 0.5},{10.1 + i * 0.5}" for i in range(12)))
        out = os.path.join(self.dir, "ba.png")
        code, out_text, err = run_main(["bland-altman", path, "--a", "a", "--b", "b",
                                        "--out", out])
        self.assertEqual(code, 0, err)
        self.assertGreater(os.path.getsize(out), 10000)
        self.assertAlmostEqual(review_of(out_text)["estimates"]["bias"], -0.1, places=6)


class FlowModels(unittest.TestCase):
    def test_strobe_example_checks_pass(self):
        model = med.flow_model("strobe", med._example_flow("strobe"))
        self.assertEqual(len(model["checks"]), 2)
        self.assertTrue(all(c.ok for c in model["checks"]))

    def test_strobe_wrong_total_shows_both_sides(self):
        data = med._example_flow("strobe")
        data["assessed"] = 501
        failed = [c for c in med.flow_model("strobe", data)["checks"] if not c.ok]
        self.assertEqual(len(failed), 1)
        self.assertEqual((failed[0].left, failed[0].right), (501, 500))

    def test_strobe_reason_counts_enter_the_sum(self):
        data = med._example_flow("strobe")
        data["excluded"][0]["n"] = 25  # total becomes 31, assessed is 500
        self.assertFalse(all(c.ok for c in med.flow_model("strobe", data)["checks"]))

    def test_prisma_example_chain_has_four_checks(self):
        model = med.flow_model("prisma", med._example_flow("prisma"))
        self.assertEqual(len(model["checks"]), 4)
        self.assertTrue(all(c.ok for c in model["checks"]))

    def test_prisma_one_break_is_reported_by_both_equations(self):
        data = med._example_flow("prisma")
        data["records_screened"] = 1049
        failed = [c for c in med.flow_model("prisma", data)["checks"] if not c.ok]
        self.assertIn("identified (databases + registers) = duplicates + screened",
                      [c.label for c in failed])
        self.assertIn("screened = records excluded + reports sought",
                      [c.label for c in failed])

    def test_prisma_more_studies_than_reports_warns(self):
        data = med._example_flow("prisma")
        data["reports_excluded"] = [{"reason": "Wrong population", "n": 40},
                                    {"reason": "Wrong outcome", "n": 10}]
        data["reports_included"] = 90
        data["studies_included"] = 100
        model = med.flow_model("prisma", data)
        self.assertTrue(all(c.ok for c in model["checks"]))
        self.assertTrue(any("more studies than reports" in w
                            for w in model["warnings"]))

    def test_consort_example_equations(self):
        model = med.flow_model("consort", med._example_flow("consort"))
        self.assertEqual(len(model["checks"]), 6)
        self.assertTrue(all(c.ok for c in model["checks"]))

    def test_consort_arm_break_is_named_after_the_arm(self):
        data = med._example_flow("consort")
        data["arms"][0]["analysed"] = 211
        failed = [c for c in med.flow_model("consort", data)["checks"] if not c.ok]
        self.assertEqual(len(failed), 1)
        self.assertIn("Intervention: received = analysed + lost/excluded",
                      failed[0].label)

    def test_bad_counts_are_refused_with_the_field_named(self):
        cases = [
            ("assessed", -1), ("included", True), ("analysed", 1.5),
        ]
        for key, value in cases:
            data = med._example_flow("strobe")
            data[key] = value
            with self.assertRaises(med.FigureError) as caught:
                med.flow_model("strobe", data)
            self.assertIn(key, str(caught.exception))
        data = med._example_flow("strobe")
        del data["included"]
        with self.assertRaises(med.FigureError):
            med.flow_model("strobe", data)

    def test_bad_reason_lists_are_refused(self):
        for value in ("nope", [{"reason": "", "n": 1}],
                      [{"reason": "ok", "n": -1}], [{"n": 1}]):
            data = med._example_flow("strobe")
            data["excluded"] = value
            with self.assertRaises(med.FigureError):
                med.flow_model("strobe", data)

    def test_consort_needs_two_to_four_arms(self):
        data = med._example_flow("consort")
        data["arms"] = data["arms"][:1]
        with self.assertRaises(med.FigureError):
            med.flow_model("consort", data)
        data["arms"] = data["arms"] * 5
        with self.assertRaises(med.FigureError):
            med.flow_model("consort", data)

    def test_unknown_design_and_non_object_input(self):
        with self.assertRaises(med.FigureError):
            med.flow_model("bogus", {})
        with self.assertRaises(med.FigureError):
            med.flow_model("strobe", ["not", "an", "object"])


class FlowLayout(unittest.TestCase):
    def test_every_box_stays_inside_its_canvas(self):
        # This is the invariant that caught a clipped bottom row during
        # development: the canvas must contain the text that is drawn.
        for design in ("strobe", "prisma", "consort"):
            model = med.flow_model(design, med._example_flow(design))
            layout = med.flow_layout(model, 183)
            xmin, xmax, ymin, ymax = layout["canvas"]
            self.assertGreater(xmax, 0)
            self.assertLess(ymin, ymax)
            for box in layout["boxes"]:
                self.assertGreaterEqual(box["x"] - box["w"] / 2, xmin - 1e-6)
                self.assertLessEqual(box["x"] + box["w"] / 2, xmax + 1e-6)
                self.assertGreaterEqual(box["y"] - box["h"] / 2, ymin - 1e-6)
                self.assertLessEqual(box["y"] + box["h"] / 2, ymax + 1e-6)
            self.assertTrue(layout["arrows"])


class FlowCli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write_json(self, name: str, data: dict, encoding: str = "utf-8") -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding=encoding) as fh:
            json.dump(data, fh, ensure_ascii=False)
        return path

    def test_example_option_prints_a_usable_template(self):
        for design in ("strobe", "prisma", "consort"):
            code, out, err = run_main(["flow", "--example", design])
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["design"], design)
            self.assertTrue(all(c.ok for c in med.flow_model(design, data)["checks"]))

    def test_missing_json_is_a_usage_error(self):
        code, _, err = run_main(["flow"])
        self.assertEqual(code, 2)
        self.assertIn("input JSON", err)

    def test_wrong_counts_refuse_to_draw(self):
        data = med._example_flow("strobe")
        data["assessed"] = 501
        path = self.write_json("wrong.json", data)
        out = os.path.join(self.dir, "wrong.png")
        code, stdout, err = run_main(["flow", path, "--out", out])
        self.assertEqual(code, 2)
        self.assertIn("do not add up", err)
        self.assertIn("FAIL", err)
        self.assertNotIn("```review", stdout)
        self.assertFalse(os.path.exists(out))

    def test_bad_json_and_missing_design(self):
        path = os.path.join(self.dir, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("not json")
        code, _, err = run_main(["flow", path])
        self.assertEqual(code, 2)
        self.assertIn("invalid JSON", err)
        empty = self.write_json("empty.json", {})
        code, _, err = run_main(["flow", empty])
        self.assertEqual(code, 2)
        self.assertIn("design", err)

    def test_out_cannot_overwrite_the_input(self):
        path = self.write_json("f.json", med._example_flow("strobe"))
        code, _, err = run_main(["flow", path, "--out", path])
        self.assertEqual(code, 2)
        self.assertIn("overwrite the input", err)

    def test_utf16_json_is_read(self):
        path = self.write_json("utf16.json", med._example_flow("strobe"),
                               encoding="utf-16")
        out = os.path.join(self.dir, "utf16.png")
        code, stdout, err = run_main(["flow", path, "--out", out])
        self.assertIn(code, (0, 3), err)
        self.assertEqual(review_of(stdout)["design"], "strobe")

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_valid_file_renders_a_double_column_png(self):
        path = self.write_json("prisma.json", med._example_flow("prisma"))
        out = os.path.join(self.dir, "prisma.png")
        code, stdout, err = run_main(["flow", path, "--out", out])
        self.assertEqual(code, 0, err)
        payload = review_of(stdout)
        self.assertEqual(payload["gate"], "med-figures/flow")
        self.assertEqual(len(payload["checks"]), 4)
        self.assertTrue(payload["rendered"])
        self.assertTrue(os.path.isfile(out))
        width, _ = png_size(out)
        self.assertGreater(width, 1800)
        self.assertGreater(os.path.getsize(out), 30000)

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_missing_matplotlib_keeps_the_check_report(self):
        path = self.write_json("strobe.json", med._example_flow("strobe"))
        out = os.path.join(self.dir, "strobe.png")
        with mock.patch.object(med, "_import_pyplot", return_value=None):
            code, stdout, _ = run_main(["flow", path, "--out", out])
        self.assertEqual(code, 3)
        payload = review_of(stdout)
        self.assertFalse(payload["rendered"])
        self.assertTrue(any("matplotlib is not installed" in w
                            for w in payload["warnings"]))
        self.assertFalse(os.path.exists(out))

    def test_the_printed_output_survives_a_gbk_console(self):
        path = self.write_json("strobe.json", med._example_flow("strobe"))
        out = os.path.join(self.dir, "strobe.png")
        code, stdout, stderr = run_main(["flow", path, "--out", out])
        (stdout + stderr).encode("gbk")


if __name__ == "__main__":
    unittest.main(verbosity=2)