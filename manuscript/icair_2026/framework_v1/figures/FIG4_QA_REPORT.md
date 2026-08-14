# Figure 4 QA report

## Outcome

PASS for data, statistical boundaries, export, typography, grayscale, and two-run reproducibility.
Original-size visual inspection: **PASS - color and grayscale inspected at native 3,755 x 1,464 px; point and interval marks are clear with no direct-value or reference-line text overlaps**.

## Claim and evidence boundary

- Claim: action readiness is determined at the selected operating point and by evidence eligibility, not by predictive ranking alone.
- Panel a uses only external Mendeley cap-8 action precision. Only the HGB point estimate reaches 0.60; its interval lower endpoint is 0.5997. The line is a development condition, not a tested, clinical, safety, or fairness boundary.
- Panel b uses only constructed hash-scheduled missing/stale HGB decisions. It is an audit stress test, not an operational prevalence estimate.
- Prediction scores are unchanged in both component arms; the panel isolates routing permission, not predictive credit.
- Full-gate zeros are exact counts with no interval. Gate-off intervals are paired participant-cluster percentile intervals for arm minus full (2,000 replicates).
- Cross-cohort contrasts are descriptive.

## Point and denominator audit

| Panel | Proposal/cohort | Condition | Count | Estimate | 95% interval |
|---|---|---|---:|---:|---:|
| a | History | external cap 8 | 215/476 | 45.17% | 41.13-49.21% |
| a | Logistic | external cap 8 | 298/580 | 51.38% | 47.21-55.33% |
| a | HGB | external cap 8 | 373/584 | 63.87% | 59.97-67.76% |
| b | Many Labs | full gate | 0/6798 | 0.00% | exact zero; none displayed |
| b | Many Labs | gate off | 630/6798 | 9.27% | 8.64-9.88% |
| b | Mendeley | full gate | 0/1208 | 0.00% | exact zero; none displayed |
| b | Mendeley | gate off | 56/1208 | 4.64% | 3.51-5.90% |

All seven plotted points equal their frozen count ratios within 1e-12; all five displayed intervals contain their frozen estimates. Machine-readable checks are in `fig4_prediction_permission_audit.csv`.

## Export and design checks

- Physical size: 159.000 x 62.000 mm in SVG; 159.000 x 62.000 mm in PDF.
- Raster canvas: 3755 x 1464 px at 600 dpi.
- Editable SVG text nodes: 25; minimum text: 7.5 pt.
- Resolved typeface: Calibri.
- Non-white content margins (left/top/right/bottom): 109/122/51/146 px.
- White background; no cards, hatch, grid, embedded table, AUROC, bridge, or capacity panel.
- No point-value labels or reference-line text are drawn; exact values, counts and interval definitions remain in the caption, QA table and source data, so no annotation overlaps an interval.
- Color semantics are stable across panels: blue denotes the governed/condition-meeting state; orange denotes below-condition/bypass. Model labels and marker shapes in panel a, plus open/filled markers and one legend in panel b, make the encoding redundant.
- Grayscale export generated and checked for nonblank content and final dimensions.

## Reproducibility and traceability

- Independent two-run hash match: **PASS** for 9 primary artifacts.
- `route_workload_metrics.csv` SHA-256: `9bc3a3682bf70ab983301596a3f9be5216ded1e4ab9a96277d58fca6491af355`
- `bootstrap_confidence_intervals.csv` SHA-256: `f47d31ee04c772b44daa480031bfb8f840c6b2b72bc836b5d49138b499395a6d`
- `route_component_metrics.csv` SHA-256: `9e8d60e96478a2f1e8a0a5050de29279d941a7ac8425f6ccf37f97b699861283`
- `route_component_bootstrap.csv` SHA-256: `152e93af10732a1e879712894981c86c7f7522ae07917acc28d6d41a5d6d1374`
- Plot source: `fig4_prediction_permission_source_data.csv`.
- Hash comparison: `fig4_prediction_permission_determinism.json`.
- Drawing/export script: `make_fig4_prediction_permission.py`.
