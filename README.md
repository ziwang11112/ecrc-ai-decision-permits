# ECRC: Permission and Budget Control for Language Model Agents

ECRC constructs action permissions from evidence metadata, route and claim
rules, and cumulative budgets. Once an operation is authorized, its identity
and budget unit persist through uncertain delivery. Recovery records the unit
as spent without starting another job or refunding the allowance.

This repository contains implementation code, numerical evidence and
reproduction tools. The manuscript and Overleaf project are maintained separately.

Current software release: [code-v1.3.0](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/code-v1.3.0).
The [revision code and evidence](revision_results/README.md) are included in
this source revision and are separate from that fixed release.
Start with the [result-to-source map](docs/RESULTS.md) or
[reproduction guide](REPRODUCIBILITY.md).

## Start here

| Material | Entry point |
|---|---|
| Additional 504 assignments, primary reanalysis and local runtime checks | [revision results](revision_results/README.md) |
| Online agent loop, tools, permission controllers and tests | [online_agent](online_agent/README.md) |
| Primary 576 trajectories and all 864 later provider trajectories | [online_results](online_results/README.md) |
| Numerical reanalysis and current result plots | [online_results](online_results/README.md) |
| Core permit implementation | [governance](src/agentic_eeg_dm/governance), [tests](tests/) |
| Atomic issuance, delivery and recovery | [runtime](iasc/runtime/PROTOCOL.md), [end-to-end](iasc/end_to_end/README.md) |
| Corrected archived-program verification | [context correction](iasc_application/context_correction/README.md) |
| Finite lifecycle model | [model verification](iasc_model_check/PORTABLE_REPRODUCTION.md) |
| Airline qualification and restart witness | [airline](iasc_airline/README.md), [restart](iasc_restart/README.md) |

The primary online study uses 96 HumanEval tasks in 24 four-task batches,
two model profiles, three execution controls, two response conditions and
two repetitions. Four tasks share three new verification jobs. Prompt-only
control exceeded that quota in 75/96 GPT-4.1 mini trajectories and 16/96
GPT-6 Luna trajectories. ECRC and the complete conventional controller
recorded no excess starts. The release includes all later DeepSeek, Gemini
and Claude outcomes, including null results and incomplete trajectories.

The two complete controllers enforce the same obligations. The comparison
with prompt-only control measures runtime enforcement; it does not establish
an exclusive ECRC advantage over another complete implementation.

## Quick verification

Use Python 3.12 and NumPy for numerical reanalysis. These checks inspect saved
evidence and do not call a model or execute candidate programs:

```console
git clone https://github.com/ziwang11112/ecrc-ai-decision-permits.git
cd ecrc-ai-decision-permits
git checkout code-v1.3.0
python -m pip install numpy==2.4.5
python scripts/verify_release.py
python scripts/verify_source_view.py
python -B scripts/verify_current_results.py
```

The online packages document dependency, reanalysis and test commands.
Offline verification, injected-runner tests and a new live experiment are
separate operations. Fresh online execution requires a configured model
transport and the documented isolated execution environment.

## Historical evidence

Larger event/database archives remain pinned in [ARTIFACTS.json](ARTIFACTS.json).
For example:

```console
python scripts/download_artifact.py s9-c --output artifacts/s9-c
python scripts/download_artifact.py s11 --output artifacts/s11
python scripts/download_artifact.py s12 --output artifacts/s12
```

The downloader verifies archive size, SHA-256 and manifest members before
extraction. Current archived-program analysis retains 112 original plus
32 corrected trajectories, totaling 1,769 jobs and 188 injected response losses.
The original results remain in their fixed releases. The September plotting
sources in `plots/current/` retain their historical names and numbering;
use `online_results/` for the latest numerical figures.

See [availability](docs/ARTIFACT_COMPLETENESS.md), [licenses](LICENSES.md),
[software citation metadata](CITATION.cff) and [changes](CHANGELOG.md).
Private API traffic, credentials and author accounting ledgers are excluded.
