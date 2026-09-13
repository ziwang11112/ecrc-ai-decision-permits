# ECRC: decision permits

Reference implementations of authorization, cumulative action budgets,
durable delivery and effect-backed receipts, with experiment inputs, saved
results, tests and plotting code.

The fixed current source release is [code-v1.1.0](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/code-v1.1.0).
It contains code, selected data, plots and reproduction documentation. Cite this
version for the software; identify any separately used experiment archives with
their release tags and hashes in [ARTIFACTS.json](ARTIFACTS.json).

## Get started

Use Python 3.12. These checks require only the standard library:

```console
git clone https://github.com/ziwang11112/ecrc-ai-decision-permits.git
cd ecrc-ai-decision-permits
git checkout code-v1.1.0
python scripts/verify_release.py
python scripts/verify_source_view.py
python -B iasc_model_check/portable_reproduce.py
python -B scripts/run_wrapper_qa.py --output artifacts/wrapper-qa-1
```

The wrapper command runs ten supplemental checks in a fresh output directory.
Use a new destination for each run. The S10 default verifies saved evidence
without Java or state-space enumeration.

## Code and data

| Component | Location |
|---|---|
| Core implementation and tests | [src/](src/), [tests/](tests/), [historical experiments](icair_2026/) |
| Separate-service delivery and recovery | [iasc/runtime/](iasc/runtime/PROTOCOL.md) |
| Atomic issuance and recovery | [iasc/end_to_end/](iasc/end_to_end/README.md) |
| Participant-level analysis | [iasc/statistics/](iasc/statistics/README.md) |
| Calibration and source provenance | [calibration](iasc/calibration/README.md), [methods](iasc/methods/README.md) |
| Controlled program verification | [iasc_application/](iasc_application/SOURCE_VIEW.md) |
| Finite lifecycle model | [iasc_model_check/](iasc_model_check/PORTABLE_REPRODUCTION.md) |
| Plotting and numerical summaries | [plots/current/](plots/current/README.md) |

The [reproducibility guide](REPRODUCIBILITY.md) separates saved-result checks
from new experiment execution and lists the required environments.

## Download archived experiment evidence

The Git source view contains selected evidence. Large saved-run records are
provided as pinned archives:

```console
python scripts/download_artifact.py s1-s8 --output artifacts/s1-s8
python scripts/download_artifact.py s9 --output artifacts/s9
python scripts/download_artifact.py s10 --output artifacts/s10
```

[ARTIFACTS.json](ARTIFACTS.json) records archive URLs, sizes and SHA-256 values.
The downloader verifies every member before extraction and refuses existing
destinations. `--archive PATH_TO_ZIP` verifies an existing download offline.

## Scope and licenses

The current source view omits standalone manuscript text, LaTeX tables,
bibliography files, editorial documents and obsolete manuscript-layout outputs.
It retains experiment code, numerical evidence, technical protocols and plots.
Frozen protocols retain their original wording, including historical
publication-planning context. [SOURCE_VIEW.json](SOURCE_VIEW.json)
records intentional omissions from historical inventories. Old commits and
fixed release archives retain their originally published contents.

Some historical training source bytes and inner calibration grids remain
unavailable. S9 public results can be recalculated from projections; full
candidate execution requires separately obtained upstream programs and the
documented sandbox environment. See [availability and validation](docs/ARTIFACT_COMPLETENESS.md).

See [LICENSES.md](LICENSES.md) and [dataset attribution](docs/DATA_SOURCES_AND_LICENSES.md)
for code, derived-data and upstream terms. Citation metadata is in
[CITATION.cff](CITATION.cff).
