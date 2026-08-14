# Figure 3 QA report

## Outcome

PASS. The figure is a 159 mm x 62 mm, two-panel Python/matplotlib export using only the frozen official-v2 evidence tables. It contains no ablation or systems results.

## Contract and statistics

- Claim: increasing automated-alert quota raises action coverage and automated false-alert exposure in both cohorts; Mendeley external coverage remains lower.
- Model: frozen `hist_gradient_boosting` proposal only.
- Intervals: 95% participant-cluster percentile bootstrap; 2,000/2,000 finite replicates for every point. They are conditional on the frozen predictions, thresholds, and routing rules.
- Human-review quota: fixed at two per participant (caption only, not plotted as a result).
- Automated-alert caps: finite values 2, 4, 6, and 8 per participant; no sample-unbounded point is plotted.
- Panel a denominator: all proxy-positive choices; numerator: those routed to alert or review.
- Panel b includes automated false alerts only, expressed per 100 decisions.
- Decision lengths differ by cohort: Many Labs has 95 decisions for 15 participants, 100 for 504, and 150 for 98 (mean 107.82); the Mendeley cohort has 200 for each of 59 participants. Cross-cohort fixed-cap contrasts are descriptive, not matched capacity exposures.
- No hypothesis test or causal claim is displayed.

## Export, size, crop, and grayscale checks

- SVG physical size: 159.000 x 62.000 mm; editable SVG text nodes: 26.
- PDF media box: 159.000 x 62.000 mm.
- Expected 600-dpi raster canvas: 3755 x 1464 px; PNG/JPG checks passed.
- Non-white content margins (left/top/right/bottom): 82/35/51/68 px; no edge contact detected.
- Grayscale luminance separation: 39.3; series also use redundant solid-circle versus dashed-square encoding.
- Minimum configured text size: 7.5 pt.
- All four panel/cohort series connect exactly the finite caps 2, 4, 6, and 8; the figure contains no unbounded category.
- White background, no hatch, no grid, no embedded result table, and no footnote block.
- No direct point-value or auxiliary grey annotations are drawn; confidence intervals remain visually separated from markers and neighbouring series at the final 159 mm size.

## Point-by-point CI audit

All 16 plotted estimates and both CI endpoints match the selected frozen bootstrap rows exactly after the declared display transform (x100 only for coverage). The pooled route-workload estimate independently matches each bootstrap estimate within 1e-12.

| Panel | Cohort | Cap | Estimate | 95% CI | Check |
|---|---|---:|---:|---:|---|
| a | Many Labs | 2 | 5.39% | 5.16-5.63% | PASS |
| a | Mendeley cohort | 2 | 2.31% | 2.06-2.59% | PASS |
| a | Many Labs | 4 | 8.51% | 8.20-8.87% | PASS |
| a | Mendeley cohort | 4 | 3.68% | 3.36-4.03% | PASS |
| a | Many Labs | 6 | 11.59% | 11.17-12.03% | PASS |
| a | Mendeley cohort | 6 | 5.01% | 4.62-5.42% | PASS |
| a | Many Labs | 8 | 14.47% | 13.96-15.00% | PASS |
| a | Mendeley cohort | 8 | 6.44% | 5.99-6.95% | PASS |
| b | Many Labs | 2 | 0.478 | 0.434-0.525 | PASS |
| b | Mendeley cohort | 2 | 0.381 | 0.297-0.466 | PASS |
| b | Many Labs | 4 | 0.882 | 0.812-0.957 | PASS |
| b | Mendeley cohort | 4 | 0.703 | 0.602-0.805 | PASS |
| b | Many Labs | 6 | 1.254 | 1.161-1.344 | PASS |
| b | Mendeley cohort | 6 | 1.034 | 0.898-1.178 | PASS |
| b | Many Labs | 8 | 1.663 | 1.554-1.782 | PASS |
| b | Mendeley cohort | 8 | 1.305 | 1.144-1.483 | PASS |

The machine-readable row audit is saved in `fig2_point_check.csv`.

## Traceability

- Route-workload input SHA-256: `9bc3a3682bf70ab983301596a3f9be5216ded1e4ab9a96277d58fca6491af355`
- Bootstrap-CI input SHA-256: `f47d31ee04c772b44daa480031bfb8f840c6b2b72bc836b5d49138b499395a6d`
- Plot source table: `fig2_capacity_tradeoff_source_data.csv`.
- Drawing/export script: `make_fig2_capacity_tradeoff.py`.
- Color and grayscale files were visually inspected at final dimensions after generation.
