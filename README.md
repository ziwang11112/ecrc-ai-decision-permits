# ECRC: decision permits for capacity-bounded AI actions

Implementation, saved evidence and figure sources for **Decision Permits for
Capacity-Bounded Artificial Intelligence Actions: Binding Authorization to Effects**.

ECRC makes authorization, cumulative action-budget responsibility and effect
completion explicit in a decision-permit lifecycle. The evaluated ordinary
implementation is information-matched and supports the same tested obligations.
The contribution is the contract, its implementation and measured boundaries;
it is not a claim that the ECRC record format uniquely provides correctness or
task benefit.

## Start here

| What you want to do | Entry point |
|---|---|
| Check what is included and what remains unavailable | [Completeness and scope](docs/ARTIFACT_COMPLETENESS.md) |
| Follow commands for a fresh checkout | [Reproducibility guide](REPRODUCIBILITY.md) |
| Rebuild the current paper's five figures and inspect its five tables | [Current paper artifacts](paper_artifacts/README.md) |
| Download the complete saved study evidence | [Pinned archive registry](ARTIFACTS.json) and commands below |
| Inspect the implementation, protocols and comparisons | [Source map](#source-map) |
| Check original dataset attribution and reuse terms | [Data sources](docs/DATA_SOURCES_AND_LICENSES.md), [licenses](LICENSES.md) |

The Git checkout contains browsable code and selected evidence. The complete
S1–S8 and S9 evidence is in the fixed release ZIPs. The current S10 verification
package and compact current figure inputs are included directly in Git.

## Quick verification

Use Python 3.12. These checks use only its standard library. They do not train
models, execute candidate programs or start a new formal experiment.

```console
git clone https://github.com/ziwang11112/ecrc-ai-decision-permits.git
cd ecrc-ai-decision-permits
python scripts/verify_release.py
python -B iasc_model_check/portable_reproduce.py
python -B scripts/run_wrapper_qa.py --output artifacts/wrapper-qa-1
```

The last command copies the frozen S8 sources into a **fresh** output directory
and runs ten supplemental exception/thread checks. It preserves the archived
report. Choose a different output directory for another run. Those checks are
separate from the formal S8 HTTP/process-recovery experiment.

## Complete study archives

Download whichever study you need. Each command verifies the pinned archive
SHA-256, exact member inventory and every member's hash before extraction.
No account, credentials or paid API is required.

```console
python scripts/download_artifact.py s1-s8 --output artifacts/s1-s8
python scripts/download_artifact.py s9 --output artifacts/s9
python scripts/download_artifact.py s10 --output artifacts/s10
```

| Archive | Size | Fixed release |
|---|---:|---|
| S1–S8, including both S8 run sets | 100.4 MB | [iasc-restructured-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-restructured-2026-09-12) |
| S9 application, including public trajectory projections | 11.4 MB | [iasc-application-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-application-2026-09-12) |
| S10 saved evidence and corrected portable verifier | 0.26 MB | [iasc-portability-fix-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-portability-fix-2026-09-12) |

The [guide](REPRODUCIBILITY.md) identifies the extracted package roots and gives
public-only recalculation commands. The earlier S1–S8 downloader remains
available for compatibility. Original release assets and scientific records
remain unchanged.

## Source map

| Study / component | Sources and evidence | Boundary |
|---|---|---|
| Historical simulator and replay | [src/](src/), [icair_2026/](icair_2026/), [tests/](tests/) | Original simulator; separate from later atomic issuance |
| S6 preissued delivery | [iasc/runtime/](iasc/runtime/PROTOCOL.md) | Separate service, recovery, boundary checks and timing |
| S7 participant analysis | [iasc/statistics/](iasc/statistics/README.md) | Frozen-score policy analysis; original fits are not rerun |
| Calibration and training provenance | [calibration](iasc/calibration/README.md), [methods](iasc/methods/README.md) | Historical source and retained-grid limitations are explicit |
| S8 issuance through recovery | [iasc/end_to_end/](iasc/end_to_end/README.md) | All 34 frozen source/input files; full saved databases in S1–S8 ZIP |
| S9 controlled program verification | [source view](iasc_application/SOURCE_VIEW.md), [results](iasc_application/FINAL_RESULTS.md) | Public projections in S9 ZIP; candidate bodies obtained upstream |
| S10 finite lifecycle model | [model and results](iasc_model_check/README.md), [verification guide](iasc_model_check/PORTABLE_REPRODUCTION.md) | Finite specification evidence; default verifier does not enumerate |
| Current paper Figures 1–5 and Tables 1–5 | [paper_artifacts/](paper_artifacts/README.md) | Locally generated figures, compact inputs and current numbering |

The current main tables are: (1) lifecycle states, (2) S6 delivery latency,
(3) S9 application outcomes, (4) cap-removal precision, and (5) related-work
scope. Earlier presentation indices under `iasc/presentation_revision/` retain
their historical figure/table numbering. They are not the current paper index.

## Evidence and limits

- Replay: 617 development and 59 external participants from the same IGT task;
  A/B choices are proxy labels, not verified intervention opportunities.
- S8: 36 primary runs and a separately retained 36-run reproduction. Effects
  are synthetic records; checks and snapshots are not independent samples.
- S9: 144 formal trajectories, 1,802 actual verification jobs and 194 cached
  response recoveries without additional suite starts. The two complete
  implementations tie on timely task counts in 71 of 72 paired cells. Tasks
  were previously exposed and acceptance is limited to the finite test suite.
- S10: fully explored normal instances with 684 and 21,960 reachable states,
  plus a 12-transition changed-release counterexample. This is not a theorem
  for unbounded instances or a proof of the Python implementation.

The budget is cumulative held-plus-committed action units. Completion does not
replenish a concurrency slot. An armed action with unknown outcome retains its
budget responsibility. An effect-backed receipt does not guarantee that a
crash before persistence never causes repeated computation.

## Data, licensing and historical gaps

Code uses MIT terms. Derived IGT evidence and figures retain CC BY-SA 4.0 and
upstream attribution; the public artifact includes participant- and
decision-level derived records. No raw EEG, new participant collection or
candidate-program redistribution is included. See [LICENSES.md](LICENSES.md).

Full historical training reconstruction is not claimed: the original
`run_e1.py` bytes and ten inner calibration grids were not recovered. S9's
public checker reconstructs saved outcomes without candidate bodies; executing
the original sandbox workflow additionally requires the documented upstream
material and author-environment setup. See the explicit
[availability matrix](docs/ARTIFACT_COMPLETENESS.md).

This repository cleanup changes navigation and adds current presentation
materials and safe execution entry points. Frozen studies and old release
assets are preserved. [Prior top-level documentation](docs/history/pre-artifact-guide-2026-09-12/README.md)
and earlier release history remain available. Full manuscript PDFs, complete Overleaf projects,
cover letters and editorial correspondence are not part of this code repository.
