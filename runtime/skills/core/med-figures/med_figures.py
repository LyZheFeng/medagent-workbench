#!/usr/bin/env python3
"""Medical publication figures from data: ROC, forest, Kaplan-Meier,
Bland-Altman, the diagnostic 2x2 table, and STROBE/PRISMA/CONSORT flow
diagrams.

The numbers are computed here, in stdlib, so they can be checked and so the
script still reports them when matplotlib is missing; matplotlib only draws.
Flow diagrams are laid out only after every count identity holds: a diagram
whose boxes do not sum is refused, not drawn. Every run writes a PNG at 300 dpi
(optionally a PDF beside it) and one ```review JSON block carrying the input
file's sha256, the estimates/checks, the warnings and the output paths - a
figure that cannot be traced to the code and data that made it is the thing this
script exists to prevent.

Chart forms follow the med-figures skill: ROC with an AUC confidence interval,
a forest plot with a heterogeneity footnote, Kaplan-Meier with a number-at-risk
table and the log-rank p, Bland-Altman with the bias and limits of agreement,
the 2x2 diagnostic table with its accuracy measures and intervals, and the
three reporting-guideline flow diagrams. The style is
publication-figures/openscience.mplstyle, resolved beside this skill's
directory; journal column widths are in millimetres.

Usage:
    python med_figures.py roc scores.csv [--score col] [--label col] [--cutoff x]
    python med_figures.py forest studies.csv [--measure rr|or|hr|md] [--model random|fixed]
    python med_figures.py km survival.csv [--time col] [--event col] [--group col] [--times 0,12,24]
    python med_figures.py bland-altman pairs.csv [--a col] [--b col]
    python med_figures.py table 2x2.csv [--tp tp] [--fp fp] [--tn tn] [--fn fn]
    python med_figures.py flow flow.json [--design strobe|prisma|consort]
    python med_figures.py flow --example prisma        # print a filled template
    python med_figures.py km data.csv --out figures/km.png --vector

Exit codes: 0 figure written; 2 bad input/usage; 3 estimates computed but no
figure (matplotlib not installed) - install it with `pip install matplotlib`.

(Console text is deliberately ASCII: this runs on a Chinese Windows console,
where an en dash or a superscript raises UnicodeEncodeError instead of printing.)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

Z = 1.959963984540054  # two-sided 95%
GATE = "med-figures"
STYLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "publication-figures"
    / "openscience.mplstyle"
)
# Slots 1-8 of the shared palette, in order; a figure never invents a hue.
PALETTE = ["#2a78d6", "#1baf7a", "#eda100", "#008300",
           "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
INK = "#2a2723"
MUTED = "#8c877d"
GRID = "#e7e3da"


class FigureError(Exception):
    """Bad input or a data shape this chart cannot represent."""


# --------------------------------------------------------------------------- #
# Intervals and distributions (stdlib; same conventions as diag_stats.py)
# --------------------------------------------------------------------------- #


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float, float]:
    """Proportion with Wilson score 95% CI."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - h) / d, (c + h) / d)


def _gser(a: float, x: float) -> float:
    """Lower regularized gamma P(a, x) by its series (x < a + 1)."""
    ap = a
    term = 1.0 / a
    total = term
    for _ in range(1000):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * 1e-15:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Upper regularized gamma Q(a, x) by its continued fraction (x >= a + 1)."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """P(chi-square with df > x), the p-value of a Q or log-rank statistic."""
    if df <= 0:
        raise FigureError("chi-square degrees of freedom must be positive")
    if x < 0:
        return float("nan")
    if x == 0:
        return 1.0
    a = df / 2.0
    return 1.0 - _gser(a, x / 2.0) if x / 2.0 < a + 1 else _gcf(a, x / 2.0)


def _invert(matrix: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inversion with partial pivoting (small matrices only)."""
    n = len(matrix)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
           for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise FigureError("the log-rank variance matrix is singular "
                              "(no information to compare the groups at any "
                              "event time)")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        lead = aug[col][col]
        aug[col] = [v / lead for v in aug[col]]
        for r in range(n):
            if r != col and aug[r][col]:
                factor = aug[r][col]
                aug[r] = [rv - factor * cv for rv, cv in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #


@dataclass
class Table:
    path: Path
    sha256: str
    header: list[str]
    rows: list[dict]
    line_offset: int = 2

    @property
    def n(self) -> int:
        return len(self.rows)


def read_table(path: str | Path, required: list[str]) -> Table:
    p = Path(path)
    if not p.is_file():
        raise FigureError(f"no such file: {p}")
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise FigureError(f"{p}: not UTF-8 text ({e})")
    reader = csv.DictReader(io.StringIO(text))
    header = list(reader.fieldnames or [])
    missing = [c for c in required if c not in header]
    if missing:
        raise FigureError(
            f"{p.name}: missing column {', '.join(repr(c) for c in missing)} "
            f"(columns found: {', '.join(header) if header else 'none'})"
        )
    rows = [r for r in reader if any((v or "").strip() for v in r.values()
                                     if isinstance(v, str))]
    if not rows:
        raise FigureError(f"{p.name}: the table has no data rows")
    return Table(p, hashlib.sha256(raw).hexdigest(), header, rows)


def num(row: dict, col: str, line: int) -> float:
    value = (row.get(col) or "").strip()
    if not value:
        raise FigureError(f"line {line}: column {col!r} is empty")
    try:
        number = float(value)
    except ValueError:
        raise FigureError(f"line {line}: column {col!r} is not a number: {value!r}")
    if not math.isfinite(number):
        raise FigureError(f"line {line}: column {col!r} is not finite: {value!r}")
    return number


def label01(row: dict, col: str, line: int) -> int:
    value = (row.get(col) or "").strip()
    if value not in {"0", "1"}:
        raise FigureError(f"line {line}: column {col!r} must be 0 or 1, got {value!r}")
    return int(value)


def _round(x: float | None, nd: int = 4) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, nd)


def _fmt_p(p: float) -> str:
    """Never print p = 0: the exact value is below the resolution of the test."""
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


# --------------------------------------------------------------------------- #
# ROC
# --------------------------------------------------------------------------- #


def auc(scores: list[float], labels: list[int]) -> float:
    """AUC by the Mann-Whitney rank statistic; ties count 0.5 each."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise FigureError("ROC needs both a positive and a negative class")
    pairs = sorted(zip(scores, labels))
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_pos = sum(r for r, (_, y) in zip(ranks, pairs) if y == 1)
    return (r_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def roc_points(scores: list[float], labels: list[int]) -> list[dict]:
    """Empirical ROC points, one per distinct score, from (0,0) to (1,1)."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise FigureError("ROC needs both a positive and a negative class")
    points = [{"fpr": 0.0, "tpr": 0.0, "threshold": float("inf")}]
    for t in sorted(set(scores), reverse=True):
        tp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 1)
        fp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 0)
        point = {"fpr": fp / n_neg, "tpr": tp / n_pos, "threshold": t}
        if point["fpr"] == points[-1]["fpr"] and point["tpr"] == points[-1]["tpr"]:
            continue
        points.append(point)
    if points[-1]["fpr"] != 1.0 or points[-1]["tpr"] != 1.0:
        points.append({"fpr": 1.0, "tpr": 1.0, "threshold": float("-inf")})
    return points


def _sens_spec_at(scores: list[float], labels: list[int],
                  cutoff: float) -> tuple[int, int, int, int]:
    tp = sum(1 for s, y in zip(scores, labels) if s >= cutoff and y == 1)
    fn = sum(1 for s, y in zip(scores, labels) if s < cutoff and y == 1)
    fp = sum(1 for s, y in zip(scores, labels) if s >= cutoff and y == 0)
    tn = sum(1 for s, y in zip(scores, labels) if s < cutoff and y == 0)
    return tp, fp, tn, fn


