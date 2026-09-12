# Portable calibration redundancy audit

This package reproduces the existing calibration audit from frozen predictions, fold assignments, selected operating points and the original routing/configuration code. No model fitting or adoption of new thresholds occurs. Read the unchanged historical report `CALIBRATION_CHECK.md`; its statement that participant-equal policy sensitivity was not yet available describes the earlier review date. That sensitivity was subsequently completed in the separate statistics supplement.

## Run from any working directory

The recorded environment is Python 3.12.14, NumPy 2.3.5 and pandas 3.0.1. Use the path to this package in place of `/path/to/calibration`:

```sh
python -m pip install -r /path/to/calibration/requirements.txt
python /path/to/calibration/check_calibration.py --out /path/to/calibration/fresh_out
python /path/to/calibration/verify_portable.py --out /path/to/calibration/fresh_out
```

Input files are always found relative to the script's own location, independent of the current working directory. `--out` must name a new directory: the script refuses to overwrite an existing directory. When omitted, it defaults to `out/` beside the script. `verify_portable.py` writes the validation record beside the script and also checks overwrite refusal without altering saved results. The archived `out/` is already populated, so use a fresh name when rerunning.

The supplied run was invoked from `D:/Codex/home`, outside both the package and paper workspace, using an absolute script path and an output directory inside this package. The original core CSVs are compared byte for byte. Cross-platform newline conventions can affect byte identity; the scientific JSON and frozen input hashes are also checked. The archived software versions and hashes are recorded in `out/calibration_audit.json` and `PORTABLE_VALIDATION.json`.

## Scope and findings

The existing calibration sets use at most eight alerts plus two reviews per participant. For m participants, let A be the total number of actions, TP their total proxy-positive count, F = A - TP the total proxy-negative count, and N the total number of decisions. The capacities imply A <= 10m; pooled action precision TP/A >= 0.60 implies F <= 0.40A <= 4m. This is an aggregate bound, not a bound of four proxy-negative actions for each participant. Since every calibration episode contains at least 95 decisions, N >= 95m and 100F/N <= 400m/N <= 400/95 = 4.210526 per 100 decisions. The additional nine-per-100 ceiling is therefore redundant. The audit checks all 15 saved outer selected rows and reconstructs only the eight grids supported by archived score sets: three final-development OOF grids and five history outer-training grids, comprising 448 threshold rows. Of these, 348 satisfy the precision condition and none violates the nine-per-100 limit. Removing only the false-action eligibility filter leaves these selected thresholds unchanged.

Ten fitted-model outer-training **inner-OOF** score sets/grids are not archived and are not reconstructed. Whole-development outer-OOF scores cannot substitute for those inner-OOF scores. The algebraic conclusion under the bounds is separate from empirical enumeration. The package must not be described as a complete rerun of all 18 training-side threshold grids or as a model-training reproduction.

## Included artifacts

- `archived/`: the untouched original report, audit JSON, original script, three core CSVs, and ancillary `calibration_grid_activity.csv`.
- `out/`: the portable run's three core CSVs and audit JSON. Only provenance/path fields are added or changed in the JSON.
- `input/evidence/`: minimal frozen predictions, experiment configuration, subject fold assignments, outer selected points, final frozen points and the original E1 code-hash manifest.
- `input/source/e1/`: exact configuration/routing/package-initializer bytes. `models.py` is retained for provenance/hash checking only and is not imported or executed; scikit-learn is not needed.
- `input/SOURCE_MANIFEST.json`: original workspace-relative paths, copied-file hashes and their comparisons to the original audit input hashes. Original audit hashes remain explicitly preserved even where an original source is no longer a runtime dependency.
- `input/ENTRYPOINT_PROVENANCE.json`: the current `run_e1.py` hash and historical mismatch. This entrypoint was only hashed by the original audit, is not necessary for the portable audit, and is neither copied nor executed here. Its current 30,252-byte hash does not equal the original E1 manifest's 30,128-byte hash; no equivalence is claimed.
- `PORTABILITY_ONLY.diff`: the complete changes between original and portable audit scripts. Only path resolution, output-directory handling and provenance validation were adapted; the grid and selection calculations are unchanged.
- `PROTOCOL_PORTABLE.md`, `PORTABLE_VALIDATION.json` and `PACKAGE_MANIFEST.json`: packaging scope, exact-reproduction evidence and full-package hashes.

The ancillary fourth CSV records the earlier precision-floor activity check. It is preserved with its original hash but is not a direct output of the original three-CSV script, so this package does not claim to regenerate it. `prepare_portable.py` documents the source-workspace copying/adaptation process and refuses to replace existing inputs; it is unnecessary for using the supplied portable package and should not be run after extraction.

Keep the entire directory when archiving. No external dataset download, network service, GPU or original workspace is required to run the audit.
