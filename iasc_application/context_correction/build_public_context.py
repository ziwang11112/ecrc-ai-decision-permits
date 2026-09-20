"""Build the local S9-C source/projection supplement; never publish or run jobs."""
from __future__ import annotations
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

sys.dont_write_bytecode = True
from context_catalog import HERE, ORIGINAL, read, file_sha, write_new
from run_correction import verified_protocol, preserved

ARCHIVE_NAME = "AIR-014_IASC_S9_Context_Correction"
ORIGINAL_RELEASE = {
    "url": "https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/download/iasc-application-2026-09-12/AIR-014_IASC_S9_Code_and_Results.zip",
    "tag": "iasc-application-2026-09-12", "filename": "AIR-014_IASC_S9_Code_and_Results.zip",
    "sha256": "b3d8d6fa8254a2a5c3de1fecae5f52c4383b5b0846640ea96de983cb19bd9f0f",
    "scope": "Original uncorrected S9 archive, not this public-helper correction"}
CSV_NAMES = ("S9_runs.csv", "S9_jobs.csv", "S9_cells.csv", "S9_paired_batches.csv",
             "old_new_run_differences.csv", "assembly_source_mapping.csv", "context_job_outcomes.csv")


def copy_new(source, target):
    target = Path(target)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def write_text_new(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def projection_module():
    public = ORIGINAL / "public"
    sys.path.insert(0, str(public))
    spec = importlib.util.spec_from_file_location("original_s9_public_projection", public / "build_public.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # New neutral identity fields only; the original recursive closed projection
    # still controls every raw result and nested receipt. No source file changes.
    module.NUMERIC.add("original_run_index")
    module.STRINGS.add("original_run_id")
    return module


def build(out, archive_path, analysis):
    out, archive_path, analysis = Path(out).resolve(), Path(archive_path).resolve(), Path(analysis).resolve()
    if not out.is_relative_to(HERE / "public"):
        raise ValueError("Bundle output must be under this new study's public directory")
    if archive_path != (HERE.parents[1] / "output" / (ARCHIVE_NAME + ".zip")).resolve():
        raise ValueError("Unexpected archive destination")
    if out.exists() or archive_path.exists():
        raise FileExistsError("Fresh public directory and archive required")
    fp, plan = verified_protocol()
    summary = read(HERE / "runs/SUMMARY.json")
    if (summary["planned_runs"], summary["observed_runs"], summary["technical_failures"]) != (32, 32, 0):
        raise ValueError("Completed successful 32-cell correction required")
    completion = read(analysis / "COMPLETION.json")
    if completion["status"] != "PASS" or completion["input_hashes_unchanged_after"] is not True:
        raise ValueError("Completed fixed analysis required")
    for name in (*CSV_NAMES, "merged_run_index.csv", "corrected_summary.json"):
        if file_sha(analysis / name) != completion["outputs"][name]:
            raise ValueError("Analysis output changed: " + name)
    original_archive = HERE.parents[1] / "output" / ORIGINAL_RELEASE["filename"]
    if file_sha(original_archive) != ORIGINAL_RELEASE["sha256"]:
        raise ValueError("Original public archive changed")
    projector = projection_module()
    out.mkdir(parents=True)

    # Complete unchanged frozen executable sources; no raw run tree is copied.
    original_protocol = read(ORIGINAL / "FINAL_PROTOCOL.json")
    for name in sorted(original_protocol["source_hashes"]):
        copy_new(ORIGINAL / name, out / "application" / name)
    copy_new(ORIGINAL / "FINAL_PROTOCOL.json", out / "application/FINAL_PROTOCOL.json")
    for name in ("HumanEval.jsonl.gz", "HUMANEVAL_LICENSE", "candidate_download_recipe.json"):
        copy_new(ORIGINAL / "workload/sources" / name, out / "application/workload/sources" / name)
    for name in ("context_catalog.py", "run_correction.py", "test_context.py", "PROTOCOL.md", "FINAL_PROTOCOL.json",
                 "ASSEMBLY_AUDIT.json", "GRID_PLAN.json", "PRESERVATION_BASELINE.json", "IMPLEMENTATION_QA.json"):
        copy_new(HERE / name, out / "correction" / name)
    for name in ("rebuild_public_catalog.py", "verify_public_context.py", "build_public_context.py"):
        copy_new(HERE / name, out / name)
    # Preserve the old public auditor source separately. Its post-study variant
    # changes only lookup of the retained original run number in each plan cell.
    for name in ("build_public.py", "reconstruct_catalog.py", "review_frozen.py", "check_public.py"):
        copy_new(ORIGINAL / "public" / name, out / "vendor" / name)
    original_auditor = (ORIGINAL / "public/check_public.py").read_text("utf-8")
    old_line = "folder = grid_root / f'r{index:03d}'"
    if original_auditor.count(old_line) != 1:
        raise ValueError("Unexpected original public auditor source")
    patched_auditor = original_auditor.replace(old_line, "folder = grid_root / cell['original_run_id']")
    write_text_new(out / "vendor/context_public_audit.py", patched_auditor)
    write_new(out / "metadata/PUBLIC_AUDITOR_ADAPTATION.json", {
        "original_source_sha256": file_sha(ORIGINAL / "public/check_public.py"),
        "adapted_source_sha256": file_sha(out / "vendor/context_public_audit.py"),
        "change": "Only folder lookup changes from enumeration position to each cell's original_run_id; the inherited audit function is invoked directly, not its old CLI.",
        "study_runtime_changed": False})

    catalog = read(HERE / "corrected_catalog.json")
    template = {**catalog, "jobs": [{k: v for k, v in job.items() if k not in ("solution", "test", "context_correction")}
                                    for job in catalog["jobs"]]}
    write_new(out / "metadata/catalog_template.json", template)
    # Independent original-catalog reconstruction keeps the unchanged old
    # template and pinned runner view; no candidate text is included.
    original_template = ORIGINAL / "public/bundle_formal_v1/metadata/catalog_template.json"
    copy_new(original_template, out / "original_reconstruction/metadata/catalog_template.json")
    for name in catalog["runner_manifest"]:
        copy_new(ORIGINAL / "workload" / name, out / "original_reconstruction/application/workload" / name)
    for name in ("HumanEval.jsonl.gz", "HUMANEVAL_LICENSE"):
        copy_new(ORIGINAL / "workload/sources" / name, out / "original_reconstruction/application/workload/sources" / name)
    projection_count = projector.export_run(HERE, HERE / "runs", out)
    # The saved projection identifies original cells; the old helper's grid
    # writer includes new identity fields through the additions above.
    public_grid = read(out / "results/runs/GRID_PLAN.public.json")
    if [c["original_run_id"] for c in public_grid["cells"]] != [c["original_run_id"] for c in plan["cells"]]:
        raise ValueError("Projected original run identity lost")

    retained = []
    with zipfile.ZipFile(original_archive) as archive:
        for run_id in plan["retained_original_runs"]:
            public_path = f"results/evaluation_v1/{run_id}/run_summary.json.public.json"
            member = "AIR-014_IASC_S9/" + public_path
            blob = archive.read(member)
            record = json.loads(blob)
            retained.append({"run_id": run_id, "original_run_index": int(run_id[1:]),
                             **{key: record[key] for key in ("batch_id", "arm", "policy", "condition")},
                             "original_public_path": public_path,
                             "original_public_sha256": projector.sha(blob),
                             "original_raw_summary_sha256": file_sha(ORIGINAL / "evaluation_v1" / run_id / "run_summary.json")})
    write_new(out / "metadata/RETAINED_ORIGINAL_RUNS.json", {"original_release": ORIGINAL_RELEASE, "runs": retained})
    copy_new(HERE / "analyze_correction.py", out / "analysis_source/analyze_correction.py")
    copy_new(HERE.parents[1] / "qa/iasc_application_pilot_2026-09-12/analyze_application.py",
             out / "analysis_source/analyze_application.py")
    for name in CSV_NAMES:
        with (analysis / name).open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or any(not re.fullmatch(r"[A-Za-z0-9_./:+|\-]*", value or "") for row in rows for value in row.values()):
            raise ValueError("Unexpected free text in analysis CSV: " + name)
        copy_new(analysis / name, out / "analysis/combined" / name)
    with (analysis / "merged_run_index.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    projected_index = [{k: v for k, v in row.items() if k not in ("selected_path", "original_path")} for row in rows]
    write_new(out / "analysis/combined/merged_run_index.public.json", projected_index)
    copy_new(analysis / "corrected_summary.json", out / "analysis/combined/corrected_summary.json")
    write_new(out / "metadata/ANALYSIS_PROVENANCE.json", {"original_completion_sha256": file_sha(analysis / "COMPLETION.json"),
        "files": {name: file_sha(analysis / name) for name in (*CSV_NAMES, "merged_run_index.csv", "corrected_summary.json")},
        "transforms": {"merged_run_index.csv": "Drop absolute selected_path/original_path; publish neutral fields as JSON. Other named analysis tables are byte-identical."},
        "scope": "Combined 112-original/32-replacement descriptive analysis; byte-complete raw SQLite analysis requires private local records."})
    write_text_new(out / "README.md", readme())
    write_new(out / "metadata/PROVENANCE.json", {
        "original_release": ORIGINAL_RELEASE, "correction_protocol_sha256": file_sha(HERE / "FINAL_PROTOCOL.json"),
        "corrected_catalog_sha256": fp["catalog_sha256"], "original_primary_study_unmodified": True,
        "replacement_trajectories": 32, "retained_original_trajectories": 112,
        "projected_result_files": projection_count, "candidate_programs_redistributed": False,
        "arbitrary_stdout_stderr_redistributed": False, "candidate_execution_during_packaging": False,
        "public_reconstruction": "Exact private corrected catalog can be rebuilt from separately obtained original author source; never included here.",
        "projection_limit": "Original result_hash identifies retained private bytes. A redacted projection has its own hash and cannot reconstruct the original result hash.",
        "preservation": preserved()})
    files = [{"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size, "sha256": file_sha(p)}
             for p in sorted(out.rglob("*")) if p.is_file()]
    write_new(out / "PUBLIC_MANIFEST.json", {"version": "S9-C-public-helper-context-v1", "files": files,
               "original_primary_study_unmodified": True, "new_context_correction_results": True,
               "complete_public_raw_results": False, "manuscript_included": False})
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                archive.write(path, ARCHIVE_NAME + "/" + path.relative_to(out).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        for member in archive.infolist():
            relative = member.filename[len(ARCHIVE_NAME) + 1:]
            if projector.sha(archive.read(member)) != file_sha(out / relative):
                raise ValueError("ZIP member differs: " + member.filename)
    checksum = archive_path.with_name(ARCHIVE_NAME + "_SHA256SUMS.txt")
    write_text_new(checksum, file_sha(archive_path) + "  " + archive_path.name + "\n")
    report = {"passed": True, "bundle": str(out), "archive": str(archive_path), "archive_sha256": file_sha(archive_path),
              "manifest_sha256": file_sha(out / "PUBLIC_MANIFEST.json"), "files": len(files) + 1,
              "projected_result_files": projection_count, "checksums": str(checksum), "candidate_execution_performed": False}
    write_new(HERE / "PUBLIC_PACKAGE_BUILD.json", report)
    print(json.dumps(report, indent=2))


def readme():
    return """# S9-C: public-helper context correction

This local supplement replaces all eight cells of four S9 batches (32 trajectories) and retains the other 112 original trajectories. It does not replace or silently modify the historical [original S9 release](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-application-2026-09-12). That release contains the **original uncorrected** study. Its fixed asset URL and SHA-256, and the 112 retained run identities and public-summary hashes, are in `metadata/RETAINED_ORIGINAL_RUNS.json`.

Exactly eleven selected programs lacked public, non-entry helper definitions from HumanEval/10, /32, /38 or /50. The corrected input prefixes only those missing public helpers and necessary public imports. It never imports a reference solution or derives context from tests. Existing candidate bindings and all other candidate bytes remain unchanged; empty programs do not acquire a prompt entry stub. Each original candidate, public prompt and added context has a separate hash, while the job binding identifies the assembled executable source. `correction/ASSEMBLY_AUDIT.json` contains the source-free map for all 656 selections.

The original runner, service and two complete clients are unchanged and included under `application/`. Budget16, deadline5 seconds, recovery backoff1 second, candidate order, fault rule and serial recovery remain fixed. `correction/GRID_PLAN.json` preserves the original run indices and order. There was no recalibration or automatic rerun. All 32 replacement runs are included through the original closed typed projection; `analysis/combined/` contains the descriptive 112+32 analysis. Different measurement sessions prevent attributing every timing difference solely to restored context.

## Public verification without candidate programs

Use a fresh report path outside the extracted bundle:

```
python -B verify_public_context.py --bundle . --out ../S9C_PUBLIC_CHECK.json
```

The verifier checks every public file/hash, exact inventory coverage, absence of source/output body fields, all32 replacement identities, and112 retained references. The inherited public trajectory auditor independently reconstructs retained-field policy choices, timely/eventual outcomes, actual child starts, budgets, effect/receipt/job bindings and response/cache events. Its only adaptation is using the original run ID from the grid instead of renumbering the 32 cells. The original auditor and adaptation note are retained in `vendor/` and `metadata/`.

## Rebuild the exact private corrected catalog

Obtain the original authors' program archive separately using `application/workload/sources/candidate_download_recipe.json`. The exact JSON member SHA is `4ef4b6b65e77ba2b1f44b6f890ac5d1f7e82b817bbdb7492b71fa1f825ef3522`. No selected candidate bodies are redistributed here. Run:

```
python -B rebuild_public_catalog.py --bundle . --source /private/author_archive.zip --verify-only
python -B rebuild_public_catalog.py --bundle . --source /private/author_archive.zip --out /private/corrected_catalog.json
```

The second destination must be fresh and outside this public bundle. Reconstruction executes no candidate, checks the original source/runner/catalog hashes, reproduces the missing-helper selection using only public prompts, and verifies the complete corrected catalog SHA `5d223ddb9a4c1cd42bd0b22dff8f495beeb9e7aaf05466c329c5814701207cc1`. Its candidate text remains private.

For new execution, copy `application/` to a private work directory, reproduce the documented Windows/WSL sandbox environment, and use its original `run_workflow.py` with the private corrected catalog and `correction/FINAL_PROTOCOL.json`. For example, from the copied application directory:

```
python -B run_workflow.py --catalog /private/corrected_catalog.json --batch evaluation_01 --arm ecrc --policy depth_first --condition normal --budget 16 --deadline 5 --backoff 1 --out /private/fresh_run --formal-protocol /path/to/S9C/correction/FINAL_PROTOCOL.json
```

This command executes untrusted candidate programs in the isolated runner; it is separate from reconstruction and public verification. Follow all32 cells and their recorded factor order for a complete new correction-grid reproduction. Keep all outputs fresh and outside public archives. The author-side `correction/run_correction.py` additionally binds the original local evidence tree and is retained as provenance, not advertised as a standalone public-layout launcher. No CPU or wall-time equality across hosts is promised.

## Contents and limits

`PUBLIC_MANIFEST.json` inventories exactly the public files. Protocol hashes can refer to excluded private inputs; such references are not claims that those bytes are inside this ZIP. Candidate bodies, raw databases, arbitrary stdout/stderr, logs, full raw receipt/result strings and manuscript files are excluded. Official HumanEval material is distributed under its included MIT license; no redistribution license is inferred for third-party candidate programs.

Projection manifests retain both original-file and public-file hashes. `result_hash` remains a reference to private original bytes and cannot be recomputed from a redacted result. Counts and preserved fields can be checked publicly; complete raw-result verification requires the retained private evidence. The analysis sources are included for inspection; their full raw SQLite analysis also requires that private layout. Finite-suite pass is not general correctness, and neither equal client results nor this context correction establishes ECRC-exclusive utility. No model generation, new API spending, journal validation by a publisher, or new theory proof is claimed by this package.
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "public" / ARCHIVE_NAME)
    parser.add_argument("--archive", type=Path, default=HERE.parents[1] / "output" / (ARCHIVE_NAME + ".zip"))
    parser.add_argument("--analysis", type=Path, default=HERE / "analysis_v1")
    args = parser.parse_args()
    build(args.out, args.archive, args.analysis)
