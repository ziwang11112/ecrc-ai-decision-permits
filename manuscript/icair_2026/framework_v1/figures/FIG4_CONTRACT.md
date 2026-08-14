# Figure 4 contract

## Core conclusion

Action readiness is determined at the selected operating point and by evidence eligibility, not by predictive ranking alone: a proposal must separately satisfy an action-quality condition, and evidence eligibility can withhold action without changing prediction scores.

## Evidence logic

- Panel a is the external cap-8 action-precision check for all three frozen proposals. It shows the point estimate and conditional 95% participant-cluster percentile interval for each proposal, plus the 0.60 development selection condition. Only the HGB point estimate reaches the condition; its interval lower endpoint is 0.5997.
- Panel b is the HGB evidence-eligibility audit on the constructed, hash-scheduled missing/stale-evidence subset. It contrasts the exact full-gate zero with the paired participant-bootstrap gate-off estimate in each cohort.
- Both panels are required: panel a concerns quality of action-bearing routes; panel b concerns permission to act when evidence is invalid.
- The dashed operating-point condition is deliberately unlabelled in-panel, and all point values/counts remain in the caption and source data rather than competing with confidence intervals.

## Statistical and denominator boundaries

- Panel a numerator: true alert plus review routes. Denominator: all alert plus review routes. The interval is conditional on frozen predictions, thresholds, cap 8, and routing rules.
- The 0.60 line is a development selection condition, not a hypothesis-test, clinical, safety, or fairness boundary.
- Panel b denominator: only hash-scheduled missing/stale HGB decisions (6,798 Many Labs; 1,208 Mendeley), not all decisions and not observed operational missingness.
- Full-gate zeros are exact observed counts and carry no displayed confidence interval.
- Gate-off intervals are paired 95% participant-cluster percentile intervals (2,000 replicates) for the arm-minus-full change; because full is exactly zero, the plotted change equals the gate-off rate.
- Cohorts are not compared inferentially.

## Layout and exclusion rules

- Quantitative two-panel grid, 159 x 62 mm, white background, Calibri at or above 7.5 pt.
- Panel a uses a horizontal point-and-interval plot with direct model labels: orange marks point estimates below the development condition and blue marks the point estimate that reaches it.
- Panel b uses paired open/filled points with a single condition legend.
- No AUROC, bridge analysis, capacity sweep, cards, hatch, grid, embedded table, or formula block.

## Principal reviewer risks

1. Misreading 0.60 as a tested or clinical boundary.
2. Treating the constructed invalid-evidence subset as a prevalence estimate.
3. Treating the ablation as a predictive-model comparison even though prediction scores are unchanged.
4. Treating cross-cohort differences as an inferential contrast.
