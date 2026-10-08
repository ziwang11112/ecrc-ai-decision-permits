# Reproduce or verify an artifact

Run the commands below from the repository root using Python 3.12 unless a
section explicitly names another working directory. Use a fresh destination
for each new run; the two figure builders intentionally share its new output
directory. A saved-evidence check, a supplemental QA
run and a new scientific reproduction answer different questions.

## 1. Verify the checkout and run the small supplemental QA

```console
python scripts/verify_release.py
python scripts/verify_source_view.py
python -B iasc_model_check/portable_reproduce.py
python -B scripts/run_wrapper_qa.py --output artifacts/wrapper-qa-1
```

These commands require only the Python standard library. The first checks
the current file checksums. The second cross-checks every entry of the four
historical inventories against the current source-view mapping, including
original hashes and explicit omissions. The third checks S10's retained files
and result bindings; it does not invoke Java or enumerate any states. The fourth runs the
retained ten-case S8 supplemental wrapper QA from a fresh copy of its 34 frozen
source/input files and checks the report contents as well as the process exit.

Do not invoke the archived `review_atomic_wrapper_portable.py` directly in the
Git mirror: it intentionally refuses to overwrite its tracked historical
report. The new runner preserves those bytes and places the fresh report at
`artifacts/wrapper-qa-1/revision_reviews/runtime_review/WRAPPER_QA_PORTABLE_RESULT.json`.

## 2. Current result checks and full saved evidence

```console
python -B scripts/verify_current_results.py
python -B plots/current/verify_observations.py
python -B iasc_application/context_correction/verify_current.py
python -B iasc_airline/verify_results.py
python -B iasc_restart/verify.py
```

The combined entry point runs six checks, including online numerical reanalysis
and S10's saved-evidence check. Install NumPy with
`python -m pip install numpy==2.4.5` for the online reanalysis. The five historical
commands use the standard library. No model, paid API, candidate program or
formal experiment runs. The current figure/table mapping is in
[RESULTS.md](docs/RESULTS.md).

### Online agent implementation and numerical results

```console
python -B online_agent/check.py
python -B online_agent/schedule.py --check
python -B online_results/verify.py
python -B -m unittest discover -s online_results -p "test_*.py"
```

The implementation check uses the standard library and injected test responses
and runners. It verifies public source bindings, the frozen schedules and the
feedback loop without inference or sandbox execution. The result check uses
NumPy to recompute the 1,440 retained trajectory projections, including failures,
30 outcome cells and 60 paired contrasts. These trajectories share 96 tasks and
24 analysis batches; they are not 1,440 independent tasks.

Read [the implementation guide](online_agent/README.md) for fresh execution.
It supplies the actor loops, prompts, tasks, execution controllers and sandbox
sources. Provider transports, response and usage normalization, paid-account
controls and orchestration must be supplied by the caller. The parameterized
public sandbox launcher has a different identity from the historical launcher.

Read [the results guide](online_results/README.md) for projection provenance,
missing-value rules and the paired batch bootstrap. These public scalar records
do not contain raw provider traffic, generated candidate bodies or cost ledgers.
The earlier 360-trajectory single-task study is a separate, author-held archive.

```console
python scripts/download_artifact.py s9-c --output artifacts/s9-c
python scripts/download_artifact.py s11 --output artifacts/s11
python scripts/download_artifact.py s12 --output artifacts/s12
```

Follow [S9-C](iasc_application/context_correction/README.md),
[S11](iasc_airline/README.md) and [S12](iasc_restart/README.md) for full
projection/native-record/SQL audits and exact archive root paths. Large records
are separate from the code view. The original archive selectors remain available:


```console
python scripts/download_artifact.py s1-s8 --output artifacts/s1-s8
python scripts/download_artifact.py s9 --output artifacts/s9
python scripts/download_artifact.py s10 --output artifacts/s10
```

