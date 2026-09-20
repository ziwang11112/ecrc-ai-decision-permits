# S12: cumulative responsibility under restart

S12 is an eight-cell controlled development witness with synthetic database
effects, one normal and one mixed run per client. It is the evidence for current
Supplementary Table S2. `runs/batch_02` is the verified historical comparison;
`runs/batch_01` retains the preceding complete grid and its four failed mixed-cell
process-identity audits. The two batches are not independent replications.

All four inputs A/B/C/D and all outcomes are included. Each cell has the same
external K=2 target. All clients share stable request identities, an upstream
queue and a service with durable deduplication. `raw` uses the original direct
client without a count limit; `volatile_count` uses its original in-memory limit.
`durable_count` is a conventional SQLite request-log/count remedy without ECRC
permits. ECRC uses the unchanged S8 implementation.

| Condition | Client | Distinct effects | Over K=2 | Effects A/B/C/D | Eligible but uncompleted |
|---|---|---:|---:|---|---|
| normal | raw | 4 | 2 | 1/1/1/1 | none |
| normal | volatile_count | 2 | 0 | 1/1/0/0 | C, D |
| normal | durable_count | 2 | 0 | 1/1/0/0 | C, D |
| normal | ECRC | 2 | 0 | 1/1/0/0 | C, D |
| mixed | raw | 3 | 1 | 0/1/1/1 | none |
| mixed | volatile_count | 3 | 1 | 0/1/1/1 | none |
| mixed | durable_count | 2 | 0 | 0/1/1/0 | D |
| mixed | ECRC | 2 | 0 | 0/1/1/0 | D |

In mixed cells A misses the shared queue deadline in every arm. B commits but
its response is withheld; the real worker process is killed and restarted.
C/D are attempted before the original B descriptor is redelivered. The volatile
count goes from 1 before restart to 0 after restart, then admits C and D.
Durable counting and ECRC both preserve B's unit and leave D uncompleted.
All arms have zero duplicate effects because of the shared service cache.
The eight current cells contain 20 effects, 24 successful service POSTs, four
withheld responses and four cached same-key returns.

ECRC's held/committed/receipt sequence is 1/0/0, 2/0/0, restart 2/0/0,
A cleanup 1/0/0, C completion 1/1/1, B reconciliation 0/2/2. This extra interface
does not establish better business utility than durable counting. The clocks
are scripted logical times; there is no observed hour-long delay, latency
advantage, statistical interval, clinical outcome or real-money effect.

## Verify saved evidence without network access

Python 3.12 and its standard library are sufficient. No package install, model,
API key or model/API call is needed. From the repository root:

```sh
python -B iasc_restart/verify.py
python -B iasc_restart/verify.py --json /path/to/qa/S12_VERIFY.json --csv /path/to/qa/ALL_CELLS.csv
```

The default verifier reconstructs every current CSV row from the retained
`PROXY.jsonl` service responses, checks request/response identities and process
traces, compares saved audits, preserves the prior batch's failed audits, and
checks all six ECRC observations and the volatile restart counter. It checks
published-file hashes. Transport reconstruction alone cannot establish that no
additional database effects exist; the full SQL check below addresses this.

The separate release asset `iasc_s12_restart_witness_2026-09-20.zip` includes both
complete `runs/batch_01` and `runs/batch_02` grids with all 108 original SQLite
databases and all 36 accompanying WAL files. It contains no manuscript files.
Its root `MANIFEST.json` hashes all 349 other members. After downloading and
extracting it through the repository artifact instructions, run:

```sh
python -B iasc_restart/verify.py --raw-root /path/to/extracted/archive --json /path/to/qa/S12_SQL_VERIFY.json
```

This runs the unchanged independent SQL/transport/process auditor on temporary
copies of all 16 cells, checks all 84 checkpoint databases, and verifies the
current ECRC sequence directly from SQL. It checks archive-member hashes before
and after reading. SQLite may create empty journals/reader indexes on the
temporary copies; originals remain untouched. Regenerable SHM files are omitted
from the release, while every main DB and WAL byte is retained.

## Run a new bounded portability check

```sh
python -B iasc_restart/run_portable.py --out /path/to/new/s12_qa
```

The output directory must be new and outside this package. The wrapper stages
the original source layout, runs the original 13 tests, freezes the staged
runtime, and calls the original `run_cell` for the same complete eight-cell
schedule. All HTTP traffic is between local loopback processes. Windows Python
3.12 replay is validated; the inherited POSIX process branch has not been
validated for this public packaging update.

This command creates **new QA**, not new paper evidence. It does not replace or
append to either historical batch. The portable wrapper bypasses the original
`manifest()` guard that required local manuscript files and substitutes a
runtime-only source manifest. Client, counter, service, input, process control,
`run_cell`, tests and auditor code are unchanged. Code needed for verification
and replay is included here; there are no sibling-workspace dependencies.

## Files and provenance

- `PROTOCOL.md` and `DEVELOPMENT_LOG.md`: byte-identical plan and repair history.
- `ALL_CELLS.csv`: byte-identical eight-row current result table, including over-limit and uncompleted outcomes.
- `frozen/source/`: byte-identical final development code.
- `frozen/review/`: both historical code freezes, QA logs, source hashes and final status.
- `vendor/`: byte-identical original DirectClient, S8 core/service and their complete Python dependency snapshot.
- `runs/`: complete historical JSON/JSONL/log records and checkpoint observations for both grids. Native DB/WAL records are in the release asset.
- `PROVENANCE.json`: source-relative paths, original hashes, exported hashes and each path-only transformation.
- `verify.py`, `run_portable.py`, `PUBLICATION_QA.json`: explicitly new publication/portability helpers and QA summary.

The authoritative source is
`research_pilots/ecrc_mixed_workflow_dev_2026-09-15`, linked by the reviewed
2026-09-19 result index and focus-revision S12 source index. Historical metadata
replaces the author's absolute local root with `SOURCE_WORKSPACE`. Original
source hashes remain recorded separately from exported hashes; redacted JSON
is not described as byte-identical. Frozen implementation, database, WAL,
protocol and CSV bytes are unchanged. Some original freeze metadata names
protected manuscript paths/hashes; manuscript contents are intentionally absent
and are unnecessary for the portable commands above.

The first batch remains failed for proof of actual Windows worker termination.
The launcher PID had been recorded instead of the actual child PID. The next
freeze changed only the runner to acquire and terminate the real worker handle,
then reran the whole grid without weakening the independent audit. See
`DEVELOPMENT_LOG.md`; no unfavorable cell or failed audit was discarded.
