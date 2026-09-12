# Participant-equal alert-policy sensitivity results

This post hoc analysis was locked in `PROTOCOL.md` before execution. It uses only frozen participant-level counts and keeps every planned cell. It does not fit a model, reselect a threshold, reconstruct a new policy, or estimate an intervention benefit. The complete grid comprises 24 S3 online arm cells and 12 fixed-cap/cap-removed arm cells: 36 arm cells, 72 arm-metric estimates and 36 metric contrasts from 18 paired comparisons.

## Findings

Participant weighting changes two directions in the cap-removal comparison. In development HGB and logistic, pooled alert-precision changes of +0.021 and +0.009 become participant-equal changes of -0.030 (95% CI -0.040 to -0.021) and -0.035 (-0.046 to -0.023). Development history also declines under both weighting schemes. These reversals mean the pooled precision changes must not be presented as improvements for an average alert-receiving participant.

For the previously emphasized external HGB cap-removal comparison, the pooled precision difference of +0.103 is attenuated to a macro difference of +0.037 (95% CI 0.00015 to 0.079). The unrounded lower limit is positive but close to zero; rounding it to 0.000 and describing it as reaching zero would be inaccurate. Fixed and removed-cap macro precisions are 0.665 and 0.703. The macro coverage difference is +0.285 (0.225 to 0.344), from 0.058 to 0.343, compared with the pooled difference of +0.318. External logistic also has a positive macro precision difference, whereas the external history macro precision interval includes zero. Cap-removal macro coverage increases in all six cohort-generator cells.

For online pacing versus FIFO, macro coverage point estimates decrease in all 12 cohort-generator-budget cells. The external HGB and logistic 8-per-episode coverage intervals include zero; all other macro coverage intervals lie below zero. Development macro precision decreases in all six cells. External macro precision point estimates increase in all six cells, but both HGB and both history intervals include zero, as does logistic under 8 per 100 planned decisions. External logistic at 8 per episode has a macro precision difference of +0.089 (0.024 to 0.154). The macro results therefore preserve the precision/coverage tradeoff and heterogeneous generator evidence; they do not support a general benefit of pacing.

## Estimands, eligibility and uncertainty

For each participant, precision is positive alerts divided by alerts, and coverage is positive alerts divided by all proxy positives. Pooled ratios weight participants by their alert or positive-event counts. Macro means give equal weight to eligible participants. Zero-alert precision and zero-positive coverage are undefined and excluded with counts retained. Positive-bearing participants receiving no alert contribute zero coverage. These are alternative descriptive weightings, not proof of fairness or true action utility.

There are 617 development and 59 external participants. Precision is defined for 614/612/576 development HGB/logistic/history participants and 59/58/54 external participants, respectively, for every included arm of each generator. Coverage is defined for 615 development participants and all 59 external participants; the two zero-positive development participants are reported and excluded. Across all 18 paired comparisons, the two arms happen to have identical valid-participant sets. Thus the arm-specific macro difference and the common-valid paired difference agree to numerical precision in these frozen data. The analysis nevertheless retains both estimands and the valid-only-one-arm counts; this equivalence is not assumed for arbitrary policies.

Intervals are unadjusted 95% participant-cluster percentile intervals from 2,000 shared paired bootstrap replicates per cohort (seed 20260912). All reported estimates and contrasts have 2,000 finite replicates. Intervals condition on the frozen predictions, thresholds, routes and observed eligibility; fitting, threshold selection, new-study uncertainty, and causal treatment benefit are outside their scope. All real-data labels remain the manuscript's IGT proxy labels. No model or threshold was tuned after observing these results.

## Complete paired comparison grid

Differences are comparison minus reference. Macro differences below use the common valid population. Intervals and estimates are rounded to three decimals except very small nonzero bounds, which retain five decimals. Full-precision values, both arm means, pooled intervals and all eligibility counts are in `out/arm_estimates.csv` and `out/paired_comparisons.csv`.

