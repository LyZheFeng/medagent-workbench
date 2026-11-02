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
- Likelihood ratios: LR+ = Sens/(1−Spec), LR− = (1−Sens)/Spec
- All proportions get **Wilson 95% CIs** (never bare Wald)
- ROC + AUC with DeLong or bootstrap CI; optimal cutoff by Youden's J only
  with a stated clinical rationale (rule-out → high sensitivity, rule-in →
  high specificity)
- Agreement: Cohen's κ (Fleiss κ for >2 raters) with interpretation bands

Helper (stdlib-only, reuses the stats-integrity checker conventions):

```bash
python "$XDG_CONFIG_HOME/opencode/skills/medical-stats/diag_stats.py" <table.csv>
```

where `table.csv` has header `tp,fp,tn,fn` (one row; or per-cutoff rows). It
prints Sens/Spec/PPV/NPV/LR± with Wilson CIs and a JSON block.

## Sample size / power

State all of: alpha (two-sided by default), power, effect size **and its
source** (prior literature? pilot? — say which), allocation ratio, and the
primary endpoint the calculation serves. Provide the standard formulas for:

- Two-proportion (superiority), non-inferiority with margin Δ
- Paired/continuous (mean difference, pooled SD)
- Diagnostic accuracy: sensitivity/specificity CI precision (Buderer's method)

## Survival analysis

- Kaplan–Meier with log-rank for unadjusted comparison; report median survival
  with CI and number at risk at landmarks
- Cox PH: report HR with 95% CI per covariate, verify PH assumption
  (Schoenfeld residuals), state censoring counts
- Never plot a survival curve without the risk table under it

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
