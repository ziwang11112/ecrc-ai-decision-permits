# Experiment artifact map

| Component | Numerical evidence |
|---|---|
| Online agent feedback and execution control | [Public implementation](../online_agent/README.md), three frozen schedules and offline checks |
| Primary shared-budget comparison | [Online results](../online_results/README.md): 576 scalar trajectory records, outcomes, paired contrasts and plots |
| Additional provider comparisons | `online_results/external_trajectory_scalars.csv` and `online_results/claude_trajectory_scalars.csv`, with cell summaries and paired contrasts: all 864 formal records |
| Capacity and recovery simulator | `icair_2026/framework_v1/evidence_systems/` |
| Prediction and frozen route evaluation | `icair_2026/framework_v1/evidence_v2/` |
| Component ablation | `icair_2026/framework_v1/evidence_v2/component_ablation/` |
| Runtime bridge | `icair_2026/framework_v1/evidence_bridge/` |
| Participant weighting | `iasc/statistics/input/` and `iasc/statistics/out/` |
| Delivery and raw-request recovery | Complete S1–S8 saved archive; source under `iasc/runtime/` and `iasc/end_to_end/` |
| Controlled program verification | `iasc_application/`; full public projections in the S9 archive |
| Finite lifecycle model | `iasc_model_check/runs/v1/` and the retained audit bindings |
| Current numerical figures | [Reproducible plot checks](../online_results/README.md); [exhibit map](RESULTS.md) |
| September technical plots and summaries | `plots/current/data/`, `plots/current/expected/`, `plots/current/exports/` |

See [reproducibility](../REPRODUCIBILITY.md) for executable entry points and
the individual protocols for denominators and interpretation boundaries.
