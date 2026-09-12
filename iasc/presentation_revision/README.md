# Current manuscript result index and presentation sources

This presentation revision reorganizes the manuscript around the permission
lifecycle, then separates allocation outcomes under frozen proposals. It adds
no training, bootstrap, runtime experiment, or primary sample. The five main
figures and five tables replace the main-text selection; the original six
figures and all S1–S8 records remain unchanged elsewhere in this artifact.

## Every current main item

| Item | Evidence and exact index |
|---|---|
| Figure 1 | Illustrative timeout-release counterexample; figures/data/fig1_illustrative_events.csv. Not an observed full-implementation failure or new ablation. |
| Figure 2 | Specified lifecycle/transaction diagram; figures/data/fig2_lifecycle_states.csv, figure_evidence_index.csv and source hashes. |
| Figure 3 | Both arms, all three repetitions, all saved phases of two S8 scenarios; figures/data/fig3_checkpoint_counts.csv and fig3_plot_data.csv. 54 checkpoint observations, 12 final pairs checked separately. |
| Figure 4 | Six pooled/full-within/candidate-within AUROC cells and external gate geometry; figures/data/fig4_plot_data.csv and figure_evidence_index.csv. Distinct populations, no new fit. |
| Figure 5 | All 12 model/cohort/budget cells, saved paired intervals for precision, coverage and utilization; figures/data/fig5_plot_data.csv. Pooled vs participant-equal estimands and eligibility explicitly separate. |
| Table 1 | Literature scope, not an empirical performance comparison; the six table1 rows in index/NOTATION_AND_PROPERTY_MAPPING.csv and LITERATURE_SOURCE_NOTES.md. |
| Table 2 | O1–O6 obligations and supporting checks, not necessity/minimality claims; tables/table2_obligation_sources.md. |
| Table 3 | Study design and separate denominators; tables/MANUSCRIPT_RESULT_INDEX_TABLES.csv. |
| Table 4 | All 36 selected S8 observations and 36 final database pairs independently recounted; tables/MANUSCRIPT_RESULT_INDEX_TABLES.csv. |
| Table 5 | All six cap-removal cells, two metric panels and actual workload; tables/table5_cap_removal_complete.csv. |
| Equations 1–7 and notation | index/NOTATION_AND_PROPERTY_INDEX.md and NOTATION_AND_PROPERTY_SOURCE_HASHES.csv. Equation 7 is a new conditional accounting argument, not a measured result or an all-history implementation proof. |

The detailed CSV/JSON indices use exact source paths, named row keys/filters,
transformations, evidence identity and SHA-256. Prefix
`AIR-014_IASC_Reproducibility/` identifies this extracted artifact root, even if
the reader chooses a different directory name. Original filenames are not
renamed. Counters and notation are mapped to archived fields explicitly.

## Regeneration

Use Python 3.12. For the figures, install figures/requirements.txt and make
Arial available, then run `python -B build_figures.py` inside figures/. Its
copied frozen inputs are self-contained; read its README before recapturing
anything. Twenty PDF/SVG/PNG/TIFF exports and six plot-value CSVs rebuilt byte
identically in the recorded environment. No image-generation model was used.

For Tables 2–5, from the extracted artifact root run:

```console
python presentation_revision/tables/build_tables.py --bundle . --out fresh_table_output
```

The generator reads saved CSV/SQLite evidence, refuses missing or duplicate
keys and verifies source bytes. It writes the four numbered .tex files.
`tables/generated_main/` retains the exact main-text versions: the only assembly
change is renaming their files/labels to obligations, evaluation_design,
lifecycle_states and cap_removal. Table 1 is a reviewed literature mapping,
with an editable .tex source and cited-version index, rather than a data result.

## Provenance and scope

The property requires a finite consistent global cut, accurate disjoint
reservation counts, a controlled serialized lifecycle, distinct reservations
for distinct operations, persistent sink deduplication, no bypass effects and
no reclamation of committed expenditure. The low-level Ledger.release API alone
does not enforce the outbox condition. Checkpoint database counts are observed
states, not a simultaneous all-interleaving proof.

Historical training-entrypoint bytes and ten fitted-model inner grids remain
unavailable. Post hoc chronology, frozen-score uncertainty and the single-task,
proxy-label/synthetic-service limits remain unchanged. DATA_SOURCES_AND_LICENSES.md
at the artifact root governs derived data and figures; software retains MIT.
