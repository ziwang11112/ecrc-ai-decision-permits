"""Read-only public package inventory and retained-field trajectory verification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
FORBIDDEN_FIELDS = {"solution", "test", "canonical_solution", "original_solution", "context_source", "public_prompt",
                    "candidate_stdout_base64", "candidate_stderr_base64", "stdout", "stderr", "traceback"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def content_check(value):
    if isinstance(value, dict):
        if FORBIDDEN_FIELDS & set(value):
            raise ValueError("Forbidden candidate/output field in public JSON: " + repr(FORBIDDEN_FIELDS & set(value)))
        for item in value.values():
            content_check(item)
    elif isinstance(value, list):
        for item in value:
            content_check(item)


def verify(bundle):
    if sys.flags.optimize:
        raise ValueError("Do not disable inherited auditor assertions with -O")
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / "PUBLIC_MANIFEST.json").read_text("utf-8"))
    seen = set()
    for row in manifest["files"]:
        name = row["path"]
        path = PurePosixPath(name)
        if not isinstance(name, str) or "\\" in name or path.is_absolute() or not path.parts or path.as_posix() != name or any(p in (".", "..") or ":" in p for p in path.parts):
            raise ValueError("Unsafe noncanonical inventory path")
        target = (bundle / Path(*path.parts)).resolve()
        if not target.is_relative_to(bundle) or name in seen or not target.is_file():
            raise ValueError("Inventory path missing, duplicated or escaping")
        seen.add(name)
        if target.stat().st_size != row["bytes"] or sha(target) != row["sha256"]:
            raise ValueError("Public file digest differs: " + name)
        if target.suffix == ".json" and not name.startswith("application/legacy/request_template"):
            content_check(json.loads(target.read_text("utf-8")))
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    if actual != seen | {"PUBLIC_MANIFEST.json"}:
        raise ValueError("Public file coverage differs")
    sys.path.insert(0, str(bundle / "vendor"))
    from context_public_audit import audit_public_structure
    derived = audit_public_structure(bundle)
    if len(derived["runs"]) != 32:
        raise ValueError("Expected all 32 replacement trajectories")
    plan = json.loads((bundle / "correction/GRID_PLAN.json").read_text("utf-8"))
    if {r["run_id"] for r in derived["runs"]} != {c["original_run_id"] for c in plan["cells"]}:
        raise ValueError("Derived replacement IDs differ")
    retained = json.loads((bundle / "metadata/RETAINED_ORIGINAL_RUNS.json").read_text("utf-8"))
    if len(retained["runs"]) != 112 or {r["run_id"] for r in retained["runs"]} != set(plan["retained_original_runs"]):
        raise ValueError("Retained original coverage differs")
    return {"passed": True, "public_files_checked": len(seen), "replacement_trajectories": 32,
            "retained_original_index_entries": 112, "derived": derived,
            "scope": "Inventory, body exclusion and preserved-field trajectory checks; no raw result-hash reconstruction or candidate execution"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(args.bundle.resolve()) or args.out.exists():
        raise ValueError("Report destination must be fresh and outside public bundle")
    report = verify(args.bundle)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False); stream.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "derived"}, sort_keys=True))
