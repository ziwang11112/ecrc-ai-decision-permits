# Historical plotting sources

This reader-document overlay describes the current Git source view. Historical manifests retain their original release hashes; the complete fixed release is unchanged.

For a standalone rebuild from this checkout, use [the current plotting package](../../../plots/current/README.md). This historical Git mirror omits `data/input/`, including the copied database snapshots required by `build_figures.py`. Its retained `data/input_manifest.json` records their provenance but does not supply the missing files.

To reproduce these older figures, obtain the complete pinned S1–S8 archive using the [reproducibility guide](../../../REPRODUCIBILITY.md). Use Python 3.12, make Arial available to Matplotlib, and install the copied requirements (Matplotlib 3.10.9 and Pillow 12.3.0; PyMuPDF is used only by export QA). Start at the repository root and use fresh destinations:

```sh
python scripts/download_artifact.py s1-s8 --output artifacts/s1-s8
python -c "import shutil; shutil.copytree('artifacts/s1-s8/presentation_revision/figures', 'artifacts/historical-plots-rebuild-1')"
cd artifacts/historical-plots-rebuild-1
python -m pip install -r requirements.txt
python -B build_figures.py
```

The builder writes into its own directory, which is why these commands first copy the complete archived figure directory. If `artifacts/s1-s8` is already downloaded and verified, omit the download command. The archive's input snapshots are sufficient; no original author workspace or recapture is needed. Do not use `--capture-from` for this rebuild.

The five historical figures use saved inputs; no model training, bootstrap or runtime experiment is performed. Figure 1 is explicitly illustrative; Figure 2 is a state/transaction schematic; Figures 3–5 show stored state or statistical evidence. The complete archive and a rebuild contain PDF, SVG, 600-dpi PNG and 600-dpi LZW TIFF exports. Figures are 6.6 inches wide, with heights of 3.6, 4.25, 5.8, 5.4 and 6.4 inches respectively, embedded Arial fonts in PDF and vector glyphs in SVG, black text, a single blue data color, and a minimum source type size of 9.5 pt.

`data/fig*_*.csv` are the editable plot-value exports. `fig3_checkpoint_counts.csv` includes every selected phase for both implementations and all three repetitions (54 checkpoint observations), plus 12 current-final observations. The plotted cells aggregate all six observations per phase; there is no winner/run selection. The copied SQLite inputs are copied again before querying, so SQLite cannot change their SHM/WAL state. `fig5_plot_data.csv` has 36 pooled and 24 participant-equal estimates, covering every requested cell with saved intervals.

`figure_evidence_index.csv` and `.json` record plot identifiers, source files, exact keys/filters, transformations, evidence types and source SHA-256. `build_manifest.json` preserves the historical input/source/output hashes. Authored caption drafts are omitted from this source view. `verify_exports.py` checks embedded fonts, minimum type, page bounds, black text, raster size/resolution and source hashes in the complete archived package; it renders the actual PDFs for visual review. Its PyMuPDF dependency is only needed for that QA step.

Current graphical choices preserve the data: no connecting lines between different AUROC populations, no time-series lines between checkpoint counts, no selective omission of online cells, and no new confidence intervals. The History policy's action/gate overlap is the interval-union width (0.10); the legacy max-component field is not used as that union.

Figure 5 displays native proportion differences (pacing minus FIFO). No multiplication by 100 is applied. `UNITS_REVISION_QA.json` records checks of every exported point and interval against the frozen inputs, preservation of Figures 1–4, and the complete clean graphical rebuild in `units_revision_portable/`. Historical percentage-point exports and QA were retained locally under `units_revision_before/`; those are superseded, not the current outputs.

The `units_revision_before/` and `units_revision_portable/` directories mentioned above are local QA archives and are not distributed. Their recorded checks are supplied in `UNITS_REVISION_QA.json` and `PORTABILITY_CHECK.json`; a fresh historical rebuild requires the complete S1–S8 archive as described above.
