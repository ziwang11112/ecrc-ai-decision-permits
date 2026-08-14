# Figure 2 contract

## Core conclusion

On the declared trusted single-node runtime, transactional reservation preserved configured capacity under contention, while single-file SQLite contention increased tail latency.

## Figure architecture

- Archetype: focused two-panel quantitative systems result.
- Backend: Python/matplotlib only.
- Final size: 159 × 66 mm.
- Typography: Calibri first; all visible text at least 7.5 pt.
- Panel a is the correctness result: cap-relative admissions in two transactional stresses and one separately labelled constructed non-atomic witness.
- Panel b is the implementation-cost result: median within-run p95 latency and observed three-run min–max over the ordered worker sweep.
- Exact transactional counts are reported in the caption/source data rather than repeated beside the stress points; only the distinct unsafe-witness ratio is directly labelled.

## Statistics and evidence hierarchy

- Panel a contains deterministic exact counts and has no sampling interval.
- Panel b points are medians of three within-run p95 latency values; whiskers are the observed minimum and maximum over those three measured repetitions, not confidence intervals.
- Every worker-sweep run processed 96 requests at capacity eight, committed eight reservations, rejected 88 requests, emitted 96 receipts and produced zero oversubscription.

## Review-risk boundaries

- The unsafe result is one barrier-forced mechanism witness and is not a production or performance comparator.
- Timing is descriptive for the recorded Windows 11, Python 3.12.10 and SQLite 3.49.1 WAL host with simulated side effects; it does not establish performance portability.
- The runtime is one trusted file-backed node. The figure does not establish distributed consensus, external-service atomicity, live side effects or crash-free registration.
- The figure contains no bridge equivalence, evidence-admission, model discrimination or operating-point-transfer result.

## Export contract

Editable SVG and PDF are the vector masters. PNG, JPG and grayscale PNG are exported at 600 dpi. The figure uses no hatch, embedded table, cards, decorative frame or slide-style banner.
