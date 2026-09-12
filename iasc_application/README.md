# Public S9 add-on preparation

This is a local, reviewable packaging recipe. Nothing is uploaded or published by these scripts, and no candidate executes during packaging or reconstruction. The frozen application sources remain unchanged. All HumanEval tasks were previously exposed; the application remains exploratory.

The completed bundle's [FINAL_RESULTS.md](FINAL_RESULTS.md) is a self-contained account of the observed outcomes, costs and interpretation limits, including the shared serial recovery scheduler. Selected independent audit summaries are in [audits/INDEPENDENT_AUDITS.json](audits/INDEPENDENT_AUDITS.json); the PDF/PNG result figures are in [analysis/figures/](analysis/figures/).

## What the public bundle contains

`build_public.py` uses an explicit source-file list and a closed, typed projection of completed run records. It does not recursively copy a run folder. Each generated bundle contains:

- Our application, service, isolated runner and inherited client source files, with a source SHA256 manifest. Their bytes match the local sources at packaging time.
- The pinned official `HumanEval.jsonl.gz` and MIT license. Their expected SHA256 values are `b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef` and `bcba3de214851cce46ed5af42d6698044616eeace887c3231bc7a20474ab639e`.
- A catalog template containing every field except the `solution` and `test` strings. Task order, source array indices, candidate order, duplicate/empty-record identity, hashes, batches and partitions are retained. Official tests are reconstructed from the MIT dataset.
- Projected run summaries, client/service events, result numbers/statuses, child/host start records and client checkpoint states. Operation, permit, effect, task and candidate identifiers and hashes are retained when present; nested receipt JSON is decoded and projected through the same field rules. Free-form messages, paths, logs and output text are omitted.
- For every completed grid, an original-file SHA256 inventory covering all local grid artifacts, plus an explicit original-to-public projection manifest. These hashes support comparison with a separately obtained local author archive.
- A public file inventory, a path audit identifying excluded source-bearing locations, and the exact original-author download recipe.

The actual safe-inclusion list is generated in `PUBLIC_INVENTORY.json`, with one path, byte length and SHA256 per included file. `metadata/TRUSTED_SOURCE_FILES.json` lists copied source files. The path audit is an exclusion record; the listed local paths are not automatically included.

## What is excluded

There is no established redistribution license for the published candidate programs. The public bundle excludes the original candidate ZIP/JSON member, the complete `catalog.json` and `bound_catalog.json`, every `bound_job.json`, candidate `work/input/payload.json`, selected candidate text, raw databases, raw client/sink snapshots, console/exception logs and candidate stdout/stderr. It also excludes `sandbox_output/stdout.log`: that trusted supervisor stream can contain candidate stdout/stderr encoded as Base64. Nested `ack_json`, `result_json` or similar serialized strings are never copied verbatim. Our code and official MIT task materials are distinct from third-party candidate-program contents.

The source audit confirms `solution` fields in catalog, bound-job and input files. Output logs are excluded regardless of whether a particular observed file currently looks harmless. The publisher should distribute only the generated bundle directory, not this entire working `public/` directory or the local author archive.

## Audit boundary

The public projections preserve counts, event clocks, bindings, finite-suite outcomes and resource observations for independent descriptive and causal-path checks. They are derived records, not a byte-complete public release of the original raw evidence. After removing content and local raw paths, a public projection cannot reproduce the complete original `result_hash`. The stored original hash remains a reference to author-held bytes, not a hash of the projection. The projection has its own SHA256. Public reviewers can check preserved fields and trajectories, reconstruct inputs separately, and request the local author evidence for a complete original-byte audit where appropriate.

`check_public.py --public-only` performs that public-data check without the candidate archive, private SQLite databases or original local run files. It independently derives each trajectory's timely accepted-task count, actual starts from child-start records, response drops/cache hits, and held/committed state after every client event. It cross-checks the observed stop/final snapshots, checks operation/permit/effect/job bindings, and replays depth-first/round-robin choices against the trajectory's own reconciled feedback. It validates each batch's eight tasks and all 32 candidate opportunities, recomputes hash-ranked source indices using published record counts, checks official suite/job bindings, and checks input matching across the eight conditions on that batch. Source-record counts themselves remain metadata until the separately downloaded archive is verified.

The closed input projection retains all fields of this workflow's code-free `input_batch.json`, including declared policy/proposal/evidence records. The public checker therefore also recomputes `inputs_hash` and the raw-request hash carried by each issued event. It derives counts before comparing them with `run_summary` or the supplied S9 CSV. Preserved elapsed observations define the declared five-second timely-feedback boundary; no Linux clock is compared to the Windows clock.

From inside the generated bundle, write the QA report outside it so its original inventory stays immutable:

```text
python check_public.py --bundle . --public-only --out ../S9_PUBLIC_CHECK.json
```

All listed sources and frozen runner hashes remain available for inspection. Running the workflow elsewhere requires reproducing the documented WSL/bubblewrap/dependency environment. The five-file runner hash does not pin the entire installed runtime, and observed wall times are not promised to reproduce exactly on another host.

## Original candidate provenance and download

