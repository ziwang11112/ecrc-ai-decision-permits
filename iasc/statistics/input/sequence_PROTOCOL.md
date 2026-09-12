# Candidate discrimination and sequential controls: fixed follow-up protocol

Date: 2026-09-11. These are post hoc analyses and simulations, after the original results were inspected. No new real cohort, model fit, or selected threshold is introduced. The script writes only under this sequence directory. All planned cells and exclusions are retained regardless of direction.

## Frozen candidate discrimination

Use the manifest-verified `evidence_v2/predictions.csv.gz` and frozen reference-capacity route thresholds. Join thresholds by dataset/model/outer fold, asserting one threshold per key and complete matches. Preserve the original floating-point rule: ambiguity `1-abs(2*s-1) >= .90`; review `abs(s-theta) <= .03` after that gate; alert candidates require the gate not to fire and `s > theta+.03`. Assert that review and alert masks do not overlap on observed data. Do not round scores or relax a boundary.

Analyze both real cohorts and all three generators. For both full episodes and their alert-candidate subsets, retain every participant and report numbers of decisions, positives, negatives, candidates, participants with no candidates, and participants with both classes. An AUROC requires both classes in that subset. Report the discordant-pair-weighted within-participant AUROC, equal-participant macro AUROC over eligible participants, and share of eligible participant estimates below 0.5. Half credit for tied scores is mandatory.

Use 2,000 participant-cluster bootstrap draws with seed 20260911, preserving sorted participant order. Draw multinomial multiplicities over all participants, including those ineligible for candidate AUROC; recompute pair-weighted and macro summaries from weighted sufficient statistics. Use the same weights for full/candidate summaries within each cohort-model cell. Report percentile 2.5/97.5 limits, the number of finite replicates, and estimand-specific eligible counts. These intervals condition on frozen scores, folds, thresholds and episodes. Full and candidate AUROCs are distinct descriptive estimands; no superiority test or intervention contrast between them is planned.

## Validate the history reconstruction first

The original feature builder resets history per participant, uses the number of previously processed rows (not the numerical trial ID), emits `(prior positives+1)/(prior rows+2)`, and only then appends the current label. The generator returns that `history_score` unchanged. Sort by participant and trial ID, check duplicate keys, record first trial IDs/gaps, compare all archived history scores against complete row-order reconstruction, and assert agreement within 1e-12. Record the first predicted score and confirm there is no unexplained warm-up offset. Stop dependent simulation/reference analysis if reconstruction fails. Include a suffix/current-label mutation test showing current and previous scores are invariant.

## Fixed simulations

Each process has 1,000 participants and exactly 200 predictions including the first observation. No warm-up is discarded. Seeds are fixed by process: IID=2026091101, heterogeneous=2026091102, Markov=2026091103. The three processes are:

1. IID Bernoulli probability 0.5 at every decision.
2. Independent decisions conditional on a participant's fixed probability. Assign probabilities 0.2, 0.5, 0.8 in a repeating participant-index cycle, producing strata of 334, 333, 333 participants. These are known generating probabilities, not rates estimated from future observations.
3. Symmetric first-order Markov dependence: first-label probability 0.5; thereafter probability of repeating the previous label 0.8. Thus the oracle positive probability is 0.8 following a positive and 0.2 following a negative; the stationary marginal positive rate is 0.5.

For each generated sequence, score the fully causal smoothed history rule and the known conditional-probability oracle. History always starts at 0.5. Use a single prespecified history-based candidate mask with theta=0.43, delta=0.03, gamma=0.90. Both scorers are evaluated on the same full and history-candidate subsets; the oracle does not choose its own candidates. Do not change parameters if candidates or eligible episodes are sparse.

Report full and candidate pair-weighted/macro within AUROC, eligible-participant below-0.5 fraction and all denominators for both scorers. Report Brier score and natural-log log loss over ALL 200 predictions, never restricted to candidates. Clip probabilities only within the log calculation to [1e-15,1-1e-15]; this never changes candidate selection or ranking. Save participant sufficient statistics, all generated labels/scores/oracle probabilities/candidate masks, and every aggregate. These are descriptive results for three fixed synthetic cohorts, not inference about real participants or a new fitted-model validation. No hypothesis tests are planned.

## External history random-order reference

Use all 59 frozen external history episodes. Fix each participant's episode length and positive count and generate 1,000 independent random orders, seed 2026091104. Rebuild causal history scores and the history candidate mask from each new order. This is an independently recomputed exploratory reference, not an attempt to recover the old global RNG stream that first processed development participants.

For every replicate, report the same full/candidate discrimination summaries, eligible counts and full-sequence Brier/log loss. Report the mean, median and 2.5/97.5 percentiles of the random-order reference alongside the actual observed reconstruction. These are reference-distribution ranges, not confidence intervals for observed performance; random exchangeability is an illustrative assumption, not an assertion about the true behavioral process. Do not attach a null-hypothesis p-value. A poor comparison with 0.5 or with a constant scorer is not automatically evidence of future predictive benefit.

## Provenance and checks

Use Python 3.12.14 with the task's `qa/iasc_conversion_2026-09-11/python_deps` search path and bundled NumPy/pandas. Implement tie-aware ranks in NumPy; no SciPy/model dependency is needed. Record exact versions, script/protocol hashes, inputs and all output hashes. Verify all original inputs are unchanged. Validate rank calculations against an independent pairwise definition including ties, single-class and empty subsets; verify candidate summaries against the earlier independently archived aggregate; verify clustered resampling against explicit participant duplication on small cases; verify simulation oracle probabilities and history causality; verify every permutation preserves each subject's class count. Execute twice into separate output directories and compare every emitted file byte for byte. Save short English methods/results wording without modifying the manuscript or figures.
