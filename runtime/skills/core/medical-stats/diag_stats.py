#!/usr/bin/env python3
"""Diagnostic-accuracy statistics from a 2x2 table, stdlib-only.

Input: CSV with header ``tp,fp,tn,fn`` — one row per cutoff (or a single row).
Output: per-row metrics with 95% confidence intervals plus one ```review JSON
block, matching the stats-integrity / domain-check output convention.

Intervals: Wilson score by default; ``--exact`` uses Clopper-Pearson, which is
what a reviewer asks for when a cell holds fewer than five events (the warning
below says so). Likelihood ratios get the log-scale delta interval from Simel et
al. (1991) - the standard for LR+ / LR-, and the one that respects their
asymmetric scale.

Usage:
    python diag_stats.py <table.csv>            # Wilson intervals
    python diag_stats.py --exact <table.csv>    # Clopper-Pearson intervals

(The text above is deliberately ASCII: this prints on a Chinese Windows console,
where a U+2212 minus or an en dash raises UnicodeEncodeError instead of showing
usage.)
"""
from __future__ import annotations

import csv
import json
import math
import sys

Z = 1.959963984540054  # two-sided 95%


# --------------------------------------------------------------------------- #
# Intervals
# --------------------------------------------------------------------------- #


def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Proportion with Wilson score 95% CI."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + Z * Z / n
    c = p + Z * Z / (2 * n)
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return (p, (c - h) / d, (c + h) / d)


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p). Small n only — this is a 2x2 table."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float, float]:
    """Proportion with the exact Clopper-Pearson interval.

    Stdlib only: each bound is a bisection on the binomial CDF, which is monotone
    in p, so 60 iterations is far past double precision. Used when a cell has
    fewer than five events — Wilson is optimistic exactly there.
    """
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    half = alpha / 2

    # Lower bound: the p at which P(X >= k) = alpha/2, which decreases as p grows.
    if k == 0:
        lo = 0.0
    else:
        left, right = 0.0, p
        for _ in range(60):
            mid = (left + right) / 2
            if 1 - _binom_cdf(k - 1, n, mid) < half:
                left = mid
            else:
                right = mid
        lo = (left + right) / 2

    # Upper bound: the p at which P(X <= k) = alpha/2.
    if k == n:
        hi = 1.0
    else:
        left, right = p, 1.0
        for _ in range(60):
            mid = (left + right) / 2
            if _binom_cdf(k, n, mid) > half:
                left = mid
            else:
                right = mid
        hi = (left + right) / 2

    return (p, lo, hi)


def interval(k: int, n: int, exact: bool) -> tuple[float, float, float]:
    return clopper_pearson(k, n) if exact else wilson(k, n)


def lr_intervals(tp: int, fp: int, tn: int, fn: int,
                 sens: float, spec: float) -> tuple[tuple[float, float] | None,
                                                    tuple[float, float] | None]:
    """95% CIs for LR+ and LR- on the log scale (Simel 1991).

    A likelihood ratio is a ratio, so its interval is asymmetric and must be built
    on log(LR): SE(ln LR+) = sqrt((1-sens)/(sens*n1) + spec/((1-spec)*n0)). A
    symmetric interval on the LR itself would put the lower bound below zero.
    Undefined (None) when a cell is zero — adding 0.5 to the cells to paper over it
    changes the estimate, so it is left to the reader to decide.
    """
    n1 = tp + fn  # diseased
    n0 = tn + fp  # non-diseased
    if n1 == 0 or n0 == 0 or not (0.0 < sens < 1.0) or not (0.0 < spec < 1.0):
        return (None, None)

    se_pos = math.sqrt((1 - sens) / (sens * n1) + spec / ((1 - spec) * n0))
    log_pos = math.log(sens) - math.log(1 - spec)
    pos = (math.exp(log_pos - Z * se_pos), math.exp(log_pos + Z * se_pos))

    se_neg = math.sqrt(sens / ((1 - sens) * n1) + (1 - spec) / (spec * n0))
    log_neg = math.log(1 - sens) - math.log(spec)
    neg = (math.exp(log_neg - Z * se_neg), math.exp(log_neg + Z * se_neg))
    return (pos, neg)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def _fmt(t: tuple[float, float, float] | None) -> str:
    if t is None or math.isnan(t[0]):
        return "n/a"
    return f"{t[0]:.3f} (95% CI {t[1]:.3f}–{t[2]:.3f})"


def _fmt_ci(ci: tuple[float, float] | None, point: float | None) -> str:
    if point is None:
        return "undefined"
    if ci is None:
        return f"{point:.3g} (CI undefined: a cell is zero)"
    return f"{point:.3g} (95% CI {ci[0]:.3g}–{ci[1]:.3g})"


