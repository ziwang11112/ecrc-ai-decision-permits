# ECRC: Decision Permits for Budgeted Workflows

Code, saved results and reproduction tools for ECRC. The reference implementation
constructs action permissions from evidence metadata, route and claim rules, and
cumulative budgets. Its lifecycle retains an armed operation's unit through
uncertain delivery and records committed expenditure on recovery.

Current software release: [code-v1.2.0](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/code-v1.2.0).
Start with the [result-to-source map](docs/RESULTS.md) and [reproduction guide](REPRODUCIBILITY.md).

## Quick verification

Use Python 3.12. These standard-library checks read saved records; they do not
call a model/API or execute candidate programs.

```console
git clone https://github.com/ziwang11112/ecrc-ai-decision-permits.git
cd ecrc-ai-decision-permits
git checkout code-v1.2.0
python scripts/verify_release.py
python scripts/verify_source_view.py
python -B scripts/verify_current_results.py
```

## Code and evidence

| Component | Entry point |
|---|---|
| Core permit implementation | [governance](src/agentic_eeg_dm/governance), [tests](tests/) |
| S6/S8 delivery, atomic issuance and recovery | [runtime](iasc/runtime/PROTOCOL.md), [end-to-end](iasc/end_to_end/README.md) |
| S9-C corrected program verification | [context correction](iasc_application/context_correction/README.md) |
| S10 finite lifecycle model | [model and retained verification](iasc_model_check/PORTABLE_REPRODUCTION.md) |
| S11 airline action qualification | [iasc_airline](iasc_airline/README.md) |
| S12 restart/count witness | [iasc_restart](iasc_restart/README.md) |
| Current three technical figures and S6/S8 observations | [plots/current](plots/current/README.md) |
| Historical behavioural replay and calibration | [icair_2026](icair_2026/), [statistics](iasc/statistics/README.md), [calibration](iasc/calibration/README.md) |

S9-C uses **112 original + 32 replacement trajectories = 144**, with **1,769
jobs / 188 injected response losses** across both clients. Original S9's
1,802/194 totals remain historical. S11 covers **600 request contexts on 200
reservations**, plus a separate 16-case constructed boundary set. S12 is an
**eight-cell development witness**, with its prior batch retained for provenance.

## Saved-record archives

Code and compact evidence are in Git. Larger event/database archives are pinned
in [ARTIFACTS.json](ARTIFACTS.json):

```console
python scripts/download_artifact.py s9-c --output artifacts/s9-c
python scripts/download_artifact.py s11 --output artifacts/s11
python scripts/download_artifact.py s12 --output artifacts/s12
```

The downloader also retains `s1-s8`, `s9` (original) and `s10`. It validates size,
SHA-256 and manifest members before extraction. Use fresh destinations; follow
each study README for full-event/database audits and fresh execution.
The S11 asset preserves per-cell records and reconstructable canonical database
states; it is a documented projection, not a byte-identical raw snapshot archive.

## Scope and history

Manuscript prose, paper PDFs, LaTeX, bibliography and editorial reviews are
maintained separately. Previous commits and fixed releases retain original
evidence and old plotting layouts. [CHANGELOG.md](CHANGELOG.md) records changes.
S9 candidates require separate upstream acquisition; S11 uses a pinned synthetic
benchmark, not live bookings. See [availability](docs/ARTIFACT_COMPLETENESS.md),
[licenses](LICENSES.md) and [citation metadata](CITATION.cff).