def roc_analysis(scores: list[float], labels: list[int],
                 cutoff: float | None = None, boot: int = 2000,
                 seed: int = 2026) -> dict:
    if boot < 100:
        raise FigureError("--boot must be at least 100 resamples")
    if cutoff is not None and not math.isfinite(cutoff):
        raise FigureError("--cutoff must be a finite number")
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    auc_value = auc(scores, labels)
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    rng = random.Random(seed)
    draws = []
    for _ in range(boot):
        sp = [rng.choice(positives) for _ in positives]
        sn = [rng.choice(negatives) for _ in negatives]
        draws.append(auc(sp + sn, [1] * len(sp) + [0] * len(sn)))
    draws.sort()
    ci_low = draws[int(0.025 * boot)]
    ci_high = draws[min(boot - 1, int(0.975 * boot))]

    points = roc_points(scores, labels)
    finite = [p for p in points if math.isfinite(p["threshold"])]
    best = max(finite, key=lambda p: p["tpr"] - p["fpr"]) if finite else None
    if cutoff is None:
        if best is None:
            raise FigureError("ROC has no finite score to place an operating point on")
        operating = dict(best)
        op_source = "youden"
    else:
        operating = {"threshold": cutoff}
        op_source = "given"
    tp, fp, tn, fn = _sens_spec_at(scores, labels, operating["threshold"])
    sens = wilson(tp, tp + fn)
    spec = wilson(tn, tn + fp)
    operating["tpr"] = sens[0]
    operating["fpr"] = 1 - spec[0]
    operating["sensitivity_ci"] = (sens[1], sens[2])
    operating["specificity_ci"] = (spec[1], spec[2])

    warnings = []
    if min(n_pos, n_neg) < 10:
        warnings.append(
            f"only {min(n_pos, n_neg)} patients in the smaller class; the "
            "bootstrap interval is unstable below 10"
        )
    if n_pos / n_neg > 4 or n_neg / n_pos > 4:
        warnings.append("class imbalance over 4:1; ROC/AUC is prevalence-free but "
                        "the operating point's PPV will not transfer")
    if ci_high - ci_low > 0.2:
        warnings.append("AUC 95% CI is wider than 0.20: too imprecise to rank this test")
    if cutoff is not None and not (min(scores) <= cutoff <= max(scores)):
        warnings.append("--cutoff is outside the observed score range; it is an "
                        "extrapolated operating point, not one the data contains")
    return {
        "n": len(scores),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "prevalence": n_pos / len(scores),
        "auc": auc_value,
        "auc_ci": (ci_low, ci_high),
        "bootstrap": boot,
        "seed": seed,
        "points": points,
        "operating": operating,
        "operating_source": op_source,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Forest plot
# --------------------------------------------------------------------------- #


@dataclass
class Study:
    name: str
    effect: float
    low: float
    high: float
    y: float          # analysis scale (log for ratio measures)
    se: float
    weight_fixed: float = 0.0
    weight_random: float = 0.0


def forest_analysis(studies: list[Study], log_scale: bool,
                    model: str = "random") -> dict:
    if len(studies) < 1:
        raise FigureError("forest plot needs at least one study")
    warnings = []
    for s in studies:
        if s.low >= s.high:
            raise FigureError(f"study {s.name!r}: the lower CI must be below the upper CI")
        if not (s.low <= s.effect <= s.high):
            raise FigureError(
                f"study {s.name!r}: the effect {s.effect:g} is outside its CI "
                f"({s.low:g}, {s.high:g})"
            )
        if log_scale and min(s.effect, s.low, s.high) <= 0:
            raise FigureError(
                f"study {s.name!r}: a ratio measure cannot be zero or negative "
                f"({s.effect:g})"
            )
        s.y = math.log(s.effect) if log_scale else s.effect
        if log_scale:
            s.se = (math.log(s.high) - math.log(s.low)) / (2 * Z)
        else:
            s.se = (s.high - s.low) / (2 * Z)
        if not (s.se > 0):
            raise FigureError(f"study {s.name!r}: zero standard error from its CI")

    fixed_w = [1.0 / (s.se * s.se) for s in studies]
    sum_w = sum(fixed_w)
    fixed_y = sum(w * s.y for w, s in zip(fixed_w, studies)) / sum_w
    fixed_se = math.sqrt(1.0 / sum_w)
    q = sum(w * (s.y - fixed_y) ** 2 for w, s in zip(fixed_w, studies))
    df = len(studies) - 1
    p_het = chi2_sf(q, df) if df > 0 else 1.0
    i2 = max(0.0, (q - df) / q) if q > 0 else 0.0
    c = sum_w - sum(w * w for w in fixed_w) / sum_w
    tau2 = max(0.0, (q - df) / c) if df > 0 and c > 0 else 0.0
    random_w = [1.0 / (s.se * s.se + tau2) for s in studies]
    sum_rw = sum(random_w)
    random_y = sum(w * s.y for w, s in zip(random_w, studies)) / sum_rw
    random_se = math.sqrt(1.0 / sum_rw)
    if model == "fixed":
        chosen_y, chosen_se, chosen_w = fixed_y, fixed_se, fixed_w
    else:
        chosen_y, chosen_se, chosen_w = random_y, random_se, random_w
    for s, wf, wr in zip(studies, fixed_w, random_w):
        s.weight_fixed = wf / sum_w
        s.weight_random = wr / sum_rw
    if len(studies) == 1:
        warnings.append("one study: the pooled estimate is that study's estimate, "
                        "not a meta-analysis")
    if len(studies) < 5:
        warnings.append(f"{len(studies)} studies: the heterogeneity statistics are "
                        "unstable below five")
    if i2 > 0.75:
        warnings.append(f"I2 = {i2:.0%}: substantial heterogeneity; report the "
                        "random-effects estimate and its tau2")
    return {
        "studies": studies,
        "log_scale": log_scale,
        "model": model,
        "fixed": {"effect": math.exp(fixed_y) if log_scale else fixed_y,
                  "ci": ((math.exp(fixed_y - Z * fixed_se), math.exp(fixed_y + Z * fixed_se))
                         if log_scale else (fixed_y - Z * fixed_se, fixed_y + Z * fixed_se))},
        "random": {"effect": math.exp(random_y) if log_scale else random_y,
                   "ci": ((math.exp(random_y - Z * random_se), math.exp(random_y + Z * random_se))
                          if log_scale else (random_y - Z * random_se, random_y + Z * random_se))},
        "chosen": {"effect": math.exp(chosen_y) if log_scale else chosen_y,
                   "ci": ((math.exp(chosen_y - Z * chosen_se), math.exp(chosen_y + Z * chosen_se))
                          if log_scale else (chosen_y - Z * chosen_se, chosen_y + Z * chosen_se))},
        "q": q,
        "df": df,
        "p_heterogeneity": p_het,
        "i2": i2,
        "tau2": tau2,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Kaplan-Meier
# --------------------------------------------------------------------------- #


def km_curve(rows: list[tuple[float, int]]) -> list[dict]:
    """Kaplan-Meier estimate with Greenwood variance and log-log 95% CI."""
    data = sorted(rows)
    at_risk = len(data)
    survival = 1.0
    greenwood = 0.0
    curve = [{"time": 0.0, "survival": 1.0, "ci_low": 1.0, "ci_high": 1.0,
              "at_risk": at_risk, "events": 0, "censored": 0}]
    i = 0
    while i < len(data):
        t = data[i][0]
        deaths = 0
        censored = 0
        while i < len(data) and data[i][0] == t:
            if data[i][1] == 1:
                deaths += 1
            else:
                censored += 1
            i += 1
        if deaths:
            survival *= 1.0 - deaths / at_risk
            if at_risk - deaths > 0:
                greenwood += deaths / (at_risk * (at_risk - deaths))
            if 0.0 < survival < 1.0 and greenwood > 0:
                se = math.sqrt(greenwood) / abs(math.log(survival))
                ci_low = survival ** math.exp(Z * se)
                ci_high = survival ** math.exp(-Z * se)
            else:
                ci_low = ci_high = survival
            curve.append({"time": t, "survival": survival, "ci_low": ci_low,
                          "ci_high": ci_high, "at_risk": at_risk,
                          "events": deaths, "censored": censored})
        at_risk -= deaths + censored
    return curve


def km_median(curve: list[dict]) -> tuple[float | None, float | None, float | None]:
    """Median survival and its CI (the times where the survival CI crosses 0.5)."""
    median = next((p["time"] for p in curve if p["survival"] <= 0.5), None)
    if median is None:
        return None, None, None
    low = next((p["time"] for p in curve if p["time"] >= median and p["ci_high"] <= 0.5), None)
    high = next((p["time"] for p in curve if p["time"] >= median and p["ci_low"] <= 0.5), None)
    return median, low, high


def _survival_at(curve: list[dict], time: float) -> float:
    value = 1.0
    for p in curve:
        if p["time"] <= time:
            value = p["survival"]
        else:
            break
    return value


def logrank(groups: dict[str, list[tuple[float, int]]]) -> dict:
    """k-sample log-rank test (Mantel-Haenszel); k-1 degrees of freedom."""
    names = list(groups)
    k = len(names)
    if k < 2:
        raise FigureError("log-rank needs at least two groups")
    times = sorted({t for rows in groups.values() for t, e in rows if e == 1})
    if not times:
        return {"chi2": None, "df": k - 1, "p": None,
                "observed": [0] * k, "expected": [0.0] * k,
                "note": "no events in any group"}
    observed = [0] * k
    expected = [0.0] * k
    variance = [[0.0] * k for _ in range(k)]
    for t in times:
        n = [sum(1 for tt, _ in rows if tt >= t) for rows in groups.values()]
        d = [sum(1 for tt, e in rows if tt == t and e == 1) for rows in groups.values()]
        total_n = sum(n)
        total_d = sum(d)
        if total_d == 0 or total_n < 2:
            continue
        for g in range(k):
            observed[g] += d[g]
            expected[g] += total_d * n[g] / total_n
        factor = total_d * (total_n - total_d) / (total_n - 1)
        for i in range(k):
            for j in range(k):
                variance[i][j] += factor * (
                    (n[i] / total_n if i == j else 0.0)
                    - n[i] * n[j] / total_n ** 2
                )
    size = k - 1
    u = [observed[g] - expected[g] for g in range(size)]
    sub = [[variance[i][j] for j in range(size)] for i in range(size)]
    inv = _invert(sub)
    chi2_value = sum(u[i] * inv[i][j] * u[j] for i in range(size) for j in range(size))
    return {"chi2": chi2_value, "df": size, "p": chi2_sf(chi2_value, size),
            "observed": observed, "expected": expected, "note": None}


def km_analysis(groups: dict[str, list[tuple[float, int]]],
                times: list[float] | None) -> dict:
    warnings = []
    curves = {}
    medians = {}
    for name, rows in groups.items():
        if not rows:
            raise FigureError(f"group {name!r} has no rows")
        if sum(e for _, e in rows) == 0:
            warnings.append(f"group {name!r} has no events; its curve is flat at 1.0")
        curves[name] = km_curve(rows)
        medians[name] = km_median(curves[name])
    max_time = max(t for rows in groups.values() for t, _ in rows)
    if len(groups) > 8:
        warnings.append(f"{len(groups)} groups: the palette has eight slots and "
                        "repeats after that; combine or split groups before "
                        "publication")
    if times is None:
        times = [0.0] + [round(max_time * f, 1) for f in (0.25, 0.5, 0.75, 1.0)]
    times = sorted(set(float(t) for t in times))
    if times[0] != 0:
        times.insert(0, 0.0)
    risk = {name: [sum(1 for t, _ in rows if t >= when) for when in times]
            for name, rows in groups.items()}
    for name, rows in groups.items():
        if len(rows) < 10:
            warnings.append(f"group {name!r} has {len(rows)} patients; a KM curve "
                            "is not informative at that size")
        events = sum(e for _, e in rows)
        if events < 5:
            warnings.append(f"group {name!r} has {events} events; the median and "
                            "log-rank p are unstable")
        if medians[name][0] is None:
            warnings.append(f"group {name!r}: median survival not reached before "
                            "the end of follow-up")
    test = logrank(groups)
    if test["note"]:
        warnings.append(test["note"])
    return {
        "groups": list(groups),
        "curves": curves,
        "medians": medians,
        "risk_times": times,
        "risk": risk,
        "logrank": test,
        "max_time": max_time,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Bland-Altman
# --------------------------------------------------------------------------- #


def bland_altman_analysis(a: list[float], b: list[float]) -> dict:
    if len(a) != len(b) or len(a) < 3:
        raise FigureError("Bland-Altman needs at least three paired measurements")
    diffs = [x - y for x, y in zip(a, b)]
    means = [(x + y) / 2.0 for x, y in zip(a, b)]
    n = len(diffs)
    bias = sum(diffs) / n
    sd = math.sqrt(sum((d - bias) ** 2 for d in diffs) / (n - 1))
    loa_low = bias - 1.96 * sd
    loa_high = bias + 1.96 * sd
    se_bias = sd / math.sqrt(n)
    se_loa = math.sqrt(3.0) * sd / math.sqrt(n)  # Bland & Altman 1986
    warnings = []
    if n < 30:
        warnings.append(f"{n} pairs: the bias and limits of agreement use a normal "
                        "approximation that is unreliable below 30")
    if sd == 0:
        warnings.append("every pair has the same difference; the limits of "
                        "agreement collapse onto the bias")
    return {
        "n": n,
        "means": means,
        "differences": diffs,
        "bias": bias,
        "sd": sd,
        "loa": (loa_low, loa_high),
        "bias_ci": (bias - Z * se_bias, bias + Z * se_bias),
        "loa_ci": ((loa_low - Z * se_loa, loa_low + Z * se_loa),
                   (loa_high - Z * se_loa, loa_high + Z * se_loa)),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Diagnostic 2x2 table
# --------------------------------------------------------------------------- #


def _prop(k: int, n: int) -> tuple[float, float, float]:
    return wilson(k, n) if n else (float("nan"), float("nan"), float("nan"))


def _lr_intervals(tp: int, fp: int, tn: int, fn: int, sens: float,
                  spec: float) -> tuple[tuple[float, float] | None,
                                         tuple[float, float] | None]:
    """95% CIs for LR+ / LR- on the log scale (Simel 1991).

    Same rule as diag_stats.py: a likelihood ratio is a ratio, so the interval
    is asymmetric and belongs on log(LR). A zero cell leaves it undefined; no
    0.5 correction is applied, because that would change the estimate.
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


def table_analysis(tp: int, fp: int, tn: int, fn: int) -> dict:
    """Accuracy measures from one 2x2 table, with Wilson intervals."""
    if min(tp, fp, tn, fn) < 0:
        raise FigureError("2x2 counts cannot be negative")
    n = tp + fp + tn + fn
    if n == 0:
        raise FigureError("the 2x2 table is empty (all counts are zero)")
    sens = _prop(tp, tp + fn)
    spec = _prop(tn, tn + fp)
    ppv = _prop(tp, tp + fp)
    npv = _prop(tn, tn + fn)
    acc = _prop(tp + tn, n)
    lr_p = (sens[0] / (1 - spec[0])
            if math.isfinite(sens[0]) and math.isfinite(spec[0]) and spec[0] < 1
            else None)
    lr_n = ((1 - sens[0]) / spec[0]
            if math.isfinite(sens[0]) and math.isfinite(spec[0]) and spec[0] > 0
            else None)
    lr_p_ci, lr_n_ci = _lr_intervals(
        tp, fp, tn, fn,
        sens[0] if math.isfinite(sens[0]) else 0.0,
        spec[0] if math.isfinite(spec[0]) else 0.0,
    )
    warnings = []
    if min(tp, fp, tn, fn) < 5:
        warnings.append("a 2x2 cell has <5 events; Wilson intervals are "
                        "optimistic there (diag_stats.py --exact gives "
                        "Clopper-Pearson)")
    if tp + fn == 0 or tn + fp == 0:
        warnings.append("sensitivity or specificity undefined (no participants "
                        "in that group)")
    if tp + fp == 0 or tn + fn == 0:
        warnings.append("PPV or NPV undefined (a test-result row is empty)")
    if lr_p_ci is None:
        warnings.append("likelihood-ratio CIs undefined (a cell is zero); no 0.5 "
                        "correction is applied")
    return {
        "n": n,
        "counts": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "prevalence": (tp + fn) / n,
        "metrics": {
            "sensitivity": sens,
            "specificity": spec,
            "ppv": ppv,
            "npv": npv,
            "accuracy": acc,
        },
        "lr_positive": lr_p,
        "lr_negative": lr_n,
        "lr_positive_ci": lr_p_ci,
        "lr_negative_ci": lr_n_ci,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Flow diagrams: counts first, picture second
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FlowCheck:
    """One arithmetic identity the diagram depends on; it must hold exactly."""

    label: str
    left: float
    right: float

    @property
    def ok(self) -> bool:
        return self.left == self.right


def _count(n: int) -> str:
    return f"{n:,}"


def _int_field(data: dict, key: str, where: str) -> int:
    if key not in data:
        raise FigureError(f"{where}: missing required key {key!r}")
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FigureError(f"{where}: {key!r} must be a non-negative integer, "
                          f"got {value!r}")
    return value


def _reasons_field(data: dict, key: str, where: str) -> list[dict]:
    if key not in data:
        return []
    value = data[key]
    if not isinstance(value, list):
        raise FigureError(f"{where}: {key!r} must be a list of "
                          '{"reason": "...", "n": N}')
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise FigureError(f"{where}: {key}[{i}] must be an object")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise FigureError(f"{where}: {key}[{i}].reason must be a non-empty string")
        n = item.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise FigureError(f"{where}: {key}[{i}].n must be a non-negative integer")
        out.append({"reason": reason.strip(), "n": n})
    return out


def _reason_total(reasons: list[dict]) -> int:
    return sum(r["n"] for r in reasons)


def strobe_model(data: dict) -> dict:
    where = "strobe"
    assessed = _int_field(data, "assessed", where)
    included = _int_field(data, "included", where)
    analysed = _int_field(data, "analysed", where)
    excluded = _reasons_field(data, "excluded", where)
    lost = _reasons_field(data, "lost", where)
    checks = [
        FlowCheck("assessed = excluded + included", assessed,
                  _reason_total(excluded) + included),
        FlowCheck("included = lost + analysed", included,
                  _reason_total(lost) + analysed),
    ]
    warnings = []
    if not excluded:
        warnings.append("no exclusions declared: assessed must equal included")
    if not lost:
        warnings.append("no losses declared: included must equal analysed")
    return {
        "design": "strobe",
        "title": str(data.get("title") or "Participant flow"),
        "assessed": assessed,
        "included": included,
        "analysed": analysed,
        "excluded": excluded,
        "lost": lost,
        "checks": checks,
        "warnings": warnings,
        "counts": {"assessed": assessed, "excluded": _reason_total(excluded),
                   "included": included, "lost": _reason_total(lost),
                   "analysed": analysed},
    }


def prisma_model(data: dict) -> dict:
    where = "prisma"
    databases = _int_field(data, "databases", where)
    registers = _int_field(data, "registers", where)
    duplicates = _int_field(data, "duplicates", where)
    screened = _int_field(data, "records_screened", where)
    records_excluded = _int_field(data, "records_excluded", where)
    sought = _int_field(data, "reports_sought", where)
    not_retrieved = _int_field(data, "reports_not_retrieved", where)
    assessed = _int_field(data, "reports_assessed", where)
    reports_excluded = _reasons_field(data, "reports_excluded", where)
    reports_included = _int_field(data, "reports_included", where)
    studies_included = _int_field(data, "studies_included", where)
    checks = [
        FlowCheck("identified (databases + registers) = duplicates + screened",
                  databases + registers, duplicates + screened),
        FlowCheck("screened = records excluded + reports sought",
                  screened, records_excluded + sought),
        FlowCheck("sought = not retrieved + assessed",
                  sought, not_retrieved + assessed),
        FlowCheck("assessed = reports excluded + reports included",
                  assessed, _reason_total(reports_excluded) + reports_included),
    ]
    warnings = []
    if studies_included > reports_included:
        warnings.append("more studies than reports included: a study can have "
                        "several reports, never fewer")
    if studies_included == 0:
        warnings.append("no studies included; an empty review usually reports why")
    return {
        "design": "prisma",
        "title": str(data.get("title") or "PRISMA 2020 flow"),
        "databases": databases,
        "registers": registers,
        "duplicates": duplicates,
        "records_screened": screened,
        "records_excluded": records_excluded,
        "reports_sought": sought,
        "reports_not_retrieved": not_retrieved,
        "reports_assessed": assessed,
        "reports_excluded": reports_excluded,
        "reports_included": reports_included,
        "studies_included": studies_included,
        "checks": checks,
        "warnings": warnings,
        "counts": {"databases": databases, "registers": registers,
                   "duplicates": duplicates, "records_screened": screened,
                   "records_excluded": records_excluded, "reports_sought": sought,
                   "reports_not_retrieved": not_retrieved,
                   "reports_assessed": assessed,
                   "reports_excluded": _reason_total(reports_excluded),
                   "reports_included": reports_included,
                   "studies_included": studies_included},
    }


def consort_model(data: dict) -> dict:
    where = "consort"
    assessed = _int_field(data, "assessed", where)
    randomised = _int_field(data, "randomised", where)
    excluded = _reasons_field(data, "excluded", where)
    raw_arms = data.get("arms")
    if not isinstance(raw_arms, list) or not 2 <= len(raw_arms) <= 4:
        raise FigureError("consort: 'arms' must be a list of two to four arms")
    arms = []
    checks = [
        FlowCheck("assessed = excluded + randomised", assessed,
                  _reason_total(excluded) + randomised),
        FlowCheck("randomised = sum of arm allocations", randomised,
                  sum(_int_field(a, "allocated", f"consort: arm {i + 1}")
                      for i, a in enumerate(raw_arms) if isinstance(a, dict))),
    ]
    for i, raw in enumerate(raw_arms):
        arm_where = f"consort: arm {i + 1}"
        if not isinstance(raw, dict):
            raise FigureError(f"{arm_where} must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FigureError(f"{arm_where}: 'name' must be a non-empty string")
        allocated = _int_field(raw, "allocated", arm_where)
        received = _int_field(raw, "received", arm_where)
        analysed = _int_field(raw, "analysed", arm_where)
        not_received = _reasons_field(raw, "not_received", arm_where)
        lost = _reasons_field(raw, "lost", arm_where)
        excluded_analysis = _reasons_field(raw, "excluded_analysis", arm_where)
        checks.append(FlowCheck(f"{name}: allocated = did not receive + received",
                                allocated, _reason_total(not_received) + received))
        checks.append(FlowCheck(
            f"{name}: received = analysed + lost/excluded",
            received,
            analysed + _reason_total(lost) + _reason_total(excluded_analysis)))
        arms.append({"name": name.strip(), "allocated": allocated,
                     "received": received, "analysed": analysed,
                     "not_received": not_received, "lost": lost,
                     "excluded_analysis": excluded_analysis})
    warnings = []
    if not excluded:
        warnings.append("no exclusions before randomisation declared")
    for arm in arms:
        if arm["analysed"] == 0:
            warnings.append(f"arm {arm['name']!r} analysed 0 patients")
    return {
        "design": "consort",
        "title": str(data.get("title") or "CONSORT flow"),
        "assessed": assessed,
        "randomised": randomised,
        "excluded": excluded,
        "arms": arms,
        "checks": checks,
        "warnings": warnings,
        "counts": {"assessed": assessed, "excluded": _reason_total(excluded),
                   "randomised": randomised,
                   "arms": {a["name"]: {"allocated": a["allocated"],
                                        "received": a["received"],
                                        "analysed": a["analysed"]}
                            for a in arms}},
    }


def flow_model(design: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise FigureError("flow input must be a JSON object")
    builders = {"strobe": strobe_model, "prisma": prisma_model,
                "consort": consort_model}
    if design not in builders:
        raise FigureError(f"unknown flow design {design!r} "
                          "(one of strobe, prisma, consort)")
    return builders[design](data)


def _flow_side_text(head: str, reasons: list[dict]) -> str:
    # The total sits on its own line: a long head plus "(n = 1,234)" wraps
    # into a broken count like "(n =" / "1,234)" in a narrow side box.
    lines = [head, f"(n = {_count(_reason_total(reasons))})"]
    for reason in reasons:
        lines.append(f"• {reason['reason']}")
        lines.append(f"  (n = {_count(reason['n'])})")
    return "\n".join(lines)


def flow_layout(model: dict, width_mm: float) -> dict:
    """Lay the model out in data units; text is wrapped for the chosen width."""
    design = model["design"]
    xmax = {"strobe": 124.0, "prisma": 138.0}.get(design)
    if design == "consort":
        xmax = 30 + 72 * (len(model["arms"]) - 1) + 36 + 14 + 8
    width_in = width_mm / 25.4
    unit = width_in * 72 / xmax          # points per data unit
    line_h = 10.5 / unit                 # one 8 pt line, in data units
    gap = 2.0 * line_h
    boxes: list[dict] = []
    arrows: list[tuple[float, float, float, float]] = []
    bands: list[dict] = []

    def wrap(text: str, width_units: float) -> str:
        chars = max(10, int(width_units * unit / 4.6))
        return "\n".join(line for raw in text.split("\n")
                         for line in (textwrap.wrap(raw, chars) or [""]))

    def place(x: float, top: float, width: float, text: str,
              kind: str = "main") -> tuple[float, float]:
        text = wrap(text, width)
        lines = text.count("\n") + 1
        height = lines * line_h * 1.3 + 1.3 * line_h
        boxes.append({"x": x, "y": top - height / 2, "w": width, "h": height,
                      "text": text, "kind": kind})
        return top - height, top - height / 2

    def side_arrow(main_x: float, main_w: float, cy: float,
                   side_x: float, side_w: float) -> None:
        arrows.append((main_x + main_w / 2, cy, side_x - side_w / 2, cy))

    def v_arrow(x: float, y1: float, y2: float) -> None:
        arrows.append((x, y1, x, y2))

    if design == "strobe":
        main_x, side_x, main_w, side_w = 42.0, 97.0, 50.0, 40.0
        top = 0.0
        bottom, cy = place(main_x, top, main_w,
                           f"Assessed for eligibility\n(n = {_count(model['assessed'])})")
        row_bottom = bottom
        if model["excluded"]:
            side_bottom, side_cy = place(
                side_x, top, side_w,
                _flow_side_text("Excluded", model["excluded"]), "side")
            side_arrow(main_x, main_w, cy, side_x, side_w)
            row_bottom = min(row_bottom, side_bottom)
        top = row_bottom - gap
        bottom, cy = place(main_x, top, main_w,
                           f"Included in study\n(n = {_count(model['included'])})")
        v_arrow(main_x, row_bottom, top)
        row_bottom = bottom
        if model["lost"]:
            side_bottom, side_cy = place(
                side_x, top, side_w,
                _flow_side_text("Lost / excluded from analysis", model["lost"]),
                "side")
            side_arrow(main_x, main_w, cy, side_x, side_w)
            row_bottom = min(row_bottom, side_bottom)
        top = row_bottom - gap
        analysed_bottom, _ = place(
            main_x, top, main_w, f"Analysed\n(n = {_count(model['analysed'])})")
        v_arrow(main_x, row_bottom, top)
        ymin = analysed_bottom - 3 * line_h
        return {"boxes": boxes, "arrows": arrows, "bands": bands,
                "stage_labels": [],
                "canvas": (0.0, xmax, ymin, 0.3 * line_h),
                "title": model["title"],
                "footnote": "n = number of participants; every branch must add up."}

    if design == "prisma":
        main_x, side_x, main_w, side_w = 46.0, 103.0, 54.0, 40.0
        rows = [
            ("Identification",
             f"Records identified from databases\n(n = {_count(model['databases'])})\n"
             f"Registers (n = {_count(model['registers'])})",
             f"Duplicates removed\n(n = {_count(model['duplicates'])})"),
            ("Screening",
             f"Records screened\n(n = {_count(model['records_screened'])})",
             f"Records excluded\n(n = {_count(model['records_excluded'])})"),
            ("Screening",
             f"Reports sought for retrieval\n(n = {_count(model['reports_sought'])})",
             f"Reports not retrieved\n(n = {_count(model['reports_not_retrieved'])})"),
            ("Screening",
             f"Reports assessed for eligibility\n(n = {_count(model['reports_assessed'])})",
             _flow_side_text("Reports excluded", model["reports_excluded"])
             if model["reports_excluded"] else
             f"Reports excluded (n = {_count(_reason_total(model['reports_excluded']))})"),
            ("Included",
             f"Studies included in review\n(n = {_count(model['studies_included'])})\n"
             f"Reports of included studies (n = {_count(model['reports_included'])})",
             None),
        ]
        top = 0.0
        current_phase = None
        last_bottom = 0.0
        for index, (phase, main_text, side_text) in enumerate(rows):
            if phase != current_phase:
                bands.append({"top": top, "bottom": top, "label": phase})
                current_phase = phase
            bottom, cy = place(main_x, top, main_w, main_text)
            row_bottom = bottom
            if side_text:
                side_bottom, _ = place(side_x, top, side_w, side_text, "side")
                side_arrow(main_x, main_w, cy, side_x, side_w)
                row_bottom = min(row_bottom, side_bottom)
            bands[-1]["bottom"] = row_bottom - gap / 2
            last_bottom = row_bottom
            if index < len(rows) - 1:
                top = row_bottom - gap
                v_arrow(main_x, bottom, top)
        ymin = last_bottom - 3 * line_h
        return {"boxes": boxes, "arrows": arrows, "bands": bands,
                "stage_labels": [],
                "canvas": (0.0, xmax, ymin, 0.3 * line_h),
                "title": model["title"],
                "footnote": "n = number of records, reports or studies, as labelled; "
                            "every branch must add up."}

    # CONSORT: one column per arm, with its own side boxes.
    main_w, side_w, step, side_offset = 36.0, 28.0, 72.0, 36.0
    main_xs = [30.0 + i * step for i in range(len(model["arms"]))]
    side_xs = [x + side_offset for x in main_xs]
    center = (main_xs[0] + main_xs[-1]) / 2.0
    stage_labels: list[dict] = []
    top = 0.0
    bottom, cy = place(center, top, 50.0,
                       f"Assessed for eligibility\n(n = {_count(model['assessed'])})")
    stage_labels.append({"label": "Enrolment", "y": cy})
    row_bottom = bottom
    if model["excluded"]:
        side_bottom, _ = place(side_xs[-1], top, side_w,
                               _flow_side_text("Excluded", model["excluded"]),
                               "side")
        side_arrow(center, 50.0, cy, side_xs[-1], side_w)
        row_bottom = min(row_bottom, side_bottom)
    top = row_bottom - gap
    bottom, cy = place(center, top, 50.0,
                       f"Randomised\n(n = {_count(model['randomised'])})")
    v_arrow(center, row_bottom, top)
    row_bottom = bottom
    top = row_bottom - gap
    allocated_bottoms = []
    allocated_cys = []
    for arm, x in zip(model["arms"], main_xs):
        b, cy = place(x, top, main_w,
                      f"{arm['name']}\nAllocated (n = {_count(arm['allocated'])})")
        allocated_bottoms.append(b)
        allocated_cys.append(cy)
        arrows.append((center, row_bottom, x, top))
    stage_labels.append({"label": "Allocation",
                         "y": sum(allocated_cys) / len(allocated_cys)})
    top = min(allocated_bottoms) - gap
    received_bottoms = []
    received_cys = []
    for arm, x, sx in zip(model["arms"], main_xs, side_xs):
        b, cy = place(x, top, main_w,
                      f"Received allocated\nintervention (n = {_count(arm['received'])})")
        received_bottoms.append(b)
        received_cys.append(cy)
        row_bottom = b
        if arm["not_received"]:
            sb, _ = place(sx, top, side_w,
                          _flow_side_text("Did not receive allocated intervention",
                                          arm["not_received"]), "side")
            side_arrow(x, main_w, cy, sx, side_w)
            row_bottom = min(row_bottom, sb)
        received_bottoms[-1] = row_bottom
    stage_labels.append({"label": "Follow-up",
                         "y": sum(received_cys) / len(received_cys)})
    top = min(received_bottoms) - gap
    analysed_bottoms = []
    analysed_cys = []
    for arm, x, sx in zip(model["arms"], main_xs, side_xs):
        b, cy = place(x, top, main_w,
                      f"Analysed (n = {_count(arm['analysed'])})")
        analysed_bottoms.append(b)
        analysed_cys.append(cy)
        reasons = arm["lost"] + arm["excluded_analysis"]
        if reasons:
            sb, _ = place(sx, top, side_w,
                          _flow_side_text("Lost / excluded from analysis", reasons),
                          "side")
            side_arrow(x, main_w, cy, sx, side_w)
            analysed_bottoms[-1] = min(b, sb)
    stage_labels.append({"label": "Analysis",
                         "y": sum(analysed_cys) / len(analysed_cys)})
    ymin = min(analysed_bottoms) - 3 * line_h
    footnote = ("n = number of participants; each arm must add up from "
                "allocation to analysis.")
    return {"boxes": boxes, "arrows": arrows, "bands": bands,
            "stage_labels": stage_labels,
            "canvas": (0.0, xmax, ymin, 0.3 * line_h),
            "title": model["title"], "footnote": footnote}


def render_flow(plt, model: dict, layout: dict, out: Path, vector: bool,
                width_mm: float) -> list[dict]:
    from matplotlib.patches import FancyBboxPatch
    xmin, xmax, ymin, ymax = layout["canvas"]
    width_in = width_mm / 25.4
    fig = plt.figure(figsize=(width_in, width_in * (ymax - ymin) / xmax))
    ax = fig.add_axes([0.02, 0.05, 0.96, 0.88])
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.axis("off")
    for band in layout["bands"]:
        ax.axhspan(band["bottom"], band["top"], color="#f7f5f0", zorder=0, lw=0)
        ax.text(xmin + 4, (band["top"] + band["bottom"]) / 2, band["label"],
                rotation=90, ha="center", va="center", fontsize=8,
                color=MUTED, zorder=1)
    for item in layout.get("stage_labels", []):
        ax.text(xmin + 4, item["y"], item["label"], rotation=90,
                ha="center", va="center", fontsize=8, color=MUTED, zorder=1)
    for box in layout["boxes"]:
        patch = FancyBboxPatch(
            (box["x"] - box["w"] / 2, box["y"] - box["h"] / 2),
            box["w"], box["h"],
            boxstyle="round,pad=0,rounding_size=1.2",
            linewidth=0.9, edgecolor=MUTED,
            facecolor="white" if box["kind"] == "main" else "#fbfaf7",
            zorder=2,
        )
        ax.add_patch(patch)
        ax.text(box["x"], box["y"], box["text"], ha="center", va="center",
                fontsize=8, color=INK, linespacing=1.35, zorder=3)
    for x1, y1, x2, y2 in layout["arrows"]:
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.0,
                                    shrinkA=0, shrinkB=0, mutation_scale=9),
                    zorder=4)
    fig.text(0.01, 0.985, layout["title"], ha="left", va="top",
             fontsize=11, color=INK, fontweight="bold")
    fig.text(0.01, 0.008, layout["footnote"], ha="left", va="bottom",
             fontsize=7.5, color=MUTED)
    return _save(plt, fig, out, vector)


def _example_flow(design: str) -> dict:
    examples = {
        "strobe": {
            "design": "strobe", "title": "Participant flow",
            "assessed": 500,
            "excluded": [{"reason": "Not meeting inclusion criteria", "n": 24},
                         {"reason": "Declined to participate", "n": 6}],
            "included": 470,
            "lost": [{"reason": "Lost to follow-up", "n": 10}],
            "analysed": 460,
        },
        "prisma": {
            "design": "prisma", "title": "PRISMA 2020 flow",
            "databases": 1200, "registers": 50,
            "duplicates": 200, "records_screened": 1050,
            "records_excluded": 900, "reports_sought": 150,
            "reports_not_retrieved": 10, "reports_assessed": 140,
            "reports_excluded": [{"reason": "Wrong population", "n": 20},
                                 {"reason": "Wrong outcome", "n": 10}],
            "reports_included": 110, "studies_included": 100,
        },
        "consort": {
            "design": "consort", "title": "CONSORT 2010 flow",
            "assessed": 500,
            "excluded": [{"reason": "Not meeting inclusion criteria", "n": 50}],
            "randomised": 450,
            "arms": [
                {"name": "Intervention", "allocated": 225, "received": 220,
                 "not_received": [{"reason": "Withdrew before treatment", "n": 5}],
                 "lost": [{"reason": "Lost to follow-up", "n": 10}],
                 "analysed": 210},
                {"name": "Control", "allocated": 225, "received": 225,
                 "not_received": [],
                 "lost": [{"reason": "Lost to follow-up", "n": 15}],
                 "analysed": 210},
            ],
        },
    }
    if design not in examples:
        raise FigureError(f"unknown example {design!r}")
    return examples[design]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _import_pyplot():
    """Import pyplot for the Agg backend, or return None when it is absent."""
    try:
        import matplotlib
    except ImportError:
        return None
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _apply_style(plt) -> str:
    style = "default"
    if STYLE_PATH.is_file():
        plt.style.use(str(STYLE_PATH))
        style = "openscience"
    try:
        from matplotlib import font_manager
        available = {f.name for f in font_manager.fontManager.ttflist}
        generic = {"sans-serif", "serif", "monospace", "cursive", "fantasy"}
        families = [f for f in plt.rcParams["font.sans-serif"]
                    if f in available or f in generic]
        fallback = [f for f in ("DejaVu Sans", "Arial") if f in available]
        plt.rcParams["font.sans-serif"] = families + [f for f in fallback
                                                      if f not in families]
        # A style naming Inter/Arial resolves to a fallback on most machines;
        # matplotlib logs that at WARNING for every title. The figure is fine,
        # so keep the log for real problems only (missing glyphs still warn).
        import logging
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    except Exception:  # font discovery is a nicety, never a failure
        pass
    plt.rcParams["savefig.dpi"] = 300
    return style


def _fig(plt, width_mm: float, height_mm: float):
    return plt.subplots(figsize=(width_mm / 25.4, height_mm / 25.4))


def _save(plt, fig, out: Path, vector: bool) -> list[dict]:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=300, bbox_inches="tight", facecolor="white")
    outputs = [{"path": str(out), "format": out.suffix.lstrip(".") or "png"}]
    if vector:
        pdf = out.with_suffix(".pdf")
        fig.savefig(str(pdf), bbox_inches="tight", facecolor="white")
        outputs.append({"path": str(pdf), "format": "pdf"})
    plt.close(fig)
    return outputs


def render_roc(plt, analysis: dict, out: Path, vector: bool,
               width_mm: float) -> list[dict]:
    fig, ax = _fig(plt, width_mm, width_mm)
    points = analysis["points"]
    ax.plot([0, 1], [0, 1], ls=":", lw=1.0, color=MUTED, zorder=1)
    ax.text(0.56, 0.60, "AUC 0.5", rotation=45, fontsize=7, color=MUTED,
            ha="left", va="bottom")
    ax.step([p["fpr"] for p in points], [p["tpr"] for p in points],
            where="post", color=PALETTE[0], lw=2.0, zorder=2)
    op = analysis["operating"]
    if op is not None:
        ax.scatter([op["fpr"]], [op["tpr"]], s=36, color=PALETTE[5],
                   zorder=4, edgecolors="white", linewidths=0.6)
        label = (f"cutoff {op['threshold']:g}\n"
                 f"Sens {op['tpr']:.2f}, Spec {1 - op['fpr']:.2f}")
        ax.annotate(label, (op["fpr"], op["tpr"]), textcoords="offset points",
                    xytext=(8, -26), fontsize=8, color=INK)
    auc_text = (f"AUC {analysis['auc']:.3f} "
                f"(95% CI {analysis['auc_ci'][0]:.3f}-{analysis['auc_ci'][1]:.3f})")
    ax.text(0.98, 0.04, auc_text, transform=ax.transAxes, ha="right",
            fontsize=9, color=INK)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.set_xlabel("1 - Specificity")
    ax.set_ylabel("Sensitivity")
    ax.set_title("ROC curve")
    return _save(plt, fig, out, vector)


def render_forest(plt, analysis: dict, out: Path, vector: bool,
                  width_mm: float) -> list[dict]:
    studies = analysis["studies"]
    k = len(studies)
    height_in = 1.35 + 0.42 * k + 0.35
    fig = plt.figure(figsize=(width_mm / 25.4, height_in))
    grid = fig.add_gridspec(1, 2, width_ratios=[2.9, 1.0], wspace=0.02)
    ax = fig.add_subplot(grid[0, 0])
    text_ax = fig.add_subplot(grid[0, 1], sharey=ax)
    text_ax.set_axis_off()
    ys = list(range(k - 1, -1, -1))
    pooled_y = -1.35
    if analysis["log_scale"]:
        ax.set_xscale("log")
        low = min(s.low for s in studies)
        high = max(s.high for s in studies)
        ticks = [t for t in (0.1, 0.2, 0.25, 0.5, 1, 2, 4, 5, 10, 20, 50, 100)
                 if low * 0.95 <= t <= high * 1.05]
        if not ticks:
            ticks = [low, 1.0, high]
        ax.set_xticks(ticks)
        ax.set_xticklabels([f"{t:g}" for t in ticks])
        ax.minorticks_off()
    for study, y in zip(studies, ys):
        ax.plot([study.low, study.high], [y, y], color=PALETTE[0], lw=2.0,
                solid_capstyle="butt", zorder=2)
        size = 28 + 90 * (study.weight_random / max(s.weight_random for s in studies))
        ax.scatter([study.effect], [y], s=size, color=PALETTE[0], zorder=3,
                   edgecolors="white", linewidths=0.6)
        text_ax.text(0.98, y, f"{study.effect:.2f} ({study.low:.2f}-{study.high:.2f})",
                     ha="right", va="center", fontsize=8, color=INK)
    null = 1.0 if analysis["log_scale"] else 0.0
    ax.axvline(null, color=INK, lw=1.0, zorder=1)
    chosen = analysis["chosen"]
    width = chosen["ci"][1] - chosen["ci"][0]
    diamond = [(chosen["ci"][0], pooled_y), (chosen["effect"], pooled_y + 0.28),
               (chosen["ci"][1], pooled_y), (chosen["effect"], pooled_y - 0.28)]
    ax.add_patch(plt.Polygon(diamond, closed=True, color=PALETTE[4], zorder=3))
    text_ax.text(0.98, pooled_y,
                 f"{chosen['effect']:.2f} ({chosen['ci'][0]:.2f}-{chosen['ci'][1]:.2f})",
                 ha="right", va="center", fontsize=8, fontweight="bold", color=INK)
    text_ax.text(0.98, k - 0.25, "Effect (95% CI)", ha="right", va="bottom",
                 fontsize=8, color=MUTED)
    ax.set_yticks(ys + [pooled_y])
    ax.set_yticklabels([s.name for s in studies] + [f"Pooled ({analysis['model']})"])
    ax.set_ylim(pooled_y - 0.55, k - 0.15)
    ax.grid(False, axis="y")
    label = {"rr": "Risk ratio", "or": "Odds ratio", "hr": "Hazard ratio",
             "md": "Mean difference"}.get(analysis.get("measure", ""), "Effect")
    ax.set_xlabel(f"{label} (log scale)" if analysis["log_scale"] else label)
    ax.set_title("Forest plot")
    het = (f"I2 = {analysis['i2']:.1%}, tau2 = {analysis['tau2']:.3f}, "
           f"Q = {analysis['q']:.2f} (df {analysis['df']}, "
           f"{_fmt_p(analysis['p_heterogeneity'])})")
    fig.text(0.01, 0.01, het, fontsize=8, color=MUTED)
    fig.subplots_adjust(top=0.90, bottom=0.16, left=0.24, right=0.99)
    return _save(plt, fig, out, vector)


def render_km(plt, analysis: dict, out: Path, vector: bool,
              width_mm: float, time_unit: str) -> list[dict]:
    groups = analysis["groups"]
    k = len(groups)
    fig = plt.figure(figsize=(width_mm / 25.4, 4.1 + 0.38 * k))
    grid = fig.add_gridspec(2, 1, height_ratios=[3.6, 0.8 + 0.32 * k], hspace=0.34)
    ax = fig.add_subplot(grid[0, 0])
    ax_tab = fig.add_subplot(grid[1, 0])
    ax_tab.set_axis_off()
    for index, name in enumerate(groups):
        curve = analysis["curves"][name]
        xs = [p["time"] for p in curve]
        ys = [p["survival"] for p in curve]
        xs.append(analysis["max_time"])
        ys.append(curve[-1]["survival"])
        color = PALETTE[index % len(PALETTE)]
        ax.step(xs, ys, where="post", color=color, lw=2.0, label=_legend(name, curve,
                                                                         analysis))
        censored = [(t, _survival_at(curve, t)) for t, e in _group_rows(analysis, name)
                    if e == 0]
        if censored:
            ax.plot([c[0] for c in censored], [c[1] for c in censored], ls="none",
                    marker="|", markersize=7, color=color, zorder=3)
    ax.set_ylim(0, 1.03)
    ax.set_xlim(0, analysis["max_time"] * 1.02)
    ax.set_ylabel("Survival probability")
    ax.set_xlabel("Time" + (f" ({time_unit})" if time_unit else ""))
    ax.set_title("Kaplan-Meier estimate")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    test = analysis["logrank"]
    if test["p"] is not None:
        ax.text(0.02, 0.06, f"Log-rank {_fmt_p(test['p'])} "
                            f"(chi2 {test['chi2']:.2f}, df {test['df']})",
                transform=ax.transAxes, fontsize=9, color=INK)
    times = analysis["risk_times"]
    xmin, xmax = ax.get_xlim()
    ax_tab.set_xlim(xmin, xmax)
    ax_tab.set_ylim(-0.6, k + 0.9)
    ax_tab.text(xmin, k + 0.55, "Number at risk", fontsize=9, color=INK,
                ha="left", va="bottom")
    for when in times:
        ax_tab.text(when, k + 0.05, f"{when:g}", fontsize=8, color=MUTED,
                    ha="center", va="bottom")
    for row, name in enumerate(groups):
        y = k - 1 - row
        ax_tab.text(xmin - 0.015 * (xmax - xmin), y, name, fontsize=8, color=INK,
                    ha="right", va="center")
        ax_tab.plot([xmin, xmax], [y + 0.62, y + 0.62], color=GRID, lw=0.8)
        for col, when in enumerate(times):
            ax_tab.text(when, y, str(analysis["risk"][name][col]), fontsize=8,
                        color=INK, ha="center", va="center")
    return _save(plt, fig, out, vector)


def _group_rows(analysis: dict, name: str) -> list[tuple[float, int]]:
    return analysis["rows"][name]


def _legend(name: str, curve: list[dict], analysis: dict) -> str:
    median, low, high = analysis["medians"][name]
    if median is None:
        return f"{name} (median not reached)"
    interval = ("not estimable" if low is None or high is None
                else f"{low:g}-{high:g}")
    return f"{name} (median {median:g}, 95% CI {interval})"


def render_bland_altman(plt, analysis: dict, out: Path, vector: bool,
                        width_mm: float, a_label: str, b_label: str) -> list[dict]:
    fig, ax = _fig(plt, width_mm, width_mm * 0.82)
    ax.scatter(analysis["means"], analysis["differences"], s=18, color=PALETTE[0],
               alpha=0.75, edgecolors="white", linewidths=0.4, zorder=3)
    bias = analysis["bias"]
    low, high = analysis["loa"]
    ax.axhline(bias, color=INK, lw=1.2, zorder=2)
    ax.axhline(low, color=PALETTE[5], lw=1.0, ls="--", zorder=2)
    ax.axhline(high, color=PALETTE[5], lw=1.0, ls="--", zorder=2)
    xmax = max(analysis["means"])
    for y, text in ((bias, f"Bias {bias:.3f}"),
                    (low, f"-1.96 SD {low:.3f}"),
                    (high, f"+1.96 SD {high:.3f}")):
        ax.text(xmax, y, text, ha="right", va="bottom" if y >= bias else "top",
                fontsize=8, color=INK)
    ax.set_xlabel(f"Mean of {a_label} and {b_label}")
    ax.set_ylabel(f"{a_label} - {b_label}")
    ax.set_title("Bland-Altman agreement")
    return _save(plt, fig, out, vector)


def _ci_text(estimate: float | None,
             ci: tuple[float, float] | None) -> tuple[str, str]:
    if estimate is None or not math.isfinite(estimate):
        return ("undefined", "-")
    if ci is None or not all(math.isfinite(x) for x in ci):
        return (f"{estimate:.3f}", "undefined")
    return (f"{estimate:.3f}", f"{ci[0]:.3f}-{ci[1]:.3f}")


def render_table(plt, analysis: dict, out: Path, vector: bool, width_mm: float,
                 title: str, test_label: str, reference_label: str) -> list[dict]:
    """Draw the 2x2 counts and the accuracy measures as one publication table."""
    counts = analysis["counts"]
    tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]
    n = analysis["n"]
    fig = plt.figure(figsize=(width_mm / 25.4, 4.6))
    grid = fig.add_gridspec(2, 1, height_ratios=[0.9, 1.55], hspace=0.38)
    ax = fig.add_subplot(grid[0, 0])
    ax.set_axis_off()
    ax.set_title(title, fontsize=10, color=INK, pad=6)
    cells = [
        ["", f"{reference_label} +", f"{reference_label} -", "Total"],
        [f"{test_label} +", tp, fp, tp + fp],
        [f"{test_label} -", fn, tn, fn + tn],
        ["Total", tp + fn, fp + tn, n],
    ]
    tab = ax.table(cellText=[[str(c) for c in row] for row in cells],
                   cellLoc="center", bbox=[0.04, 0.0, 0.92, 1.0])
    tab.auto_set_font_size(False)
    tab.set_fontsize(8.5)
    for (row, col), cell in tab.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_linewidth(0.8)
        if row == 0 or col == 0:
            cell.set_facecolor("#f6f3ed")
        cell.set_text_props(weight="bold" if row == 0 or col == 0 else "normal",
                            color=INK)
    ax2 = fig.add_subplot(grid[1, 0])
    ax2.set_axis_off()
    body = [["Measure", "Estimate", "95% CI"]]
    for label, key in (("Sensitivity", "sensitivity"),
                       ("Specificity", "specificity"),
                       ("PPV", "ppv"), ("NPV", "npv"),
                       ("Accuracy", "accuracy")):
        point, low, high = analysis["metrics"][key]
        estimate, ci = _ci_text(point, (low, high))
        body.append([label, estimate, ci])
    for label, estimate, ci in (
            ("LR+", analysis["lr_positive"], analysis["lr_positive_ci"]),
            ("LR-", analysis["lr_negative"], analysis["lr_negative_ci"])):
        if estimate is None or not math.isfinite(estimate):
            body.append([label, "undefined", "-"])
        elif ci is None:
            body.append([label, f"{estimate:.2f}", "undefined"])
        else:
            body.append([label, f"{estimate:.2f}",
                         f"{ci[0]:.2f}-{ci[1]:.2f}"])
    tab2 = ax2.table(cellText=body, cellLoc="center", bbox=[0.02, 0.0, 0.96, 1.0])
    tab2.auto_set_font_size(False)
    tab2.set_fontsize(8)
    for (row, _col), cell in tab2.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_linewidth(0.6)
        if row == 0:
            cell.set_facecolor("#f6f3ed")
        cell.set_text_props(weight="bold" if row == 0 else "normal", color=INK)
    fig.text(0.01, 0.01,
             f"Prevalence {analysis['prevalence']:.1%}. PPV/NPV depend on it and "
             "do not transfer to another setting. Counts, not a diagnosis.",
             fontsize=7, color=MUTED)
    return _save(plt, fig, out, vector)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def _default_out(source: str, kind: str) -> Path:
    p = Path(source)
    return p.with_name(f"{p.stem}_{kind}.png")


def _report(kind: str, table: Table | None, params: dict, estimates: dict,
            warnings: list[str], out: Path, vector: bool, width_mm: float,
            renderer, analysis: dict, time_unit: str = "time",
            extra: dict | None = None) -> int:
    if table and out.resolve() == table.path.resolve():
        raise FigureError("--out would overwrite the input CSV")
    plt = _import_pyplot()
    outputs: list[dict] = []
    rendered = False
    style = "none"
    if plt is None:
        warnings.append("matplotlib is not installed; figure not written "
                        "(pip install matplotlib)")
    else:
        style = _apply_style(plt)
        if kind == "roc":
            outputs = renderer(plt, analysis, out, vector, width_mm)
        elif kind == "forest":
            outputs = renderer(plt, analysis, out, vector, width_mm)
        elif kind == "km":
            outputs = renderer(plt, analysis, out, vector, width_mm, time_unit)
        elif kind == "table":
            outputs = renderer(plt, analysis, out, vector, width_mm,
                               params["title"], params["test_label"],
                               params["reference_label"])
        else:
            outputs = renderer(plt, analysis, out, vector, width_mm,
                               params["a_label"], params["b_label"])
        rendered = True
    payload = {
        "gate": f"{GATE}/{kind}",
        "input": ({"path": str(table.path), "sha256": table.sha256, "rows": table.n}
                  if table else None),
        "params": params,
        "estimates": estimates,
        "warnings": warnings,
        "outputs": outputs,
        "rendered": rendered,
        "style": style,
    }
    if extra:
        payload.update(extra)
    print("```review")
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    print("```")
    return 0 if rendered else 3


def cmd_roc(ns) -> int:
    table = read_table(ns.csv, [ns.score, ns.label])
    scores, labels = [], []
    for line, row in enumerate(table.rows, start=table.line_offset):
        scores.append(num(row, ns.score, line))
        labels.append(label01(row, ns.label, line))
    analysis = roc_analysis(scores, labels, cutoff=ns.cutoff, boot=ns.boot,
                            seed=ns.seed)
    op = analysis["operating"]
    print(f"roc: n={analysis['n']}, AUC {analysis['auc']:.3f} "
          f"(95% CI {analysis['auc_ci'][0]:.3f}-{analysis['auc_ci'][1]:.3f})")
    if op is not None:
        print(f"  operating point ({analysis['operating_source']}) cutoff "
              f"{op['threshold']:g}: sensitivity {op['tpr']:.3f} "
              f"({op['sensitivity_ci'][0]:.3f}-{op['sensitivity_ci'][1]:.3f}), "
              f"specificity {1 - op['fpr']:.3f} "
              f"({op['specificity_ci'][0]:.3f}-{op['specificity_ci'][1]:.3f})")
    for warning in analysis["warnings"]:
        print(f"  warning: {warning}")
    estimates = {
        "n": analysis["n"],
        "n_positive": analysis["n_positive"],
        "n_negative": analysis["n_negative"],
        "prevalence": _round(analysis["prevalence"]),
        "auc": _round(analysis["auc"]),
        "auc_ci": [_round(x) for x in analysis["auc_ci"]],
        "bootstrap": analysis["bootstrap"],
        "seed": analysis["seed"],
        "operating_point": ({"source": analysis["operating_source"],
                             "cutoff": _round(op["threshold"]),
                             "sensitivity": _round(op["tpr"]),
                             "sensitivity_ci": [_round(x) for x in op["sensitivity_ci"]],
                             "specificity": _round(1 - op["fpr"]),
                             "specificity_ci": [_round(x) for x in op["specificity_ci"]]}
                            if op else None),
    }
    params = {"score_column": ns.score, "label_column": ns.label,
              "cutoff": ns.cutoff, "boot": ns.boot, "seed": ns.seed,
              "width_mm": ns.width_mm}
    out = Path(ns.out) if ns.out else _default_out(ns.csv, "roc")
    return _report("roc", table, params, estimates, analysis["warnings"], out,
                   ns.vector, ns.width_mm, render_roc, analysis)


def cmd_forest(ns) -> int:
    table = read_table(ns.csv, [ns.study, ns.effect, ns.low, ns.high])
    if ns.measure not in {"rr", "or", "hr", "md"}:
        raise FigureError("--measure must be one of rr, or, hr, md")
    log_scale = ns.measure != "md"
    studies = []
    for line, row in enumerate(table.rows, start=table.line_offset):
        studies.append(Study(
            name=(row.get(ns.study) or "").strip() or f"study {line}",
            effect=num(row, ns.effect, line),
            low=num(row, ns.low, line),
            high=num(row, ns.high, line),
            y=0.0, se=0.0,
        ))
    analysis = forest_analysis(studies, log_scale, model=ns.model)
    analysis["measure"] = ns.measure
    chosen = analysis["chosen"]
    print(f"forest ({ns.measure}, {ns.model}): {len(studies)} studies, "
          f"pooled {chosen['effect']:.3f} "
          f"(95% CI {chosen['ci'][0]:.3f}-{chosen['ci'][1]:.3f})")
    print(f"  heterogeneity: I2 {analysis['i2']:.1%}, tau2 {analysis['tau2']:.3f}, "
          f"Q {analysis['q']:.2f} (df {analysis['df']}, "
          f"{_fmt_p(analysis['p_heterogeneity'])})")
    for warning in analysis["warnings"]:
        print(f"  warning: {warning}")
    estimates = {
        "n_studies": len(studies),
        "measure": ns.measure,
        "model": ns.model,
        "pooled": _round(chosen["effect"]),
        "pooled_ci": [_round(x) for x in chosen["ci"]],
        "fixed": {"effect": _round(analysis["fixed"]["effect"]),
                  "ci": [_round(x) for x in analysis["fixed"]["ci"]]},
        "random": {"effect": _round(analysis["random"]["effect"]),
                   "ci": [_round(x) for x in analysis["random"]["ci"]]},
        "heterogeneity": {"i2": _round(analysis["i2"]),
                          "tau2": _round(analysis["tau2"]),
                          "q": _round(analysis["q"]),
                          "df": analysis["df"],
                          "p": _round(analysis["p_heterogeneity"], 6)},
        "studies": [{"name": s.name,
                     "effect": _round(s.effect),
                     "ci": [_round(s.low), _round(s.high)],
                     "weight_fixed": _round(s.weight_fixed),
                     "weight_random": _round(s.weight_random)}
                    for s in studies],
    }
    params = {"study_column": ns.study, "effect_column": ns.effect,
              "low_column": ns.low, "high_column": ns.high,
              "measure": ns.measure, "model": ns.model, "width_mm": ns.width_mm}
    out = Path(ns.out) if ns.out else _default_out(ns.csv, "forest")
    return _report("forest", table, params, estimates, analysis["warnings"], out,
                   ns.vector, ns.width_mm, render_forest, analysis)


def cmd_km(ns) -> int:
    table = read_table(ns.csv, [ns.time, ns.event, ns.group])
    groups: dict[str, list[tuple[float, int]]] = {}
    for line, row in enumerate(table.rows, start=table.line_offset):
        name = (row.get(ns.group) or "").strip() if ns.group else "all"
        if ns.group and not name:
            raise FigureError(f"line {line}: column {ns.group!r} is empty")
        event = label01(row, ns.event, line)
        groups.setdefault(name, []).append((num(row, ns.time, line), event))
    times = None
    if ns.times:
        try:
            times = [float(x) for x in ns.times.split(",") if x.strip()]
        except ValueError:
            raise FigureError("--times must be comma-separated numbers, e.g. 0,12,24")
    if len(groups) < 2:
        raise FigureError("Kaplan-Meier needs at least two groups (a --group column)")
    analysis = km_analysis(groups, times)
    analysis["rows"] = groups
    test = analysis["logrank"]
    print(f"km: {len(groups)} groups, {table.n} patients")
    for name in groups:
        median, low, high = analysis["medians"][name]
        if median is None:
            reached = "median not reached"
        else:
            interval = ("not estimable" if low is None or high is None
                        else f"{low:g}-{high:g}")
            reached = f"median {median:g} (95% CI {interval})"
        print(f"  {name}: n={len(groups[name])}, {reached}")
    if test["p"] is not None:
        print(f"  log-rank {_fmt_p(test['p'])} "
              f"(chi2 {test['chi2']:.2f}, df {test['df']})")
    for warning in analysis["warnings"]:
        print(f"  warning: {warning}")
    estimates = {
        "n": table.n,
        "groups": {name: {"n": len(groups[name]),
                          "events": sum(e for _, e in groups[name]),
                          "median": _round(analysis["medians"][name][0]),
                          "median_ci": [_round(analysis["medians"][name][1]),
                                        _round(analysis["medians"][name][2])]}
                   for name in groups},
        "logrank": {"chi2": _round(test["chi2"]), "df": test["df"],
                    "p": _round(test["p"])},
        "risk_times": analysis["risk_times"],
    }
    params = {"time_column": ns.time, "event_column": ns.event,
              "group_column": ns.group, "times": analysis["risk_times"],
              "time_unit": ns.time_unit, "width_mm": ns.width_mm}
    out = Path(ns.out) if ns.out else _default_out(ns.csv, "km")
    return _report("km", table, params, estimates, analysis["warnings"], out,
                   ns.vector, ns.width_mm, render_km, analysis,
                   time_unit=ns.time_unit)


def cmd_flow(ns) -> int:
    if ns.example:
        print(json.dumps(_example_flow(ns.example), ensure_ascii=False, indent=2))
        return 0
    if not ns.json:
        print("error: flow needs an input JSON, or --example "
              "strobe|prisma|consort", file=sys.stderr)
        return 2
    path = Path(ns.json)
    if not path.is_file():
        raise FigureError(f"no such file: {path}")
    raw = path.read_bytes()
    try:
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            data = json.loads(raw.decode("utf-16"))
        else:
            data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as e:
        raise FigureError(f"{path.name}: not UTF-8/UTF-16 text ({e})")
    except json.JSONDecodeError as e:
        raise FigureError(f"{path.name}: invalid JSON at line {e.lineno}, "
                          f"column {e.colno}: {e.msg}")
    if not isinstance(data, dict):
        raise FigureError("flow input must be a JSON object")
    design = ns.design or data.get("design")
    if not isinstance(design, str) or not design.strip():
        raise FigureError("flow input needs a 'design' field "
                          "(strobe, prisma, consort), or pass --design")
    design = design.strip().lower()
    declared = data.get("design")
    if (ns.design and isinstance(declared, str)
            and declared.strip().lower() != design):
        raise FigureError(f"the JSON says design {declared!r} but --design "
                          f"{ns.design!r} was passed")
    model = flow_model(design, data)
    failed = [c for c in model["checks"] if not c.ok]
    if failed:
        print("error: flow counts do not add up:", file=sys.stderr)
        for check in model["checks"]:
            print(f"  {'ok  ' if check.ok else 'FAIL'} {check.label}: "
                  f"left {check.left:g}, right {check.right:g}", file=sys.stderr)
        return 2
    print(f"flow ({design}): {len(model['checks'])} count checks passed")
    for warning in model["warnings"]:
        print(f"  warning: {warning}")
    out = Path(ns.out) if ns.out else path.with_name(f"{path.stem}_flow.png")
    if out.resolve() == path.resolve():
        raise FigureError("--out would overwrite the input JSON")
    layout = flow_layout(model, ns.width_mm)
    plt = _import_pyplot()
    warnings = list(model["warnings"])
    outputs: list[dict] = []
    rendered = False
    style = "none"
    if plt is None:
        warnings.append("matplotlib is not installed; figure not written "
                        "(pip install matplotlib)")
    else:
        style = _apply_style(plt)
        outputs = render_flow(plt, model, layout, out, ns.vector, ns.width_mm)
        rendered = True
    payload = {
        "gate": f"{GATE}/flow",
        "design": design,
        "input": {"path": str(path),
                  "sha256": hashlib.sha256(raw).hexdigest()},
        "params": {"design": design, "width_mm": ns.width_mm,
                   "title": model["title"]},
        "checks": [{"label": c.label, "left": c.left, "right": c.right}
                   for c in model["checks"]],
        "counts": model["counts"],
        "warnings": warnings,
        "outputs": outputs,
        "rendered": rendered,
        "style": style,
    }
    print("```review")
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    print("```")
    return 0 if rendered else 3


def cmd_bland_altman(ns) -> int:
    table = read_table(ns.csv, [ns.a, ns.b])
    a_values, b_values = [], []
    for line, row in enumerate(table.rows, start=table.line_offset):
        a_values.append(num(row, ns.a, line))
        b_values.append(num(row, ns.b, line))
    analysis = bland_altman_analysis(a_values, b_values)
    bias = analysis["bias"]
    low, high = analysis["loa"]
    print(f"bland-altman: n={analysis['n']}, bias {bias:.3f} "
          f"(95% CI {analysis['bias_ci'][0]:.3f}-{analysis['bias_ci'][1]:.3f})")
    print(f"  limits of agreement {low:.3f} to {high:.3f} "
          f"(SD of differences {analysis['sd']:.3f})")
    for warning in analysis["warnings"]:
        print(f"  warning: {warning}")
    estimates = {
        "n": analysis["n"],
        "bias": _round(bias),
        "bias_ci": [_round(x) for x in analysis["bias_ci"]],
        "sd": _round(analysis["sd"]),
        "loa": [_round(low), _round(high)],
        "loa_ci": [[_round(x) for x in pair] for pair in analysis["loa_ci"]],
    }
    params = {"a_column": ns.a, "b_column": ns.b,
              "a_label": ns.a_label, "b_label": ns.b_label,
              "width_mm": ns.width_mm}
    out = Path(ns.out) if ns.out else _default_out(ns.csv, "bland-altman")
    return _report("bland-altman", table, params, estimates,
                   analysis["warnings"], out, ns.vector, ns.width_mm,
                   render_bland_altman, analysis)


def _ci_list(t) -> list[float | None] | None:
    if t is None or not all(math.isfinite(x) for x in t):
        return None
    return [_round(x) for x in t]


def cmd_table(ns) -> int:
    table = read_table(ns.csv, [ns.tp, ns.fp, ns.tn, ns.fn])
    if table.n != 1:
        raise FigureError(f"table draws one 2x2 table, but this CSV has "
                          f"{table.n} rows; diag_stats.py handles several cutoffs")
    row = table.rows[0]
    line = table.line_offset
    counts = {}
    for key, column in (("tp", ns.tp), ("fp", ns.fp),
                        ("tn", ns.tn), ("fn", ns.fn)):
        value = num(row, column, line)
        if (not math.isfinite(value) or value < 0
                or abs(value - round(value)) > 1e-9):
            raise FigureError(f"line {line}: {column} must be a non-negative "
                              "whole number")
        counts[key] = int(round(value))
    analysis = table_analysis(**counts)
    m = analysis["metrics"]
    print(f"table: n={analysis['n']}, prevalence "
          f"{analysis['prevalence']:.3f}")
    print(f"  sensitivity {m['sensitivity'][0]:.3f} "
          f"({m['sensitivity'][1]:.3f}-{m['sensitivity'][2]:.3f}), "
          f"specificity {m['specificity'][0]:.3f} "
          f"({m['specificity'][1]:.3f}-{m['specificity'][2]:.3f})")
    for warning in analysis["warnings"]:
        print(f"  warning: {warning}")
    estimates = {
        "n": analysis["n"],
        "counts": analysis["counts"],
        "prevalence": _round(analysis["prevalence"]),
        "sensitivity": _ci_list(m["sensitivity"]),
        "specificity": _ci_list(m["specificity"]),
        "ppv": _ci_list(m["ppv"]),
        "npv": _ci_list(m["npv"]),
        "accuracy": _ci_list(m["accuracy"]),
        "lr_positive": _round(analysis["lr_positive"]),
        "lr_positive_ci": _ci_list(analysis["lr_positive_ci"]),
        "lr_negative": _round(analysis["lr_negative"]),
        "lr_negative_ci": _ci_list(analysis["lr_negative_ci"]),
    }
    params = {"columns": {"tp": ns.tp, "fp": ns.fp, "tn": ns.tn, "fn": ns.fn},
              "test_label": ns.test_label,
              "reference_label": ns.reference_label,
              "title": ns.title, "width_mm": ns.width_mm}
    out = Path(ns.out) if ns.out else _default_out(ns.csv, "table")
    return _report("table", table, params, estimates, analysis["warnings"],
                   out, ns.vector, ns.width_mm, render_table, analysis)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="med_figures.py",
        description="Medical publication figures: ROC, forest, Kaplan-Meier, "
                    "Bland-Altman, and the diagnostic 2x2 table. Numbers are "
                    "computed in stdlib; matplotlib only draws.",
    )
    sub = parser.add_subparsers(dest="kind", required=True)

    def common(p):
        p.add_argument("csv", help="input CSV")
        p.add_argument("--out", help="PNG path (default: <input>_<kind>.png)")
        p.add_argument("--vector", action="store_true",
                       help="also write a PDF beside the PNG")
        p.add_argument("--width-mm", type=float, default=None,
                       help="figure width in mm (default: 89 ROC/BA, 183 forest/KM)")

    roc = sub.add_parser("roc", help="ROC curve with AUC and its 95%% CI")
    common(roc)
    roc.add_argument("--score", default="score", help="score column")
    roc.add_argument("--label", default="label", help="0/1 outcome column")
    roc.add_argument("--cutoff", type=float, help="operating point to mark")
    roc.add_argument("--boot", type=int, default=2000, help="bootstrap resamples")
    roc.add_argument("--seed", type=int, default=2026, help="bootstrap seed")
    roc.set_defaults(func=cmd_roc, width_mm_default=89)

    forest = sub.add_parser("forest", help="forest plot with heterogeneity")
    common(forest)
    forest.add_argument("--study", default="study", help="study label column")
    forest.add_argument("--effect", default="effect", help="effect column")
    forest.add_argument("--low", default="ci_low", help="lower CI column")
    forest.add_argument("--high", default="ci_high", help="upper CI column")
    forest.add_argument("--measure", default="rr", choices=["rr", "or", "hr", "md"])
    forest.add_argument("--model", default="random", choices=["random", "fixed"])
    forest.set_defaults(func=cmd_forest, width_mm_default=183)

    km = sub.add_parser("km", help="Kaplan-Meier curve with risk table")
    common(km)
    km.add_argument("--time", default="time", help="follow-up time column")
    km.add_argument("--event", default="event", help="1 event, 0 censored")
    km.add_argument("--group", default="group", help="group column")
    km.add_argument("--times", help="risk-table times, comma separated")
    km.add_argument("--time-unit", default="",
                    help="unit shown on the axis, e.g. months (default: none)")
    km.set_defaults(func=cmd_km, width_mm_default=183)

    ba = sub.add_parser("bland-altman", help="agreement plot with bias and LoA")
    common(ba)
    ba.add_argument("--a", default="method_a", help="first measurement column")
    ba.add_argument("--b", default="method_b", help="second measurement column")
    ba.add_argument("--a-label", default="method A")
    ba.add_argument("--b-label", default="method B")
    ba.set_defaults(func=cmd_bland_altman, width_mm_default=89)

    table = sub.add_parser("table", help="diagnostic 2x2 table figure")
    common(table)
    table.add_argument("--tp", default="tp", help="true-positive column")
    table.add_argument("--fp", default="fp", help="false-positive column")
    table.add_argument("--tn", default="tn", help="true-negative column")
    table.add_argument("--fn", default="fn", help="false-negative column")
    table.add_argument("--test-label", default="Index test",
                       help="row label (the test being evaluated)")
    table.add_argument("--reference-label", default="Reference standard",
                       help="column label (the reference standard)")
    table.add_argument("--title", default="Diagnostic accuracy (2x2)")
    table.set_defaults(func=cmd_table, width_mm_default=183)

    flow = sub.add_parser(
        "flow", help="STROBE/PRISMA/CONSORT flow diagram with count checks")
    flow.add_argument("json", nargs="?", help="input JSON (omit with --example)")
    flow.add_argument("--design", choices=["strobe", "prisma", "consort"],
                      help="schema to use (default: the JSON's design field)")
    flow.add_argument("--example", choices=["strobe", "prisma", "consort"],
                      help="print a filled template and exit")
    flow.add_argument("--out", help="PNG path (default: <input>_flow.png)")
    flow.add_argument("--vector", action="store_true",
                      help="also write a PDF beside the PNG")
    flow.add_argument("--width-mm", type=float, default=None,
                      help="figure width in mm (default: 183, double column)")
    flow.set_defaults(func=cmd_flow, width_mm_default=183)
    return parser


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code) if isinstance(exit_.code, int) else 2
    if ns.width_mm is None:
        ns.width_mm = ns.width_mm_default
    if ns.width_mm <= 0:
        print("error: --width-mm must be positive", file=sys.stderr)
        return 2
    try:
        return ns.func(ns)
    except FigureError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))