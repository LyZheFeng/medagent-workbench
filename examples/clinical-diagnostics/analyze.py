#!/usr/bin/env python3
"""Diagnostic-accuracy analysis of the simulated clinical-diagnostics dataset.

Pipeline: cutoff sweep -> Youden-optimal cutoff -> ROC/AUC (bootstrap CI)
-> roc_curve.png -> report.md. Every number written to report.md is computed
here, in the same run.

Usage: python analyze.py [--no-plot]
Requires: matplotlib (for the figure); statistics use stdlib only.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "diagnostic_test.csv"
CUTOFFS = [round(0.05 + 0.01 * i, 2) for i in range(91)]
Z = 1.959963984540054  # two-sided 95%


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float, float]:
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - h) / d, (c + h) / d)


def table_at(rows: list[dict], cutoff: float) -> tuple[int, int, int, int]:
    tp = sum(1 for r in rows if r["y"] == 1 and r["s"] >= cutoff)
    fp = sum(1 for r in rows if r["y"] == 0 and r["s"] >= cutoff)
    tn = sum(1 for r in rows if r["y"] == 0 and r["s"] < cutoff)
    fn = sum(1 for r in rows if r["y"] == 1 and r["s"] < cutoff)
    return tp, fp, tn, fn


def metrics(tp: int, fp: int, tn: int, fn: int) -> dict:
    sens = wilson(tp, tp + fn)
    spec = wilson(tn, tn + fp)
    ppv = wilson(tp, tp + fp)
    npv = wilson(tn, tn + fn)
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "sens": sens, "spec": spec, "ppv": ppv, "npv": npv,
        "youden": sens[0] + spec[0] - 1,
    }


def lr_intervals(tp: int, fp: int, tn: int, fn: int, sens: float, spec: float):
    """95% CIs for LR+ and LR- on the log scale (Simel 1991).

    Kept in step with the medical-stats skill's diag_stats.py: a ratio needs an
    asymmetric interval, so it is built on log(LR). None when a cell is zero —
    a 0.5 correction would change the estimate, so it is the reader's call.
    """
    n1, n0 = tp + fn, tn + fp
    if n1 == 0 or n0 == 0 or not (0.0 < sens < 1.0) or not (0.0 < spec < 1.0):
        return None
    se_pos = math.sqrt((1 - sens) / (sens * n1) + spec / ((1 - spec) * n0))
    log_pos = math.log(sens) - math.log(1 - spec)
    se_neg = math.sqrt(sens / ((1 - sens) * n1) + (1 - spec) / (spec * n0))
    log_neg = math.log(1 - sens) - math.log(spec)
    return (
        (math.exp(log_pos - Z * se_pos), math.exp(log_pos + Z * se_pos)),
        (math.exp(log_neg - Z * se_neg), math.exp(log_neg + Z * se_neg)),
    )


def auc_mw(scores_pos: list[float], scores_neg: list[float]) -> float:
    """AUC by Mann-Whitney statistic (ties = 0.5)."""
    wins = 0.0
    for p in scores_pos:
        for q in scores_neg:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(scores_pos) * len(scores_neg))


def auc_bootstrap_ci(scores_pos, scores_neg, n_boot: int = 2000) -> tuple[float, float]:
    rng = random.Random(2026)
    aucs = []
    for _ in range(n_boot):
        sp = [rng.choice(scores_pos) for _ in scores_pos]
        sn = [rng.choice(scores_neg) for _ in scores_neg]
        aucs.append(auc_mw(sp, sn))
    aucs.sort()
    return aucs[int(0.025 * n_boot)], aucs[int(0.975 * n_boot)]


def main() -> int:
    with open(DATA, newline="", encoding="utf-8-sig") as f:
        rows = [
            {"s": float(r["test_score"]), "y": int(r["gold_standard"])}
            for r in csv.DictReader(f)
        ]
    n = len(rows)
    prev = sum(r["y"] for r in rows) / n
    print(f"n={n}, prevalence={prev:.3f}")

    sweep = [metrics(*table_at(rows, c)) for c in CUTOFFS]
    best = max(sweep, key=lambda m: m["youden"])
    best_cutoff = CUTOFFS[sweep.index(best)]
    print(f"best cutoff (Youden): {best_cutoff:.2f}  J={best['youden']:.3f}")

    scores_pos = [r["s"] for r in rows if r["y"] == 1]
    scores_neg = [r["s"] for r in rows if r["y"] == 0]
    auc = auc_mw(scores_pos, scores_neg)
    lo, hi = auc_bootstrap_ci(scores_pos, scores_neg)
    print(f"AUC={auc:.3f} (95% CI {lo:.3f}–{hi:.3f})")

    m = metrics(*table_at(rows, 0.50))  # README's reference cutoff

    if "--no-plot" not in sys.argv:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib unavailable; skipping roc_curve.png")
        else:
            fig, ax = plt.subplots(figsize=(5.2, 4.6))
            ax.plot([m["fp"] / (m["fp"] + m["tn"])] * 2, [0, 1], ls="--", lw=0.8, c="#999")
            xs = [1 - mm["spec"][0] for mm in sweep]
            ys = [mm["sens"][0] for mm in sweep]
            order = sorted(range(len(xs)), key=lambda i: xs[i])
            ax.plot([xs[i] for i in order], [ys[i] for i in order], lw=2, color="#0e7490")
            ax.scatter([1 - best["spec"][0]], [best["sens"][0]], zorder=3, color="#b91c1c", s=28)
            ax.annotate(f"Youden cutoff {best_cutoff:.2f}",
                        (1 - best["spec"][0], best["sens"][0]),
                        textcoords="offset points", xytext=(8, -10), fontsize=9)
            ax.plot([0, 1], [0, 1], ls=":", lw=1, c="#666")
            ax.text(0.62, 0.06, f"AUC {auc:.2f} (95% CI {lo:.2f}–{hi:.2f})", fontsize=10)
            ax.set_xlabel("1 − Specificity")
            ax.set_ylabel("Sensitivity")
            ax.set_title("ROC — simulated diagnostic test (n=200)")
            fig.tight_layout()
            fig.savefig(HERE / "roc_curve.png", dpi=300)
            print("wrote roc_curve.png")

    ci = lambda t: f"{t[0]:.3f} (95% CI {t[1]:.3f}–{t[2]:.3f})"
    lr = lr_intervals(best["tp"], best["fp"], best["tn"], best["fn"],
                      best["sens"][0], best["spec"][0])
    if lr:
        lr_line = (f"- LR+ {best['sens'][0] / (1 - best['spec'][0]):.2f} "
                   f"(95% CI {lr[0][0]:.2f}–{lr[0][1]:.2f});"
                   f"LR- {(1 - best['sens'][0]) / best['spec'][0]:.2f} "
                   f"(95% CI {lr[1][0]:.3f}–{lr[1][1]:.2f})")
    else:
        lr_line = (f"- LR+ {best['sens'][0] / (1 - best['spec'][0]):.2f};"
                   f"LR- {(1 - best['sens'][0]) / best['spec'][0]:.2f}"
                   "(有零格,CI 未定义)")
    report = f"""# 诊断试验准确度报告(模拟数据)

