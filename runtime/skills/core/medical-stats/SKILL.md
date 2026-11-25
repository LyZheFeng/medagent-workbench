---
name: medical-stats
description: Use when running statistical analysis on clinical or biomedical data — diagnostic accuracy (sensitivity/specificity/ROC, kappa), sample size or power calculation, survival analysis (Kaplan-Meier, Cox), group comparison of clinical outcomes, or multiple-comparison correction in a medical context. Provides formulas, stdlib Python helpers, and reporting standards (STARD/STROBE/REMARK). Reports estimates with CIs; never certifies an analysis as publication-ready.
---

# Medical statistics

Clinical statistics fail differently from other domains: the numbers run fine
but the **denominators are wrong** (dropping indeterminate results inflates
sensitivity), **CIs are missing**, or **multiple endpoints go uncorrected**.
This skill pins the standard computations and their reporting rules.

## Diagnostic accuracy (2×2)

For an index test vs gold standard, build the 2×2 table from **every enrolled
patient** — never drop indeterminate or failed tests (report them separately,
per STARD).

- Sensitivity = TP/(TP+FN), Specificity = TN/(TN+FP)
- PPV/NPV are **prevalence-dependent** — state the study prevalence beside them
- Likelihood ratios: LR+ = Sens/(1−Spec), LR− = (1−Sens)/Spec, each with the
  **log-scale 95% CI** (Simel 1991: SE(ln LR+) = √((1−Sens)/(Sens·n₁) +
  Spec/((1−Spec)·n₀))). A symmetric interval on a ratio puts the lower bound
  below zero, so the log scale is not a nicety.
- All proportions get **Wilson 95% CIs** (never bare Wald); when a cell holds
  fewer than five events, that is **Clopper-Pearson** territory — Wilson is
  optimistic exactly there.
- ROC + AUC with DeLong or bootstrap CI; optimal cutoff by Youden's J only
  with a stated clinical rationale (rule-out → high sensitivity, rule-in →
  high specificity)
- Agreement: Cohen's κ (Fleiss κ for >2 raters) with interpretation bands

Helper (stdlib-only, reuses the stats-integrity checker conventions):

```bash
python "$XDG_CONFIG_HOME/opencode/skills/medical-stats/diag_stats.py" <table.csv>
python "$XDG_CONFIG_HOME/opencode/skills/medical-stats/diag_stats.py" --exact <table.csv>
```

where `table.csv` has header `tp,fp,tn,fn` (one row; or per-cutoff rows). It
prints Sens/Spec/PPV/NPV and LR± with their 95% CIs, plus a JSON block. `--exact`
switches the proportion intervals to Clopper-Pearson; the default is Wilson.

One rule the helper refuses to paper over: **when a 2×2 cell is zero, the
likelihood-ratio CI is reported as undefined rather than computed after adding
0.5 to every cell.** A continuity correction changes the estimate, so if you want
it, say so in the report and justify it for that table.

## Sample size / power

State all of: alpha (two-sided by default), power, effect size **and its
source** (prior literature? pilot? — say which), allocation ratio, and the
primary endpoint the calculation serves. Provide the standard formulas for:

- Two-proportion (superiority), non-inferiority with margin Δ
- Paired/continuous (mean difference, pooled SD)
- Diagnostic accuracy: sensitivity/specificity CI precision (Buderer's method)

Helper (stdlib-only, same ```review block as `diag_stats.py`):

```bash
python "$XDG_CONFIG_HOME/opencode/skills/medical-stats/stats_power.py" \
  two-proportions --p1 0.50 --p2 0.30 --power 0.80
python ... non-inferiority --p1 0.50 --p2 0.50 --margin 0.10
python ... means --delta 5 --sd 10 --power 0.80
python ... accuracy --sensitivity 0.90 --specificity 0.85 \
  --half-width 0.05 --prevalence 0.30
python ... survival --hr 0.70 --event-rate 0.60 --power 0.80
```

Each design prints the rounded-up size, the **power actually achieved at that
size** (the number a protocol should quote), and the formula it used. Common
options: `--alpha` (0.05), `--power` (0.80), `--ratio` (n2/n1, 1), `--dropout`
(0, inflates n without changing the target power). The script refuses a zero
difference, a margin smaller than the expected difference, `hr = 1`, and
non-inferiority with unequal allocation. It does not choose the effect size for
you: state where p1/p2/Δ/SD/HR came from (prior literature, pilot, or the
smallest clinically important difference).

## Survival analysis

- Kaplan–Meier with log-rank for unadjusted comparison; report median survival
  with CI and number at risk at landmarks
- Cox PH: report HR with 95% CI per covariate, verify PH assumption
  (Schoenfeld residuals), state censoring counts
- Never plot a survival curve without the risk table under it

The helpers cover KM + log-rank (`med-figures/med_figures.py`) and the event
count for a log-rank comparison (`stats_power.py survival`, Schoenfeld). Fitting
a Cox model is still done elsewhere (R/Stata/Python); report it with the PH check
and the censoring count, not just the HR.

## Multiple comparisons & reporting

- More than two arms or a panel of biomarkers → name the correction
  (Bonferroni/Holm/BH-FDR) before reporting p-values
- Report **effect size + CI first**, p-value second; never "p ≈ 0" — write
  p < 0.001
- Missing data: report the mechanism assumption (MCAR/MAR) and the handling
  (complete-case, multiple imputation) explicitly

## Boundaries

- Surface estimates; do not volunteer causal claims from cross-sectional data
- Every number in the write-up must trace to executed code (see
  stats-integrity / traceability-review skills)
- Subgroup analyses are exploratory unless pre-specified — label them so
