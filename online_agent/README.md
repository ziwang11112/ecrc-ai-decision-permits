# Online shared-budget agent code and protocol

This source package exposes the feedback-driven agent loop, three execution
arms, immutable candidate registry, durable effect service, isolated test
runner, and offline regression checks used for the four-task shared-budget
experiment. The task data, assignment schedules, and analysis plans support the
576-trajectory primary study, the separate 576-trajectory DeepSeek/Gemini
replication, and the 288-trajectory Claude v2 replication. These studies reuse
the same 96 HumanEval tasks and 24 batches. The earlier 360 single-task
experiment is a different design and is not implemented by this package.

## Run the public offline checks

Use a fresh Python 3.12 interpreter from the repository root:

```sh
python online_agent/check.py
python -B online_agent/schedule.py --check
python -B online_agent/schedule.py --study external
```

These commands require only Python's standard library. They neither call a
model API nor execute candidate programs. The checks use inert strings and
explicitly fabricated runner results; subprocess launch and socket connection
tripwires are active while the tests run. Tests cover quota enforcement,
hidden-result recovery, persistent obligations, immutable identity, final
selection, failed-job accounting, wrong result bindings, actor feedback,
provider failure categories, provider-native history, task selection, and all
1,440 frozen assignments. Fixture outputs are temporary and are not research
observations. This directory is an independent source bundle, not an installed
module of the repository's `src` distribution.

## Source map and provenance

| File | Role |
| --- | --- |
| `runtime/trajectory.py` | Primary actor loop: one model response, validated tool dispatch, feedback, next model call, endpoint, independent acceptance |
| `runtime/trajectory_external.py` | Supplemental loop retaining `_provider_content` and `reasoning_content` for native transport round trips |
| `runtime/prompts.py` | Shared system instructions, tool schemas, task projection |
| `runtime/batch_backend.py` | Three arms, registry, cumulative quota, response visibility, explicit recovery |
| `runtime/effect_service.py` | Same-process durable job service with a separate safety cap |
| `runtime/vendor/` | Complete active ordinary/ECRC adapter dependencies, with hash checks |
| `runtime/workload/` | Candidate isolation, supervisor events, job binding and result collection |
| `runtime/acceptance.py` | Fresh post-endpoint evaluation with the same official suites |
| `runtime/data/` | 96 public tasks/tests, 115-task selection ranks, 49 exclusions, HumanEval license |
| `protocol/` | Three frozen schedule projections and analysis-plan projections |
| `SOURCE_PROVENANCE.json` | Original source digests, public digests and each transformation |

Most copied source files preserve their exact bytes. The public actor loops
replace the private accounting-module exception import with
`transport_contract.py`; the supplemental loop has its own module name. The
sandbox launcher replaces three author-local paths with mandatory environment
variables. The active vendor manifest retains dependency paths and digests but
omits local provenance and an unused legacy HTTP service. The original frozen
runner hash is recorded separately: **the public runner has a different hash**.
It must never be substituted into an existing historical job binding.

The original experiment files are unchanged. Schedule and plan JSON/CSV files
here are public projections prepared after outcomes, not new preregistrations.
The source's `registered_before_outcomes` field describes its local historical
freeze, not the timing of this public release. Analysis plans retain failure,
unknown-start, null-result and incomplete-coverage rules; report-production
instructions are omitted. Official tests are public benchmark data, even
though they are withheld from the actor during an episode. No canonical
solutions or recorded model candidate bodies are included. HumanEval material
is covered by `runtime/data/HUMANEVAL_LICENSE`; project code uses the repository
MIT license.

## Live integration boundary

There is deliberately no paid-run CLI in this package. A researcher can reuse
`run_episode(row, batch, out, client)` by adding `online_agent/runtime` to the
module search path in a fresh interpreter and supplying their own client.
Output must be a new directory inside that runtime directory, because the
original backend keeps state within its dedicated source tree. Avoid long
Windows paths. The injected interface is:

```python
client.chat(messages=messages, tools=tools, episode=episode, max_tokens=4096)
# -> (normalized_assistant_message, unique_call_id)
client.budget.summary(episode)
# -> JSON-serializable usage/accounting summary
```

Normalized messages use `role`, `content`, and `tool_calls`, with each call
containing `id`, `type: "function"`, and
`function: {"name": ..., "arguments": "<JSON object>"}`. A primary client must
supply Chat Completions-compatible messages. A supplemental client must also
preserve and translate native provider content/tool history using the metadata
retained by `trajectory_external.py`. This release does not include native
provider payload builders, response parsing, usage normalization, credential
loading, paid-budget accounting, four-worker orchestration, continuation
authorization, or raw requests/responses. Therefore it does **not** by itself
reproduce provider compatibility, billing, or a fresh full online study.

Clients raise `BudgetDenied` before dispatch if their own limit declines a
call. For a sent but unusable call, they raise `ProviderFailure` with `category`,
`stage`, and `call_id`; the loop records the attempt and stops without retry.
The original loop serializes returned messages into local run artifacts, so
caller implementations must not place credentials in messages or accounting
summaries. No account state or API keys are distributed here.

Candidate execution is a separate integration requirement. The retained runner
requires Linux (historically Ubuntu 24.04) with Python 3.12, `bash`, `prlimit`,
`timeout`, user namespaces, `libseccomp.so.2`, and the pinned bubblewrap binary.
On Windows it uses the `Ubuntu-24.04` WSL distribution. See
[SANDBOX.md](SANDBOX.md) for the exact dependency inventory and configuration.
The public release was verified only in the offline scope above; no live model
calls, sandbox launches, or generated candidate executions were made during
release preparation.
