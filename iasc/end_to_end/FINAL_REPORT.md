# S8 end-to-end extension: completed evidence

All 36 primary runs passed the predeclared outcome checks: six scenarios,
three repetitions and two implementations. The actual final databases contain
300 raw requests and registered permits, and 78 synthetic sink effects matched
to 78 local receipts. Eighteen workers were actually terminated at issuance
checkpoints; six accepted requests produced a real client TimeoutError after
the service committed and delayed its response. These counts come from the
saved traces and databases, not prefilled expected values.

The independent auditor read all 36 final client/sink database pairs and all
126 intermediate backup pairs. All 36,210 checks passed. Each arm received
identical original raw input bytes in all 18 paired scenario/repetition cells.
Each run admitted two distinct alert decisions from eight contenders; the
mixed-route scenario additionally admitted one review and retained the
unsupported-claim release record. Concurrent winner IDs were not required to
match.

## Observed boundaries

| Checkpoint | Permits / held / effects / receipts |
|---|---|
| Distinct-decision competition completed | 8 / 0 / 2 / 2 |
| Unsupported claim released and fallback registered | 1 / 0 / 0 / 0 |
| Process killed after reservation SQL but before issuance commit | 0 / 0 / 0 / 0; raw request remained received |
| Issued permit survived process kill and pre-expiry cleanup | 1 / 1 / 0 / 0 |
| Expired unarmed permit cancelled and released | 1 / 0 / 0 / 0; subsequent replay dispatched nothing |
| Accepted request timed out; cleanup retained unknown grant | 1 / 1 / 1 / 0 |

These tuples were identical across the six observations per scenario. They
are observed committed states, not an exhaustive enumeration of interleavings.
The cancelled permit remains registered for audit. After explicitly restored
communication and recovery, all primary runs finished with no unresolved held
unit; this is not a claim of unconditional completion during indefinite outage.

## Fresh portable reproduction

Only the 34 frozen code/input files plus the freeze and documentation files
were copied to a new `../portable_e2e_check` directory before execution. No
previous database, permit fixture or result was copied. From that location,
all 36 runs were repeated with new service processes and databases, followed
by the same independent read-only audit of 36 final and 126 checkpoint pairs.
All passed again (36,210 checks). The aggregate `outcomes.csv` and
`S8_state_table.csv` were byte-identical to the primary outputs. Permitted
concurrent winners differed in 33 of the 36 runs, confirming that reproduction
does not require identity-level equality. See `PORTABLE_VERIFICATION.json`.

Reproduction runs, 41 ordinary development checks, 10 independent wrapper QA
checks, 10 cloned-database corruption checks and four canonical-comparison
checks remain separate from the 36-run primary denominator. The initial
Windows temporary-file cleanup failure and pre-freeze audit deficiencies are
retained in the development documentation. The 13 copied legacy source files
match their original hashes; the original runtime, S6 outputs and manuscript
were not changed by this subtask.

## Manuscript-ready results paragraph

Across the 36 raw-request runs, both implementations met all planned state
checks. After a kill before the new issuance commit, only the durable raw
request remained; reservation, registration and permit persistence rolled back
together. A complete issued permit survived a later process kill, while
expired unarmed cleanup released its reservation and prevented subsequent
dispatch. Unsupported action claims likewise released provisional capacity
before non-action registration. By contrast, a client timeout after sink
acceptance left one effect, no receipt and one held unit; cleanup retained
that grant, and recovery reconciled the original effect without duplication.
Distinct decisions respected alert and review budgets of two and one. The
ordinary implementation independently issued permits from the same raw
requests and reached the same tested outcomes; the experiment establishes no
exclusive correctness advantage for ECRC. Independent inspection covered all
final databases and 126 intermediate database pairs. A full run from a fresh
relocated code/input directory reproduced aggregate outcomes while allowing
different concurrent winners.

## Scope retained

This is newly implemented atomic issuance, not a retrospective claim that the
archived multi-transaction adjudicator was already atomic. The ordinary arm
shares declarative input construction, transport and sink, but not ECRC
issuance/validation functions. The evaluated contract uses one fixed policy,
canonical schema, trusted model/evidence declarations, one scope and synthetic
records. It does not validate predictor computational provenance, useful alert
timeliness, cross-revision budget continuity, cancellation after arm,
power-loss resilience or production scalability. Injected policy clocks are
distinct from wall-clock service/receipt timestamps; the sink samples its
stored effect timestamp before insertion, rather than measuring commit
completion. S6 performance results remain unchanged; S8 reports no performance
comparison.

## Integration files

- `out/S8_results_table.tex`: editable LaTeX state/result table, generated from actual outputs.
- `out/S8_state_table.csv`: the same table as data.
- `out/MANUSCRIPT_SNIPPETS.md`: methods/results/limits text.
- `out/outcomes.csv`, `out/INDEPENDENT_AUDIT.json`, `out/INFORMATION_MATCH.json`: all primary outcomes and audits.
- `out/*/rep-*/*/`: raw inputs, durable client/sink files, logs, full traces and backups.
- `CODE_FREEZE.json`: 34 locked files; SHA-256 `32d7f1b448ce0358a1af73145b1f203006468c3e732c8d04a9001e053d2802bc`.
- `PORTABLE_VERIFICATION.json`: fresh execution comparison and stable-output hashes.

For the portable submission package retain the frozen files at their relative
paths, CODE_FREEZE, protocol/amendment, README/requirements, capability/source
matrix, primary out tree, QA reports and this report. Development matrices and
the full second execution can remain a separately labelled audit archive;
their summaries and comparison record should remain available. The complete
primary `out` currently contains about 34.6 MB of uncompressed evidence.
