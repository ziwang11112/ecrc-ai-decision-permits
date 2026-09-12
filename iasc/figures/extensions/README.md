# Figures 4 and 5: portable plotting package

The final `fig4.pdf` and `fig5.pdf` are vector figures, 6.5 inches wide, with embedded Arial fonts and black text of at least 8 pt. Matching editable SVG, 600 dpi PNG and LZW-compressed 1200 dpi TIFF exports are supplied. `fig4_proof.png` and `fig5_proof.png` are rendered from the final PDFs. Grayscale PNGs support print inspection.

Rebuild from the snapshots, without the original repository or experimental execution:

```text
python -m pip install -r requirements.txt
python build_fig4_fig5.py --out rebuilt
```

Arial must be installed and licensed on the rebuilding computer. The script fails if Arial is unavailable. `journal_style.py` is an unchanged copy of the previous figure builder, retained to reproduce its capacity/latency panels, font settings, vector exports and archived-data validation. Only its helper functions are called; its original entry point and Figure 1 are not run.

`data/provenance.json` identifies all input snapshots and their original workspace-relative paths and hashes. `fig4_fig5_manifest.json` records numeric source checks, plot counts, scripts, output hashes and PDF/font checks. `fig4_plot_values.csv` and `fig5_plot_values.csv` expose exactly the plotted values. These are plotting outputs, not newly simulated observations.

Figure 4 retains all archived capacity and latency values and all four archived validator rows. Its new independent row reads `data/component_summary.csv`. The new clean check is **one accepted complete trace containing 32 permits and 32 receipts**, not 32 newly independent clean traces.

Figure 5 has 6 candidate-AUROC points and 12 paired contrasts in each of panels (b) and (c). The panel-(a) counts are participants with both classes in the alert-candidate set; those counts do not define the online analysis sample. Pacing uses all 617 development and 59 external participants. A filled point is capacity 8 per episode; an open point is `ceil(8H/100)` for protocol horizon H. The direction is always pacing minus FIFO. Intervals are the saved conditional 95% participant-cluster intervals, not refit uncertainty or prediction intervals. The 0.5 candidate-AUROC reference is descriptive, not a sequence-adjusted significance threshold.

The build performs source/identity/numeric/format validation only. It neither refits models, reselects thresholds, reruns statistical bootstrap nor invokes an image generation service.
