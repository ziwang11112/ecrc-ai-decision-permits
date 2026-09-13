# Availability and validation

The current Git tree is a source and data view. It contains implementation,
tests, experiment protocols, numerical inputs/results and plotting tools.
Standalone manuscript paragraphs, LaTeX tables, bibliography files, editorial documents and
obsolete document-layout outputs are omitted. Local author documents remain
separate from this repository.

## Source inventories

`MANIFEST.json` and `SHA256SUMS.txt` describe the current tree.
[SOURCE_VIEW.json](../SOURCE_VIEW.json) distinguishes retained files,
intentional omissions and current source/documentation overlays relative to
historical inventories. Those historical inventories keep their original
hashes; they are not claimed to be complete inventories of the reduced tree.
The source-view verifier cross-checks all four complete historical path sets,
original SHA-256 bindings, explicit statuses and current file contents. It
rejects missing mappings, duplicate paths and unrecognized inventory groups.

| Component | Current scope |
|---|---|
| Core and S6 delivery | Implementation, focused tests and experiment inputs retained |
| S8 | All 34 frozen source/input files retained; complete primary and repeated database evidence in the fixed archive |
| Participant analysis | Calculation, independent verification, input counts and saved estimates retained; prose/LaTeX formatter excluded |
| S9 | Execution and public-checking source retained; large public projections supplied in the fixed archive |
| S10 | All 15 frozen sources and 19 evidence bindings retained; editorial inclusion decision excluded |
| Plots and summaries | Five visualizations, six input CSVs and 17 expected numerical summary rows in `plots/current/` |

The S8 frozen source set includes its original report-output code because it
is bound by the pre-run freeze. Technical protocol and audit records remain
with the implementation. They are execution/provenance material, not a copy
of the authored manuscript or a complete Overleaf project.
Frozen protocols keep their original wording, including historical
publication-planning context.

## Verification

The [validation record](ARTIFACT_VALIDATION.json) gives the current source-view
and numerical-package checks. The unchanged artifact helpers passed 25
standard-library tests on Windows and Ubuntu; the retained wrapper completed
ten supplemental cases per platform. All three archive downloaders were
checked, including deep Windows paths, with unchanged archive/member hashes.

For `code-v1.1.0`, the combined helper suite has 46 tests, including 21 new
source-view regression tests. Ubuntu Python 3.12.3 passed all 46. Windows
Python 3.12.14 passed 45 and skipped the symlink test because creating a
symlink requires a privilege unavailable in that process; Ubuntu ran that
test successfully. The current CFF software citation passes schema 1.2.0.

The plotting package verifies its complete current inventory. All five
rebuilt PDFs and numerical input bytes match the previous version. CSV-only
aggregation verifies all 17 expected summary rows, including reaggregating
delivery latency from 30 saved run-level p95 values. Removal of a legacy
figure-caption output branch also leaves that figure PDF unchanged.

No model fitting, candidate execution, formal recovery experiment or
state-space exploration was added for this source-view cleanup. GitHub
Actions remain disabled; local checks are not a cloud-CI claim.

## External material and historical limits

- Full saved-run archives are selected by [ARTIFACTS.json](../ARTIFACTS.json).
  Existing Git history and old release archives retain their originally
  published contents, including older manuscript-formatting material. This
  cleanup is not a history rewrite or deletion of those fixed releases.
- Original historical `run_e1.py` bytes and ten inner calibration grids were
  not recovered. Post hoc analyses condition on retained frozen outputs.
- S9 candidate bodies require separate upstream acquisition and are not
  redistributed. Public projections support saved-result recalculation;
  complete execution additionally needs the documented sandbox setup.
- S10 default checking verifies retained evidence. A new exploration needs
  separately supplied Java/TLC; external author-workspace baseline targets
  remain explicitly outside public verification.

See [licenses](../LICENSES.md) and [dataset attribution](DATA_SOURCES_AND_LICENSES.md)
for data reuse and upstream terms.
