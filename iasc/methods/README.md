# Methods and reproducibility index

This index exposes settings already used for the frozen prediction experiment, plus the location of the new sensitivity and implementation checks. It does not introduce new features, fit a model, retune a threshold, or claim a new full training reproduction. All paths below are relative to the reproduction archive root.

## Prediction inputs and availability

`methods/feature_availability.csv` lists all 27 fitted-model input columns, their construction, availability and initial-history handling. `methods/archived/feature_schema.json` gives their original order. Families are trial/block position, previous deck, previous proxy/reward/loss/net outcome, cumulative net outcome, previous-choice run length, smoothed prior A/B rate, prior deck probabilities and entropy, and prior 5/10/20-trial risk/loss/net summaries. Trial/block position uses prior trial count; it does not use the episode's future observed endpoint.

Features are emitted before adding the current trial's choice or outcome to history (`methods/source/e1/data.py`, `build_causal_history_features`). Only outcomes from preceding trials enter the history. The target is whether the current choice is A/B. Participant, study and dataset identifiers, the current label and the duplicate `history_score` column are excluded from fitted-model features. The history rule uses `(prior A/B choices + 1)/(prior choices + 2)` directly and requires no fitting. No EEG input is used.

Both fitted pipelines apply training-partition median imputation with `keep_empty_features=True` and `add_indicator=True`. The logistic pipeline then uses a training-partition StandardScaler; HGB has no scaler. Empty history is handled by the explicit initial values or missing-value handling in the source, rather than access to later outcomes. These are time-order guarantees in the trusted prediction pipeline, not runtime enforcement of every predictor input's authorization eligibility.

## Fixed model settings

| Generator | Settings actually implemented |
|---|---|
| History | Smoothed causal proportion above; no training. |
| Logistic | L2; C=1; lbfgs; maximum 2,000 iterations; imputer and scaler above. |
| HGB | Learning rate 0.05; 200 iterations; maximum 15 leaf nodes; minimum 30 samples/leaf; L2 regularization 1; early stopping disabled; median imputer above. |

`methods/archived/model_specifications.json` is the archived summary; `methods/source/e1/models.py` is the implementation and additionally makes missingness-indicator creation explicit. Settings are fixed, not a model-hyperparameter search. `methods/archived/run_manifest.json` records the original software environment: Python 3.12.10, scikit-learn 1.9.0, NumPy 2.4.5, pandas 3.0.3, SciPy 1.17.1 and joblib 1.5.3. New post hoc analysis/runtime environments are recorded separately and are not substituted for this original fitting environment.

## Splits, seeds and selection

Five outer folds and three inner folds group by participant and stratify by source study. Within each sorted study, participant IDs are shuffled and assigned round-robin with a seeded random offset. This tests new participants within represented studies, not held-out-study transfer. `methods/archived/outer_fold_assignments.csv` records every outer assignment.

The archived base seed is 20260813. The current entrypoint uses model order history, logistic, HGB with indices 0, 1, 2. For outer fold f and model index j, its inner split seed is `base + 1000*f + 100*j` (inner fit seeds additionally add the inner fold); outer fit seed is `base + 10000*f + j`. Final all-development fits use `base + 100000 + j`. These formulas are inspectable in `methods/source/run_e1.py` and `methods/source/e1/models.py`. The core model module matches its original archived hash, but the current entrypoint does not; see the provenance limit below rather than treating its code as an authenticated original execution trace.

Each outer-training pool creates its own participant-grouped inner out-of-fold scores for operating-point selection. Threshold search is 0.30 to 0.85 inclusive in steps of 0.01. Under alert capacity 8, review capacity 2, review half-band 0.03 and ambiguity threshold 0.90, a feasible threshold has a nonempty action set, finite action precision at least 0.60, and at most nine negative actions per 100 decisions. Feasible rows are ordered by highest action coverage, then highest action precision, lowest negative-action rate, lowest action-route rate, and highest threshold. If no threshold is feasible, the implemented fallback minimizes excess negative-action rate, then precision shortfall, then negative coverage, then action-route rate; exact residual ties follow the ascending grid order. No observed outer or final selection used this fallback.

The 9/100 filter is redundant for this calibration setting. For m participants, let A be total actions, TP their total proxy-positive count, F = A - TP total proxy-negative actions, and N total decisions. Capacity gives A <= 10m, and pooled precision TP/A >= 0.60 gives F <= 0.40A <= 4m. This aggregate bound does not imply F_i <= 4 for each participant. Every episode has at least 95 decisions, so N >= 95m and 100F/N <= 400m/N <= 400/95 = 4.210526 per 100 decisions. See `calibration/CALIBRATION_CHECK.md` for the algebra, 15 selected outer rows and eight reconstructable full grids. Ten fitted-model outer-training inner-OOF grids were not saved; they are not fabricated from the different full-development outer-OOF scores. Frozen thresholds remain 0.43, 0.58 and 0.60.

The archived records identify final thresholds as selected from development outer-OOF predictions, with final models fitted on all development participants before external scoring. They record that external labels or scores were not used for selection. This revision audits code and archived artifacts, rather than rerunning fitting. `methods/SOURCE_VERIFICATION.json` confirms that all seven core `e1` modules and the selected method metadata match their original archived hashes. The current `run_e1.py` is 30,252 bytes with SHA-256 `47f54734eb5ae1cf71ed1df789c6ecdc07825dba4321f8a85bbb516a76fdd0ac`; the original record lists 30,128 bytes and `e94273e551014ea7c1d832d874bb10d41ced6d6aeeec922067d7a6eaaf438719`. It is retained as a current inspection copy, not represented as the exact original entrypoint. The cause of that difference and full historical code identity have not been established by this audit. Original prediction, route and calibration results remain unchanged.

## Evidence map

| Question | Reproduction-package entry point |
|---|---|
| Original frozen replay, route counts, prediction and model-method snapshots | `reproduce_analysis/` and `methods/` |
| Allocation expectation, gate overlap, online pacing and sequence controls | `supplement/S1*` through `supplement/S4*`; existing analysis reproduction scripts |
| Information-matched offline semantic checks | `supplement/S5*` and existing system-baseline inputs/code |
| Preissued-permit HTTP delivery, failure recovery and timings | `runtime/`, `reproduce_runtime.py`, `supplement/S6_runtime.md` |
| Participant-equal alert-policy sensitivity | `statistics/PROTOCOL.md`, `statistics/run_analysis.py`, `statistics/out/`, `supplement/S7_statistics.md` |
| Calibration redundancy and feasible selections | `calibration/check_calibration.py`, `calibration/verify_portable.py` and the archived calibration tables |
| New raw-request issuance through HTTP reconciliation | `end_to_end/PROTOCOL.md`, amendments, frozen implementation, run records and audit; `supplement/S8_end_to_end.md` |
| Actual plotted values and editable exports | `figures/` and `reproduce_figures.py` |

Protocols and manifests identify which experiments were post hoc. No checkpoint test or number of clean record pairs is represented as an independent random trial. The original public input-file audit establishes availability and matching hashes, not a new rerun of the original model pipeline. Archived result tables, repeated deterministic analysis outputs and newly measured runtime observations remain separately identifiable.