数据:`data/diagnostic_test.csv`(模拟,seed=2026,n={n},患病率 {prev:.2f})。
本报告每个数字由 `analyze.py` 本次运行计算生成。

## 最佳截断(Youden 指数)

最佳截断 **{best_cutoff:.2f}**(J={best['youden']:.3f}):

- 灵敏度 {ci(best['sens'])}
- 特异度 {ci(best['spec'])}
- PPV {ci(best['ppv'])}(患病率 {prev:.2f} 条件下)
- NPV {ci(best['npv'])}
{lr_line}

## ROC/AUC

AUC = **{auc:.3f}**(95% CI {lo:.3f}–{hi:.3f};Mann-Whitney 法,bootstrap CI
2000 次重抽样,seed=2026)。见 `roc_curve.png`。

## 截断 0.5 处(与 README 对照)

灵敏度 {ci(m['sens'])};特异度 {ci(m['spec'])}。

## 局限

- 模拟数据,两组同方差高斯,不代表真实器械性能谱(谱偏倚未建模)。
- 单一模拟数据集;PPV/NPV 依赖本研究患病率,不可外推到筛查场景。
"""
    (HERE / "report.md").write_text(report, encoding="utf-8")
    print("wrote report.md")

    (HERE / "results.json").write_text(
        json.dumps({"n": n, "prevalence": round(prev, 4),
                    "best_cutoff": best_cutoff, "best": {k: v for k, v in best.items()},
                    "auc": round(auc, 4), "auc_ci": [round(lo, 4), round(hi, 4)]},
                   ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print("wrote results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
