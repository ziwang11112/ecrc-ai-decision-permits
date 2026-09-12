"""Render reports from the frozen completed analysis; no new statistical analysis."""
from pathlib import Path
import csv
import hashlib
import json

HERE = Path(__file__).resolve().parent


def f(value, signed=False):
    x = float(value)
    digits = 5 if 0 < abs(x) < 0.0005 else 3
    return format(x, f"{'+' if signed else ''}.{digits}f")


def main():
    with (HERE / "out/paired_comparisons.csv").open(newline="", encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    names = {"hist_gradient_boosting": "HGB", "regularised_logistic": "Logistic", "history_baseline": "History"}
    budgets = {"separate_8_2_vs_unbounded": "Cap removed - fixed 8+2", "eight_per_episode": "Paced - FIFO, 8/episode", "eight_per_100_planned": "Paced - FIFO, 8/100 planned"}
    grouped = {}
    for row in records:
        key = (row["analysis"], row["cohort"], row["model_name"], row["capacity_basis"])
        grouped.setdefault(key, {})[row["metric"]] = row
    summaries = []
    lines = ["| Comparison | Cohort | Generator | Eligible precision / coverage | Pooled precision difference | Macro precision difference [95% CI] | Macro coverage difference [95% CI] |",
             "|---|---|---|---:|---:|---:|---:|"]
    for (analysis, cohort, model, budget), rows in grouped.items():
        p, c = rows["alert_precision"], rows["alert_coverage"]
        summary = {"analysis": analysis, "cohort": cohort, "model_name": model, "capacity_basis": budget,
                   "n_participants": p["n_participants"], "n_precision_common": p["n_common_valid"], "n_coverage_common": c["n_common_valid"]}
        for metric, row in (("precision", p), ("coverage", c)):
            for field in ("pooled_difference", "pooled_difference_ci_low", "pooled_difference_ci_high", "common_macro_difference", "common_macro_difference_ci_low", "common_macro_difference_ci_high"):
                summary[f"{metric}_{field}"] = row[field]
        summaries.append(summary)
        intervals = [f"{f(r['common_macro_difference'], True)} [{f(r['common_macro_difference_ci_low'])}, {f(r['common_macro_difference_ci_high'])}]" for r in (p, c)]
        lines.append(f"| {budgets[budget]} | {cohort} | {names[model]} | {p['n_common_valid']} / {c['n_common_valid']} | {f(p['pooled_difference'], True)} | {intervals[0]} | {intervals[1]} |")
    assert len(summaries) == 18
    with (HERE / "all_comparisons_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    result = r"""# Participant-equal alert-policy sensitivity results

This post hoc analysis was locked in `PROTOCOL.md` before execution. It uses only frozen participant-level counts and keeps every planned cell. It does not fit a model, reselect a threshold, reconstruct a new policy, or estimate an intervention benefit. The complete grid comprises 24 S3 online arm cells and 12 fixed-cap/cap-removed arm cells: 36 arm cells, 72 arm-metric estimates and 36 metric contrasts from 18 paired comparisons.

## Findings

Participant weighting changes two directions in the cap-removal comparison. In development HGB and logistic, pooled alert-precision changes of +0.021 and +0.009 become participant-equal changes of -0.030 (95% CI -0.040 to -0.021) and -0.035 (-0.046 to -0.023). Development history also declines under both weighting schemes. These reversals mean the pooled precision changes must not be presented as improvements for an average alert-receiving participant.

For the previously emphasized external HGB cap-removal comparison, the pooled precision difference of +0.103 is attenuated to a macro difference of +0.037 (95% CI 0.00015 to 0.079). The unrounded lower limit is positive but close to zero; rounding it to 0.000 and describing it as reaching zero would be inaccurate. Fixed and removed-cap macro precisions are 0.665 and 0.703. The macro coverage difference is +0.285 (0.225 to 0.344), from 0.058 to 0.343, compared with the pooled difference of +0.318. External logistic also has a positive macro precision difference, whereas the external history macro precision interval includes zero. Cap-removal macro coverage increases in all six cohort-generator cells.

For online pacing versus FIFO, macro coverage point estimates decrease in all 12 cohort-generator-budget cells. The external HGB and logistic 8-per-episode coverage intervals include zero; all other macro coverage intervals lie below zero. Development macro precision decreases in all six cells. External macro precision point estimates increase in all six cells, but both HGB and both history intervals include zero, as does logistic under 8 per 100 planned decisions. External logistic at 8 per episode has a macro precision difference of +0.089 (0.024 to 0.154). The macro results therefore preserve the precision/coverage tradeoff and heterogeneous generator evidence; they do not support a general benefit of pacing.

## Estimands, eligibility and uncertainty

For each participant, precision is positive alerts divided by alerts, and coverage is positive alerts divided by all proxy positives. Pooled ratios weight participants by their alert or positive-event counts. Macro means give equal weight to eligible participants. Zero-alert precision and zero-positive coverage are undefined and excluded with counts retained. Positive-bearing participants receiving no alert contribute zero coverage. These are alternative descriptive weightings, not proof of fairness or true action utility.

There are 617 development and 59 external participants. Precision is defined for 614/612/576 development HGB/logistic/history participants and 59/58/54 external participants, respectively, for every included arm of each generator. Coverage is defined for 615 development participants and all 59 external participants; the two zero-positive development participants are reported and excluded. Across all 18 paired comparisons, the two arms happen to have identical valid-participant sets. Thus the arm-specific macro difference and the common-valid paired difference agree to numerical precision in these frozen data. The analysis nevertheless retains both estimands and the valid-only-one-arm counts; this equivalence is not assumed for arbitrary policies.

Intervals are unadjusted 95% participant-cluster percentile intervals from 2,000 shared paired bootstrap replicates per cohort (seed 20260912). All reported estimates and contrasts have 2,000 finite replicates. Intervals condition on the frozen predictions, thresholds, routes and observed eligibility; fitting, threshold selection, new-study uncertainty, and causal treatment benefit are outside their scope. All real-data labels remain the manuscript's IGT proxy labels. No model or threshold was tuned after observing these results.

## Complete paired comparison grid

Differences are comparison minus reference. Macro differences below use the common valid population. Intervals and estimates are rounded to three decimals except very small nonzero bounds, which retain five decimals. Full-precision values, both arm means, pooled intervals and all eligibility counts are in `out/arm_estimates.csv` and `out/paired_comparisons.csv`.

TABLE

## Provenance and checks

`input/INPUT_MANIFEST.json` maps every copied input to its original workspace path and SHA-256. The cap-off alert arm uses saved S4 alert-candidate counts; the fixed arm uses saved S3 FIFO counts. All 36 corresponding pooled arm cells reproduce S3/A4 archived values, with maximum absolute difference 1.78e-15. No uncapped review-action results are inferred from alert-candidate counts.

The calculation retains 12,168 harmonized participant-arm rows and saves all bootstrap draws, multiplicities and participant IDs. Hand-computable zero-denominator/unequal-eligibility fixtures and explicit participant-duplication checks pass. `verify_results.py` does not import the analysis implementation: it reads the copied source counts, independently reconstructs all 72 arm estimates, all 36 metric contrasts, and 468 bootstrap vectors of 2,000 replicates each. Its maximum absolute difference is 1.27e-15. This is a separate algorithmic verification, not a claim of blinded analyst replication. `verification.json` records the checks. Two complete fresh runs produce 11 byte-identical output files in `out/` and `out_repeat/`.

The copied `input/CALIBRATION_CHECK.md` separately documents redundancy of the false-action calibration constraint under the recorded precision and capacity bounds. This supplement does not reselect thresholds and cannot make that constraint active. The frozen policy estimates remain unchanged.
"""
    (HERE / "RESULTS.md").write_text(result.replace("TABLE", "\n".join(lines)), encoding="utf-8")
    snippet_dir = HERE / "snippets"
    snippet_dir.mkdir(exist_ok=True)
    methods = r"""\paragraph{Participant-equal policy sensitivity.}
As a post hoc sensitivity analysis, we retained the frozen predictions, thresholds, and routes and reported participant-equal alert precision and proxy-positive alert coverage for all two-cohort, three-generator, two-budget, two-allocator cells, together with every fixed-cap versus cap-removed comparison. For participant $i$, precision is $T_i/A_i$ and coverage is $T_i/P_i$, where $T_i$ is the number of proxy-positive alerts, $A_i$ the number of alerts, and $P_i$ the number of proxy-positive decisions. Macro precision averages over $A_i>0$ and macro coverage over $P_i>0$; a positive-bearing participant with no alert contributes zero coverage. Zero-denominator cases are reported rather than assigned zero precision or coverage. We distinguish the difference of arm-specific macro means from the mean of individual differences among participants valid in both arms. Unadjusted 95\% percentile intervals use 2,000 participant-cluster bootstrap samples, with the same sampled participants shared across paired arms and all cells within each cohort. These intervals condition on the frozen model, threshold, and policy outputs and do not propagate fitting or threshold-selection uncertainty. The original pooled ratios remain a separate estimand.
"""
    results = r"""\paragraph{Sensitivity to participant weighting.}
Macro coverage decreased under pacing in all 12 cohort--generator--budget cells; macro precision decreased in all six development cells and increased in all six external cells. On the external cohort, both HGB precision intervals and both history precision intervals included zero; logistic precision included zero under 8 per 100 planned decisions but not under 8 per episode. For cap removal, development HGB and logistic pooled precision differences of $+0.021$ and $+0.009$ became macro differences of $-0.030$ (95\% CI $-0.040$ to $-0.021$) and $-0.035$ ($-0.046$ to $-0.023$), respectively. The external HGB precision difference attenuated from a pooled $+0.103$ to a macro $+0.037$ ($0.00015$ to $0.079$), while its macro coverage increased by $0.285$ ($0.225$ to $0.344$). Cap-removal macro coverage increased in all six cells. Precision was defined for 614/612/576 development and 59/58/54 external HGB/logistic/history participants; coverage was defined for 615 of 617 development and all 59 external participants. The valid-participant sets happened to match within every paired comparison, so the two macro-difference estimands agreed in these data. The complete grid, excluded counts, and conditional bootstrap results are retained in the supplement. These changes describe weighting of proxy-label outcomes and do not establish intervention utility.
"""
    (snippet_dir / "participant_policy_methods.tex").write_text(methods, encoding="utf-8")
    (snippet_dir / "participant_policy_results.tex").write_text(results, encoding="utf-8")
    chosen = [
        ("capacity_removal", "Development", "hist_gradient_boosting", "separate_8_2_vs_unbounded"),
        ("capacity_removal", "Development", "regularised_logistic", "separate_8_2_vs_unbounded"),
        ("capacity_removal", "External", "hist_gradient_boosting", "separate_8_2_vs_unbounded"),
        ("online", "External", "hist_gradient_boosting", "eight_per_episode"),
        ("online", "External", "hist_gradient_boosting", "eight_per_100_planned"),
    ]
    tex_rows = []
    for key in chosen:
        rows = grouped[key]
        p, c = rows["alert_precision"], rows["alert_coverage"]
        label = "Cap removed" if key[0] == "capacity_removal" else ("Paced, 8/episode" if key[3] == "eight_per_episode" else "Paced, 8/100 planned")
        cells = [f"{f(r['common_macro_difference'], True)} [{f(r['common_macro_difference_ci_low'])}, {f(r['common_macro_difference_ci_high'])}]" for r in (p, c)]
        tex_rows.append(f"{key[1]} {names[key[2]]}, {label} & {p['n_common_valid']}/{c['n_common_valid']} & ${cells[0]}$ & ${cells[1]}$ " + chr(92) * 2)
    table = r"""% Selected examples; all 18 comparisons are in all_comparisons_summary.csv.
% Place and number this table according to the destination manuscript.
\begin{table}[htbp]
\centering
\small
\setlength{\tabcolsep}{3pt}
\caption{Selected participant-equal alert-policy sensitivity results. Cap removal is compared with fixed separate capacity 8+2; pacing is compared with FIFO at the stated budget. $n_P/n_C$ denotes the common valid precision/coverage participant counts. Entries are paired macro differences with unadjusted conditional 95\% bootstrap intervals. The complete supplement retains all 18 comparisons.}
\label{tab:participant-policy-sensitivity}
\begin{tabular}{p{0.31\linewidth}r p{0.25\linewidth}p{0.25\linewidth}}
\hline
Comparison & $n_P/n_C$ & $\Delta$ precision [95\% CI] & $\Delta$ coverage [95\% CI] \\
\hline
ROWS
\hline
\end{tabular}
\end{table}
"""
    (snippet_dir / "participant_policy_table.tex").write_text(table.replace("ROWS", "\n".join(tex_rows)), encoding="utf-8")
    print(json.dumps({"complete_comparisons": len(summaries), "selected_table_rows": len(tex_rows)}, indent=2))


if __name__ == "__main__":
    main()
