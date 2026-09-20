"""Restore only missing public-prompt helpers; never inspect tests or references.

All original candidate bytes are retained. Executable solution hashes describe
the assembled source actually supplied to the unchanged frozen S9 runner.
"""
from __future__ import annotations
import ast
import copy
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "iasc_application_2026-09-12"
TASK_HELPERS = {"HumanEval/10": "is_palindrome", "HumanEval/32": "poly",
                "HumanEval/38": "encode_cyclic", "HumanEval/50": "encode_shift"}
BATCHES = ["evaluation_01", "evaluation_10", "evaluation_14", "evaluation_15"]
FIELDS = ("task_id", "candidate_id", "solution_sha256", "test_sha256", "runner_sha256")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha_bytes(Path(path).read_bytes())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return sha_bytes(canonical(value).encode("utf-8"))


def read(path):
    return json.loads(Path(path).read_text("utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def top_bindings(tree):
    """Names bound by top-level statements, without running candidate code."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                         for alias in node.names)
        else:
            # Traverse compound top-level statements, but not inner local scopes.
            stack = [node]
            while stack:
                child = stack.pop()
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    if hasattr(child, "name"):
                        names.add(child.name)
                    continue
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    names.add(child.id)
                stack.extend(ast.iter_child_nodes(child))
    return names


def public_components(prompt, entry_point):
    tree = ast.parse(prompt)
    helpers = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name != entry_point]
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    return helpers, imports


def assemble(solution, prompt, entry_point):
    """Only prompt + candidate + entry name enter context selection.

    A candidate's own helper/binding is never replaced. Empty or syntactically
    invalid candidates are unchanged. The entry-point prompt stub is excluded.
    """
    helpers, imports = public_components(prompt, entry_point)
    if not solution.strip():
        return solution, "", [], "empty_candidate_unchanged"
    try:
        candidate = ast.parse(solution)
    except SyntaxError:
        return solution, "", [], "syntax_invalid_candidate_unchanged"
    bound = top_bindings(candidate)
    selected = [node for node in helpers if node.name not in bound]
    if not selected:
        return solution, "", [], "context_already_present_or_not_required"
    loads = {node.id for helper in selected for node in ast.walk(helper)
             if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    needed_imports = []
    for node in imports:
        imported = top_bindings(ast.Module(body=[node], type_ignores=[]))
        if imported & loads and not imported <= bound:
            if imported & bound:
                raise ValueError("Partial public import collision requires explicit review")
            needed_imports.append(node)
    nodes = [*needed_imports, *selected]
    context = "\n\n".join(ast.get_source_segment(prompt, node) for node in nodes) + "\n\n"
    # Prefixing preserves the candidate verbatim. Do not move a future import or
    # rewrite candidate code silently if a future corpus introduces one.
    if any(isinstance(node, ast.ImportFrom) and node.module == "__future__" for node in candidate.body):
        raise ValueError("Candidate future import requires a separately reviewed assembly rule")
    assembled = context + solution
    ast.parse(assembled)
    return assembled, context, [node.name for node in selected], "public_helpers_added"


def build_catalog(original, public_records):
    """public_records exposes only task_id, prompt, entry_point, never tests."""
    observed = {task: [n.name for n in public_components(row["prompt"], row["entry_point"])[0]]
                for task, row in public_records.items()}
    observed = {task: names for task, names in observed.items() if names}
    if observed != {task: [name] for task, name in TASK_HELPERS.items()}:
        raise ValueError("Public helper task inventory changed; scope review required: " + repr(observed))
    catalog = copy.deepcopy(original)
    rows, changed = [], []
    for job in catalog["jobs"]:
        old = copy.deepcopy(job)
        if sha_bytes(old["solution"].encode("utf-8")) != old["solution_sha256"]:
            raise ValueError("Original candidate digest differs")
        public = public_records[old["task_id"]]
        if old["entry_point"] != public["entry_point"]:
            raise ValueError("Entry-point identity changed")
        if old["task_id"] in TASK_HELPERS:
            source, context, helpers, disposition = assemble(old["solution"], public["prompt"], old["entry_point"])
        else:
            source, context, helpers, disposition = old["solution"], "", [], "outside_four_task_scope_unchanged"
        job.update(solution=source, solution_sha256=sha_bytes(source.encode("utf-8")))
        hashed = digest({name: job[name] for name in FIELDS})
        job.update(job_hash=hashed, job_digest=hashed, decision_id="verify:" + hashed, used_evidence_ids=["job:" + hashed])
        provenance = {"original_solution": old["solution"], "original_solution_sha256": old["solution_sha256"],
                      "original_decision_id": old["decision_id"], "assembled_solution_sha256": job["solution_sha256"],
                      "public_prompt": public["prompt"], "public_prompt_sha256": sha_bytes(public["prompt"].encode("utf-8")),
                      "context_source": context, "context_sha256": sha_bytes(context.encode("utf-8")),
                      "added_helper_names": helpers, "disposition": disposition,
                      "context_origin": "Pinned official public prompt; no canonical solution or test used in assembly"}
        job["context_correction"] = provenance
        row = {"candidate_id": job["candidate_id"], "task_id": job["task_id"], "batch_id": job["batch_id"],
               "rank": job["rank"], **{k: v for k, v in provenance.items() if k not in ("original_solution", "public_prompt", "context_source")}}
        rows.append(row)
        if source != old["solution"]:
            changed.append(row)
        for name in ("candidate_id", "rank", "source_array_index", "task_id", "test", "test_sha256", "entry_point", "runner_sha256", "batch_id"):
            if job[name] != old[name]:
                raise ValueError("Forbidden candidate/test/runner change: " + name)
    if {r["task_id"] for r in changed} != set(TASK_HELPERS) or {r["batch_id"] for r in changed} != set(BATCHES):
        raise ValueError("Changed tasks/batches differ from the fixed scope")
    if len(changed) != 11:
        raise ValueError("Expected exactly eleven context additions")
    catalog["context_correction"] = {"version": "public-helper-context-v1", "changed_candidates": len(changed),
                                     "changed_tasks": sorted(TASK_HELPERS), "rerun_batches": BATCHES,
                                     "assembly": "Prefix missing public non-entry helpers and their required public imports; retain original candidate bytes"}
    return catalog, rows, changed


def load_public_records(path):
    # The official distribution contains tests/references, but those fields are
    # discarded here and never passed to assembly or selection functions.
    records = map(json.loads, gzip.decompress(Path(path).read_bytes()).decode("utf-8").splitlines())
    return {row["task_id"]: {name: row[name] for name in ("task_id", "prompt", "entry_point")} for row in records}


def main():
    if (HERE / "runs").exists() or (HERE / "FINAL_PROTOCOL.json").exists():
        raise FileExistsError("Preparation cannot run after freeze or execution")
    original_protocol = read(ORIGINAL / "FINAL_PROTOCOL.json")
    source = ORIGINAL / "bound_catalog.json"
    official = ORIGINAL / "workload/sources/HumanEval.jsonl.gz"
    if file_sha(source) != original_protocol["catalog_sha256"] or file_sha(official) != original_protocol["official_data_sha256"]:
        raise ValueError("Original pinned input changed")
    baseline = {str((ORIGINAL / name).relative_to(HERE.parents[1])): h for name, h in original_protocol["source_hashes"].items()}
    for path in (ORIGINAL / "FINAL_PROTOCOL.json", source, official, ORIGINAL / "evaluation_v1/GRID_PLAN.json",
                 ORIGINAL / "evaluation_v1/outcomes.jsonl", ORIGINAL / "evaluation_v1/SUMMARY.json"):
        baseline[str(path.relative_to(HERE.parents[1]))] = file_sha(path)
    for name, expected in baseline.items():
        if file_sha(HERE.parents[1] / name) != expected:
            raise ValueError("Original protected input/source differs: " + name)
    catalog, rows, changed = build_catalog(read(source), load_public_records(official))
    original_plan = read(ORIGINAL / "evaluation_v1/GRID_PLAN.json")
    cells = [{**cell, "original_run_index": i, "original_run_id": f"r{i:03d}"}
             for i, cell in enumerate(original_plan["cells"], 1) if cell["batch"] in BATCHES]
    if len(cells) != 32:
        raise ValueError("Expected thirty-two original-indexed replacement cells")
    write_new(HERE / "corrected_catalog.json", catalog)
    write_new(HERE / "PRESERVATION_BASELINE.json", baseline)
    write_new(HERE / "ASSEMBLY_AUDIT.json", {"all_candidates": len(rows), "changed_candidates": len(changed),
              "changed": changed, "all_candidate_bindings": rows, "original_catalog_sha256": file_sha(source),
              "corrected_catalog_sha256": file_sha(HERE / "corrected_catalog.json"),
              "official_data_sha256": file_sha(official), "candidate_execution_performed": False,
              "test_or_reference_used_for_context_selection": False})
    write_new(HERE / "GRID_PLAN.json", {"planned_runs": 32, "cells": cells,
              "original_grid_sha256": file_sha(ORIGINAL / "evaluation_v1/GRID_PLAN.json"),
              "retained_original_runs": [f"r{i:03d}" for i, cell in enumerate(original_plan["cells"], 1) if cell["batch"] not in BATCHES],
              "order": "Subsequence of original 144-cell plan, preserving original run index and all factor order",
              "parallel_trajectories": 1, "automatic_reruns": 0})
    print(canonical({"changed_candidates": len(changed), "changed_tasks": sorted(TASK_HELPERS),
                     "rerun_batches": BATCHES, "planned_runs": len(cells), "catalog_sha256": file_sha(HERE / "corrected_catalog.json")}))


if __name__ == "__main__":
    main()
