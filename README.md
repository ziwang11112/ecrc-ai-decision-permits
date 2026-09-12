# ECRC: decision permits for capacity-bounded AI actions

Code and reproducibility materials for **Decision Permits for Capacity-Bounded Artificial Intelligence Actions: Binding Authorization to Effects**.

**Current S10 tool repair:** [iasc-portability-fix-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-portability-fix-2026-09-12).
The post-study portable wrapper now resolves archived Windows separators on
POSIX while rejecting rooted or escaping paths. Windows and Linux verify-only
checks cover both the source and the extracted revision ZIP. All 15 frozen
study files and the 19 retained evidence digests match the original study.
The old wrapper, original POSIX failure and focused repair checks are retained
under [portability_revision/](iasc_model_check/portability_revision/).
This is an artifact usability correction; no model exploration, TLC run or S9
experiment was added. Original tags and assets remain unchanged.

**Original finite lifecycle study (S10):** [iasc-model-check-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-model-check-2026-09-12).
The [model, results and limits](iasc_model_check/README.md) provide two fully
explored normal instances (684 and 21,960 reachable states), cross-checked by
TLC and independent exact enumeration, plus a replayed 12-transition
changed-release counterexample. This is finite specification evidence, not a
parameterized theorem, implementation proof or ECRC-exclusive advantage.
[Portable reproduction](iasc_model_check/PORTABLE_REPRODUCTION.md) verifies
retained evidence by default and can run the unchanged cases with explicit
Java/TLC paths into a fresh directory. [Release contents](iasc_model_check/RELEASE_CONTENTS.md)
distinguish the original study from the successful extracted-archive repeat.

**Earlier controlled application (S9):** [iasc-application-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-application-2026-09-12).
Browse its [source and analysis](iasc_application/SOURCE_VIEW.md) and
[complete results and limits](iasc_application/FINAL_RESULTS.md). The fixed S9
ZIP supplies all public trajectory projections and a public-only independent
recalculation. It executed 1,802 actual verification jobs across 144 fixed
trajectories. The 194 cached response recoveries added no suite starts. Timely
task counts match between the two complete implementations in 71 of 72 paired
cells; policy contrasts are not an ECRC-exclusive utility advantage. Candidate
bodies are obtained directly from their authors using the documented exact
download/hash reconstruction recipe. No manuscript PDF or Overleaf source is
included in this code release.

**Unchanged S1–S8 IASC version:** [iasc-restructured-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-restructured-2026-09-12).
The release contains the full S1–S8 reproducibility archive, including both S8
run sets, and checksums. This repository also exposes the current implementation,
analysis and plotting sources in [iasc/](iasc/README.md).

The [S1–S8 presentation index](iasc/presentation_revision/README.md) maps five main
figures, five editable tables and seven equations to their sources, row keys,
transformations and hashes. That earlier presentation revision added no
training, bootstrap or formal experiment. S9 is a separate new experiment,
with the original Table 6 and an extension of the design table documented in
its own index. The current manuscript places application results before the
allocation analysis: application is now Table 5 and cap removal is Table 6.
Archived table identifiers retain their original meaning.
The older
[iasc-r2-2026-09-12](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-r2-2026-09-12)
release remains fixed and accessible. All its scientific files are unchanged;
the current full artifact adds presentation_revision/ and updated root indices.

## What is evaluated

ECRC separates a frozen model proposal from permission to act. It binds eligible
authorization evidence, an exclusive route, scoped alert/review capacity, finite
claims and completion records. Conventional transactions, outbox delivery and
sink idempotency implement these obligations; those mechanisms are established.

The original simulator, S6 delivery adapter and S8 atomic issuance wrapper have
different boundaries. The original simulator does not gain S8's new issuance
transaction retrospectively. S6 starts with preissued permits; S8 starts with
persisted raw requests. Evidence eligibility does not certify the full predictor
input provenance. Ordinary information-matched implementations support the same
tested obligations; this is not an ECRC-record-format superiority claim.

| Question | Evidence |
|---|---|
| Ranking versus allocation | 617 development and 59 external same-task participants; frozen scores and thresholds |
| Sensitivity to participant weighting | S7: all 36 policy arms and 18 comparisons; two positive development pooled precision contrasts reverse under participant-equal averaging |
| Original semantic checks | 84 fault cases; one clean trace containing 32 permit/receipt pairs |
| S6 preissued delivery | Nine recovery scenarios × five repeats × two arms, plus separate boundary and timing studies |
| S8 issuance through recovery | Six scenarios × three repeats × two arms = 36 primary runs, 300 requests and 78 synthetic effects/receipts |
| Complete S8 reproduction | Separate retained 36-run repeat; outcomes/state summaries match, winner identities differ in 33 runs |
| S9 controlled program verification | 18 batches × two policies × two complete clients × two response conditions = 144 trajectories, 1,802 real test jobs, measured costs and live feedback; previously exposed tasks and finite-suite acceptance only |

