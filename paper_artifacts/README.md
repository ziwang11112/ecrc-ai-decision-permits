# Current manuscript Figures 1–5 and Tables 1–5

This standalone package reconstructs the current five main figures from the saved
specification and aggregate scientific CSVs, and preserves the five current table
TeX sources. It adds the current presentation to
the earlier experiment archives; it does not replace their code or history.
It contains no manuscript body/full PDF, author declarations, generated candidate
programs, raw execution outputs or third-party papers.

## Rebuild

Use Python 3.12 and Matplotlib 3.10.9. From this directory:

```sh
python -m pip install -r requirements.txt
python scripts/verify_package.py
python scripts/build_main_figures.py --out ../rebuilt_current_figures
python scripts/build_pacing_figure.py --out ../rebuilt_current_figures
python scripts/build_table_values.py --out ../rebuilt_current_tables
```

The scripts also work from another working directory when invoked by absolute
path. Omit `--out` to write to this package's `exports/`. The two figure builders
write PDF, SVG and 240-dpi PNG; Figures 3–5 also receive source sidecars. The table
builder writes CSV/JSON, and `verify_package.py` is read-only. The figure builders
intentionally share one new output directory, writing different figure numbers.
No network is used by the
plotting commands. Dependency installation can require network access. The
inventory check is strict: use an output directory outside this package to keep
the shipped inventory unchanged. `.gitattributes` preserves its exact bytes
when checked out through Git.

## Contents and scientific scope

| Figure | Source | Included coverage |
|---|---|---|
| 1 | Explicit one-unit example in `scripts/build_main_figures.py` | Specified release-versus-retention illustration, not measured experimental observations |
| 2 | Explicit lifecycle in `scripts/build_main_figures.py` | Local authority/ledger, independent service and recovery-path schematic; not a distributed-transaction claim |
| 3 | `data/fig3_plot_data.csv` | All 36 saved metric/checkpoint rows in the two displayed scenarios; six matching observations per cell, not continuous trajectories |
| 4 | `data/S9_cells.csv` | All eight condition/policy/client cells, 18 batches and 144 eligible tasks per cell; plots `timely_tasks` and preserves the full aggregate CSV |
| 5 | `data/fig5_plot_data.csv` | All 12 cohort/model/budget conditions and all 60 saved metric/estimand rows with their exact interval endpoints |

Figure 4 counts distinct tasks with reconciled suite-pass feedback by the fixed
deadline. The 144 tasks are reused across cells. The source study used previously
exposed tasks and a shared serial recovery schedule; this plot provides no new
experiment, uncertainty interval or ECRC-exclusive task-benefit claim.

Figure 5 plots pacing minus FIFO proportion differences. Pooled and
participant-equal/common-valid precision and coverage retain their separate
denominators; budget utilization uses its saved pooled estimand. `Episode` means
eight units per episode; `100 planned` means capacity ceil(8H/100) for planned
horizon H. HGB is histogram gradient boosting. The saved 95% participant-cluster
bootstrap intervals use 2,000 replicates and condition on the archived fits,
folds, thresholds and routes. They are not recomputed here.

## Provenance and verification

`SOURCE_MANIFEST.json` identifies the original local source paths relative to
the paper artifact directory, source hashes, copied data columns and row counts.
`provenance/original_scripts/` preserves the original script bytes.
`provenance/path_adjustments.diff` shows every standalone script change: package
root, input paths, output default and corresponding path text in source sidecars.
Drawing instructions, numerical values, intervals and styling are unchanged.
`provenance/ROW_COVERAGE.json` records the complete plotted keys and values.
`provenance/REBUILD_COMPARISON.json` records a local rebuild and PDF-render pixel
comparison against the current canonical figure PDFs. Those reference PDFs are
not separately copied into this package.

`FILE_MANIFEST.json` lists the SHA-256 and size of each other package file. The
plotting dependency is pinned; its transitive dependency versions are not pinned.
The pip command installs required dependencies. Poppler is separate and needed
only to repeat the recorded PDF-render comparison. No runtime is vendored here.
Exact rendering can vary with those
versions/platforms; the comparison report records the tested environment. A
changed standalone script hash or source path in a sidecar is a provenance
change, not a numerical change. The package reuses the repository's applicable
code/data terms and does not assign a new third-party redistribution license.

## Current tables

`tables/TABLE_INDEX.md` maps the current Table 1–5 numbering and labels to each
verbatim TeX source. Tables 2–4 additionally have standard-library numeric display
generation and verification: `scripts/build_table_values.py` writes three display
CSVs and `TABLE_VALUE_CHECK.json`. It recomputes the Table 2 median/minimum/maximum
from the 30 saved run-level p95 measurements, checks the six-cell saved summary,
formats the eight Table 3 application cells and six Table 4 precision cells,
and requires exact equality with every data-row string in the included TeX.
No new measurement or bootstrap is performed. The copied run/summary CSVs and
complete cap-removal CSV retain their original bytes and columns.

Table 1 is a manually curated lifecycle-checkpoint summary whose full database
evidence remains in S8; no independent raw-database reconstruction is claimed
here. Table 5 is a manually authored qualitative literature scope map, not a
numeric benchmark or automatic feature ranking. Its citation keys are retained.
No unrelated bibliography or manuscript body is added. These table fragments
use the parent document's `array`, `booktabs` and `tabularx` setup and citation
definitions; this package is not a standalone manuscript build.
