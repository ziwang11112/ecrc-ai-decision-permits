# Results and source map

Artifact index for **Permission and Budget Control for Language Model Agents**,
updated 22 October 2026 with the additional revision evidence. Manuscript prose, LaTeX and paper PDFs are maintained
separately. Historical S8/S9-C/S10/S11/S12 codes identify studies, not current
supplementary table numbers.

## Revision evidence

The [revision package](../revision_results/README.md) contains all 504 additional
assignments, the primary resource/failure reanalysis and local authorization
and issuance measurements. Its numerical entry point verifies 21 strata and
51 paired contrasts, while compact tables make the main compliant-yield
comparisons and all 39 non-finished additional-study trajectories easy to find.
The joint challenge tests claim support: eligible `context` evidence lacks the
`verification_job` type required for `run_verification`. Frozen keys retain
their original names, with an explicit terminology mapping in the guide.

| Revision result | Source | Offline check |
|---|---|---|
| Allowances 1, 3 and 5 plus joint challenge | `revision_results/budget_study/` | All 504 safe records, 945 stratum-metric rows and 357 paired-metric rows |
| Primary acceptance, resources and failures | `revision_results/primary/` | All 576 records and paired batch/sensitivity calculations |
| Issuance timing and authorization order | `revision_results/local_runtime/` | All 6,000 timings, 30 run/phase groups and 14 saved boundary traces |
| Compact paired and termination summaries | `revision_results/review_tables/` | Regenerated from complete numerical inputs |
| Additional-study actor runtime | `revision_results/agent_runtime/` | 13 offline test methods with network/process tripwires |

The additions are included in this source revision. Existing `code-v1.3.0`
material and fixed historical releases remain unchanged.

## Online agent evidence

| Study or result | Public material | Verification scope |
|---|---|---|
| Primary shared-budget study; current Figures 3/4 and primary outcome table | [online_results](../online_results/README.md) | All 576 scalar records; 96 tasks, 24 batches, two model profiles, three controls, two response conditions, two repeats |
| Later DeepSeek and Gemini evaluations | Same package, separate study projections | All 576 planned assignments, including provider, worker and usage-audit failures |
| Later Claude evaluation | Same package, separate study projections | All 288 planned assignments, including eight provider failures |
| Feedback-driven actor loop and execution controllers | [online_agent](../online_agent/README.md) | Public implementation, protocol and offline tests; fresh online use requires explicit model and sandbox configuration |
| Earlier single-task study | Documented in the separate supplement | 360 revised evaluation trajectories over 30 tasks; its raw evidence remains author-held and is not relabeled as the 576-trajectory primary study |

The primary and two later provider studies total 1,440 planned trajectories.
They remain separately identified. The primary plot uses the first 576 only;
all 864 later trajectories remain available for inspection and reanalysis.

Raw verified yield counts distinct tasks with a passing result visible to the
agent by its endpoint, divided by four eligible tasks. Compliant verified yield
sets a trajectory to zero when its actual start count is unknown or exceeds
three. The resulting 75% ceiling is an allowance constraint. It is not a
general program-correctness score. Final candidate acceptance comes from
separately counted post-endpoint execution and is not substituted for visible yield.

The primary study has 559 finishes, 15 unusable-model-response terminations
and two turn-limit terminations. All 576 records have known start counts.
Later provider failures and unknown starts retain their recorded missing-value
semantics rather than becoming invented zero work. Reanalysis uses batch
clusters and preserves pairing, following each package's documented scope.

## Lifecycle and complementary evidence

| Study or result | Code / saved evidence | Check and interpretation |
|---|---|---|
| Raw-request lifecycle; current lifecycle outcome table | [checkpoint observations](../plots/current/data/S8_CHECKPOINT_COUNTS.csv), [42 audits](../plots/current/data/checkpoint_audits/) | Seven checkpoints, two clients, three repetitions; 36 lifecycle runs produced 78 effects and receipts |
| Delivery latency | [run-level observations](../plots/current/data/S6_performance_runs.csv) | 30 runs / 1,920 timed requests; summaries of five run-level 95th-percentile latencies per setting |
| Finite-model boundary; main Figure 5 | [model and verification](../iasc_model_check/PORTABLE_REPRODUCTION.md), [current renderer](../online_results/README.md) | Normal configurations: 684 and 21,960 reachable states; unsafe trace retains all 13 states |
| Airline qualification | [iasc_airline](../iasc_airline/README.md) | 600 contexts / 200 reservations; 2,400 condition runs; 129 eligible, 117 known-ineligible and 354 unresolved contexts |
| Constructed airline boundaries | Same source package | 16 fixtures times four controls, excluded from the native cohort denominator |
| Archived-program verification | [S9-C](../iasc_application/context_correction/README.md) | 112 original + 32 replacement = 144 trajectories; 1,769 jobs / 188 response losses |
| Restart/count witness | [iasc_restart](../iasc_restart/README.md) | Eight current development cells; prior batch and its audit failures retained |

The two workflow schematics are explanatory drawings rather than experimental
observations. Current supplement result plots use the numerical rendering
package linked above. The old figure/table labels in `plots/current/` refer
to the September revision and are not a second set of current outcomes.

## Comparator names and provenance

In the shared-budget online study, prompt-only control receives the same quota
instructions and uses stable identity, cached results and recovery, but lacks
the three-job gate. A separate common eight-job safety cap bounds all arms.
Complete conventional control and ECRC enforce cumulative held-plus-spent units.

S11 direct dispatch calls the native task tool without qualification gating;
its business-rules comparator uses the same domain checker as ECRC. Claim
ablation removes one ECRC dependency. Historical `ordinary` paths in S6/S8/S9
identify the contract-matched lifecycle client. S12 has separate direct,
volatile-count, durable-count and ECRC clients. These are different comparisons.

S9-C corrects omitted public-prompt helpers: all 176 original/replacement
executions remain identifiable, while the current analysis selects 144.
Original totals of 1,802 jobs / 194 drops remain historical. Online numerical
projections support count and interval reanalysis; they do not certify omitted
raw model traffic, private usage ledgers or candidate-execution records.

Run `python -B scripts/verify_current_results.py` for compact saved-result
checks, then follow the [reproduction guide](../REPRODUCIBILITY.md) for
statistical reanalysis, full historical event audits or fresh execution.
