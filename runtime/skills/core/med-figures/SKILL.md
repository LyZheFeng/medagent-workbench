---
name: med-figures
description: Use when generating figures for medical research — ROC curves with CIs, forest plots of effect sizes, Kaplan-Meier survival curves with risk tables, Bland-Altman agreement plots, flow diagrams (STROBE/PRISMA/CONSORT), or diagnostic 2x2 summaries. Ships med_figures.py for the four statistical chart forms (numbers in stdlib, matplotlib only draws); flow diagrams and the 2x2 table-figure remain templates. Extends the publication-figures style with journal conventions (NEJM/Lancet-style clean axes, colorblind-safe palettes, 89/183 mm column widths).
---

# Medical publication figures

Extends the bundled `publication-figures` style with the chart forms medical
journals actually expect. The four statistical forms are scripted; run the
script and adjust the figure, do not re-derive the statistics by hand.

## Scripted chart forms

`med_figures.py` (next to this file, stdlib statistics + optional matplotlib)
takes a CSV, computes the estimates with their intervals, writes a 300 dpi PNG
and prints one ```review JSON block. The block carries the input file's sha256,
the estimates, warnings and the output path, so the figure can be traced back
to the data and code that produced it.

```bash
python "$XDG_CONFIG_HOME/opencode/skills/med-figures/med_figures.py" roc scores.csv
python ... forest studies.csv --measure rr --model random
python ... km survival.csv --times 0,12,24 --time-unit months
python ... bland-altman pairs.csv --a-label "CT" --b-label "MRI"
```

Common options: `--out FIG.png` (default `<input>_<kind>.png`), `--vector`
(also PDF), `--width-mm` (89 single column, 183 double; the defaults match the
chart). Exit codes: 0 figure written; 2 bad input; 3 estimates computed but no
figure because matplotlib is missing — `pip install matplotlib` and rerun.

**ROC** — input columns `score,label` (label 0/1; use `--score`/`--label` for
other names). AUC by the Mann-Whitney statistic with a seeded bootstrap 95% CI;
the operating point is Youden-optimal unless `--cutoff` names one. The figure
marks the cutoff, labels the chance line, and prints the AUC with its CI. Never
quote the AUC without that interval.

**Forest** — input columns `study,effect,ci_low,ci_high`. DerSimonian-Laird
random-effects (default) or `--model fixed`; squares are inverse-variance
weighted, the diamond is the pooled estimate, the null line is 1 for
`--measure rr|or|hr` and 0 for `md`. The footnote carries I², τ², Q, df and p.
The review block always reports both fixed and random pooled estimates; the
figure shows the one chosen. With fewer than five studies the heterogeneity
statistics are flagged as unstable.

**Kaplan-Meier** — input columns `time,event,group` (event 1 = death/event, 0 =
censored). Step curves with censoring ticks, the number-at-risk table under the
axis at `--times`, median survival with its 95% CI in the legend, and the
log-rank p (k-sample, k−1 df) on the plot. A median that is never reached is
said so, not estimated from the last follow-up.

**Bland-Altman** — input columns `method_a,method_b` (or `--a`/`--b`). Bias and
±1.96 SD limits of agreement with their approximate CIs, labelled on the plot;
below 30 pairs the normal approximation is flagged. A trend in the differences
(proportional bias) is not tested by the script — inspect the plot and say so.

## Chart-form conventions (all forms)

**ROC** — diagonal reference line labeled "AUC 0.5"; the AUC in the legend with
its CI; the chosen cutoff marked with a point and annotation; equal aspect
ratio. Never quote AUC without its CI.

**Forest plot** — one row per study/subgroup: square proportional to weight,
horizontal 95% CI line, diamond for the pooled estimate; solid vertical line at
the null (RR/OR=1, HR=1); log scale for RR/OR/HR; a heterogeneity footnote
(I², τ², Q, p). Subgroup headers in bold; the numeric column sits beside the
plot.

**Kaplan–Meier** — step curve with censoring ticks; number-at-risk table under
the time axis (mandatory); median survival with CI in the legend; log-rank p
between curves stated on the plot.

**Bland–Altman** — mean-bias line and ±1.96 SD limits of agreement with numeric
labels; never a plain scatter without them.

**2×2 accuracy summary** — table-figure: Sens/Spec/PPV/NPV each with Wilson CI;
footnote the prevalence. Compute the numbers with `medical-stats/diag_stats.py`;
the table layout is still hand-built.

**Flow diagrams (STROBE/PRISMA/CONSORT)** — no script yet. Draw them as
matplotlib/SVG in the workspace (not a drawing tool). Counts at every box must
sum correctly (enrolled = excluded + analysed); excluded boxes carry reasons
with counts. Check the arithmetic before the figure goes into a manuscript — a
flow diagram that does not sum is a finding, not a layout problem.

## Style rules

- Load `publication-figures/openscience.mplstyle` first when you draw by hand;
  `med_figures.py` applies it automatically (and prunes fonts the machine does
  not have, so the run is quiet)
- Colorblind-safe palettes only (the shared palette slots or Okabe-Ito);
  curves also distinguishable by linestyle — survival curves get printed in
  grayscale too
- CI whiskers always visible; error bars without CIs are a finding to fix, not
  a style choice
- Axis labels carry **units** (mg/dL, months, %) and the reference/therapeutic
  range where clinically meaningful
- Export: 300 dpi PNG (the script) or 600 dpi TIFF for journals; physical size
  matching the target column (89 mm single / 183 mm double)

## Integrity

- Every figure must be regenerable from a script in the workspace (figure–code
  traceability; the traceability-review skill checks this). Keep the review
  block beside the manuscript or in the run log.
- No digitizing or "approximating" data points from a source figure — cite the
  source instead, or extract with stated method.
- The script computes and draws; it does not decide whether the test, cutoff,
  model or grouping is clinically appropriate. State that choice yourself, with
  its rationale.