# E7 sequence-only fault benchmark

This experiment reads the existing complete held-out claim-licence trace but
does not modify the old evidence, manuscript, or figures.

## Question

Can a verifier that compares records detect faults that are invisible to both a
primitive presence/type checker and the existing independently written
row-conditional validator?

## Prespecified faults

The benchmark injects 100 deterministic cases from each of six families:

1. adjacent automated-alert counter discontinuity;
2. adjacent review-counter discontinuity;
3. nonzero participant-segment start;
4. duplicate decision index;
5. missing decision index; and
6. failure to reset counters at a participant boundary.

Every injected row must still pass the existing primitive and independent
row-conditional validators. Each case must produce exactly one sequence-aware
finding at the prespecified location. Case construction fails closed if either
condition is not met.

Boundary-reset cases use the complete preceding participant segment plus the
first row of the next segment. This is a boundary window, not a truncation
test: the archived schema contains no declared segment-end field from which a
missing tail could be inferred.

`decision_index` is an absolute task index in this trace: held-out segments
start at 66, 70, or 105 rather than zero. The segment-start fault therefore
tests counter reset, not an incorrect requirement that the decision index begin
at zero.

## Reproduction boundary

The privacy-minimised review release includes the verifier source and aggregate
outcomes, but deliberately excludes the complete participant-linked trace and
the three row-level case files. To rerun the benchmark, first regenerate the
archived 19,965-row claim-licence trace from the public Many Labs inputs, then
supply that trace explicitly:

```text
python icair_2026/framework_v1/sequence_fault_benchmark.py \
  --clean path/to/heldout_claim_license_trace.csv \
  --output-dir scratch/sequence_fault
```

The review release retains these aggregate verification files:

- `validator_family_summary.csv`: family sensitivity and localisation;
- `clean_false_positive_results.csv`: row- and participant-segment FPR;
- `benchmark_summary.json`: scope, source hash, and interpretation limits;
- `determinism_check.json` and `artifact_hashes.json`: reproducibility hashes.

The full internal run additionally produced `sequence_fault_manifest.csv`,
`validator_case_results.csv`, and `sequence_findings.csv`. Those files are
participant-linked and are therefore represented only by their hashes here.

## Interpretation boundary

This is a controlled capability comparison for six declared sequence faults.
It does not establish detection of unknown, adversarial, security, coordinated
semantic, or deployment faults. The row-local validators have zero sensitivity
by construction because the experiment specifically asks what additional
cross-record information makes observable.
