# Lifecycle plots and saved result summaries

This package rebuilds five visualizations and three numerical summaries from
saved specifications and scientific CSVs. It contains plotting code, numeric
inputs, expected result rows, figure exports and provenance. It runs no new
experiment, candidate program, model fit or bootstrap.

## Run

Use Python 3.12 and Matplotlib 3.10.9. Start at the repository root:

```sh
cd plots/current
python -m pip install -r requirements.txt
python -B scripts/verify_package.py
python -B scripts/build_main_figures.py --out ../rebuilt_plots
python -B scripts/build_pacing_figure.py --out ../rebuilt_plots
python -B scripts/summarize_results.py --out ../rebuilt_results
```

The two plot builders share an output directory and write different files.
They produce PDF, SVG and 240-dpi PNG exports; plots 3–5 also have source JSON
sidecars. They resolve inputs relative to their own package and work from any
working directory. Keep rebuild outputs outside this package so its strict
file inventory remains unchanged. Plotting performs no network access.
Dependency installation may require network access. Transitive dependency
versions and runtime binaries are not bundled; rendering can vary across
platforms or versions.

`summarize_results.py` requires only the Python standard library. Without
`--out`, it verifies the saved input hashes and numerical results without
writing files. With `--out`, it requires a fresh directory and writes
`latency_summary.csv`, `application_summary.csv`,
`cap_precision_summary.csv` and `RESULT_SUMMARY_CHECK.json`.

## Plots

| Export | Inputs and interpretation |
|---|---|
| `fig1` | Specified one-unit release/retention example; explanatory schematic, not measured observations |
| `fig2` | Specified client/service lifecycle and recovery path; schematic, not a distributed-transaction claim |
| `fig3` | All 36 saved metric/checkpoint rows for the two displayed lifecycle scenarios; six observations per cell, not continuous trajectories |
| `fig4` | All eight response/policy/client application cells; timely suite-pass feedback counts out of 144 tasks per cell |
| `fig5` | All 12 cohort/model/budget conditions and all 60 saved pacing metric/estimand rows, including every saved interval endpoint |

The application task set is reused across cells and was previously exposed.
Its workflow used a shared serial recovery schedule. The visualization adds
no uncertainty interval or exclusive client performance advantage.

Pacing values are pacing-minus-FIFO proportion differences. Pooled and
participant-equal/common-valid precision and coverage have separate
denominators; budget utilization retains its pooled estimand. `Episode`
means eight units per episode; `100 planned` means capacity ceil(8H/100) for
planned horizon H. HGB means histogram gradient boosting. The saved 95%
participant-cluster intervals used 2,000 bootstrap replicates conditional on
the archived fits, folds, thresholds and routes. This package does not
recompute them.

## Numerical summaries

The latency summary reaggregates median/minimum/maximum from the 30 saved
run-level p95 measurements and checks the six-condition saved summary. Each
condition has five repetitions of 64 timed requests. Its ranges describe
variation among observed run p95 values, not confidence intervals.

The application summary retains all eight cells. The precision summary
retains all six cap-removal conditions, pooled and participant-equal changes,
the common-valid participant counts and saved interval endpoints. The small
positive external HGB lower endpoint is preserved as 0.00015. The complete
cap-removal input also retains coverage contrasts and workload counts.

Every generated summary must equal the saved `expected/*.csv` bytes,
including all 17 rows and their formatting. The expected records and six
input CSVs retain their original numerical bytes. These checks confirm
saved-data aggregation and formatting, not the validity of new measurements.

## Provenance

`SOURCE_MANIFEST.json` binds inputs, expected rows and scripts to their source
snapshot hashes. `provenance/REBUILD_CHECK.json` records the tested runtime,
complete data preservation and byte comparisons for all five PDF exports and
three result CSVs. Source sidecars describe the plotted row coverage.
`FILE_MANIFEST.json` binds the size and SHA256 of every other package file;
`verify_package.py` checks that inventory without changing files.

The package reuses the repository's applicable code/data terms and grants no
new rights over third-party material.
