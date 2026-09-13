# Current Table 1–5 index

The current numbering is fixed by the main manuscript's input order. All five
TeX fragments are byte-for-byte copies, with their original captions, notes,
labels and citation keys. Numerical supporting CSVs are also copied verbatim.

| Current table | TeX source and label | Scientific type and local support |
|---|---|---|
| 1 — Raw-request lifecycle checkpoints | `lifecycle_states.tex`; `tab:lifecycle-states` | Manually curated empirical checkpoint summary. Six displayed checkpoints describe permit/held/effect/receipt counts; they are not conceptual simulations or field-fault rates. Full S8 database provenance is outside this presentation package; automatic reconstruction of this table is not claimed. |
| 2 — Failure-free preissued-delivery latency | `delivery_cost.tex`; `tab:delivery-cost` | Numerical summary. `data/S6_performance_runs.csv` contains 30 runs; the six client/thread cells in `data/S6_performance_summary.csv` are independently reaggregated and displayed as three rows, with median/minimum/maximum of five run-level p95 values per cell. |
| 3 — Application outcomes and launcher cost | `application_results.tex`; `tab:application` | Numerical summary. All eight rows of `data/S9_cells.csv` support timely/eventual tasks, actual jobs and launcher seconds. The same CSV supplies Figure 4. |
| 4 — Cap-removal precision sensitivity | `cap_precision.tex`; `tab:cap-precision` | Numerical summary. All six conditions of `data/table5_cap_removal_complete.csv` support common-valid counts, pooled and participant-equal precision differences and saved conditional intervals. |
| 5 — Reviewed specification boundaries | `closest_scope.tex`; `tab:closest_scope` | Manually authored qualitative/literature scope map. Seven rows retain version-qualified comparisons; this is neither an empirical performance table nor a scored superiority matrix. |

The source filename `table5_cap_removal_complete.csv` belongs to an earlier
results index; its bytes and filename are preserved. It supports **current Table
4**, not current Table 5. Figure 1's specified example and Figure 2's lifecycle
schematic are conceptual illustrations; that classification does not turn
current Table 1's observed checkpoints into simulated data.

## Numeric display check

Run from the package root:

```sh
python scripts/build_table_values.py --out ../rebuilt_current_tables
```

The standard-library script checks input hashes, writes `table2_display.csv`,
`table3_display.csv`, `table4_display.csv` and `TABLE_VALUE_CHECK.json`, and matches
all 17 data rows against the included TeX. Table 2 uses one decimal place;
Table 3 launcher costs use two; Table 4 contrasts and limits use three except
the explicitly retained external-HGB lower endpoint 0.00015. This preserves
the current display and does not change the underlying saved numbers.

The verifier does not validate literature judgments, caption claims, hidden
implementation behavior or S8 raw database contents. Current Table 5 retains
the keys `lavi2026right`, `uchibeke2026before`, `ye2026contracts`, `chen2026cordon`,
`peng2026masugate` and `santosgrueiro2026commit`; the parent document supplies
the bibliography. No third-party paper or unrelated bibliography is bundled.
