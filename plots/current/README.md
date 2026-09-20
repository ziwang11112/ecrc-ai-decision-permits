# Current technical figures and observations

Sources for the three figures in **ECRC: Decision Permits for Budgeted Workflows**.
This folder contains drawing code and numerical evidence, not manuscript text or
LaTeX. Generated images are written outside the source tree.

| Figure | Source | Meaning |
|---|---|---|
| 1 | `source/supplement/figure_revision/draw_workflows.py` | Constructed cancellation example: missing evidence and an unknown armed outcome. It is not an airline recovery experiment. |
| 2 | Same script | Client/service permit lifecycle, including non-action exit, unarmed expiry, armed retention and reconciliation. |
| 3 | `source/supplement/figure_revision/counterexample/` | Archived unsafe-release TLC states 4, 7, 8, 10 and 13; full 13-state source trace is retained. |

```console
python -m pip install -r plots/current/requirements.txt
python -B plots/current/build_figures.py --out artifacts/current-figures
python -B plots/current/verify_observations.py
```

The paper figures use Arial. If it is unavailable, `--font "DejaVu Sans"`
produces an explicitly marked font/layout variant; it does not claim pixel or
byte identity to the paper. The builder checks frozen source hashes and copies
them into a fresh destination before execution. It runs no model, API or study.

The standard-library observation check reconstructs Table 2 from all 42 saved
checkpoint audits (seven rows, two clients, three repetitions), and Table 3 from
30 timing runs / 1,920 actions. `ordinary` is the historical disk name of the
contract-matched lifecycle client. The recovery checkpoint includes recovery
**and remaining contention**, not a single reconciled operation.

Table 1 and supplementary Tables S1/S2 are indexed in `../../docs/RESULTS.md`;
Table 4 uses corrected S9-C results. Superseded five-figure outputs and their old
numbering remain available in Git tag `code-v1.1.0`. They are not current figures.
