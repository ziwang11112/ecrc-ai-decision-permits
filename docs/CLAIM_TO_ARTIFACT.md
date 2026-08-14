# Claim-to-artifact index

| Manuscript evidence claim | Primary artifact | Boundary |
|---|---|---|
| Route-specific reservation preserves configured capacity in the declared single-node tests | `icair_2026/framework_v1/evidence_systems/systems_benchmark_structure.json`, `systems_performance_runs.csv`, `systems_unsafe_race_witness.json` | Single-host SQLite WAL; unsafe race is a constructed witness |
| Model discrimination and frozen operating-point behaviour across cohorts | `icair_2026/framework_v1/evidence_v2/model_performance.csv`, `route_workload_metrics.csv`, `bootstrap_confidence_intervals.csv` | Same-task external cohort; conditional participant bootstrap |
| Evidence and capacity components alter distinct route outcomes | `icair_2026/framework_v1/evidence_v2/component_ablation/route_component_metrics.csv`, `route_component_bootstrap.csv`, `route_component_deltas.csv` | Deterministic missing/stale fixture; not real missingness prevalence |
| Runtime stack reproduces vectorized HGB route/reason decisions | `icair_2026/framework_v1/evidence_bridge/bridge_summary.json`, `runtime_input_contract.json` | Retrospective simulated-side-effect replay; row-level artifacts omitted here |
| Trusted-stack conformance checks flag 84/84 injected permit/receipt cases and 0/32 clean controls | `icair_2026/framework_v1/evidence_v2/component_ablation/record_component_summary.csv`, `record_clean_validator_summary.csv`, `record_fault_family_summary.csv` | Prespecified conformance fixtures only; not unknown or adversarial fault coverage |
| Sequence-aware checking covers six declared cross-record fault families | `icair_2026/framework_v1/evidence/benchmark_summary.json`, `validator_family_summary.csv` | Prespecified deterministic families only; not unknown/adversarial coverage |
| Publication figures match archived estimates | `manuscript/icair_2026/framework_v1/figures/*_source_data.csv` and figure manifests/QA reports | Figures are descriptive where cohorts or host timings differ |
