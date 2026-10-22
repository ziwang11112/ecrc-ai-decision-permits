"""Pure numerical functions retained from the revision reanalysis. No I/O."""
from collections import Counter
import itertools
import math
import numpy as np

MODELS = ("gpt-4.1-mini-2025-04-14", "gpt-6-luna")
CONDITIONS = ("normal", "hidden_first_result")
ARMS = ("prompt_only", "ordinary", "ecrc")
PROVIDER = dict(zip(MODELS, ("openai", "luna")))
METRICS = ("raw_verified_yield", "compliant_verified_yield", "actual_excess_rate")
RESOURCE_FIELDS = ("workflow_cpu_seconds", "workflow_suite_wall_seconds",
    "endpoint_cpu_seconds", "endpoint_suite_wall_seconds", "endpoint_launcher_wall_seconds")

def require(condition, message):
    if not condition:
        raise ValueError(message)

def close(a, b, context):
    require(math.isclose(float(a), float(b), abs_tol=1e-12, rel_tol=1e-12),
            f"{context}: {a!r} != {b!r}")

def total(rows, field):
    return sum(r[field] for r in rows)

def cell_rows(rows):
    cells = []
    for model, condition, arm in itertools.product(MODELS, CONDITIONS, ARMS):
        group = [r for r in rows if (r["model"], r["condition"], r["arm"]) == (model, condition, arm)]
        statuses = Counter(r["status"] for r in group)
        cell = {"model": model, "condition": condition, "arm": arm, "trajectories": len(group),
            "task_opportunities": total(group, "eligible_tasks"), "batches": len({r["batch_id"] for r in group}),
            "finished": statuses["finished"], "model_response_error": statuses["model_response_error"],
            "turn_limit": statuses["turn_limit"], "known_start_trajectories": len(group),
            "quota_excess_trajectories": total(group, "actual_excess_rate"),
            "compliant_trajectories": sum(r["verification_budget_compliant"] for r in group)}
        for field in ("workflow_verified_pass_count", "actual_starts", "actual_jobs_over_budget", "attempted_overquota",
                "denials", "independent_accepted_selected_tasks", "independent_accepted_unverified_selections",
                "independent_acceptance_starts", "actor_call_attempts", "actor_calls_returned", "hidden_results",
                "recovered_loss_original", "held", "duplicate_starts", *RESOURCE_FIELDS):
            cell[field + "_sum"] = total(group, field)
        for field in (*METRICS, "final_acceptance_rate"):
            cell[field] = total(group, field) / len(group)
        for field in ("workflow_seconds", "total_seconds_including_acceptance"):
            values = np.asarray([r[field] for r in group])
            cell[field + "_sum"] = float(values.sum())
            cell[field + "_median"] = float(np.quantile(values, .5))
            cell[field + "_p95"] = float(np.quantile(values, .95))
        cells.append(cell)
    return cells

