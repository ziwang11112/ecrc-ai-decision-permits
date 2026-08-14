#!/usr/bin/env python3
"""Remove transient bridge databases and rebuild versionable evidence hashes."""

from __future__ import annotations

import json
from pathlib import Path

from e1.provenance import finalize_manifest, write_json

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
OUTPUT_DIR = HERE / "evidence_bridge"
TRANSIENT_NAMES = (
    "runtime_bridge.sqlite",
    "runtime_bridge.sqlite-wal",
    "runtime_bridge.sqlite-shm",
)
VERSIONED_ARTIFACTS = (
    "bridge_decisions.csv.gz",
    "capacity_snapshots.csv",
    "runtime_artifacts.jsonl.gz",
    "policy_manifest.json",
    "runtime_input_contract.json",
    "input_hashes.csv",
    "code_hashes.csv",
    "bridge_summary.json",
    "README.md",
)


def main() -> int:
    summary_path = OUTPUT_DIR / "bridge_summary.json"
    manifest_path = OUTPUT_DIR / "run_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(
            "Bridge summary/manifest must exist before finalization"
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in TRANSIENT_NAMES:
        path = OUTPUT_DIR / name
        if path.exists():
            path.unlink()
    summary["runtime_database_retained"] = False
    summary["transient_sqlite_sidecars_retained"] = False
    write_json(summary_path, summary)
    artifacts = [OUTPUT_DIR / name for name in VERSIONED_ARTIFACTS]
    for path in artifacts:
        if not path.is_file():
            raise FileNotFoundError(path)
    manifest_payload = {
        key: value
        for key, value in prior_manifest.items()
        if key not in {"completed_at_utc", "artifacts"}
    }
    manifest_payload.update(summary)
    finalize_manifest(
        OUTPUT_DIR,
        manifest_payload=manifest_payload,
        artifact_paths=artifacts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