All archives are pinned by size, SHA-256 and member count in
[ARTIFACTS.json](ARTIFACTS.json). The downloader also verifies each internal
manifest member before creating the destination. An existing download can be
checked offline with `--archive PATH_TO_ZIP`; the same validation is used.
The downloader uses Windows extended filesystem paths for deep archive members;
it does not require changing system settings or shortening the archive's names.

| Selection | Extracted package root | Verified files |
|---|---|---:|
| `s1-s8` | `artifacts/s1-s8` | 9,744 |
| `s9` | `artifacts/s9/AIR-014_IASC_S9` | 6,698 |
| `s10` | `artifacts/s10/AIR-014_IASC_S10` | 107 |

### S8: audit both retained run sets without executing the experiment

```console
python -B artifacts/s1-s8/end_to_end/portable_reproduction/R2_AUDIT/verify_s8_reproduction.py --primary-root artifacts/s1-s8/end_to_end --reproduction-root artifacts/s1-s8/end_to_end/portable_reproduction --report-dir artifacts/s8-saved-audit-1
```

This full-archive-only helper audits temporary copies of the databases. It
does not start services or add experimental runs. Each run set contains 36
final client/sink pairs and 126 checkpoint backup pairs (90 non-final and 36
final), with 78 effects and 78 receipts. Each saved-state audit reports 36,210
checks. The primary and reproduction sets remain separate.

The full ZIP's `end_to_end/portable_reproduction/README_ARCHIVE.md` documents
this helper. That directory is intentionally absent from the smaller Git
source mirror. The frozen low-level `audit_e2e.py` writes its `passed` result
but does not reliably encode failures in its process exit status; inspect its
JSON and inventory if using it directly. An empty directory is not evidence.

### Original S9: historical public projections

```console
python -B artifacts/s9/AIR-014_IASC_S9/check_public.py --bundle artifacts/s9/AIR-014_IASC_S9 --public-only --out artifacts/s9-public-check-1.json
```

These are **historical, pre-correction** results. For the
current 112+32 selection use the S9-C verifier above.

Expect `checks_passed: true`. This verifies 152 retained run records: eight
development integration runs and 144 formal trajectories. The checker derives
task counts, actual starts, budget accounting, timing, response loss/cache
behavior and feedback-dependent policy choices from public projections. It
does not execute candidate programs. The formal denominator remains 144.

Use this checker for the public ZIP. The historical `analyze_application.py`
also expects author-held raw databases and is not the public-only entry point.

### S10: inspect retained finite-model evidence

The Git source view includes the retained verification inputs. To verify the
downloaded copy separately:

```console
python -B artifacts/s10/AIR-014_IASC_S10/portable_reproduce.py --report artifacts/s10-saved-check-1.json
```

Expect `status: PASS`, 15 frozen source bindings and 19 retained evidence
digests verified. The normal-case counts are 684 and 21,960 states. The
counterexample endpoint is checked; default mode does not independently
replay its entire trace or re-enumerate the state space. The 205 external
author-workspace baseline targets are explicitly `NOT_CHECKED`, not bundled
S10 files. See [the full S10 guide](iasc_model_check/PORTABLE_REPRODUCTION.md).

## 3. Rebuild the numerical figures

```console
python -m pip install -r online_results/requirements.txt
python -B online_results/verify_plots.py --output-dir artifacts/online-figures-1 --require-baseline
```

This rebuilds the two primary online-agent plots, the airline and archived
program plots, and the finite counterexample plot. It first checks the numerical
inputs. The recorded baseline uses NumPy 2.4.5, Matplotlib 3.10.9 and Arial;
the font must already be installed. See [the plot guide](online_results/README.md)
for individual commands and the rendering checks. Figure scripts use retained
records and make no model/API calls.

### September technical figures

```console
python -m pip install -r plots/current/requirements.txt
python -B plots/current/build_figures.py --out artifacts/current-figures
```

