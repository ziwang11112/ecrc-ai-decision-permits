# S11: airline cancellation permission study

This package contains runnable, model-free airline code and saved results from
two fixed cohorts: 200 distinct synthetic bookings, three scripted reasons per
booking, and four implementations (600 contexts; 2,400 primary execution cells).
A separate constructed boundary grid has 16 fixtures and 64 cells. The boundary
fixtures and earlier pilots are not part of the primary denominator.

| Primary outcome | Direct dispatch | ECRC | Rule-gated dispatch | Claim ablation |
| --- | ---: | ---: | ---: | ---: |
| Eligible completed / 129 | 129 | 129 | 129 | 129 |
| Ineligible executed / 117 | 117 | 0 | 0 | 117 |
| Unresolved executed / 354 | 354 | 0 | 0 | 354 |

The unresolved category comprises 200 missing-information and 154
transfer-required contexts. Both ECRC and rule-gated dispatch use the same
production `cancel_basis` checker. These results preserve their equivalence;
they do not show better policy decisions than a correctly rule-gated workflow.
Withheld unresolved actions are unfinished tasks. There is no official dialogue
benchmark score, live refund, model call, or atomic native completion receipt.

## Verify saved evidence offline

Run from the repository root with Python 3.12 (standard library only):

```sh
python -B iasc_airline/verify_results.py --out /path/to/verification.json
```

The output directory is optional. The verifier checks copied-file hashes and
their applicable original pre-run freezes, independently recomputes policy
categories from the frozen synthetic database and original requests, checks the
complete context/arm grid, recounts execution evidence, and compares the pooled
published CSV. It uses the frozen independent audit predicate, not the shared
production checker. It also retains the boundary distinction between 16 direct
writes and 15 new cancelled-status transitions (one repeated write). This does
not rerun the native executor; the full saved per-cell archive supports that
deeper inspection.

## Native rerun

The frozen actor, qualification, permission-core, selector, audit and per-cell
runner Python sources are in `frozen/`. They retain their original bytes and
relative hierarchy. `run_native.py` is a new portable entry point: it loads the
unchanged per-cell runners and replaces only packaging paths and batch setup.
Use it instead of invoking archival preparation/audit scripts directly, which
retain historical absolute archive references. This wrapper takes the saved
cohort requests; it does not resample or claim a new holdout.

Use an isolated Python 3.12 environment, then install the recorded dependencies:

```sh
python -m venv .venv-airline
# Activate this environment using the command appropriate for your shell.
python -m pip install -r iasc_airline/requirements-native.txt
```

The requirements record exact versions from the original no-model environment.
They do not install provider SDKs. Obtain the upstream source with Git and verify
the fixed revision:

```sh
git clone --filter=blob:none --sparse https://github.com/sierra-research/tau2-bench.git /path/to/tau2-bench
git -C /path/to/tau2-bench sparse-checkout set src data/tau2/domains/airline
git -C /path/to/tau2-bench checkout 2174a603f6d014ef94473ffa95957f6ce27100db
git -C /path/to/tau2-bench rev-parse HEAD
```

`TAU2_REQUIRED_SHA256.json` binds all required upstream `src/` files, airline
data, license and project metadata to the retained snapshot. The runner verifies
these hashes before loading native code. Do not install the upstream package:
the original bootstrap loads native modules directly, skips eager model-runner
initialization, rejects provider imports, denies network activity, disables
dotenv and blocks `.env` reads.

Start with one saved context and all four arms:

```sh
python -B iasc_airline/run_native.py --phase original_first100 --tau2 /path/to/tau2-bench --limit 1 --out /path/to/new-smoke
```

For the full original phase, omit `--limit`. Repeat with
`--phase fixed_next100` and `--phase constructed_boundaries`, each using a new
output directory. The boundary runner rebuilds each exact frozen fixture from
the original typed database and an explicit before-bound replacement patch;
both compressed-file and canonical-state hashes must match. A fresh native
database and permission database are used for every cell. Arm order rotates,
the technical call cap is 128, and capacity K=100 is nonbinding. Native responses
and final state are replay-checked for every completed cell.

Full reruns are resource-intensive and were not repeated during publication.
Publication validation ran one original-cohort context and one constructed
boundary context across all four arms in the already available environment:
eight smoke cells, with replay and paired equality checks passing. These smoke
cells are QA and are not added to reported sample sizes. Dependency installation
and a new upstream download were not exercised during this validation.

## Files and provenance

- `inputs/`: fixed requests, cohort selection records, protocols, synthetic base
  database and 16 explicit fixture patches.
- `results/*/SUMMARY.json.gz`: every saved per-cell result and paired comparison
  from each primary/boundary batch, losslessly compressed from the original.
- `results/supplement/`: saved CSVs, including combined counts, strata, positive
  bases, raw native effects and historical exposed-official results.
- `provenance/`: original freeze timestamps, dependency versions, source hashes,
  complete compressed independent reviews and original evidence inventories.
- `SOURCE_PROVENANCE.json`: file-by-file source mapping and byte hashes.
- `historical/`: the earlier two exposed development episodes and six-request,
  five-arm exposed official-task extension. These are distinct scopes, not
  additions to the 2,400-cell denominator or unseen validation.

The first cohort was fixed before its own comparison. The next 100 and the
constructed boundaries were fixed after first-cohort findings were known but
before their own comparisons. Post-run audits/figures are not retrospective
preregistration. Repeated synthetic contexts are correlated; the 600 contexts
are not independent participants. The primary cohorts have respectively
59 and 70 eligible contexts, on 40 and 46 distinct bookings.

The release asset `S11_airline_native_evidence_projection.zip` contains every
primary and boundary cell's native calls/responses, scripted messages,
confirmations, results, permission ledgers and replay records. To avoid thousands
of repeated whole-database snapshots, after states are represented by explicit
whole-record replacements against their original before states. The exporter
checked exact state equality for every reconstruction. Original nonprojected
files retain their bytes; reconstructed after-state JSON has the exact canonical
hash, while its gzip container bytes can differ from the archived original.
The original gzip hashes remain in `ORIGINAL_SOURCE_MANIFEST.json`.

Verify the ZIP's complete file manifest, then optionally verify every semantic
state or materialize it into a new directory (the last two operations take longer):

```sh
python -B iasc_airline/materialize_archive.py /path/to/S11_airline_native_evidence_projection.zip
python -B iasc_airline/materialize_archive.py /path/to/S11_airline_native_evidence_projection.zip --verify-states
python -B iasc_airline/materialize_archive.py /path/to/S11_airline_native_evidence_projection.zip --out /path/to/new-native-evidence
```

This public archive is a semantic-state projection, not a byte-identical raw
archive. Do not use the historical compressed-file inventory to assert that
regenerated gzip bytes are original. Full raw-byte archives remain retained
locally. Original
absolute paths embedded in historical evidence are provenance, not runtime
requirements or public download URLs. No manuscript PDF, LaTeX source,
credential file, provider transcript, virtual environment or large upstream
vendor tree is included in this directory.

## Upstream attribution

Synthetic airline data and native tools are from Sierra Research's
[tau2-bench pinned revision](https://github.com/sierra-research/tau2-bench/tree/2174a603f6d014ef94473ffa95957f6ce27100db),
with data originating in tau-bench. They are distributed under the upstream MIT
license retained in `UPSTREAM_LICENSE.txt`. This license and attribution also
apply to copied synthetic records, constructed derivatives, and saved native
tool outputs. Detailed pinned source links are in `SOURCE_ATTRIBUTION.json`.
The surrounding ECRC code follows the repository license.
