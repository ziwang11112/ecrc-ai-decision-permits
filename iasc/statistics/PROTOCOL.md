# Participant-equal alert-policy sensitivity: locked analysis protocol

Locked before numerical execution for this extension, 2026-09-12. This is a post hoc sensitivity analysis requested after the original and supplemental results were known. It neither changes the deployed thresholds/routes nor supplies a new intervention outcome. All newly written files stay in this statistics directory. No model is fitted and no threshold is selected.

## Scope and frozen inputs

Analyze alert precision and proxy-positive alert coverage, the policy outcomes emphasized in the manuscript. Include every S3 combination: two cohorts, three generators, two budget bases (`eight_per_episode`, `eight_per_100_planned`), and two allocators (`fifo`, `paced`): 24 arm cells and 12 paired pacing-minus-FIFO comparisons. Both budgets retain the original planned-horizon definitions; no additional time standardization, horizon estimation or allocation is introduced.

Also analyze fixed separate capacity 8+2 versus capacity removed, with the original ambiguity gate and thresholds retained, for all six cohort-generator cells. The fixed-cap counts are S3 FIFO/eight-per-episode counts. The no-cap alert counts are the saved S4 alert-candidate sufficient statistics (`n_subset`, `n_positive` in `region=alert_candidates`). Because alerts without capacity consist exactly of that frozen candidate set, these counts represent the archived `capacity_off` alert arm. The S4 full-episode counts supply all decisions and positives. Check these interpretations against every corresponding archived A4 pooled arm result before proceeding. No claim is made that all unbounded review actions are reconstructed: action-plus-review precision/coverage is outside this alert-policy supplement.

Copy the minimum existing aggregate/participant files into a portable `input/` folder with source-relative identifiers and SHA-256 hashes. Preserve the prior S3/S4 protocol texts and the calibration redundancy check as provenance. All original files remain unchanged. The selected calibration thresholds and original results are not modified in response to the redundancy finding.

## Estimands and zero denominators

For participant i and arm a, let A_ia be issued alerts, T_ia their proxy-positive count, and P_i all proxy positives. N_i is all observed decisions. No-alert participants have A_ia=0 and T_ia=0. Require identical participant inventories, N_i and P_i across paired arms.

- Pooled alert precision is sum(T_ia)/sum(A_ia); pooled alert coverage is sum(T_ia)/sum(P_i). These reproduce the manuscript's alert-weighted and positive-event-weighted ratios.
- Participant-equal (macro) precision is the arithmetic mean of T_ia/A_ia over participants with A_ia>0. Report total participants, effective participants and zero-alert participants. A zero-alert precision is undefined, not zero.
- Participant-equal coverage is the arithmetic mean of T_ia/P_i over participants with P_i>0. A positive-bearing participant with no alerts contributes zero coverage. A zero-positive participant has undefined coverage and is excluded with the excluded count reported, not silently assigned zero.
- All original participant counts remain visible, including those ineligible for a metric. Macro means have different weighting from the pooled estimand; neither is automatically the uniquely correct or fair metric.

For every paired comparison and metric, report (1) pooled difference, (2) difference between the two arm-specific macro means, and (3) a common-valid-population paired macro difference. The latter averages the individual ratio differences on the fixed observed intersection where both denominators are positive. For precision this means A_i,reference>0 and A_i,comparison>0; for coverage it means P_i>0. Report each arm's common-population mean, the common count, and numbers valid in only one arm or neither. The arm-specific macro difference compares potentially different accepted populations and must not be described as the same-person change. The common subset is also conditioned on the frozen policies; it is a sensitivity estimand, not the effect on every participant or a causal intervention effect.

## Conditional uncertainty

Use 2,000 participant-cluster percentile bootstrap replicates, seed 20260912. Within each cohort sort all participant IDs once, draw multinomial multiplicities over all participants, and reuse the same cohort weights across every model, budget and arm. Preserve full participant records; do not resample decisions independently. Recompute pooled ratios from weighted sums and macro estimates from weighted individual ratios divided by weighted eligibility counts. For paired common-population differences, use the same multiplicities and the frozen common mask.

Report 2.5th and 97.5th percentile limits and finite-replicate counts for arm means and all three difference estimands. If a replicate has a zero total denominator/eligible multiplicity, mark it undefined and report how many such replicates occurred. Intervals condition on the frozen predictions, thresholds, histories, routes, cohort and eligibility definitions; they do not propagate fitting/threshold selection or new-study uncertainty. They are unadjusted exploratory intervals, not simultaneous confirmatory tests. Do not select conclusions by significance or reinterpret a population/weighting change as intervention benefit.

## Outputs and verification

Preserve harmonized participant counts, every arm estimate, every paired comparison, all bootstrap draws, shared bootstrap multiplicities and participant order, zero-denominator/eligibility counts, input/output hashes, exact software versions, and a portable script/README. Include complete negative and mixed results. A compact LaTeX snippet/table may focus on the manuscript's previously emphasized external HGB examples, but it must state that all six model-cohort cells and both online budgets are retained and summarize any direction changes across the full grid.

Required checks: input hash preservation; complete and unique participant inventories; integer counts satisfying 0<=T<=A<=N and T<=P<=N; exact S3 count reproduction and pooled-metric agreement; every no-cap and fixed-cap pooled alert result matches A4; no-cap candidate count is never below the fixed-cap count; macro/common calculations match hand-computable empty/zero-alert/zero-positive and unequal-denominator fixtures; bootstrap aggregation matches explicit participant duplication on independent cases; all planned cells and 2,000 shared replicates retained. An independently run verification script should reconstruct selected outputs without importing the analysis implementation. Run the portable analysis twice in fresh output directories and compare deterministic output hashes.

Stop after the prespecified full grid and checks, regardless of direction. Fail loudly on input mismatch; do not repair or overwrite frozen input. No tuning, extra models, intervention-utility claims or repeated analyses to obtain favorable intervals are allowed.
