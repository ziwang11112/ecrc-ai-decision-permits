# Controlled synthetic airline cancellation boundaries

This is a pre-fixed, modified-fixture test of the existing cancellation mechanism. It is **not** an official benchmark, an unseen native-record sample, an LLM-agent evaluation, or evidence of real economic benefit. No comparative cells may execute before protocol/code review and a source freeze. Earlier studies, frozen actors, policy checkers, core and manuscript files remain unchanged.

## Question and comparisons

Do the existing gates preserve valid cancellation paths while stopping disallowed or information-incomplete dispatch at the original rule boundaries? The four arms are `direct_native_dispatch`, `qualification_ecrc`, `existing_rules_only`, and `without_claim_evidence_requirement`. They reuse the previously frozen actors. Direct dispatch is the ordinary native-tool path without ECRC qualification; business rules are an explicit complete traditional comparator; claim ablation removes only the typed cancellation-evidence requirement from the full policy. No arm is intentionally broken. Ties with business rules are retained and do not establish a unique ECRC policy benefit.

Every arm receives the same original request and a fresh, identical per-case database. The same selector resolver and native factual tools are used. Every proposed write must receive the same explicit scripted `yes` confirmation procedure with complete reservation/flight/passenger details. A blocked workflow may make fewer confirmation turns and calls: equality of call counts is not claimed. No model, network, provider API, credential file, money or human participant is used.

## Fixed source and synthetic manipulations

The source is the pinned native FlightDB, commit `2174a603f6d014ef94473ffa95957f6ce27100db`. BASE_DB is its complete unchanged typed-schema JSON dump. The single template is `lei_santos_6163` / `9Z5X1D` / flight `HAT053`, selected as the first account and first selected reservation of the already recorded outcome-blind B cohort. This template was previously exposed and is not selected from new outcome comparisons. Sixteen modifications of one template are **not sixteen independent participants**.

`CASE_SPECS.json` fixes all 16 cases. `EXPECTED_BOUNDARIES.json` contains separate predictions; actors, selector, checker, gate and independent evaluation never consume it. A prediction mismatch is retained as an observed discrepancy, not relabelled or used to discard a cell.

For each case, reset from the full BASE_DB and explicitly replace the booking creation timestamp, cabin, insurance and status if different. Age is measured against the unchanged native-policy/checker clock **2024-05-15 15:00:00 EST**. Full ECRC capacity remains **K=100**, clean evidence metadata and native completion receipts remain absent. This study evaluates eligibility boundaries, not capacity exhaustion or metadata faults.

The booking's original one-leg list is copied with its date changed from 2024-05-12 to **2024-05-20**, whose existing native status is available; other prices/seats/history and unrelated records remain unchanged. Airline-cancelled cases replace that existing date's status object with `{"status":"cancelled"}`. This factual status is the sole positive basis in `sole_airline_cancelled`; the reason is still `other`, so the paired available control differs only by factual flight status.

For the two flying cases, the copied leg date is **2024-05-15**, and the existing HAT053 date-status object is replaced with `flying`, actual departure **13:00**, estimated arrival **16:00** on that date. HAT053's scheduled departure/arrival strings are explicitly replaced by **13:00:00 / 16:00:00** so the fixture is in flight at the fixed 15:00 clock. These clock/status edits are present only in these fixtures and identical for every arm. All other native dates are retained.

For `already_cancelled_overrides24`, the booking begins with status `cancelled` and its original payment history plus one exact reversal for each original payment, giving a pre-existing zero-net history. This is a deliberately already-completed cancellation. A repeated native cancellation may append further history without a new status transition. Report a successful repeated write, payment-history delta and new status transition separately; never call it a newly cancelled booking or monetary saving.

The fixture patch is an ordered list of `{path:[keys...], before:old, after:new}` replacements of existing JSON keys only. BASE_DB, each complete BEFORE_DB, each patch and their canonical/file SHA-256 values are recorded. Every fixture must round-trip through the unchanged native FlightDB schema and reconstruct exactly from BASE_DB plus its patch.

## Fixed grid and prediction boundary

