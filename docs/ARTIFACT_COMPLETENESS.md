# Artifact completeness and scope

Audit date: 2026-09-12 (local project date). The audit started from Git commit
`fa235c0ecb61c286f1c3a29d9c4bf66ad7c6c027`. This revision adds navigation,
checked execution entry points and the current paper exhibits. It preserves
the study sources, recorded results and existing fixed releases.

**The public saved-evidence package is complete within its declared scope.
It is not a complete restoration of every historical training input or a
turnkey execution environment for every study.**

## Availability matrix

| Component | Included and checked | Location / remaining boundary |
|---|---|---|
| Original core | Eight governance modules and focused tests; core modules match the S6 snapshot | `src/`, `tests/`, historical `icair_2026/` |
| S1–S8 browsable mirror | All 255 declared mirror entries, including 35 S6 runtime files and all 34 S8 frozen source/input files | `iasc/SOURCE_MIRROR_MANIFEST.json`; full saved database evidence is in the release ZIP |
| S1–S8 complete archive | 9,744 files, exact archive and member hashes | `s1-s8` in `ARTIFACTS.json`; both original and repeated S8 run sets included |
| S8 independent saved-state checks | Two sets of 36 cases / 126 checkpoint backups / 36,210 checks; 78 effects per set | Full-archive verifier documented in `REPRODUCIBILITY.md`; no new scenarios executed |
| S7 retained analysis | Copied participant counts, full estimates and comparison grid, bootstrap multiplicities, source and pinned dependencies | `iasc/statistics/`; conditional on the frozen predictions and operating points |
| S9 source view | 87 files overlapping the full bundle match exactly; Git adds `SOURCE_VIEW.md` | `iasc_application/`; 6,611 result files are intentionally ZIP-only |
| S9 complete public bundle | 6,698 files, all frozen source bindings, 152 retained run records and independent public recalculation | Includes 8 development integration runs and 144 formal trajectories; excludes candidate bodies and private raw databases |
| S10 current package | 107 files; all 15 frozen study sources and 19 retained evidence digests checked | `iasc_model_check/` and portability ZIP; two complete normal counts and a non-exhaustive negative search |
| Current paper exhibits | All five figures with two plotting scripts and exports, six CSV inputs, five verbatim editable table fragments and numbering indices | `paper_artifacts/`; no full manuscript or Overleaf project |
| Licenses and attribution | Project code terms, derived-data terms, upstream IGT and HumanEval notices | Root license map, data source notice and S9 license scope |

## What this cleanup fixes

1. Replaces the root README's revision timeline with clear source, download,
   verification and plotting entry points. Historical documents remain in Git
   and under `docs/history/pre-artifact-guide-2026-09-12/`.
2. Adds a pinned registry and one downloader for the three current complete
   study archives. It verifies the archive and exact internal inventory before
   extraction, refuses an existing destination and supports deep Windows
   extraction paths without renaming archived members.
3. Fixes the quick-QA command in the guide and CI workflow by copying frozen
   S8 sources to fresh output. The historical wrapper and its report stay
   unchanged. The new runner checks all ten result cases, not just exit status.
4. Points readers to the existing full-archive S8 verifier, which protects the
   original databases. It documents the lower-level frozen auditor's failure
   signaling limitation and the archive-only reproduction paths.
5. Adds the current Figure 1–5 / Table 1–5 package. It corrects current numbering
   without relabeling files in frozen earlier presentation archives.
6. Separates S9's public-only projection checker from author-side preparation
   scripts and raw-database analysis. It gives S6's actual execution commands
   and identifies their environment and experimental scope.

## What remains unavailable or environment-dependent

- **Historical training:** the original `run_e1.py` bytes and ten inner
  calibration grids were not recovered. Seven core training modules match
  their recorded hashes. Frozen outputs support the post hoc analyses; a
  newly trained model would not restore that missing source history.
- **S9 candidate programs:** redistribution permission was not established,
  so candidate bodies remain outside the release. The documented upstream
  acquisition recipe, exact member hash and catalog reconstruction permit
  checking a separately obtained source. Public task tests retain their
  upstream license. This cleanup does not redistribute the candidate archive.
- **S9 raw bytes and execution environment:** public projections support
  independent saved-result recalculation. They do not recover intentionally
  excluded raw-database/body hashes. The frozen launcher contains specific
  Windows/WSL paths and runtime package locations; execution on a new machine
  needs setup and a separately versioned portability effort.
- **S10 external baseline:** 205 author-workspace baseline targets are
  explicitly outside the package and reported `NOT_CHECKED`. Java and the
  frozen TLC JAR are supplied separately for a new model run. Default saved
  verification needs neither and does not re-enumerate states.
- **Cloud CI:** repository Actions were disabled at audit time. The provided
  workflow command has been repaired, but there is no claimed GitHub-hosted
  CI pass. Local entry-point and evidence checks are distinct from cloud CI.

## Validation performed

The [machine-readable validation summary](ARTIFACT_VALIDATION.json) records
scope, input digests and tested boundaries. The 25 standard-library helper
tests and ten-case fresh-copy wrapper QA passed on Windows and Ubuntu 24.04;
reusing an output directory was rejected and retained evidence stayed unchanged.

The original frozen source inventories, fixed ZIP hashes, member inventories
and corresponding Git release tags passed. The new downloader was exercised
on all three existing archives and on a fresh anonymous network download of
the S10 archive. The extracted S8 two-runset verifier, S9 public-only checker
and S10 retained-evidence verifier passed. Corrupt-archive and existing-output
checks refused extraction.

A later fresh-checkout check exposed Windows path-length failure with a
Python executable lacking long-path support. The downloader now uses extended
Windows paths for disk I/O. All three real archives were extracted and every
member rehashed using Python 3.12.14 at maximum logical path lengths of 348,
335 and 282 characters, respectively. Archive member names and bytes stay
unchanged. This correction concerns the downloader, not the frozen study code.

Current figure generation was exercised from the compact inputs and after
relocation to a new directory. All five rebuilt PDFs match the current
canonical figure files byte for byte; a 180-dpi Poppler rendering comparison
has zero differing pixels. This equality describes the tested environment,
not an arbitrary-platform promise. Table 2 is independently reaggregated from
30 run-level p95 values; all 17 displayed data rows in Tables 2–4 match the
saved CSVs and included TeX. Current Table 1 is a manually curated empirical
checkpoint summary and Table 5 a qualitative literature map, not automated
numeric reconstructions. See `paper_artifacts/provenance/` and its table index.

No new model fitting, candidate-program execution, formal S6/S8/S9 experiment
or S10 state-space exploration was performed for this cleanup. Supplemental
tool QA does not increase the paper's experimental denominators. Result
equality between complete implementations and the reported limitations are
preserved.
