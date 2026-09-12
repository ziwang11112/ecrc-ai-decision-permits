"""Format Tables 2--5 from retained records; no experiment or bootstrap execution.

Run with Python standard library. All numerical cells are selected by named keys.
Source files and database pairs are opened read-only and hashed for provenance.
"""
import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
B = ROOT / "output/AIR-014_IASC_Reproducibility"
SOURCES = {}
ITEMS = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(relative):
    p = B / relative
    SOURCES[relative] = {"sha256": sha(p), "bytes": p.stat().st_size}
    return p


def csvread(relative):
    with source(relative).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def jsonread(relative):
    return json.loads(source(relative).read_text(encoding="utf-8-sig"))


def unique(rows, **key):
    found = [r for r in rows if all(r[k] == v for k, v in key.items())]
    assert len(found) == 1, (key, len(found))
    return found[0]


def writecsv(name, rows):
    with (HERE / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write(name, text):
    (HERE / name).write_text(text.rstrip() + "\n", encoding="utf-8")


def item(table, source_path, key, transform, status="Retained result; independently selected/recomputed"):
    ITEMS.append(dict(manuscript_item=table, source_file=source_path, row_key=key,
                      transformation=transform, evidence_status=status))


def fmt(value, extra=False):
    return f"{float(value):+.5f}" if extra else f"{float(value):+.3f}"


def estimate_ci(row):
    low = float(row["common_macro_difference_ci_low"])
    # Preserve the small external HGB positive lower bound rather than printing 0.
    lo = f"{low:.5f}" if 0 < low < 0.0005 else f"{low:.3f}"
    return "$" + fmt(row["common_macro_difference"]) + r"\;[" + lo + ", " + f'{float(row["common_macro_difference_ci_high"]):.3f}' + "]$"


def db_rows(relative, table):
    p = source(relative)
    wal = Path(str(p) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0, "Nonempty WAL cannot be ignored: " + relative
    db = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        return [dict(r) for r in db.execute('SELECT * FROM "' + table + '"')]
    finally:
        db.close()


def state_counts(base, arm):
    client, sink = base + "/client.sqlite", base + "/sink.sqlite"
    registry = db_rows(client, "issued_permits" if arm == "ecrc" else "permit_registry")
    requests = db_rows(client, "requests")
    budget = db_rows(client, "capacity_state" if arm == "ecrc" else "budgets")
    receipt = db_rows(client, "receipt_log" if arm == "ecrc" else "receipts")
    effect = db_rows(sink, "effects")
    assert len(registry) == sum(r["permit_json"] is not None for r in requests)
    return dict(registered_permits=len(registry),
                held_units=sum(r["reserved" if arm == "ecrc" else "held"] for r in budget),
                committed_units=sum(r["committed" if arm == "ecrc" else "spent"] for r in budget),
                sink_effects=len(effect), local_receipts=len(receipt))


def table4():
    relative = "end_to_end/out/S8_state_table.csv"
    archived = csvread(relative)
    all_outcomes = csvread("end_to_end/out/outcomes.csv")
    names = {
        "distinct_contenders": "After distinct-request contention",
        "mixed_claim_fallback": "After unsupported-claim release",
        "kill_during_issuance": "After interrupted issuance rollback",
        "kill_after_issue_resume": "Early cleanup before arm",
        "expired_unarmed_cleanup": "After expired unarmed cancellation",
        "accepted_timeout_cleanup_recovery": "Cleanup after committed effect and timeout",
    }
    observations, formatted, final = [], [], []
    for old in archived:
        scenario, checkpoint = old["scenario"], old["checkpoint"]
        group = []
        for rep in range(3):
            for arm in ("ordinary", "ecrc"):
                base = f"end_to_end/out/{scenario}/rep-{rep}/{arm}/snapshots/{checkpoint}"
                counts = state_counts(base, arm)
                row = dict(scenario=scenario, checkpoint=checkpoint, rep=rep, arm=arm, **counts,
                           client_source=base + "/client.sqlite", sink_source=base + "/sink.sqlite")
                observations.append(row)
                group.append(counts)
                summary = jsonread(base + "/audit.json")
                assert [counts[k] for k in ("registered_permits", "held_units", "sink_effects", "local_receipts")] == [summary[k] for k in ("permits", "reserved", "effects", "receipts")]
                out = unique(all_outcomes, scenario=scenario, rep=str(rep), arm=arm)
                directbase = f"end_to_end/out/{scenario}/rep-{rep}/{arm}"
                finalcounts = state_counts(directbase, arm)
                assert finalcounts["sink_effects"] == int(out["effects"]) == finalcounts["local_receipts"] == int(out["receipts"])
                assert out["passed"] == "True"
                final.append(dict(scenario=scenario, rep=rep, arm=arm, **finalcounts))
        assert len(group) == int(old["checkpoint_observations"]) == 6
        assert all(g == group[0] for g in group)
        c = group[0]
        assert "/".join(str(c[k]) for k in ("registered_permits", "held_units", "sink_effects", "local_receipts")) == old["observed_P_H_E_R"]
        formatted.append(names[scenario] + " & " + " & ".join(str(c[k]) for k in ("registered_permits", "held_units", "sink_effects", "local_receipts")) + r" \\")
        item("Table 4", relative, f"scenario={scenario}; checkpoint={checkpoint}",
             "Select by scenario and checkpoint; independently reconstruct all six observations from saved SQLite pairs; retain counts, no statistical interval.")
    assert len(all_outcomes) == len(final) == 36
    assert sum(r["sink_effects"] for r in final) == sum(r["local_receipts"] for r in final) == 78
    paths = list((B / "end_to_end/out").glob("*/rep-*/*/snapshots/*/client.sqlite"))
    assert len(paths) == 126
    assert sum(p.parent.name == "final" for p in paths) == 36
    assert sum(p.parent.name != "final" for p in paths) == 90
    writecsv("table4_checkpoint_observations.csv", observations)
    writecsv("table4_final_counts.csv", final)
    write("table4_lifecycle_states.tex", r"""\begin{table}[!htbp]
\centering
\small
\setlength{\tabcolsep}{4pt}
\renewcommand{\arraystretch}{1.14}
\caption{Raw-request lifecycle states at specified checkpoints (S8). Each row was observed in all six runs of that scenario: three repetitions of each information-matched implementation. Counts were reconstructed from the saved client and sink databases. These are checkpoint observations, not continuous measurements or independent fault-rate samples.}
\label{tab:lifecycle-states}
\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrr@{}}
\toprule
Scenario checkpoint & \shortstack{Registered\\permits} & \shortstack{Held\\units} & \shortstack{Sink\\effects} & \shortstack{Local\\receipts}\\
\midrule
""" + "\n".join(formatted) + r"""
\bottomrule
\end{tabularx}
\par\smallskip
\begin{minipage}{\linewidth}\small
Registered permits include retained non-action and cancelled records. The last row is allowed: a missing receipt does not justify releasing the held unit after the sink effect has committed. All 36 formal runs met the declared checks. Each run finished with two effects and two receipts, except the mixed-claim scenario, which finished with three of each (two alerts and one review), giving 78 effects and 78 receipts overall. Each final state had zero held units. The audit retained 36 direct final database pairs and 126 checkpoint backup pairs: 90 non-final snapshots and 36 final-state backups.
\end{minipage}
\end{table}
""")


def table5():
    paired_path = "statistics/out/paired_comparisons.csv"
    paired, arms = csvread(paired_path), csvread("statistics/out/arm_estimates.csv")
    volume_path = "statistics/input/a4_permission_grid.csv"
    volumes = csvread(volume_path)
    selected, aprecision, bcoverage = [], [], []
    models = [("hist_gradient_boosting", "HGB"), ("regularised_logistic", "Logistic"), ("history_baseline", "History")]
    for dataset, cohort in [("many_labs_igt", "Development"), ("mendeley_igt_official_v2", "External")]:
        for model, label in models:
            contrasts = {}
            for metric in ("alert_precision", "alert_coverage"):
                r = unique(paired, analysis="capacity_removal", dataset_id=dataset, model_name=model,
                           reference="fixed_8_2", comparison="capacity_removed", metric=metric)
                assert r["n_reference_only"] == r["n_comparison_only"] == "0"
                assert r["n_valid_reference"] == r["n_valid_comparison"] == r["n_common_valid"]
                assert int(r["common_macro_difference_finite_replicates"]) == 2000
                assert abs(float(r["common_macro_difference"]) - float(r["arm_macro_difference"])) < 1e-14
                contrasts[metric] = r
                item("Table 5" + ("A" if metric == "alert_precision" else "B"), paired_path,
                     f"analysis=capacity_removal; dataset_id={dataset}; model_name={model}; metric={metric}; reference=fixed_8_2; comparison=capacity_removed",
                     "Read pooled_difference and common_macro_difference with existing paired percentile CI; format to three decimals, except the small positive external-HGB precision lower bound to five decimals. No bootstrap rerun.")
            fixed = unique(volumes, dataset_id=dataset, model_name=model, arm="separate_capacity_8_2")
            removed = unique(volumes, dataset_id=dataset, model_name=model, arm="capacity_off")
            for name, record in [("fixed_8_2", fixed), ("capacity_removed", removed)]:
                a = unique(arms, analysis="capacity_removal", dataset_id=dataset, model_name=model, allocator=name, metric="alert_precision")
                assert int(a["n_alert"]) == int(record["n_alert"])
                assert abs(float(a["pooled_estimate"]) - float(record["alert_precision"])) < 1e-14
            for metric in ("alert_precision", "alert_coverage"):
                assert abs(float(removed[metric]) - float(fixed[metric]) - float(contrasts[metric]["pooled_difference"])) < 1e-14
            pr, cr = contrasts["alert_precision"], contrasts["alert_coverage"]
            row = dict(dataset_id=dataset, cohort=cohort, model_name=model, model_label=label,
                       n_precision=int(pr["n_common_valid"]), n_coverage=int(cr["n_common_valid"]),
                       n_participants=int(pr["n_participants"]), precision_excluded=int(pr["n_neither_valid"]),
                       coverage_excluded=int(cr["n_neither_valid"]),
                       pooled_precision_difference=pr["pooled_difference"], macro_precision_difference=pr["common_macro_difference"],
                       macro_precision_ci_low=pr["common_macro_difference_ci_low"], macro_precision_ci_high=pr["common_macro_difference_ci_high"],
                       pooled_coverage_difference=cr["pooled_difference"], macro_coverage_difference=cr["common_macro_difference"],
                       macro_coverage_ci_low=cr["common_macro_difference_ci_low"], macro_coverage_ci_high=cr["common_macro_difference_ci_high"],
                       fixed_alerts=int(fixed["n_alert"]), removed_alerts=int(removed["n_alert"]),
                       fixed_reviews=int(fixed["n_review"]), removed_reviews=int(removed["n_review"]))
            selected.append(row)
            name = cohort + " " + label
            aprecision.append(name + " & " + pr["n_common_valid"] + " & $" + fmt(pr["pooled_difference"]) + "$ & " + estimate_ci(pr) + r" \\")
            # Narrow first column wraps naturally; volumes explicitly say fixed -> removed in header.
            bcoverage.append(name + " & " + cr["n_common_valid"] + " & $" + fmt(cr["pooled_difference"]) + "$ & " + estimate_ci(cr) + " & " + f'{row["fixed_alerts"]:,}' + r"\,$\to$\," + f'{row["removed_alerts"]:,}' + " & " + f'{row["fixed_reviews"]:,}' + r"\,$\to$\," + f'{row["removed_reviews"]:,}' + r" \\")
            item("Table 5B volumes", volume_path, f"dataset_id={dataset}; model_name={model}; arm in (separate_capacity_8_2, capacity_off)", "Read n_alert and n_review; display fixed-to-removed integer totals. Cross-check n_alert and pooled precision against S7 arm estimates.")
    assert [r["n_precision"] for r in selected] == [614, 612, 576, 59, 58, 54]
    assert [r["n_coverage"] for r in selected] == [615, 615, 615, 59, 59, 59]
    writecsv("table5_cap_removal_complete.csv", selected)
    write("table5_cap_removal.tex", r"""\begin{table}[!htbp]
\centering
\small
\setlength{\tabcolsep}{3pt}
\renewcommand{\arraystretch}{1.14}
\caption{Complete cap-removal sensitivity grid (S7; resource ablation with unequal action volumes). All differences are capacity removed minus fixed separate caps of eight alerts and two reviews per participant episode, with frozen proposals, gates and thresholds. Panel A reports alert precision; Panel B reports proxy-positive alert coverage and actual route totals. Differences use proportion units.}
\label{tab:cap-removal-complete}
\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrr>{\raggedright\arraybackslash}p{0.36\linewidth}@{}}
\toprule
\multicolumn{4}{@{}l}{Panel A: Alert precision}\\
\midrule
Cohort / generator & $n_P$ & Pooled $\Delta$ & Participant-equal $\Delta$ [95\% CI]\\
\midrule
""" + "\n".join(aprecision) + r"""
\bottomrule
\end{tabularx}
\par\medskip
\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}p{0.16\linewidth}rr>{\raggedright\arraybackslash}Xrr@{}}
\toprule
\multicolumn{6}{@{}l}{Panel B: Proxy-positive alert coverage and workload}\\
\midrule
Cohort / generator & $n_C$ & \shortstack{Pooled\\$\Delta$} & \shortstack[l]{Participant-equal\\$\Delta$ [95\% CI]} & \shortstack{Alerts\\fixed $\to$ removed} & \shortstack{Reviews\\fixed $\to$ removed}\\
\midrule
""" + "\n".join(bcoverage) + r"""
\bottomrule
\end{tabularx}
\par\smallskip
\begin{minipage}{\linewidth}\small
$n_P$ is the number with alerts in both arms; no-alert precision is undefined. Of 617 development and 59 external participants, the excluded precision counts are respectively 3/5/41 and 0/1/5 for HGB/Logistic/History. $n_C$ counts participants with at least one proxy positive: two development participants and no external participant were excluded; a positive-bearing participant with no alert contributes zero coverage. Eligibility sets matched across these paired arms. Pooled ratios weight alerts (precision) or proxy positives (coverage); participant-equal differences average paired individual ratios over the common valid set. Intervals are the retained 2,000-replicate paired participant-cluster percentile bootstrap intervals, conditional on frozen predictions, thresholds, histories, routes and eligibility; they are exploratory and unadjusted. The small positive external-HGB precision lower bound is retained as 0.00015. Workload counts are deterministic totals, with no confidence intervals; removing caps changes the resource constraint and does not establish equal-resource benefit or observed human-review benefit.
\end{minipage}
\end{table}
""")


def table3():
    raw = csvread("end_to_end/out/outcomes.csv")
    delivery = csvread("runtime/out/recovery_results.csv")
    boundary = csvread("runtime/out/boundary_results.csv")
    faults = csvread("supplement/Data_S5_validator_cases.csv")
    clean = csvread("supplement/Data_S5_clean_trace.csv")[0]
    bridgepath = "figures/data/fig1_fig4/upstream/icair_2026/framework_v1/evidence_bridge/bridge_summary.json"
    bridge = jsonread(bridgepath)
    arms = csvread("statistics/out/arm_estimates.csv")
    paired = csvread("statistics/out/paired_comparisons.csv")
    assert len(arms) == 72 and len(paired) == 36
    assert len({tuple(r[k] for k in ("analysis", "dataset_id", "model_name", "capacity_basis", "allocator")) for r in arms}) == 36
    assert len({tuple(r[k] for k in ("analysis", "dataset_id", "model_name", "capacity_basis", "reference", "comparison")) for r in paired}) == 18
    dev = unique(arms, analysis="capacity_removal", dataset_id="many_labs_igt", model_name="hist_gradient_boosting", allocator="fixed_8_2", metric="alert_precision")
    ext = unique(arms, analysis="capacity_removal", dataset_id="mendeley_igt_official_v2", model_name="hist_gradient_boosting", allocator="fixed_8_2", metric="alert_precision")
    devqa = jsonread("end_to_end/ordinary_e2e_dev_checks.json")
    wrapper = jsonread("revision_reviews/runtime_review/WRAPPER_QA_PORTABLE_RESULT.json")
    assert len(raw) == 36 and len(set(r["scenario"] for r in raw)) == 6
    assert len(delivery) == 90 and len(set(r["scenario"] for r in delivery)) == 9
    assert len(set(r["case"] for r in boundary)) == 6 and len(boundary) == 12
    assert devqa["n_passed"] == 41 and wrapper["qa_cases"] == 10 and wrapper["passed"]
    rows = [
        dict(experiment="Raw-request lifecycle (S8)", input_boundary="Identical synthetic raw requests; journal, issuance, arm, independent sink and reconciliation.", comparison="ECRC and ordinary full issuance/delivery implementations; same information and budgets.", observations=f'{len(set(r["scenario"] for r in raw))} scenarios × {len(set(r["rep"] for r in raw))} repetitions × {len(set(r["arm"] for r in raw))} implementations = {len(raw)} runs.', interpretation="Specified contention, cancellation and recovery composition; no failure-rate estimate."),
        dict(experiment="Preissued-permit delivery (S6)", input_boundary="Identical preissued permits; arm, independent sink and reconciliation.", comparison="ECRC and ordinary delivery implementations; same information and budgets.", observations=f'{len(set(r["scenario"] for r in delivery))} scenarios × {len(set(r["rep"] for r in delivery))} repetitions × {len(set(r["arm"] for r in delivery))} implementations = {len(delivery)} runs.', interpretation="Delivery/recovery boundary; no raw-request issuance or unarmed recovery claim."),
        dict(experiment="Replay-to-simulator bridge", input_boundary="External frozen HGB replay into the single-database simulator.", comparison="Vectorised router versus adjudicator route/reason correspondence.", observations=f'{bridge["n_predictions"]:,} decisions; {bridge["n_participants"]} participants.', interpretation="Route correspondence and single-database execution; retained summary, not retained runtime database."),
        dict(experiment="Offline semantic validation", input_boundary="Archived clean and faulted records; no HTTP execution.", comparison="Full ECRC, ordinary semantic validator and mechanism-removal controls.", observations=f'{len(faults)} fault cases; {clean["n_traces"]} clean trace with {clean["n_permits"]} permits and {clean["n_receipts"]} receipts.', interpretation="Detection of specified archived violations; not an execution-success denominator."),
        dict(experiment="Frozen-proposal replay", input_boundary="Development and independent cohorts in the same behavioural task; fixed scores and operating points.", comparison="Same-ceiling pacing/FIFO; resource ablations; retrospective allocation references.", observations=f'{int(dev["n_participants"]):,}/{int(ext["n_participants"]):,} participants; {int(dev["n_decisions"]):,}/{int(ext["n_decisions"]):,} decisions.', interpretation="Allocation and weighting sensitivity; participant is the resampling unit."),
    ]
    writecsv("table3_experiment_design.csv", rows)
    source("end_to_end/PROTOCOL.md"); source("statistics/PROTOCOL.md"); source("runtime/PROTOCOL.md")
    texrows = []
    for r in rows:
        # Four columns, combine comparison and interpretation rather than five narrow columns.
        texrows.append(r["experiment"] + " & " + r["input_boundary"] + " & " + r["comparison"] + " " + r["interpretation"] + " & " + r["observations"].replace("×", r"$\times$") + r" \\")
    write("table3_experiment_design.tex", r"""\begin{table}[!htbp]
\centering
\small
\setlength{\tabcolsep}{4pt}
\renewcommand{\arraystretch}{1.12}
\caption{Evaluation design and denominators. The lifecycle experiments compare information-matched implementations. Allocation comparisons distinguish equal hard ceilings from resource ablations and retrospective references. Scenario repetitions, fault records, decisions and participants are different observation units and are not pooled into a single success rate.}
\label{tab:experiment-design}
\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}p{0.17\linewidth}>{\raggedright\arraybackslash}p{0.25\linewidth}>{\raggedright\arraybackslash}X>{\raggedright\arraybackslash}p{0.18\linewidth}@{}}
\toprule
Experiment & Input and boundary & Comparison and interpretation & Observations\\
\midrule
""" + "\n".join(texrows) + r"""
\bottomrule
\end{tabularx}
\par\smallskip
\begin{minipage}{\linewidth}\small
S7 participant-equal sensitivity and S8 raw-request lifecycle tests are post hoc extensions with their own protocols fixed before numerical execution. This table orders the evidence by its role, not by study chronology. The 12 S6 boundary checks (six cases in each of two implementations), performance runs, 41 ordinary-issuer development checks, ten supplemental wrapper/cleanup QA cases, auditor QA and complete reruns are separate from the 90 S6 and 36 S8 formal runs. The S7 archive contains 36 policy arms and 18 comparisons, each with precision and coverage records (72 and 36 metric rows respectively). No behavioural replay record is represented as entering the S8 synthetic-request experiment.
\end{minipage}
\end{table}
""")
    for path, key, transform in [
        ("end_to_end/out/outcomes.csv", "all scenario/rep/arm keys", "Count unique scenarios/repetitions/implementations and rows."),
        ("runtime/out/recovery_results.csv", "all scenario/rep/arm keys", "Count unique scenarios/repetitions/implementations and rows."),
        (bridgepath, "n_predictions; n_participants; runtime_database_retained", "Read retained summary; explicitly disclose absent runtime database."),
        ("supplement/Data_S5_validator_cases.csv", "all case_id keys", "Count archived fault records."),
        ("supplement/Data_S5_clean_trace.csv", "unit=one_complete_clean_trace", "Read trace/permit/receipt counts."),
        ("statistics/out/arm_estimates.csv", "capacity_removal; HGB; fixed_8_2; alert_precision; each cohort", "Read cohort participant and decision counts; shared inventory across generators verified by S7."),
    ]: item("Table 3", path, key, transform)


def table2():
    rows = [
        ("O1", "Bind raw request and issued content", "A decision identity could name changed request content.",
         "Canonical raw journal, content hashes and unique decision registration.",
         "S8 raw-input/registry audit and replay checks; input mutations are separate development and offline checks.",
         ["end_to_end/ecrc_e2e.py", "end_to_end/ordinary_e2e.py", "end_to_end/audit_e2e.py", "end_to_end/ordinary_e2e_dev_checks.json"]),
        ("O2", "Issue the complete permit atomically", "A crash could leave an orphan hold or partial permit.",
         "S8 outer transaction commits reserve/release, registry and full permit journal together.",
         "S8 issuance interruption before commit; separate wrapper exception QA. S6 starts with preissued permits.",
         ["end_to_end/ecrc_e2e.py", "end_to_end/ordinary_e2e.py", "end_to_end/run_e2e.py", "revision_reviews/runtime_review/WRAPPER_QA_PORTABLE_RESULT.json"]),
        ("O3", "Bind each action to its scoped unit", "Distinct operations could reuse one unit; unsupported claims could strand holds.",
         "Route/scope reservation and trusted registration; release provisional capacity on claim fallback.",
         "S8 distinct-request contention and mixed-claim release/reuse; offline reservation-binding faults.",
         ["end_to_end/ordinary_e2e.py", "end_to_end/legacy_snapshot/source_snapshot/agentic_eeg_dm/governance/adjudicator.py", "end_to_end/audit_e2e.py", "supplement/Data_S5_validator_cases.csv"]),
        ("O4", "Keep delivery identity and payload immutable", "A retry could change content or create a duplicate effect.",
         "Durable arm intent binds permit, operation key and payload; trusted sink commits effect and deduplication together.",
         "S6/S8 delivery and recovery records; separate service same-key and conflicting-payload QA.",
         ["runtime/ecrc_adapter.py", "runtime/ordinary_adapter.py", "runtime/service.py", "runtime/test_service.py", "end_to_end/audit_e2e.py"]),
        ("O5", "Retain armed responsibility during cleanup", "An existing or delayed effect could lose its counted budget unit.",
         "Serialize arm with unarmed cancellation; retain armed unknown outcomes despite expiry or timeout.",
         "S8 pre-expiry retention, unarmed expiry and accepted-timeout cleanup; ordering QA is separate.",
         ["end_to_end/ecrc_e2e.py", "end_to_end/ordinary_e2e.py", "end_to_end/run_e2e.py", "revision_reviews/runtime_review/WRAPPER_QA_PORTABLE_RESULT.json"]),
        ("O6", "Reconcile effect-backed completion atomically", "A receipt could lack its effect, or completion could consume capacity twice.",
         "Match acknowledgement identity/payload; commit held capacity, receipt and local completion in one transaction.",
         "S6 reconciliation crash/retry and separate adapter QA; S8 effect/receipt database audit.",
         ["runtime/ecrc_adapter.py", "runtime/ordinary_adapter.py", "runtime/out/recovery_results.csv", "runtime/test_ordinary_adapter.py", "runtime/test_ecrc_adapter_peer.py", "end_to_end/audit_e2e.py"]),
    ]
    output, texrows = [], []
    for oid, obligation, consequence, implementation, evidence, paths in rows:
        for path in paths:
            source(path)
            item("Table 2 " + oid, path, "Named implementation methods / checks detailed in table2_obligation_sources.md",
                 "Source inspection and scope mapping; violation consequences are explanatory, not measured removal-ablations.", "Specified obligation and retained bounded checks; no sufficiency/necessity theorem")
        output.append(dict(obligation_id=oid, obligation=obligation, possible_violation=consequence,
                           implementation=implementation, supporting_checks=evidence, source_paths="; ".join(paths)))
        texrows.append(oid + ": " + obligation + ". " + consequence + " & " + implementation + " & " + evidence + r" \\" + (r"\addlinespace[3pt]" if oid != "O6" else ""))
    writecsv("table2_obligations.csv", output)
    write("table2_obligations.tex", r"""\begin{table}[!htbp]
\centering
\small
\setlength{\tabcolsep}{4pt}
\renewcommand{\arraystretch}{1.10}
\caption{Specified obligations and supporting checks. The possible violation in the first column explains the obligation; it is not a measured outcome of removing that mechanism. The map distinguishes offline semantic detection, preissued-permit delivery (S6) and raw-request lifecycle execution (S8). It is neither a necessary-and-sufficient characterization nor an exhaustive concurrency proof.}
\label{tab:specified-obligations}
\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X>{\raggedright\arraybackslash}X>{\raggedright\arraybackslash}X@{}}
\toprule
Obligation and possible violation & Implementation boundary & Supporting checks and scope\\
\midrule
""" + "\n".join(texrows) + r"""
\bottomrule
\end{tabularx}
\end{table}
""")
    write("table2_obligation_sources.md", """# Specified obligations: source and scope map

All paths are relative to the reproducibility bundle. SHA-256 hashes are in `SOURCE_MANIFEST.json`. These are explanatory obligations, not necessary/sufficient conditions, minimality results or a claim that every consequence was observed in a mechanism-removal experiment.

| ID | Exact implementation / check locations | Evidence interpretation |
|---|---|---|
| O1 | `end_to_end/ecrc_e2e.py:Adapter.ingest/issue`; `end_to_end/ordinary_e2e.py:Adapter.ingest/issue`; `end_to_end/audit_e2e.py:audit` raw-input, raw-hash, registered-all-bindings and exact-registry-permit-inventory checks | S8 compares canonical original requests and all issued content. Conflict/malformed input rejection is supported by the separate 41-check ordinary development record and archived semantic mutations; it is not relabelled as 36 adversarial formal runs. |
| O2 | `end_to_end/ecrc_e2e.py:ContainedConnection`, `JournalLedger`, `Adapter.issue`; `end_to_end/ordinary_e2e.py:Adapter.issue`; `end_to_end/run_e2e.py` kill_during_issuance; `revision_reviews/runtime_review/WRAPPER_QA_PORTABLE_RESULT.json` | The real process-kill checkpoint is after reservation SQL and before outer commit. Three exception rollback hooks per arm are supplemental QA, not process-kill HTTP repetitions. The archived original adjudicator did not have this expanded outer transaction. |
| O3 | `end_to_end/ordinary_e2e.py:_reserve/_release/issue`; `end_to_end/legacy_snapshot/source_snapshot/agentic_eeg_dm/governance/adjudicator.py:OrderedAdjudicator.adjudicate`; `end_to_end/audit_e2e.py` reservation-to-permit, budget reconstruction and claim-fallback-release checks | S8 distinct contenders and mixed claim fallback inspect scarce capacity and a released provisional unit before later competition. Offline semantic faults detect forged/mismatched bindings; they are different evidence from execution. |
| O4 | `runtime/ecrc_adapter.py:Adapter.arm`; `runtime/ordinary_adapter.py:Adapter.arm`; `runtime/service.py:EffectLedger.post` and its atomic unique-key effect row; copied delivery modules in `end_to_end/legacy_snapshot/`; `runtime/test_service.py:test_concurrent_same_key/test_conflicting_payload/test_drop_restart_retry` | S6 recovery scenarios and S8 raw-request recovery preserve stable keys/payloads. The shared sink is trusted and synthetic. Separate service same-key and conflicting-payload QA checks do not increase formal scenario counts. |
| O5 | `end_to_end/ecrc_e2e.py:Adapter.arm/cleanup`; `end_to_end/ordinary_e2e.py:Adapter.cleanup`; S6 arm transaction in both delivery adapters; `end_to_end/run_e2e.py` expired_unarmed_cleanup and accepted_timeout_cleanup_recovery | Issued unarmed cleanup is added in S8. Existing armed intent is retained even after expiry. Controlled cleanup-first/arm-first QA checks supplement but do not exhaust concurrent orderings. Unknown held state is allowed; eventual completion is conditional on resumed communication/recovery. |
| O6 | `runtime/ecrc_adapter.py:Adapter.finish`; `runtime/ordinary_adapter.py:Adapter.finish`; `runtime/out/recovery_results.csv`; `runtime/test_ordinary_adapter.py`; `runtime/test_ecrc_adapter_peer.py`; `end_to_end/audit_e2e.py` effect/receipt matching | ACK fields are checked against durable intent and the audit compares with actual sink rows. Both full implementations are information matched. Adapter QA and actual recovery scenario counts remain separate. Trusted service ACKs, persistent storage and controlled execution path remain assumptions; local ACK validation alone is not proof against a malicious sink. |

The S8 table counts each selected checkpoint six times (three repetitions × two implementations), but these six states belong to that scenario's formal runs. They are not additional experiments. There are 36 direct final pairs plus 126 saved checkpoint backup pairs, including 90 non-final and 36 final-state backups. The full retained rerun is a reproducibility check, not an additional primary sample.
""")


def main():
    global HERE, B
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=B, help="Retained reproducibility bundle root (read-only).")
    parser.add_argument("--out", type=Path, default=HERE, help="Destination for generated editable tables and provenance.")
    args = parser.parse_args()
    B, HERE = args.bundle.resolve(), args.out.resolve()
    assert (B / "statistics/out/paired_comparisons.csv").is_file(), B
    HERE.mkdir(parents=True, exist_ok=True)
    table4()
    table5()
    table3()
    table2()
    for relative, record in SOURCES.items():
        assert sha(B / relative) == record["sha256"], "Source changed during read: " + relative
    writecsv("MANUSCRIPT_RESULT_INDEX_TABLES.csv", ITEMS)
    write("SOURCE_MANIFEST.json", json.dumps(dict(generator="build_tables.py", generator_sha256=sha(Path(__file__)),
          sources=SOURCES, source_files_unchanged=True, no_new_experiments=True, no_new_bootstrap=True), indent=2))
    write("VALIDATION.json", json.dumps(dict(passed=True, numerical_cells_key_selected=True,
          table4_checkpoint_observations=36, table4_final_runs=36, table4_snapshot_pairs=126,
          table4_nonfinal_snapshots=90, table4_final_backups=36, table5_complete_cells=6,
          table5_metric_contrasts=12, preserved_source_files=len(SOURCES),
          sqlite_mode="ro&immutable=1; nonempty WAL rejected", no_training=True,
          no_new_bootstrap=True, editable_latex=True), indent=2))
    print(json.dumps(dict(passed=True, source_files=len(SOURCES), files=[p.name for p in HERE.iterdir() if p.is_file()]), indent=2))


if __name__ == "__main__":
    main()
