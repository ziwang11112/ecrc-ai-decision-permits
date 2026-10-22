# R1.2 local numerical reproducibility bundle

This folder is a local output, not a publication or upload. It contains all 504
preassigned formal-v2 trajectories: 432 core rows (24 batches × 3 controls ×
3 budgets × 2 conditions) plus 72 rows with missing required metadata and a
hidden result at budget 3. No failure or truncated trajectory is removed.

Execution was amended after three consecutive provider failures stopped the
original run. The 246 previously started trajectories and their records were
preserved; only the 258 never-started assignments continued. The same ledger,
USD 20 study subcap and USD 200 project cap were retained. The consecutive
provider-failure counter restarted at this documented recovery boundary, while
the original failed/interrupted rows remained in the full denominator. This
was not an uninterrupted execution of the original stopping schedule. See
`CONTINUATION_PROVENANCE.json` for the safe amendment and state-hash provenance.

Run with Python 3.10 or later (standard library only):

```console
python -B reproduce.py
```

The command verifies the bundle hashes, imports the unchanged frozen analysis,
rebuilds all 21 strata and 51 paired contrasts from `SAFE_ASSIGNED_ROWS.json`,
and compares every numerical result and missing-value marker in `TABLES.json`.
It also checks both complete CSV projections. Numeric tolerance is an absolute
1e-12. Successful output contains `verified: true`. No files are written.

The original workspace, private ledgers, API access, environment files, model
responses, candidate source and sandbox are unnecessary. The frozen analysis
contains its original private-run loader for source provenance; `reproduce.py`
calls only its pure `analyze` function and never calls that loader or its CLI.
This is independent numerical recomputation from audited scalar records, not
an independent rerun or raw-execution audit.

## Contents and denominators

- `analysis.py`: byte-identical frozen statistical analysis.
- `SAFE_ASSIGNED_ROWS.json`: all 504 assignment records, outcome/driver status,
  observed-endpoint flag, all prespecified numeric metrics, and safe failure
  count summaries. Missing values remain null; `model_truncated` is retained.
- `SAFE_PROTOCOL.json`: design fields and all assignments, without private
  paths, billing identifiers, credentials, prompts or candidate code.
- `CONTINUATION_PROVENANCE.json`: documented recovery amendment, disjoint
  preserved/continued assignment IDs, state/source hashes and unchanged caps;
  no private ledger or filesystem path is included.
- `TABLES.json`: complete prespecified results, including resource metrics.
- `all_strata.csv`: every metric for all 21 strata, 24 assigned rows per stratum.
- `all_paired_contrasts.csv`: all seven CI metrics for all 51 paired contrasts,
  24 planned pairs per comparison. No comparison is selected by its result.
- `MANIFEST.json`: checksums and the completion/audit provenance gate.

Each trajectory has four eligible task opportunities; each stratum therefore
has 96 task opportunities. Raw yield is visibly verified tasks / 4. Compliant
yield equals raw yield only when starts are known and within budget, otherwise
zero; its ceilings for budgets 1, 3 and 5 are 25%, 75% and 100%. Final acceptance
uses separately executed checks against the same fixed suite, with all four
task opportunities retained. It does not measure unseen-test generalization.

The independent resampling unit is one four-task batch. Intervals use 10,000
common resamples of the 24 complete paired batch blocks, seed 10000. Bounds
for missing outcomes preserve fixed denominators and are not confidence
intervals. The JSON distinguishes identification bounds, bootstrap intervals,
and bootstrap intervals for bound endpoints. No multiplicity-adjusted or
significance-selected claim is made.

Projected token counts and monetary totals are numerical research resources,
not raw billing records or independently reconciled provider invoices. Unknown
usage retains its occupied reservation. CPU values are summed child-process
CPU for measured suite executions; workflow duration also includes model and
host waiting. Gate-specific full-chain coverage is a mechanism diagnostic,
not a common cross-control efficacy score.
