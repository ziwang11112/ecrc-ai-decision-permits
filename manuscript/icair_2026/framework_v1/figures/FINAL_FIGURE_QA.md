# Final results-figure QA

## Outcome

PASS. The three result figures were generated and visually audited exclusively in Python/matplotlib at their final 159 mm width in colour and grayscale. All retain editable SVG/PDF masters, 600-dpi PNG/JPG exports, Calibri-first typography at or above 7.5 pt, frozen source-data tables and machine-readable point/interval audits.

The established image stems remain unchanged for the Word builder:

- Visible Figure 2: `fig3_layered_evaluation.*`.
- Visible Figure 3: `fig2_capacity_tradeoff.*`.
- Visible Figure 4: `fig4_prediction_permission.*`.

The legacy `FIG2_*` and `FIG3_*` support-file names are also unchanged; their internal visible figure numbers and manifest `figure_id` fields match the manuscript mapping above.

## Figure 2: atomic capacity and contention cost

- Physical canvas: 159 x 66 mm; 3,755 x 1,559 px at 600 dpi.
- Claim boundary: transactional reservation preserved configured capacity on the declared trusted single-node runtime, while SQLite contention increased tail latency.
- Panel a: six exact transactional stress points plus one separately marked constructed non-atomic witness. Redundant `3/3`, `8/8` and `configured limit` annotations were removed; exact stress counts remain in the caption/source data, and only the distinct `2/1` witness is directly labelled away from its marker.
- Panel b: three-run median end-to-end p95 latency with observed minimum-maximum whiskers over the 1/2/4/8/16-worker sweep; whiskers are not confidence intervals.
- Visual audit: no annotation, marker or whisker overlap; colour and grayscale remain legible at final size.
- Reproducibility: 11 primary/support files were byte-identical in an independent rerun.
- Support bundle: `FIG3_CAPTION.md`, `FIG3_CONTRACT.md`, `FIG3_QA_REPORT.md`, `FIG3_MANIFEST.json`, `fig3_layered_evaluation_source_data.csv` and `fig3_point_range_audit.csv`.

## Figure 3: finite-cap trade-off

- Physical canvas: 159 x 62 mm; 3,755 x 1,464 px at 600 dpi.
- Claim boundary: increasing finite automated-alert quota raises proxy-event action coverage and automated false-alert exposure in both stored HGB cohorts; fixed-cap cross-cohort contrasts remain descriptive.
- Panel a: proxy-positive choices routed to alert or review.
- Panel b: automated false alerts per 100 decisions.
- Statistics: all 16 estimates and conditional participant-cluster percentile 95% confidence-interval endpoints match the frozen rows exactly.
- Visual audit: no point-value or auxiliary grey annotations; markers and confidence intervals do not overlap neighbouring series. Solid-circle and dashed-square encodings remain separable in grayscale.
- Reproducibility: 11 primary/support files were byte-identical in an independent rerun.
- Support bundle: `FIG2_CAPTION.md`, `FIG2_CONTRACT.md`, `FIG2_QA_REPORT.md`, `FIG2_MANIFEST.json`, `fig2_capacity_tradeoff_source_data.csv` and `fig2_point_check.csv`.

## Figure 4: operating point, evidence and action readiness

- Physical canvas: 159 x 62 mm; 3,755 x 1,464 px at 600 dpi.
- Claim boundary: action readiness is determined at the selected operating point and by evidence eligibility, not by predictive ranking alone.
- Panel a: external cap-eight action precision with conditional participant-cluster percentile 95% confidence intervals and an unlabelled dashed 0.60 development condition.
- Panel b: exact full-evidence-gate zeros versus gate-off action-route rates and paired confidence intervals on the constructed invalid-evidence subset.
- All point-side values (`45.2`, `51.4`, `63.9`, `0`, `9.27`, `4.64`) and the grey `0.60 development condition` label were removed from the plot; exact values and denominators remain in the caption, QA table and source data.
- Visual audit: no direct-value or reference-line annotation overlaps; open/filled markers and model shapes preserve grayscale interpretation.
- Reproducibility: all nine primary artifacts matched across the script's independent two-run hash check.
- Support bundle: `FIG4_CAPTION.md`, `FIG4_CONTRACT.md`, `FIG4_QA_REPORT.md`, `FIG4_MANIFEST.json`, `fig4_prediction_permission_source_data.csv`, `fig4_prediction_permission_audit.csv` and `fig4_prediction_permission_determinism.json`.

## Authoritative manifest hashes

| Visible figure | Manifest file | SHA-256 |
|---|---|---|
| Figure 2 | `FIG3_MANIFEST.json` | `bc303d17a240c5a0a12682c89753128f0373046794dfb2f396582980cc1238fd` |
| Figure 3 | `FIG2_MANIFEST.json` | `061e9476b7e1cb846584eeb3dbc4547d4e86d4d0dcb150e0dcbd42c5161e4945` |
| Figure 4 | `FIG4_MANIFEST.json` | `4eed20be36921fcf0dafc635ce037dc4bee6083d4918f823459bc3ba41e705fe` |