def analyze(row: dict, exact: bool = False) -> dict:
    tp, fp, tn, fn = (int(row[k]) for k in ("tp", "fp", "tn", "fn"))
    n = tp + fp + tn + fn
    prev = (tp + fn) / n if n else float("nan")
    sens = interval(tp, tp + fn, exact)
    spec = interval(tn, tn + fp, exact)
    ppv = interval(tp, tp + fp, exact)
    npv = interval(tn, tn + fn, exact)
    lr_p = sens[0] / (1 - spec[0]) if spec[0] < 1 else float("inf")
    lr_n = (1 - sens[0]) / spec[0] if spec[0] > 0 else float("inf")
    lr_p_ci, lr_n_ci = lr_intervals(tp, fp, tn, fn, sens[0], spec[0])
    return {
        "n": n,
        "prevalence": round(prev, 4),
        "interval_method": "clopper-pearson" if exact else "wilson",
        "sensitivity": [round(x, 4) for x in sens],
        "specificity": [round(x, 4) for x in spec],
        "ppv": [round(x, 4) for x in ppv],
        "npv": [round(x, 4) for x in npv],
        "lr_positive": round(lr_p, 3) if math.isfinite(lr_p) else None,
        "lr_negative": round(lr_n, 3) if math.isfinite(lr_n) else None,
        "lr_positive_ci": [round(x, 3) for x in lr_p_ci] if lr_p_ci else None,
        "lr_negative_ci": [round(x, 3) for x in lr_n_ci] if lr_n_ci else None,
        "youden_j": round(sens[0] + spec[0] - 1, 4),
        "warnings": _warnings(tp, fp, tn, fn, lr_p_ci, exact),
    }


def _warnings(tp: int, fp: int, tn: int, fn: int,
              lr_p_ci: tuple[float, float] | None, exact: bool) -> list[str]:
    w = []
    if min(tp, fp, tn, fn) < 5:
        # The advice has to match the interval actually used: telling someone who
        # already passed --exact to rerun with --exact is worse than saying nothing.
        w.append(
            "a 2x2 cell has <5 events; these are exact (Clopper-Pearson) intervals "
            "— report them as exact"
            if exact else
            "a 2x2 cell has <5 events; Wilson is optimistic there — rerun with "
            "--exact for Clopper-Pearson intervals"
        )
    if tp + fp == 0 or tn + fn == 0:
        w.append("PPV or NPV undefined (zero denominator)")
    if (tp + fn) and (tn + fp) and abs((tp + fn) / (tp + fn + tn + fp) - 0.5) > 0.4:
        w.append("prevalence far from 50%; PPV/NPV do not transfer to other settings")
    if lr_p_ci is None:
        w.append("likelihood-ratio CIs undefined (a cell is zero); adding 0.5 would "
                 "change the estimate, so the decision is left to the reader")
    return w


def main(argv: list[str]) -> int:
    # A Windows console is not UTF-8: printing "⚠" there raised
    # UnicodeEncodeError and turned a warning into a traceback. Degrade
    # unprintable characters instead of failing the analysis.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    args = list(argv)
    exact = "--exact" in args
    if exact:
        args.remove("--exact")
    if len(args) != 1:
        print(__doc__)
        return 2
    results = []
    with open(args[0], newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                results.append(analyze(row, exact=exact))
            except (KeyError, ValueError) as e:
                print(f"skipping row ({e}): {row}", file=sys.stderr)
    if not results:
        print("no valid rows; expected header tp,fp,tn,fn", file=sys.stderr)
        return 1
    for i, r in enumerate(results):
        print(f"--- cutoff row {i + 1} (n={r['n']}, prevalence={r['prevalence']:.3f}, "
              f"{r['interval_method']} intervals)")
        print("  sensitivity  ", _fmt(r["sensitivity"]))
        print("  specificity  ", _fmt(r["specificity"]))
        print("  PPV          ", _fmt(r["ppv"]))
        print("  NPV          ", _fmt(r["npv"]))
        print(f"  LR+ {_fmt_ci(r['lr_positive_ci'], r['lr_positive'])}   "
              f"LR- {_fmt_ci(r['lr_negative_ci'], r['lr_negative'])}   "
              f"Youden J {r['youden_j']}")
        for wmsg in r["warnings"]:
            print(f"  warning: {wmsg}")
    print("```review")
    print(json.dumps({"gate": "medical-stats/diag_stats", "rows": results},
                     ensure_ascii=False, indent=1))
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))