| Comparison | Cohort | Generator | Eligible precision / coverage | Pooled precision difference | Macro precision difference [95% CI] | Macro coverage difference [95% CI] |
|---|---|---|---:|---:|---:|---:|
| Cap removed - fixed 8+2 | Development | HGB | 614 / 615 | +0.021 | -0.030 [-0.040, -0.021] | +0.273 [0.256, 0.291] |
| Cap removed - fixed 8+2 | Development | History | 576 / 615 | -0.049 | -0.108 [-0.123, -0.093] | +0.364 [0.339, 0.390] |
| Cap removed - fixed 8+2 | Development | Logistic | 612 / 615 | +0.009 | -0.035 [-0.046, -0.023] | +0.277 [0.260, 0.294] |
| Cap removed - fixed 8+2 | External | HGB | 59 / 59 | +0.103 | +0.037 [0.00015, 0.079] | +0.285 [0.225, 0.344] |
| Cap removed - fixed 8+2 | External | History | 54 / 59 | +0.125 | +0.027 [-0.013, 0.071] | +0.358 [0.265, 0.452] |
| Cap removed - fixed 8+2 | External | Logistic | 58 / 59 | +0.154 | +0.091 [0.047, 0.136] | +0.302 [0.247, 0.358] |
| Paced - FIFO, 8/100 planned | Development | HGB | 614 / 615 | -0.027 | -0.033 [-0.050, -0.016] | -0.048 [-0.054, -0.042] |
| Paced - FIFO, 8/episode | Development | HGB | 614 / 615 | -0.028 | -0.035 [-0.053, -0.018] | -0.046 [-0.052, -0.040] |
| Paced - FIFO, 8/100 planned | Development | History | 576 / 615 | -0.043 | -0.041 [-0.065, -0.018] | -0.050 [-0.057, -0.043] |
| Paced - FIFO, 8/episode | Development | History | 576 / 615 | -0.043 | -0.042 [-0.066, -0.017] | -0.048 [-0.055, -0.042] |
| Paced - FIFO, 8/100 planned | Development | Logistic | 612 / 615 | -0.035 | -0.028 [-0.046, -0.010] | -0.050 [-0.057, -0.044] |
| Paced - FIFO, 8/episode | Development | Logistic | 612 / 615 | -0.031 | -0.025 [-0.043, -0.006] | -0.047 [-0.054, -0.041] |
| Paced - FIFO, 8/100 planned | External | HGB | 59 / 59 | +0.037 | +0.010 [-0.032, 0.053] | -0.013 [-0.022, -0.004] |
| Paced - FIFO, 8/episode | External | HGB | 59 / 59 | +0.042 | +0.022 [-0.033, 0.079] | -0.006 [-0.013, 0.002] |
| Paced - FIFO, 8/100 planned | External | History | 54 / 59 | +0.086 | +0.036 [-0.030, 0.107] | -0.015 [-0.026, -0.004] |
| Paced - FIFO, 8/episode | External | History | 54 / 59 | +0.127 | +0.061 [-0.024, 0.147] | -0.009 [-0.017, -0.002] |
| Paced - FIFO, 8/100 planned | External | Logistic | 58 / 59 | +0.059 | +0.041 [-0.002, 0.087] | -0.018 [-0.028, -0.008] |
| Paced - FIFO, 8/episode | External | Logistic | 58 / 59 | +0.101 | +0.089 [0.024, 0.154] | -0.006 [-0.013, 0.001] |

## Provenance and checks

`input/INPUT_MANIFEST.json` maps every copied input to its original workspace path and SHA-256. The cap-off alert arm uses saved S4 alert-candidate counts; the fixed arm uses saved S3 FIFO counts. All 36 corresponding pooled arm cells reproduce S3/A4 archived values, with maximum absolute difference 1.78e-15. No uncapped review-action results are inferred from alert-candidate counts.

The calculation retains 12,168 harmonized participant-arm rows and saves all bootstrap draws, multiplicities and participant IDs. Hand-computable zero-denominator/unequal-eligibility fixtures and explicit participant-duplication checks pass. `verify_results.py` does not import the analysis implementation: it reads the copied source counts, independently reconstructs all 72 arm estimates, all 36 metric contrasts, and 468 bootstrap vectors of 2,000 replicates each. Its maximum absolute difference is 1.27e-15. This is a separate algorithmic verification, not a claim of blinded analyst replication. `verification.json` records the checks. Two complete fresh runs produce 11 byte-identical output files in `out/` and `out_repeat/`.

The copied `input/CALIBRATION_CHECK.md` separately documents redundancy of the false-action calibration constraint under the recorded precision and capacity bounds. This supplement does not reselect thresholds and cannot make that constraint active. The frozen policy estimates remain unchanged.
