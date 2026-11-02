---
name: med-figures
description: Use when generating figures for medical research — ROC curves with CIs, forest plots of effect sizes, Kaplan-Meier survival curves with risk tables, flow diagrams (STROBE/PRISMA/CONSORT), Bland-Altman agreement plots, or diagnostic 2x2 summaries. Extends the publication-figures style with medical chart templates and journal conventions (NEJM/Lancet-style clean axes, colorblind-safe palettes).
---

# Medical publication figures

Extends the bundled `publication-figures` style with the chart forms medical
journals actually expect. Load `publication-figures/openscience.mplstyle` first
(same palette rules), then follow the templates here.

## Chart-form conventions

**ROC curve** — diagonal reference line labeled "AUC 0.5"; AUC in the legend
with its 95% CI (`AUC 0.87 (95% CI 0.81–0.92)`); mark the chosen cutoff with a
point + annotation; equal aspect ratio. Never quote AUC without its CI.

**Forest plot** — one row per study/subgroup: square proportional to weight,
horizontal 95% CI line, diamond for the pooled estimate; solid vertical line at
the null (RR/OR=1, HR=1), dashed line at the pooled estimate; log scale for
RR/OR/HR; a **heterogeneity footnote** (I², τ², Q, p). Subgroup headers in
bold; column of numeric estimates right-aligned beside the plot.

**Kaplan–Meier** — step curve with censoring ticks; **number-at-risk table
under the time axis** (mandatory); median survival with CI in the legend;
log-rank p between curves stated on the plot.

**Bland–Altman** — mean-bias line and ±1.96 SD limits of agreement with
numeric labels; never a plain scatter without them.

**Flow diagrams (STROBE/PRISMA/CONSORT)** — counts at every box must sum
correctly (enrolled = excluded + analyzed); excluded boxes carry reasons with
counts. Generate as matplotlib/SVG, not a drawing tool.

**2×2 accuracy summary** — table-figure: Sens/Spec/PPV/NPV each with Wilson
CI; footnote the prevalence.

## Style rules

- Colorblind-safe palettes only (Okabe-Ito / viridis); curves also
  distinguishable by linestyle — survival curves get printed in grayscale too
- CI whiskers always visible; error bars without CIs are a finding to fix, not
  a style choice
- Axis labels carry **units** (mg/dL, months, %) and the reference/therapeutic
  range where clinically meaningful
- Export: 600 dpi TIFF or 300 dpi PNG + vector PDF/PDF-SVG pair, physical size
  matching the target journal's column (89 mm single / 183 mm double)

## Integrity

- Every figure must be regenerable from a script in the workspace (figure–code
  traceability; the traceability-review skill checks this)
- No digitizing or "approximating" data points from a source figure — cite the
  source instead, or extract with stated method
