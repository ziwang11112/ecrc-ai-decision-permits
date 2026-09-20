# Current results and source map

Paper: **ECRC: Decision Permits for Budgeted Workflows**. This is an artifact
index, not a copy of the paper. S1-S12 are study identifiers; supplementary
table numbers use a separate sequence.

| Current exhibit | Code / saved evidence | Check and interpretation |
|---|---|---|
| Figure 1 | [workflow renderer](../plots/current/source/supplement/figure_revision/draw_workflows.py) | Constructed missing-evidence / unknown-outcome cancellation example; no observed airline recovery trial |
| Figure 2 | Same renderer | Client/service permission lifecycle and non-action exit |
| Figure 3 | [counterexample sources](../plots/current/source/supplement/figure_revision/counterexample/) | All 13 states retained; plotted states 4/7/8/10/13; backing fails at 8, effect limit at 13 |
| Table 1 | [S11 code and outcomes](../iasc_airline/README.md) | 600 contexts / 200 reservations; 2,400 primary condition runs; eligible 129, known-ineligible 117, unresolved 354 |
| Table 2 | [checkpoint CSV](../plots/current/data/S8_CHECKPOINT_COUNTS.csv), [42 audits](../plots/current/data/checkpoint_audits/) | Seven saved states x 2 clients x 3 repetitions; `verify_observations.py` matches every count to its audit |
| Table 3 | [S6 run-level latency](../plots/current/data/S6_performance_runs.csv) | 30 runs / 1,920 timed actions; median/min/max of five run-level p95 values per client/thread setting |
| Table 4 | [S9-C retained results](../iasc_application/context_correction/README.md) | 112 original + 32 replacement = 144 trajectories; 1,769 jobs, 188 response losses; all eight condition totals retained |
| Supplementary Table S1 | [S11 constructed boundaries](../iasc_airline/README.md) | 16 fixtures x 4 conditions = 64 runs, excluded from the native cohort denominator |
| Supplementary Table S2 | [S12 restart witness](../iasc_restart/README.md) | Eight current development cells; prior batch and its audit failures retained |
| Supplementary Table S3 | Paper literature comparison | No experimental dataset or measured superiority claim; bibliography/prose remain outside this repository |

Run `python -B scripts/verify_current_results.py` for compact saved-result checks.
The [reproduction guide](../REPRODUCIBILITY.md) distinguishes full event/SQL audits
from fresh execution.

## Current and historical S9 results

The original S9 asset preserves all 144 formal trajectories. S9-C supplies 32
replacement trajectories after restoring omitted public-prompt helpers/imports.
The current selection is 112 originals plus 32 replacements. All 176 executions
remain identifiable. Original totals of 1,802 jobs / 194 drops are superseded; current
totals are 1,769/188. Correction source maps record exact input/version provenance.

Candidate bodies and arbitrary execution output are excluded where redistribution
permission was not established. Public projections permit numerical reanalysis;
full original-result hash verification requires the excluded raw bytes.

## Comparator names

The S11 direct-dispatch baseline calls the native task tool without qualification
gating. Its business-rules comparator uses the same domain checker as ECRC;
claim-evidence deletion is an internal ablation. In S6/S8/S9, historical `ordinary`
paths identify the **contract-matched lifecycle comparator**, not direct dispatch.
S12 separately compares direct, volatile-count, durable-count and ECRC clients.
These are different comparisons and must not be merged under one baseline label.

## Versioned evidence

The S1-S8, original S9 and S10 release assets remain unchanged. New S9-C, S11 and
S12 assets are pinned by `ARTIFACTS.json`; study source maps identify Git-view
omissions and any portable wrappers. Numerical equality is conformance evidence
within each study's boundary, not an exclusive ECRC utility/latency advantage.
