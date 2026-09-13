# Experiment source view

This directory contains selected implementation, analysis, plotting sources
and saved numerical evidence from the fixed experiment archives.

The current view excludes authored manuscript snippets, bibliography,
editorial prose and document-formatting helpers. Historical manifests retain
their original bytes and refer to their original complete packages. The root
`SOURCE_VIEW.json` maps the current included, omitted and modified entries;
run `python scripts/verify_source_view.py` from the repository root to check it.

All 34 frozen S8 source/input files remain included. Statistical computation,
independent numerical verification, input counts and saved output grids remain
available. The S6 delivery implementation is unchanged. Reader documentation
and a figure-caption output branch are current overlays, recorded separately
from the preserved scientific source hashes.

Use [the root guide](../REPRODUCIBILITY.md) for complete archived evidence and
commands. Use [plots/current](../plots/current/README.md) for compact plotting
and CSV-only result summaries. The older plotting code under
`presentation_revision/figures/` needs the original complete archive for all
copied database inputs; it is retained as an earlier plotting implementation.
