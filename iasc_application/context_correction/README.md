# Current S9-C results and reproducibility

The current S9 application analysis combines **112 retained original trajectories and all 32 predetermined replacement trajectories**. The replacement covers all eight conditions in each of four affected batches. Eleven of the 656 selected programs lacked public helper definitions from HumanEval/10, /32, /38 or /50. The correction adds only missing non-entry helpers and required imports from the public prompts. It preserves the remaining candidate bytes, official tests, runner, clients, budget of 16, five-second deadline, one-second recovery backoff and original factor order. It introduces no model generation or new selection rule.

This Git directory contains a selected source and numerical view of the frozen **S9-C** archive. [SOURCE_MAP.json](SOURCE_MAP.json) maps every copied file to its original path, size and SHA256 and indexes every omitted event projection. The archive SHA256 is `86556821849484ccc511586fe804c3574225afb27d064afe66148a804472018c`. [ARCHIVE_README.md](ARCHIVE_README.md) and [FROZEN_PUBLIC_MANIFEST.json](FROZEN_PUBLIC_MANIFEST.json) preserve the complete archive's original documentation and inventory; that inventory describes the full archive, not this smaller Git directory. Download links and digest checks are documented in the repository's artifact guide.

The original [S9 release](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-application-2026-09-12) remains historical and uncorrected. Its full 144-run and 1,802-job tables remain in [../analysis/](../analysis/), including all 32 superseded trajectories. The current tables live separately in [analysis/combined/](analysis/combined/). [old_new_run_differences.csv](analysis/combined/old_new_run_differences.csv) preserves all 144 comparisons and [merged_run_index.public.json](analysis/combined/merged_run_index.public.json) identifies the selected version of every run. No historical observation was silently replaced or deleted.

## Corrected descriptive results

Each cell counts timely accepted tasks out of the same 144 eligible tasks (18 batches of eight tasks). The contract-matched client retains the historical on-disk identifier `ordinary`.

| Response condition | Candidate policy | ECRC | Contract-matched |
|---|---|---:|---:|
| Normal | Depth-first | 105/144 | 107/144 |
| Normal | Round-robin | 112/144 | 112/144 |
| Post-commit response loss | Depth-first | 82/144 | 82/144 |
| Post-commit response loss | Round-robin | 98/144 | 99/144 |

The corrected aggregate has **1,769 jobs and actual starts**, 816 pass, 945 fail and eight timeout outcomes; 1,957 HTTP posts include 188 response drops and 188 cache hits. There are 797 timely accepted task observations, 808 durable passes by the deadline and 816 eventual acceptances across 1,152 repeated task-condition observations. These are 144 distinct evaluation tasks, all previously exposed. Final held units are zero, and no observed held-plus-committed budget exceeds 16. Child CPU, supervised-suite wall and launcher wall sums are 37.200464, 40.343645 and 409.567 seconds respectively; they measure different costs.

The original and replacement measurements come from different sessions. Their timing differences do not isolate the effect of restored context. Finite-suite acceptance is not general program correctness, and these observations do not establish an ECRC accuracy or production-benefit advantage. The serial recovery scheduler is shared by both clients. See [corrected_summary.json](analysis/combined/corrected_summary.json) for all descriptive totals and limitations.

## Verify the public numerical records offline

Python 3.9 or later and its standard library are sufficient. Run from the repository root, using a fresh report path outside `iasc_application/`:

```text
python -B iasc_application/context_correction/verify_current.py --out ../S9C_NUMERICAL_CHECK.json
```

The `--out` argument is optional; without it the verifier prints the JSON report without writing a file.

This checks the 77 copied archive files against their hashes; proves the complete 112+32 partition; preserves all 144 historical rows and their 1,802 jobs; derives timely, durable and eventual counts, status counts, starts, response drops and costs from the 1,769 current job rows; checks unchanged retained runs/jobs; recomputes all eight aggregate cells, all 216 paired contrasts and all 144 old/new comparisons. Workflow retry counts and budget snapshots are checked for numerical consistency in this mode; their events require the next mode. Hash references to private bytes are not treated as public raw evidence.

## Verify the complete public trajectories offline

Download and hash-check both full release ZIPs, then extract them into separate fresh directories. The original ZIP SHA256 is `b3d8d6fa8254a2a5c3de1fecae5f52c4383b5b0846640ea96de983cb19bd9f0f`; the correction ZIP SHA256 appears above. Pass the extracted bundle roots, not their enclosing directories:

```text
python -B iasc_application/context_correction/verify_current.py --original-root /data/AIR-014_IASC_S9 --correction-root /data/AIR-014_IASC_S9_Context_Correction --out /data/S9C_PUBLIC_EVENT_CHECK.json
```

This also runs the frozen public auditors over all 144 historical formal trajectories and all 32 replacement trajectories, including the superseded original evidence. It checks 112 retained public-summary hashes and binds every current job row to preserved result, commit, receipt, launcher and start records. The inherited auditors replay feedback-dependent policy choices, reconcile budget checkpoints, and verify input/permit/effect/job bindings and response/cache events. No download, model call, candidate execution or experiment occurs in either verifier mode. Do not use Python's `-O` flag for the full event audit.

Both modes were run successfully during this repository update. This is verification of existing published records, not a new execution of the experiment. The source-map file lists all 1,309 event-projection files intentionally kept in the complete S9-C release instead of Git.

## Reconstruction, execution and licensing boundaries

The reconstruction scripts and original commands in [ARCHIVE_README.md](ARCHIVE_README.md) require the **complete correction bundle**. Obtain the separately licensed candidate archive directly from the original authors using [candidate_download_recipe.json](application/workload/sources/candidate_download_recipe.json). Reconstruction verifies its exact JSON-member SHA256 and should reproduce corrected catalog SHA256 `5d223ddb9a4c1cd42bd0b22dff8f495beeb9e7aaf05466c329c5814701207cc1`; the output contains third-party candidate bodies and must remain private. The public archive and Git tree do not contain those bodies. Reconstruction reads source text without executing it.

A new experimental execution additionally requires the documented Windows/WSL, bubblewrap and Python environment, a private reconstructed catalog, the fixed protocol and fresh output directories. The author-side correction launcher and raw-analysis sources retain their original local-layout prerequisites. They are provenance and inspection sources, not claims of a standalone turnkey public rerun. No candidate reconstruction or new execution was performed for this update; matching timing on another host is not promised.

The repository's existing MIT notice applies to its software; official HumanEval data/tests retain their separate included [MIT notice](application/workload/sources/HUMANEVAL_LICENSE). No redistribution license is inferred for third-party generated candidates. Candidate bodies, arbitrary stdout/stderr, raw databases, logs and raw receipt/result strings are excluded. The projected `result_hash` identifies author-held original bytes and cannot be recomputed from a redacted projection. Complete raw-byte verification requires separately obtained private author evidence. Manuscript PDF and LaTeX files are not part of this source view.
