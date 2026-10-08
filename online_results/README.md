# Current online results: public numerical reanalysis

This `code-v1.3.0` package contains all **1,440 formal trajectory projections**:
576 primary trajectories (GPT-4.1 mini and GPT-6 Luna), 576 external trajectories
(DeepSeek Flash and Gemini 2.5 Flash), and 288 Claude Haiku 4.5 trajectories.
All 30 provider/response/control cells and 60 ECRC-versus-comparator contrasts
are retained, including null and unfavorable results. These studies reuse 96
tasks in 24 four-task batches; the trajectories are not 1,440 independent tasks.
Development preflights are outside the formal denominators.

The CSVs are byte-for-byte frozen inputs. `EVIDENCE_INDEX.json` preserves the
original projection and study binding digests. `PROVENANCE.json` binds every
included numerical/model input. No credentials, provider traffic, candidate
outputs, private cost ledgers, manuscript files, or generated plots are included.
The older `../plots/current/` package remains historical.

## Offline verification and reanalysis

Tested with Python 3.12.10, NumPy 2.4.5, and Matplotlib 3.10.9. Install the
dependencies once; subsequent commands require no network or provider access:

```sh
python -m pip install -r online_results/requirements.txt
python online_results/verify.py
python online_results/verify.py --output-dir online_results/_generated/reanalysis
python -m unittest discover -s online_results -p "test_*.py"
```

Commands are shown from the repository root. Input directories default to each
script's own directory and do not depend on the working directory.
`verify.py` requires only NumPy; it writes nothing unless `--output-dir` is given.
It refuses to write recomputed outputs over the frozen input directory.

The verifier checks all included frozen input hashes, complete factorial keys,
status counts, summary counts and observed sums. It recomputes **90 metric
estimates and intervals, 60 paired contrasts, and 108 primary job bins**, comparing
2,298 numerical values with the frozen tables to absolute tolerance `1e-12`.
Optional outputs contain recomputed metric and paired tables plus a JSON report.
The original CSVs are never rewritten.

Every metric averages the two repetitions within each batch and then weights
estimable batches equally. One NumPy `default_rng(20261007)` index matrix with
shape `(10000, 24)` jointly resamples all provider/condition/control cells.
Intervals use the 2.5th and 97.5th percentiles (`numpy.quantile` default linear
interpolation). Paired contrasts subtract ECRC and comparator means within
common estimable batches before using the same resampling matrix. Undefined
resamples, if any, are excluded and counted. These are descriptive intervals.

- Raw verified yield is actor-visible distinct passing tasks divided by four.
- Actual excess is more than three starts among trajectories with known counts.
- Compliant yield is raw yield when starts are known and at most three; otherwise
  the whole trajectory scores zero. Its ceiling is 75%. The common eight-job
  safety cap is distinct from the three-job study quota.

All four external worker interruptions retain blank endpoint scalars: one
DeepSeek/ECRC hidden-result trajectory, one Gemini/ECRC normal trajectory, and
two Gemini/prompt-only hidden-result trajectories. Missing raw outcomes are not
zero-imputed; available repetitions are averaged within batch. Consequently an
observed-only mean can differ from pooled numerator/denominator. The compliant
score is zero when compliance cannot be established. Non-finished trajectories
with observed measurements remain included. Zero excess among failed or already
compliant actors does not demonstrate additional blocking benefit.

| Projection | Finished | Other retained outcomes | Unknown starts |
|---|---:|---|---:|
| Primary, 576 | 559 | 15 model response errors; 2 turn limits | 0 |
| External, 576 | 525 | 43 usage-audit failures; 4 provider failures; 4 worker failures | 4 |
| Claude, 288 | 280 | 8 provider failures | 0 |

`*_cell_results.csv` also retains observed model calls, starts, denials, held
units, recovery, final acceptance, and termination counts. Independent final
acceptance can include unverified selections and is distinct from actor-visible
workflow yield. Suite acceptance does not establish general program correctness.
No monetary costs are inferred from call counts or timing.

## Rebuild current plots

Arial must be installed and discoverable by Matplotlib; all renderers fail if
it is unavailable. Font files are not redistributed. Exact pixels/PDF bytes
depend on library and font versions; the numerical verification is font-free.

```sh
python online_results/plot_from_csv.py --output-dir online_results/_generated/primary
python online_results/supplemental/plot_supplemental_from_csv.py --output-dir online_results/_generated/supplemental
python online_results/counterexample/draw_effect_counterexample.py --output-dir online_results/_generated/counterexample
python online_results/verify_plots.py --output-dir online_results/_generated/plot_check --require-baseline
```

The primary renderer redraws `shared_agent_jobs` and `shared_agent_yield` as PDF
and PNG. It validates all job bins and metric cells, uses proportional circle
areas, and shows all 24 yield estimates with intervals. Both PDFs are 16.5 by
10.8 cm, with black Arial labels at 9.5 or 10 pt and PNGs at 300 dpi. It reads
frozen aggregate CSVs; use `verify.py` to recompute those aggregates and intervals.

The supplemental renderer redraws `airline_results` and `verification_results`
as PDF, PNG, and SVG. It checks all 16 airline category counts (denominators 129,
117, 200, and 154) and eight verification cells, including all 16 timely/eventual
counts and 1,769 starts. These two CSVs are aggregate snapshots. Their internal
consistency is reproducible here; reconstruction of original per-run records
requires the corresponding historical archives elsewhere in the repository.

The counterexample renderer cross-checks all 13 saved state records in the
frozen replay JSON against the frozen CSV, and draws states 4, 7, 8, 10, and 13.
It produces PDF, SVG, PNG, and a scoped manifest. The original TLC stdout is
omitted because it contains local paths. Its digest is a provenance reference,
not a verified local input. Rendering does not run TLC, establish reachability,
or independently replay transition guards. See `../iasc_model_check/` for the
historical finite-model source and verification evidence.

`verify_plots.py` runs numerical verification, renders the three groups in
separate output directories, and compares the primary/supplemental outputs to
`plot_baselines.json`, along with the counterexample PNG. It reports both file
digests and decoded RGBA pixel digests. The counterexample PDF retains the
original renderer's time-dependent metadata, so it has no fixed PDF-byte
baseline. Without `--require-baseline`, environment-dependent differences are
reported rather than treated as errors. Generated files belong in ignored
`_generated/`; they are not release inputs.

## Scope of evidence

Public reanalysis verifies the published projection bytes and their mathematical
consequences. It does **not** reconstruct API requests/responses, sandbox events,
candidate execution, hidden-result delivery, or the original private execution
audit. A matching raw-run or audit digest in `EVIDENCE_INDEX.json` identifies
upstream evidence; possession of that digest alone does not verify its contents.
The verifier therefore explicitly reports `raw_execution_audit_performed: false`.

The original bindings and scalar bytes are retained for traceability, while
this package supplies a separate reproducible numerical check. All commands
above are offline replay, reanalysis, or plotting; none launches new experiments.