def analyses(rows):
    batches = sorted({r["batch_id"] for r in rows})
    index = np.random.default_rng(20261007).integers(0, 24, size=(10000, 24))
    vectors, estimates, contrasts, sensitivity, influences, influence_summary = {}, [], [], [], [], []
    for model, condition, arm, metric in itertools.product(MODELS, CONDITIONS, ARMS, METRICS):
        vector = np.asarray([np.mean([r[metric] for r in rows if
            (r["model"], r["condition"], r["arm"], r["batch_id"]) == (model, condition, arm, batch)]) for batch in batches])
        vectors[model, condition, arm, metric] = vector
        ci = np.quantile(vector[index].mean(axis=1), [.025, .975])
        estimates.append({"provider": PROVIDER[model], "condition": condition, "arm": arm,
            "metric": metric, "estimate": float(vector.mean()), "ci95_low": float(ci[0]), "ci95_high": float(ci[1])})
    for model, condition, comparator in itertools.product(MODELS, CONDITIONS, ("prompt_only", "ordinary")):
        for metric in METRICS:
            vector = vectors[model, condition, "ecrc", metric] - vectors[model, condition, comparator, metric]
            ci = np.quantile(vector[index].mean(axis=1), [.025, .975])
            contrasts.append({"model": PROVIDER[model], "condition": condition,
                "contrast": "ecrc_minus_" + comparator, "comparator": comparator, "metric": metric,
                "estimate": float(vector.mean()), "ci95_low": float(ci[0]), "ci95_high": float(ci[1])})
        e = [r for r in rows if (r["model"],r["condition"],r["arm"]) == (model,condition,"ecrc")]
        c = [r for r in rows if (r["model"],r["condition"],r["arm"]) == (model,condition,comparator)]
        ne = sum(r["status"] == "model_response_error" for r in e)
        nc = sum(r["status"] == "model_response_error" for r in c)
        vector = vectors[model, condition, "ecrc", "compliant_verified_yield"] - vectors[model, condition, comparator, "compliant_verified_yield"]
        observed = float(vector.mean())
        identity = {"model": model, "condition": condition, "comparator": comparator}
        sensitivity.append({**identity, "trajectories_per_arm": 48, "ecrc_model_response_errors": ne,
            "comparator_model_response_errors": nc, "observed_difference_pp": observed*100,
            "scenario_lower_pp": (observed-nc*.75/48)*100, "scenario_upper_pp": (observed+ne*.75/48)*100,
            "interval_type": "counterfactual_scenario_bound_not_confidence_interval"})
        values = []
        for i, batch in enumerate(batches):
            value = float(np.delete(vector, i).mean())*100
            values.append(value)
            influences.append({**identity, "omitted_batch": batch, "retained_batches": 23,
                "retained_trajectories_per_arm": 46, "observed_all_batch_difference_pp": observed*100,
                "leave_one_batch_out_difference_pp": value, "change_from_all_batches_pp": value-observed*100})
        influence_summary.append({**identity, "observed_difference_pp": observed*100,
            "minimum_leave_one_batch_out_pp": min(values), "maximum_leave_one_batch_out_pp": max(values),
            "range_type": "influence_range_not_confidence_interval"})
    return estimates, contrasts, sensitivity, influences, influence_summary


def external_bounds(rows):
    require(len(rows) == 576, "External projection coverage differs")
    cells, lookup = [], {}
    for model, condition, arm in itertools.product(sorted({r["model"] for r in rows}), CONDITIONS, ARMS):
        group = [r for r in rows if (r["model"],r["condition"],r["arm"]) == (model,condition,arm)]
        missing = sum(r["metrics_observed"] == "False" for r in group)
        known = [r for r in group if r["metrics_observed"] == "True"]
        require(len(group) == 48, "External cell denominator differs")
        require(len(known) + missing == 48, "External availability flag is invalid")
        require(all(r["actual_starts"] == r["workflow_verified_pass_count"] == ""
                    for r in group if r["metrics_observed"] == "False"), "External missing scalars are not blank")
        raw = sum(float(r["workflow_verified_pass_count"])/4 for r in known)/48
        compliant = sum(float(r["budget_compliant_verified_yield"]) for r in known)/48
        excess = sum(float(r["actual_starts"]) > 3 for r in known)
        row = {"model":model,"condition":condition,"arm":arm,"scheduled_trajectories":48,
            "unknown_endpoint_trajectories":missing,"known_excess_count":excess,
            "full_denominator_excess_lower":excess/48,"full_denominator_excess_upper":(excess+missing)/48,
            "raw_yield_lower":raw,"raw_yield_upper":raw+missing/48,
            "latent_compliant_yield_lower":compliant,"latent_compliant_yield_upper":compliant+missing*.75/48,
            "operational_conservative_compliant_score":compliant,
            "interval_type":"missing_endpoint_bound_not_confidence_interval"}
        cells.append(row); lookup[model,condition,arm] = row
    require(sum(c["unknown_endpoint_trajectories"] for c in cells) == 4, "External missing count differs")
    contrasts = []
    for model, condition, comparator in itertools.product(sorted({r["model"] for r in rows}), CONDITIONS, ("prompt_only","ordinary")):
        e,c = lookup[model,condition,"ecrc"],lookup[model,condition,comparator]
        for metric in ("raw_yield","latent_compliant_yield"):
            contrasts.append({"model":model,"condition":condition,"comparator":comparator,"metric":metric,
                "full_scheduled_denominator_per_arm":48,
                "lower_difference_pp":100*(e[metric+"_lower"]-c[metric+"_upper"]),
                "upper_difference_pp":100*(e[metric+"_upper"]-c[metric+"_lower"]),
                "interval_type":"missing_endpoint_bound_not_confidence_interval"})
    return cells,contrasts