Benedikt Stroebl, Sayash Kapoor and Arvind Narayanan, *The Limits of Inference Scaling Through Resampling*, arXiv:2411.17501v3, 26 March 2026; DOI `10.48550/arXiv.2411.17501`. The [primary paper record](https://arxiv.org/abs/2411.17501v3) and [pinned author README](https://raw.githubusercontent.com/benediktstroebl/inference-scaling-limits/11a8f6ed1aee5b996f659c3fedb549c07aeb34ad/README.md) were verified on 12 September 2026. The README supplies the sanitized HumanEval archive link and identifies the collection implementation; it does not establish the bytes of unavailable model weights.

Exact public download URL:

```text
https://www.dropbox.com/scl/fi/je3d9lrmu36g5x3alugsa/humaneval_evalplus.zip?rlkey=del4cd36kfyyseaw7r9zs8gn0&dl=1
```

Exact ZIP member:

```text
humaneval/meta-llama--Meta-Llama-3.1-8B-Instruct_openai_temp_0.8-sanitized/eval_results.json
```

The uncompressed member must be 73,874,142 bytes with SHA256 `4ef4b6b65e77ba2b1f44b6f890ac5d1f7e82b817bbdb7492b71fa1f825ef3522`. This is the JSON-member hash, not the whole ZIP hash. The locally recorded enclosing ZIP size is 928,278,140 bytes. Obtain it directly from the authors; no archive content is executed. The reconstruction script reads only the named member and never extracts arbitrary ZIP paths. A previously verified uncompressed member is also accepted.

## Reconstruct the full private catalog

From a generated public bundle:

```text
python reconstruct_catalog.py --bundle . --source /private/downloads/humaneval_evalplus.zip --verify-only
python reconstruct_catalog.py --bundle . --source /private/downloads/humaneval_evalplus.zip --out /private/reproduction/workload/catalog.json
```

The destination must be fresh and outside the public bundle. The resulting catalog contains third-party candidate text and must remain private. The script rechecks hash-based task/candidate selection, exact selected program hashes, unchanged official test hashes and runner-file hashes. Empty and duplicate selections are retained. It never accesses archived outcome labels or executes candidate code.

Expected reconstruction identities:

```text
runner bundle: e05cebc18c2dab444215fb826377edb0480db72e2bf33ed776afbbc2a1d7f150
full catalog:  bbd28484d9f10143b1d5db9d80740996b49a43987e5f737ce659114a3b87a9c8
```

The catalog byte hash uses UTF-8, sorted keys, two-space indentation and one final LF. Runner identity hashes compact sorted UTF-8 JSON of the five-file manifest. To construct the service's bound catalog, place the reconstructed catalog into a private copy of `application/workload/`, then run `application_common.py` in that private application tree. It adds deterministic job bindings without executing candidates; check the resulting bound-catalog hash against the separately supplied final protocol.

## Build a review bundle locally

In the author's `A/public/` directory:

```text
python build_public.py --app-root .. --out bundle_development_v1 --run-root development/integration_v2
```

`--run-root` may be repeated for completed grids. A fresh destination under the working `public/` directory is required, and each grid must contain matching planned/observed counts in its final `SUMMARY.json`. This completion check occurs before source auditing or output generation. The packager checks the frozen runner/catalog hashes before copying. It does not modify source files, databases, protocols or run evidence. Source auditing is restricted to workload/service/development and explicitly selected completed grids; it does not scan other active evaluation folders.

## Formal protocol and analysis support

The protocol has been reviewed read-only and is pinned to SHA256 `ab396792ad4058ad0418ccbabdf0f963723d77ddf0b8c75c613e4e757b5bdc9d`; the freeze manifest is `86e08243253d4bf19b530112462fe3195dce620a385d57237ebf8253db277df4`. `review_frozen.py` checks all 30 source files against both their current and frozen copies, all five frozen input hashes, and the declared 144 cells with K=16, D=5 seconds and a one-second recovery delay. It does not read evaluation trajectories.

After all 144 formal cells and the separate analysis finish, build a new bundle, for example:

```text
python build_public.py --app-root .. --out bundle_formal_v1 --formal --run-root development/integration_v2 --run-root evaluation_v1 --analysis-script ../../../qa/iasc_application_pilot_2026-09-12/analyze_application.py --analysis-output /absolute/path/to/completed_analysis
```

The `--analysis-script` path should be supplied as an absolute path if the example's relative layout does not match the author's checkout. `--formal` requires exactly one completed 144-cell evaluation grid bound to the pinned protocol. The source whitelist must include every frozen source file; it also includes `FINAL_PROTOCOL.json`, `FREEZE_MANIFEST.json`, `DEVELOPMENT_HISTORY.md`, the preserved runner/service revision code, and named development/reference QA summaries. It excludes old catalogs and raw old candidate records. The exported application source is sufficient to compare every frozen source hash; a duplicate copy of the entire `frozen_source/` tree is unnecessary.

Analysis inclusion is explicit: the reviewed `analyze_application.py`, optional `--plot-script /absolute/path/plot_application.py`, `S9_runs.csv`, `S9_jobs.csv`, `S9_cells.csv`, `S9_paired_batches.csv`, and the analysis `SOURCE_MANIFEST.json`. CSV cells must consist of neutral identifiers, booleans, task-ID lists or numeric values, and the formal runs table must have 144 rows. No arbitrary file in the analysis directory is copied. `S9_SUMMARY.json` and later independent audit outputs require a separate explicit review before inclusion; they are not automatically copied.

The original analysis script uses private SQLite/raw records, so byte-complete rerunning of that analysis requires the local author archive. Public CSVs, typed events/results and their manifests preserve the exported fields for independent recalculation and cross-checks. The public package does not claim it can reconstruct the original `result_hash` from a redacted record.

Before publication, regenerate a fresh bundle from all completed evaluation records and review its exact inventory. No incomplete or technically failed planned arm should disappear from the export: failures retain their occurrence and neutral fields, while arbitrary exception text stays private. A publication-ready package is not asserted merely because the development preview builds.
