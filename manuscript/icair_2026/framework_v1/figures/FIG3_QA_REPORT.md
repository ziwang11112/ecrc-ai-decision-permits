# Figure 2 QA report

## Outcome

Automated QA: PASS.
Visual inspection: PASS — color and grayscale 159 × 66 mm renders inspected at full-frame and original resolution; the single unsafe-witness label, log-scale ticks and min–max whiskers remain legible with no clipping or overlap.

## Scientific contract

- Single claim: the declared trusted single-node implementation preserved configured capacity, while SQLite contention increased tail latency.
- Panel a contains six transactional stress points and one separately labelled constructed witness; all are exact counts without sampling intervals.
- Redundant 3/3, 8/8 and configured-limit text is omitted from the plot; exact stress counts remain in the caption and source data, while the distinct 2/1 unsafe witness remains directly labelled away from its marker.
- Panel b contains five worker-sweep latency summaries. Points are three-run medians and whiskers are observed min–max ranges, not confidence intervals.
- All 15 worker-sweep runs committed 8/8 reservations, rejected 88/96 requests, emitted 96/96 receipts and recorded zero oversubscription.
- Bridge, evidence-gate, discrimination and operating-point results are absent from the figure and its source data.

## Frozen latency values

- 1 worker(s): median 17.629 ms; observed range 17.009–17.655 ms.
- 2 worker(s): median 51.549 ms; observed range 43.138–57.742 ms.
- 4 worker(s): median 72.799 ms; observed range 68.078–100.343 ms.
- 8 worker(s): median 293.991 ms; observed range 274.100–303.344 ms.
- 16 worker(s): median 668.233 ms; observed range 597.656–1012.726 ms.

## Typography, layout and export

- Canvas: SVG 159.000 × 66.000 mm; PDF 159.000 × 66.000 mm.
- Raster canvas: 3755 × 1559 px at 600 dpi.
- Minimum observed text: 7.5 pt; Calibri is first choice.
- Editable SVG text nodes: 28.
- Non-white margins left/top/right/bottom: 40/196/51/217 px.
- White background; no hatch, table, cards, bridge annotation, grid, repeated legend or overall title banner.
- Panel b explicitly labels the logarithmic latency scale.

## Traceability

- `systems_performance_runs` SHA-256: `fc84a3ee7fb89dc1597d6e70c8804c9844563a8a38f7338d44a4affbb11ca1e1`
- `systems_performance_aggregate` SHA-256: `a67e3598d16ddab1900b2b5c9ce77feeb7728cf23f37ce91220bf45b254a80e0`
- `unsafe_race_witness` SHA-256: `f53998e441cd3c8cb1e16e4ba1a1c22b888c8b47b0dc4f895dd4c9155c908b85`
- Source rows: 12 in `fig3_layered_evaluation_source_data.csv`.
- Machine-readable point/range audit: `fig3_point_range_audit.csv`.
- Drawing/export script: `make_fig3_layered_evaluation.py`.
