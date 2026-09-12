# Portable participant-equal policy sensitivity

Read `PROTOCOL.md` for the locked post hoc analysis and `RESULTS.md` for interpretation. No models are trained, no thresholds selected, and no original prediction or policy output is changed. The complete numerical records are in `out/`. The analysis concerns alert precision and proxy-positive alert coverage; it does not estimate action utility or combined alert-plus-review outcomes.

## Reproduce

The archived runs used Python 3.12.14, NumPy 2.3.5 and pandas 3.0.1. With Python 3.12 installed, from this directory:

```sh
python -m pip install -r requirements.txt
python run_analysis.py --out fresh_run
python run_analysis.py --out fresh_repeat
python verify_results.py --out fresh_run --repeat fresh_repeat
python build_report.py
```

Each analysis run requires a new output directory and refuses to overwrite one. Verification writes `verification.json` in this directory. `build_report.py` formats the archived `out/` results and regenerates the complete 18-comparison summary, report and LaTeX snippets; it does not recalculate statistics. To regenerate formatted reports for a different run, first independently verify that run against the archived outputs. All scripts resolve their copied inputs relative to this directory; no original workspace, source code, network access or model artifact is required to execute the analysis.

`prepare_inputs.py` records how the frozen participant/aggregate inputs were copied from the original workspace. It is provenance, not a prerequisite in the portable package. It refuses to overwrite an existing input directory; do not run it outside the source workspace. The already included `input/` files are the analysis inputs.

## Files and provenance

- `input/INPUT_MANIFEST.json`: original source-relative paths, SHA-256 and sizes for the minimal copied counts, archived pooled estimates, protocols and calibration check.
- `out/arm_estimates.csv`: 72 metric rows covering all 36 arm cells, pooled and macro means, intervals and eligibility counts.
- `out/paired_comparisons.csv`: all 36 metric contrasts, pooled differences, arm-specific macro differences and common-valid paired macro differences, their intervals and valid-population diagnostics.
- `out/harmonized_participant_counts.csv.gz`: 12,168 participant-arm records, including every zero denominator.
- `out/bootstrap_*.csv.gz` and `out/participant_order.csv`: all 2,000 draws, sampled participant multiplicities and their order. A single cohort weight matrix is shared across all arms and comparisons.
- `out/archived_pooled_reproduction.csv`, `out/validation.json`, and `out/manifest.json`: original S3/A4 pooled reproduction, consistency checks, exact software versions and input/output hashes.
- `out_repeat/`: the independent fresh execution, whose 11 output files are byte-identical to `out/` in the recorded environment.
- `verify_results.py` and `verification.json`: separate algorithmic verification that imports no analysis functions, reconstructs every point and bootstrap vector from copied source counts, checks hashes and compares the two runs. This is not represented as blinded analyst replication.
- `all_comparisons_summary.csv`: all 18 comparisons with precision and coverage columns at full precision; `RESULTS.md` presents the same complete grid for reading.
- `snippets/`: editable methods, results and selected example table for manuscript integration. Neither main manuscript files nor figures are modified here. All 18 comparisons remain in the complete report, including negative and mixed results.
- `PACKAGE_MANIFEST.json`: SHA-256 and size of all files in this portable directory, excluding itself and Python cache files.

Minimum archival package: the entire directory except optional `out_repeat/` and Python caches. Retaining `out_repeat/` preserves the documented repeat-run evidence. No personal names or direct participant identifiers are added; original pseudonymous participant codes are retained for paired resampling and reproducibility.

## Reading the estimates

Pooled precision and coverage are ratios of total counts. Macro precision averages each eligible participant's positive-alert fraction; no-alert precision is undefined. Macro coverage averages each positive-bearing participant's covered-positive fraction; a positive-bearing participant with no alert contributes zero, while a zero-positive participant is excluded and reported. A paired macro difference uses the same valid people in both arms. The two observed eligibility sets happen to agree in all 18 comparisons, but the implementation checks rather than assumes this.

Every interval is exploratory, unadjusted and conditional on frozen model and policy outputs. Changes in IGT proxy-label precision/coverage do not establish real-world action benefit, fitting uncertainty or cross-task generalization. The separate calibration-constraint redundancy finding is included for provenance, without changing the frozen threshold selection.
