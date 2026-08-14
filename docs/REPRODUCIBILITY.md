# Reproducibility guide

## 1. Verify the released artifact

```bash
python scripts/verify_release.py
python -m pytest -q
```

## 2. Reproduce the systems evidence

```bash
python icair_2026/framework_v1/run_systems_benchmark.py   --output-dir scratch/systems --run-id anonymous_repeat
python icair_2026/framework_v1/verify_systems_determinism.py   icair_2026/framework_v1/evidence_systems/systems_benchmark_structure.json   scratch/systems/systems_benchmark_structure.json   --output scratch/systems/determinism_check.json
```

Timing varies by host.  Capacity, route/status counts, fault outcomes, receipt
counts and the timing-free structure are the declared deterministic targets.

## 3. Reproduce E1 from public upstream data

After completing `docs/DATA_ACCESS.md`:

```bash
python icair_2026/framework_v1/run_e1.py --mode full   --many-labs data/raw/external/many_labs_igt/many_labs_igt_behavior_long.csv   --mendeley-dir data/raw/external/mendeley_igt_v2_behavior_only/IGT   --mendeley-manifest data/raw/external/mendeley_igt_v2_behavior_only/metadata/download_manifest_v2_igt_only.json   --output-dir scratch/e1_full
```

The full run produces fitted models, row-level predictions/routes, bootstrap
tables, validation checks and a manifest in `scratch/e1_full`.  Compare
aggregate CSVs against `icair_2026/framework_v1/evidence_v2`.

## 4. Component ablation and runtime bridge

```bash
python icair_2026/framework_v1/component_ablation.py   --routes scratch/e1_full/route_assignments.csv.gz   --output-dir scratch/component_ablation

python icair_2026/framework_v1/run_official_v2_runtime_bridge.py   --predictions scratch/e1_full/predictions.csv.gz   --routes scratch/e1_full/route_assignments.csv.gz   --operating-points scratch/e1_full/frozen_operating_points.csv   --model scratch/e1_full/models/hist_gradient_boosting.joblib   --version-record scratch/e1_full/mendeley_local_version_record.json   --output-dir scratch/runtime_bridge
```

The bridge is a retrospective simulated-side-effect technical replay.  It is
not a live service, institutional authorization, distributed transaction, or
security evaluation.

## 5. Rebuild figures

Figure scripts read the frozen aggregate evidence and write editable SVG/PDF
plus 600-dpi PNG/JPG files.  Run the commands listed in the root README and
check each generated manifest and QA report.