| Cases | Controlled contrast | Other positive grounds removed |
| --- | --- | --- |
| sole24_before / sole24_at / sole24_after | Age 23:59:59 / 24:00:00 / 24:00:01 | Economy, no insurance, available flight, reason other |
| insured_weather / uninsured_weather / insured_other | Insurance yes/no and weather/other reason | Age 48 h, economy, available flight |
| sole_airline_cancelled / airline_available_control | Actual flight cancelled/available | Age 48 h, economy, no insurance, reason other |
| sole_business | Business cabin | Age 48 h, no insurance, available flight, reason other |
| flying_overrides24 / flying_overrides_insured_weather | In-flight prerequisite overrides a nominal positive ground | Age 1 h or insured weather at 48 h |
| already_cancelled_overrides24 | Already cancelled before request | Age 1 h, existing refund history |
| missing_reason_overrides24 / insurance / airline / business | Required reason absent | Otherwise test the named route; no reason is imputed |

The public policy says within the last 24 hours. The frozen software and independent checker implement `0 <= age <= 24 h`; the exact-24-hour cell probes that inclusive convention. Neither time-zone interpretation nor rule precedence is rewritten for this study. Missing reason remains information-incomplete. In-flight cases remain transfer-required: blocking a write does not complete the transfer or the full task.

## Execution and replay

Exactly **16 cases × 4 arms = 64 cells**, once each. Rotate arm order by case index. Each cell constructs an official native environment through `get_environment(db=FlightDB.model_validate(deepcopy(fixture)))`, which is its supported optional-DB interface. Frozen module globals are not patched. Native-call cap is 128 per cell. No retries that silently replace a failed comparative cell; keep exceptions, partial artifacts and failed result records. Fixing a code error requires a new version and a complete affected rerun with old evidence retained.

Save the original CASE, before reference, complete gzip AFTER_DB, calls, messages, confirmations, resolver output, actor output, old independent CASE_EVALUATION, gate SQL/config/snapshot and RESULT. After every cell, a separate fresh environment starts from the same fixture and replays all recorded native calls. Save actual second-pass response objects in `NATIVE_REPLAY_RESPONSES.json`; compare full response bindings and final DB hashes. This checks replay, not an additional independent sample. No official task ID, gold, reward or full-task score is used.

## Independent evaluation and reporting

Reuse the frozen `case_evaluation.evaluate(original_request, messages, before, after, resolution_status)` and its unchanged independent audit. Selection is reconstructed from original input and BEFORE, independently of actor-resolved IDs. The independent policy and native effect reconstruction determine eligible, known-ineligible, missing-information and transfer-required counts; expected labels do not determine metrics.

Report eligible completed/missed, ineligible executed, missing-information executed and transfer-required executed, plus native calls/writes/errors, any unverified evidence and all audit violations. Ineligible and unresolved dispatch may be genuine observed policy violations with valid effect metrics. An implementation error or unverifiable effect is not successful refusal. Preserve successful repeated-cancel writes separately from new cancellation-status transitions. Report per-case results; no population-level confidence intervals, artificial error bars or strong statistical claims from the single-template grid.

Run a separate independent read-only audit to reconstruct all fixtures, full effects, confirmations, raw native responses and gate ledgers from saved artifacts. The shared audit source is frozen before comparison. Technical success requires complete grid/effect verification, source integrity, common-input pairing and all replay checks. It does **not** require expected arm performance, business-rules ties or favorable ECRC differences. Any predictive or comparative discrepancy is reported, not automatically discarded. No manuscript change depends on favorable outcomes.

## Freeze and review gate

`prepare_boundary.py create` is mechanical data/schema preparation only: no native tools, actors or evaluation. `run_boundary.py prepare --out review/prerun_01` runs synthetic plumbing QA and freezes old sources, pinned vendor, this protocol/specification/input/fixture code and shared independent auditor. It does not run comparisons. The parent and independent auditor review prepared files before authorizing `run`. Frozen inputs are copied into a fresh batch with the fixture-relative paths declared in FREEZE. Every source is checked before and after the batch; original files and prior evidence are never edited.
