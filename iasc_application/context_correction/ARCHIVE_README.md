# S9-C: public-helper context correction

This local supplement replaces all eight cells of four S9 batches (32 trajectories) and retains the other 112 original trajectories. It does not replace or silently modify the historical [original S9 release](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-application-2026-09-12). That release contains the **original uncorrected** study. Its fixed asset URL and SHA-256, and the 112 retained run identities and public-summary hashes, are in `metadata/RETAINED_ORIGINAL_RUNS.json`.

Exactly eleven selected programs lacked public, non-entry helper definitions from HumanEval/10, /32, /38 or /50. The corrected input prefixes only those missing public helpers and necessary public imports. It never imports a reference solution or derives context from tests. Existing candidate bindings and all other candidate bytes remain unchanged; empty programs do not acquire a prompt entry stub. Each original candidate, public prompt and added context has a separate hash, while the job binding identifies the assembled executable source. `correction/ASSEMBLY_AUDIT.json` contains the source-free map for all 656 selections.

The original runner, service and two complete clients are unchanged and included under `application/`. Budget16, deadline5 seconds, recovery backoff1 second, candidate order, fault rule and serial recovery remain fixed. `correction/GRID_PLAN.json` preserves the original run indices and order. There was no recalibration or automatic rerun. All 32 replacement runs are included through the original closed typed projection; `analysis/combined/` contains the descriptive 112+32 analysis. Different measurement sessions prevent attributing every timing difference solely to restored context.

## Public verification without candidate programs

Use a fresh report path outside the extracted bundle:

```
python -B verify_public_context.py --bundle . --out ../S9C_PUBLIC_CHECK.json
```

The verifier checks every public file/hash, exact inventory coverage, absence of source/output body fields, all32 replacement identities, and112 retained references. The inherited public trajectory auditor independently reconstructs retained-field policy choices, timely/eventual outcomes, actual child starts, budgets, effect/receipt/job bindings and response/cache events. Its only adaptation is using the original run ID from the grid instead of renumbering the 32 cells. The original auditor and adaptation note are retained in `vendor/` and `metadata/`.

## Rebuild the exact private corrected catalog

Obtain the original authors' program archive separately using `application/workload/sources/candidate_download_recipe.json`. The exact JSON member SHA is `4ef4b6b65e77ba2b1f44b6f890ac5d1f7e82b817bbdb7492b71fa1f825ef3522`. No selected candidate bodies are redistributed here. Run:

```
python -B rebuild_public_catalog.py --bundle . --source /private/author_archive.zip --verify-only
python -B rebuild_public_catalog.py --bundle . --source /private/author_archive.zip --out /private/corrected_catalog.json
```

The second destination must be fresh and outside this public bundle. Reconstruction executes no candidate, checks the original source/runner/catalog hashes, reproduces the missing-helper selection using only public prompts, and verifies the complete corrected catalog SHA `5d223ddb9a4c1cd42bd0b22dff8f495beeb9e7aaf05466c329c5814701207cc1`. Its candidate text remains private.

For new execution, copy `application/` to a private work directory, reproduce the documented Windows/WSL sandbox environment, and use its original `run_workflow.py` with the private corrected catalog and `correction/FINAL_PROTOCOL.json`. For example, from the copied application directory:

```
python -B run_workflow.py --catalog /private/corrected_catalog.json --batch evaluation_01 --arm ecrc --policy depth_first --condition normal --budget 16 --deadline 5 --backoff 1 --out /private/fresh_run --formal-protocol /path/to/S9C/correction/FINAL_PROTOCOL.json
```

This command executes untrusted candidate programs in the isolated runner; it is separate from reconstruction and public verification. Follow all32 cells and their recorded factor order for a complete new correction-grid reproduction. Keep all outputs fresh and outside public archives. The author-side `correction/run_correction.py` additionally binds the original local evidence tree and is retained as provenance, not advertised as a standalone public-layout launcher. No CPU or wall-time equality across hosts is promised.

## Contents and limits

`PUBLIC_MANIFEST.json` inventories exactly the public files. Protocol hashes can refer to excluded private inputs; such references are not claims that those bytes are inside this ZIP. Candidate bodies, raw databases, arbitrary stdout/stderr, logs, full raw receipt/result strings and manuscript files are excluded. Official HumanEval material is distributed under its included MIT license; no redistribution license is inferred for third-party candidate programs.

Projection manifests retain both original-file and public-file hashes. `result_hash` remains a reference to private original bytes and cannot be recomputed from a redacted result. Counts and preserved fields can be checked publicly; complete raw-result verification requires the retained private evidence. The analysis sources are included for inspection; their full raw SQLite analysis also requires that private layout. Finite-suite pass is not general correctness, and neither equal client results nor this context correction establishes ECRC-exclusive utility. No model generation, new API spending, journal validation by a publisher, or new theory proof is claimed by this package.