The [historical plotting guide](plots/current/README.md) covers three September
technical figures and saved S6/S8 table observations. These frozen sources
retain their original exhibit labels. Arial reproduces that version's font;
`--font "DejaVu Sans"`
explicitly requests a layout variant when Arial is unavailable. Generated files
stay in the fresh output directory. This performs no model/API call or new study.
The obsolete five-figure package remains in tag `code-v1.1.0`.

## 4. A new scientific reproduction requires the study's environment

| Component | What is needed and where to begin |
|---|---|
| Shared-budget online agents | `online_agent/README.md` and `online_agent/SANDBOX.md`; caller-supplied provider client/accounting/orchestration, a configured isolated Linux executor and fresh output. Public offline tests do not execute generated candidates. |
| Historical core tests | Python 3.12; `python -m pip install -e ".[test]"`, then `python -m pytest -q`. This is a separate pinned dependency set. |
| S6 delivery | The Git mirror contains the execution sources: read `iasc/runtime/PROTOCOL.md` and the retained environment. Complete historical evidence is in the S1–S8 ZIP. Run into a new directory; timing depends on the host. |
| S7 statistical reconstruction | Complete `iasc/statistics/` directory, its `requirements.txt` and README. Copy it to a new work directory first: its original verifier writes `verification.json` beside the scripts. |
| S8 full HTTP/process experiment | Complete S1–S8 package and `end_to_end/portable_reproduction/README.md`; follow the preserved platform requirements and use fresh output. The ten-case quick QA is not this experiment. |
| S11 native qualification | See `iasc_airline/README.md`: pinned tau2-bench, frozen model-free actors/evaluator and portable runner; use fresh output. |
| S12 restart witness | See `iasc_restart/README.md`: stdlib portable runner, separate from archived scientific cells. |
| S9 program execution | Exact upstream candidate material, reconstruction hashes and original task tests, plus the documented Windows/WSL sandbox and dependencies. Start with the reconstruction recipe in `iasc_application/README.md` and `reconstruct_catalog.py --help`. The frozen launcher contains author-environment paths; it is not a turnkey portable runner. |
| S10 fresh model run | Explicit Java executable/hash and frozen TLC JAR; follow `iasc_model_check/PORTABLE_REPRODUCTION.md --execute` instructions. Default verification needs neither tool. |

Candidate bodies and raw private S9 databases are not shipped. The public
projection checker cannot reconstruct hashes of deliberately excluded raw
bytes. Historical `run_e1.py` source bytes and ten inner calibration grids
also remain unavailable; do not substitute a modern retraining run for that
missing history.

The S6 entry points use only the standard library and are also present in the
Git source mirror. To execute its full suite and then audit the new results:

```console
python -B iasc/runtime/run_experiment.py --out artifacts/s6-new-run-1 --reps 5
python -B iasc/runtime/audit_runtime_traces.py --suite artifacts/s6-new-run-1 --report-dir artifacts/s6-new-audit-1
python -B iasc/runtime/audit_information_match.py --suite artifacts/s6-new-run-1 --report artifacts/s6-new-information-match-1.json
```

These are **new experiment** commands, not part of the saved-evidence quick
check. They start local services and cover recovery and timing; the cleanup
audit checked their entry points but did not execute another formal suite.

## Verification status and update policy

The cleanup audit is reported in [completeness and scope](docs/ARTIFACT_COMPLETENESS.md).
Repository GitHub Actions were disabled when audited. The workflow file is
provided and its broken wrapper command is corrected, but no cloud-CI pass is
claimed. Local checks and their scope are recorded separately.

The root `MANIFEST.json` / `SHA256SUMS.txt` describe the current Git source
revision. `SOURCE_VIEW.json` records intentional manuscript-material omissions
from historical inventories; `python scripts/verify_source_view.py` checks that
mapping. Historical releases retain their originally published contents, which
can include older manuscript-formatting material. Each fixed release has its own manifest. Preserve frozen sources,
old reports and releases when producing new output; a presentation or tooling
revision is not another experimental repetition.
