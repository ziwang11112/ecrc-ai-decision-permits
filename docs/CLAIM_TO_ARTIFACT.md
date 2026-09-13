# Experiment artifact map

| Component | Numerical evidence |
|---|---|
| Capacity and recovery simulator | `icair_2026/framework_v1/evidence_systems/` |
| Prediction and frozen route evaluation | `icair_2026/framework_v1/evidence_v2/` |
| Component ablation | `icair_2026/framework_v1/evidence_v2/component_ablation/` |
| Runtime bridge | `icair_2026/framework_v1/evidence_bridge/` |
| Participant weighting | `iasc/statistics/input/` and `iasc/statistics/out/` |
| Delivery and raw-request recovery | Complete S1–S8 saved archive; source under `iasc/runtime/` and `iasc/end_to_end/` |
| Controlled program verification | `iasc_application/`; full public projections in the S9 archive |
| Finite lifecycle model | `iasc_model_check/runs/v1/` and the retained audit bindings |
| Plots and numerical summaries | `plots/current/data/`, `plots/current/expected/`, `plots/current/exports/` |

See [reproducibility](../REPRODUCIBILITY.md) for executable entry points and
the individual protocols for denominators and interpretation boundaries.
