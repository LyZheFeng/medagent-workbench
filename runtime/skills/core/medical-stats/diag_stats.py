#!/usr/bin/env python3
"""Diagnostic-accuracy statistics from a 2x2 table, stdlib-only.

Input: CSV with header ``tp,fp,tn,fn`` — one row per cutoff (or a single row).
Output: per-row metrics with Wilson 95% CIs plus one ```review``` JSON block,
matching the stats-integrity / domain-check output convention.

Usage: python diag_stats.py <table.csv>
"""
from __future__ import annotations

import csv
import json
import math
import sys

Z = 1.959963984540054  # two-sided 95%


def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Proportion with Wilson score 95% CI."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + Z * Z / n
    c = p + Z * Z / (2 * n)
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return (p, (c - h) / d, (c + h) / d)


def _fmt(p: float, lo: float, hi: float) -> str:
    if math.isnan(p):
        return "n/a"
    return f"{p:.3f} (95% CI {lo:.3f}–{hi:.3f})"


def analyze(row: dict) -> dict:
    tp, fp, tn, fn = (int(row[k]) for k in ("tp", "fp", "tn", "fn"))
    n = tp + fp + tn + fn
    prev = (tp + fn) / n if n else float("nan")
    sens = wilson(tp, tp + fn)
    spec = wilson(tn, tn + fp)
    ppv = wilson(tp, tp + fp)
    npv = wilson(tn, tn + fn)
    lr_p = sens[0] / (1 - spec[0]) if spec[0] < 1 else float("inf")
    lr_n = (1 - sens[0]) / spec[0] if spec[0] > 0 else float("inf")
    return {
        "n": n,
        "prevalence": round(prev, 4),
        "sensitivity": [round(x, 4) for x in sens],
        "specificity": [round(x, 4) for x in spec],
        "ppv": [round(x, 4) for x in ppv],
        "npv": [round(x, 4) for x in npv],
        "lr_positive": round(lr_p, 3) if math.isfinite(lr_p) else None,
        "lr_negative": round(lr_n, 3) if math.isfinite(lr_n) else None,
        "youden_j": round(sens[0] + spec[0] - 1, 4),
        "warnings": _warnings(tp, fp, tn, fn),
    }


def _warnings(tp: int, fp: int, tn: int, fn: int) -> list[str]:
    w = []
    if min(tp, fp, tn, fn) < 5:
        w.append("a 2x2 cell has <5 events; CIs are unstable — report exact (Clopper-Pearson) intervals")
    if tp + fp == 0 or tn + fn == 0:
        w.append("PPV or NPV undefined (zero denominator)")
    if (tp + fn) and (tn + fp) and abs((tp + fn) / (tp + fn + tn + fp) - 0.5) > 0.4:
        w.append("prevalence far from 50%; PPV/NPV do not transfer to other settings")
    return w


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    results = []
    with open(argv[1], newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                results.append(analyze(row))
            except (KeyError, ValueError) as e:
                print(f"skipping row ({e}): {row}", file=sys.stderr)
    if not results:
        print("no valid rows; expected header tp,fp,tn,fn", file=sys.stderr)
        return 1
    for i, r in enumerate(results):
        print(f"--- cutoff row {i + 1} (n={r['n']}, prevalence={r['prevalence']:.3f})")
        print("  sensitivity  ", _fmt(*r["sensitivity"]))
        print("  specificity  ", _fmt(*r["specificity"]))
        print("  PPV          ", _fmt(*r["ppv"]))
        print("  NPV          ", _fmt(*r["npv"]))
        print(f"  LR+ {r['lr_positive']}   LR- {r['lr_negative']}   Youden J {r['youden_j']}")
        for wmsg in r["warnings"]:
            print(f"  ⚠ {wmsg}")
    print("```review")
    print(json.dumps({"gate": "medical-stats/diag_stats", "rows": results}, ensure_ascii=False, indent=1))
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
