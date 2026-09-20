"""Rebuild the private corrected catalog; candidate data never executes here."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def rebuild(bundle, source):
    bundle = Path(bundle).resolve()
    sys.path.insert(0, str(bundle / "vendor"))
    from reconstruct_catalog import reconstruct
    # vendor reconstruct_catalog uses the original metadata, not the corrected
    # public template. Its explicit source member/hash checks remain unchanged.
    original_view = bundle / "original_reconstruction"
    blob = reconstruct(original_view, source)
    workload = json.loads(blob)
    spec = importlib.util.spec_from_file_location("public_context_builder", bundle / "correction/context_catalog.py")
    context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context)
    original = {**workload, "permitted_claim_ids": ["run_verification"], "jobs": []}
    for job in workload["jobs"]:
        h = context.digest({name: job[name] for name in context.FIELDS})
        original["jobs"].append({**job, "job_hash": h, "decision_id": "verify:" + h})
    # Original application_common.write used Windows text-mode CRLF. Match its
    # archived byte hash explicitly on every host; corrected write_new uses LF.
    original_text = json.dumps(original, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    original_blob = original_text.replace("\n", "\r\n").encode("utf-8")
    audit = context.read(bundle / "correction/ASSEMBLY_AUDIT.json")
    if context.sha_bytes(original_blob) != audit["original_catalog_sha256"]:
        raise ValueError("Rebuilt original bound catalog hash differs")
    public = context.load_public_records(bundle / "application/workload/sources/HumanEval.jsonl.gz")
    corrected, _, changed = context.build_catalog(original, public)
    result = (json.dumps(corrected, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if context.sha_bytes(result) != audit["corrected_catalog_sha256"] or len(changed) != 11:
        raise ValueError("Rebuilt corrected catalog does not match retained input")
    return result, context.sha_bytes(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--source", type=Path, required=True, help="Original author's ZIP or exact verified JSON member; kept private")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only and args.out is None:
        parser.error("--out required unless --verify-only")
    if args.out is not None:
        destination = args.out.resolve()
        if destination.is_relative_to(args.bundle.resolve()) or destination.exists():
            raise ValueError("Private destination must be fresh and outside the public bundle")
    blob, hashed = rebuild(args.bundle, args.source)
    if not args.verify_only:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(blob)
    print(json.dumps({"passed": True, "corrected_catalog_sha256": hashed, "changed_candidates": 11,
                      "candidate_execution_performed": False, "private_catalog_written": not args.verify_only}, sort_keys=True))
