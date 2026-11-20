# ECRC: Permission and Budget Control for Language Model Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](REPRODUCIBILITY.md)
[![Release code-v1.4.0](https://img.shields.io/badge/Release-code--v1.4.0-blue.svg)](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/code-v1.4.0)

ECRC is an executable permission contract and runtime for tool-using language
model agents. It combines evidence qualification, route and claim rules, and
cumulative action budgets. An authorized operation keeps its identity and
budget unit while its result is unresolved. Recovery retrieves the original
result and records expenditure without starting a new job or refunding a unit.

This repository provides implementation code, retained numerical evidence and
reproduction tools for **Permission and Budget Control for Language Model Agents**.

**Current release:** [code-v1.4.0](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/code-v1.4.0),
including the additional 504-assignment study and local runtime measurements.
**Exact evidence snapshot cited in the manuscript:**
[`be6bb21`](https://github.com/ziwang11112/ecrc-ai-decision-permits/tree/be6bb2121cbfead548a9d54463646f9b1d6f200f).
The new release preserves that snapshot's scientific code and records and
updates project documentation, navigation and package metadata.

## Quick start: verify the published evidence

Use Python 3.12 in a virtual environment with NumPy 2.4.5. From a new checkout:

```console
git clone https://github.com/ziwang11112/ecrc-ai-decision-permits.git
cd ecrc-ai-decision-permits
git checkout code-v1.4.0
python -m pip install numpy==2.4.5
python -B scripts/verify_release.py
python -B scripts/verify_source_view.py
python -B revision_results/verify.py
python -B scripts/verify_current_results.py
```

These commands check file integrity and recompute saved results. They make no
model calls and do not execute generated programs. The revision verifier
covers all 504 additional assignments, the 576-trajectory primary reanalysis,
6,000 timing observations and 14 authorization boundary traces. The combined
result verifier covers the original online and complementary studies.

For offline actor-loop tests, plot regeneration or a new live experiment,
follow the [reproduction guide](REPRODUCIBILITY.md).

## How ECRC fits into an agent workflow

1. The agent proposes an action using the task and previous tool feedback.
2. ECRC qualifies evidence metadata, resolves the final route and claim scope,
   and checks the cumulative allowance before authorizing execution.
3. The executor preserves the operation identity. An unresolved outcome keeps
   its budget backing; recovery settles the original operation.

The online evaluation compares prompt-only control, an independently coded
conventional controller and ECRC. The two complete controllers implement the
same accounting obligations. The evidence measures budget compliance, verified
task yield, recovery and execution cost.

## Explore the code and results

| Area | Contents | Start here |
|---|---|---|
| Additional budget study | 504 assignments, paired intervals, primary reanalysis and runtime measurements | [Revision evidence](revision_results/README.md) |
| Online agent | Feedback loop, tools, candidate registration, controllers and offline tests | [Agent implementation](online_agent/README.md) |
| Primary and provider studies | 576 primary and 864 later provider trajectory records, reanalysis and plots | [Online results](online_results/README.md) |
| Core permission contract | Evidence, route, claim and capacity logic | [Governance code](src/agentic_eeg_dm/governance), [tests](tests/) |
| Durable execution | Issuance, delivery, persistent accounting and recovery | [Runtime protocol](iasc/runtime/PROTOCOL.md), [end-to-end study](iasc/end_to_end/README.md) |
| Finite lifecycle model | Model files, counterexample and saved verification evidence | [Model reproduction](iasc_model_check/PORTABLE_REPRODUCTION.md) |
| Complementary workflows | Archived-program verification, airline qualification and restart behavior | [Program verification](iasc_application/context_correction/README.md), [airline](iasc_airline/README.md), [restart](iasc_restart/README.md) |

The [results and source map](docs/RESULTS.md) connects each study to its files,
denominators and verification command. Historical directory names are retained
to preserve source and data provenance.

## Reproduction and availability

| Goal | Guide |
|---|---|
| Check saved numbers and file integrity | [Offline verification](REPRODUCIBILITY.md#quick-verification-of-this-release) |
| Rebuild numerical plots from retained records | [Figure reproduction](REPRODUCIBILITY.md#3-rebuild-the-numerical-figures) |
| Run a new online agent experiment | [Agent setup](online_agent/README.md) and [sandbox requirements](online_agent/SANDBOX.md) |
| Inspect larger historical event and database archives | [Archive index](ARTIFACTS.json) and [download instructions](REPRODUCIBILITY.md#2-current-result-checks-and-full-saved-evidence) |

Fresh online runs require a configured provider client, usage accounting and
an isolated executor. Public scalar records support numerical reanalysis;
the [availability guide](docs/ARTIFACT_COMPLETENESS.md) specifies which raw
materials remain author-held. The retained results include incomplete
trajectories and all later DeepSeek, Gemini and Claude outcomes.

Local checks on 20 November 2026 reproduced the additional study's 10,365
verified numerical values with zero difference and passed 13 offline runtime
tests. See the [release validation record](docs/RELEASE_VALIDATION_1.4.0.json).

## License, citation and contributions

Project software is distributed under the [MIT License](LICENSE).
[LICENSES.md](LICENSES.md) documents third-party data and software terms.
Use [CITATION.cff](CITATION.cff) to cite a fixed software release and record
the commit when using a different checkout.

See [CONTRIBUTING.md](CONTRIBUTING.md) for bug reports and contributions,
and [CHANGELOG.md](CHANGELOG.md) for release history. Manuscript files,
editorial correspondence, credentials and private API traffic are maintained
outside this repository's active source tree.
