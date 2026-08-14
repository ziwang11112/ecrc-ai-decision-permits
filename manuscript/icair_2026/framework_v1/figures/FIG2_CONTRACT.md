# Figure 3 contract

- **Core conclusion:** For the strongest frozen hist-gradient-boosting proposal, increasing automated-alert quota raises proxy-event action coverage and automated false-alert exposure in both cohorts, while external-cohort coverage remains lower.
- **Archetype:** Quantitative grid with two equally necessary panels.
- **Target/output:** ICAIR 2026 full-paper figure; editable vector master plus 600-dpi raster exports.
- **Backend:** Python only (matplotlib for drawing/export; Pillow for grayscale QA).
- **Final size:** 159 mm x 62 mm.
- **Panel a:** Proxy-positive choices routed to alert or review, divided by all proxy-positive choices, across finite automated-alert caps 2, 4, 6 and 8 per participant.
- **Panel b:** Automated false alerts only, per 100 decisions, across the same finite caps.
- **Evidence hierarchy:** Panel a carries the capacity/coverage result; panel b supplies the corresponding exposure cost. Neither panel substitutes for the other.
- **Statistics:** Pooled estimates with participant-cluster percentile 95% confidence intervals (2,000 bootstrap replicates). Intervals are conditional on the frozen predictions, thresholds and routing rules.
- **Source data:** Frozen official-v2 route-workload estimates and bootstrap confidence intervals; hist-gradient-boosting rows only. The exported table carries panel definitions, interval scope, per-participant cap units, cohort decision-length context and the descriptive cross-cohort interpretation on every row.
- **Image integrity:** No image manipulation or inferred values; plotting rows are copied and transformed only for percent display in panel a.
- **Line semantics:** Lines connect only finite caps 2, 4, 6 and 8; no sample-unbounded category is plotted.
- **Annotation policy:** No direct point values or auxiliary grey annotations are drawn; exact estimates and confidence intervals remain in the caption, source data and QA audit.
- **Reviewer risks:** Do not imply causal improvement, clinical benefit or calibrated uncertainty under shift. Human-review quota remains fixed at two per participant. The automated-alert cap is also per participant, but Many Labs decision lengths are 95 (15 participants), 100 (504) or 150 (98; mean 107.82), whereas Mendeley cohort participants each contribute 200 decisions (59 participants). Cross-cohort fixed-cap contrasts are therefore descriptive rather than matched capacity exposures.
