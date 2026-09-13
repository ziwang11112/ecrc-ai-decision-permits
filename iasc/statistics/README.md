# Participant-level policy analysis

The source view contains the numerical analysis, its independent verifier,
protocol, copied inputs and complete saved results. Manuscript snippets and
their prose/LaTeX formatter are excluded. `PACKAGE_MANIFEST.json` records the
historical full archive; the repository's `SOURCE_VIEW.json` identifies the
current included and omitted files without changing historical hashes.

## Run or verify

The archived environment used Python 3.12.14, NumPy 2.3.5 and pandas 3.0.1.
Copy this directory to a new working location first: the original verifier
writes `verification.json` next to its script.

From that copy, verify existing results with:

```console
python -m pip install -r requirements.txt
python verify_results.py --out out --repeat out_repeat
```

To reconstruct the analysis in new output directories:

```console
python run_analysis.py --out fresh_run
python run_analysis.py --out fresh_repeat
python verify_results.py --out fresh_run --repeat fresh_repeat
```

The analysis uses frozen participant counts; it does not fit models or select
thresholds. The verifier independently reconstructs points and bootstrap
vectors without importing the analysis implementation. `prepare_inputs.py`
is the original author-side input-copy recipe, not a prerequisite for this
self-contained numeric bundle.

## Data and estimands

- `input/`: copied participant/aggregate counts and provenance.
- `out/arm_estimates.csv`: 72 metric rows across 36 policy cells.
- `out/paired_comparisons.csv`: 36 metric contrasts across 18 comparisons.
- `out/bootstrap_*.csv.gz`: all 2,000 saved draws and participant multiplicities.
- `out_repeat/`: the retained independent analysis execution.
- `all_comparisons_summary.csv` and `RESULTS.md`: complete numerical summary.

Pooled precision weights alerts; participant-equal precision averages over
participants with a nonzero alert denominator. Paired differences use the
common valid set. No-alert precision is undefined, while a positive-bearing
participant with no alert has zero positive coverage. Intervals condition on
the frozen scores, policies and histories and are exploratory and unadjusted.
They do not estimate intervention benefit or model-fitting uncertainty.