Each S8 run set retains 36 final client/sink pairs plus 126 checkpoint backup
pairs: 90 non-final and 36 final-state backups. Each saved-state audit completed
36,210 checks. Counts of checks, snapshots and supplemental QA are not independent
experimental samples. No real intervention benefit, all-interleaving equivalence
or multi-node deployment guarantee is established.

## Download the complete artifact

Use Python 3.12. The downloader uses only the standard library, verifies the
fixed ZIP SHA-256 plus all 9,744 member paths/hashes, and requires a fresh output.
It downloads approximately 100 MB without credentials or a paid API.

```console
git clone https://github.com/ziwang11112/ecrc-ai-decision-permits.git
cd ecrc-ai-decision-permits
python scripts/download_iasc_artifact.py --output artifacts/iasc
```

Or download **AIR-014_IASC_Code_and_Reproducibility.zip** directly from the
[fixed release](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-restructured-2026-09-12); verify it against SHA256SUMS.txt there.
Read the extracted README.md and DATA_SOURCES_AND_LICENSES.md. For the original
saved models' environment use the methods provenance, not the later plotting
environment. Source-only post hoc checks do not require model refitting.

## Browse or run the current source

| Path | Purpose |
|---|---|
| [iasc/end_to_end/](iasc/end_to_end/README.md) | S8: complete 34-file frozen source/input set, raw-request issuance, cleanup and recovery |
| [iasc/runtime/](iasc/runtime/PROTOCOL.md) | S6: delivery, separate service, transport and audits |
| [iasc/statistics/](iasc/statistics/README.md) | S7: participant-equal estimates, bootstrap and input/output bundle |
| [iasc/calibration/](iasc/calibration/README.md) | Frozen calibration-grid audit and corrected pooled-total bound |
| [iasc/methods/](iasc/methods/README.md) | Features, models, selection and source-version provenance |
| [iasc/presentation_revision/](iasc/presentation_revision/GIT_README.md) | Current five figures, five tables and source indices; download full ZIP for copied inputs and all 20 exports |
| [iasc/figures/](iasc/figures/) | Retained original six figures, now supplementary; full artifact has all 24 exports |
| [iasc/revision_reviews/runtime_review/](iasc/revision_reviews/runtime_review/README_PORTABLE_WRAPPER.md) | Ten supplemental wrapper/cleanup QA cases |
| src/, icair_2026/, tests/ | Historical original simulator and its focused tests |

Fast current wrapper QA (fresh checkout; standard library only):

```console
python -B iasc/revision_reviews/runtime_review/review_atomic_wrapper_portable.py
```

It creates separate QA outputs and refuses to overwrite a previous run. These
ten exception/thread checks do not launch HTTP, kill processes or add formal
S8 repetitions. To run the complete S8 protocol, follow iasc/end_to_end/README.md
in that directory and use a new output path. Full plots and all retained database
evidence are reproduced from the downloaded artifact.

The historical core tests remain available through `pip install -e ".[test]"`
then `python -m pytest -q`; they have a separate pinned training/core dependency
set. `python scripts/verify_release.py` verifies the current Git source manifest.

## Data, licensing and scope

The public artifact contains derived participant- and decision-level outputs
from cited public IGT sources, with participant/study/trial keys and proxy labels.
It is not aggregate-only. It contains no raw EEG or new participant collection;
obtain original source datasets from their hosts. See
[data sources and licences](docs/DATA_SOURCES_AND_LICENSES.md).
Project code retains MIT terms; derived evidence/figures retain CC BY-SA 4.0,
with upstream Many Labs dataset CC BY-SA 4.0 and Mendeley v2 data CC BY 4.0
attribution preserved. See [LICENSES.md](LICENSES.md).

The historical training entrypoint run_e1.py does not match its old manifest;
seven core training modules match, but the missing entrypoint bytes have not
been recovered. This release does not claim full historical training-source
restoration. Post hoc analyses condition on frozen predictions and operating
points. The behavioural replay remains a single-task retrospective evaluation; S9 adds
a controlled program-verification workflow, and S10 adds finite specification
checks under the separately documented limits.

The initial repository release is retained in Git history; its original README
and inventories are under docs/legacy_release/. Current presentation preparation
changes figures, table layout and documentation, not experimental values. Author-side cover
letters and editorial notes are not part of the public code artifact.
