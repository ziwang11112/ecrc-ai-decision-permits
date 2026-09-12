"""Hashing, deterministic serialization, and run-manifest helpers."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: str | Path, payload: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def write_csv(path: str | Path, frame: pd.DataFrame) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False, lineterminator="\n")
    return destination


def write_gzip_csv(path: str | Path, frame: pd.DataFrame) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        destination,
        index=False,
        lineterminator="\n",
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
    return destination


def input_hash_table(paths: Iterable[str | Path], *, base: str | Path) -> pd.DataFrame:
    root = Path(base).resolve()
    rows: list[dict[str, object]] = []
    for item in sorted({Path(path).resolve() for path in paths}, key=str):
        try:
            relative = item.relative_to(root)
            display = relative.as_posix()
        except ValueError:
            display = str(item)
        rows.append(
            {
                "path": display,
                "bytes": item.stat().st_size,
                "sha256": sha256_file(item),
            }
        )
    return pd.DataFrame(rows)


def environment_record() -> dict[str, object]:
    packages = {}
    for package in ("numpy", "pandas", "scipy", "scikit-learn", "joblib"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
    }


def git_record(repository_root: str | Path) -> dict[str, object]:
    root = Path(repository_root)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        return {
            "commit": commit,
            "working_tree_dirty": bool(status),
            "status_entry_count": len(status),
        }
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "working_tree_dirty": None, "status_entry_count": None}


def finalize_manifest(
    output_dir: str | Path,
    *,
    manifest_payload: dict[str, object],
    artifact_paths: Iterable[str | Path],
) -> tuple[Path, Path]:
    root = Path(output_dir).resolve()
    artifacts = sorted({Path(path).resolve() for path in artifact_paths}, key=str)
    output_hashes: list[dict[str, object]] = []
    for path in artifacts:
        output_hashes.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        **manifest_payload,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": output_hashes,
    }
    manifest_path = write_json(root / "run_manifest.json", payload)
    checksum_rows = output_hashes + [
        {
            "path": manifest_path.relative_to(root).as_posix(),
            "bytes": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
        }
    ]
    checksum_path = root / "sha256sums.txt"
    checksum_path.write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in checksum_rows),
        encoding="utf-8",
    )
    return manifest_path, checksum_path


def verify_finalized_manifest(output_dir: str | Path) -> None:
    """Fail closed unless every finalized artifact and checksum entry matches."""

    root = Path(output_dir).resolve()
    manifest_path = root / "run_manifest.json"
    checksum_path = root / "sha256sums.txt"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Finalized manifest has no artifact inventory")
    expected: dict[str, tuple[int, str]] = {}
    for record in artifacts:
        if not isinstance(record, dict):
            raise ValueError("Finalized manifest contains a non-object artifact record")
        relative = str(record.get("path", ""))
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError(f"Artifact escapes evidence directory: {relative!r}")
        size = int(record.get("bytes", -1))
        digest = str(record.get("sha256", ""))
        if relative in expected:
            raise ValueError(f"Duplicate artifact record: {relative}")
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError(f"Artifact size verification failed: {relative}")
        if sha256_file(path) != digest:
            raise ValueError(f"Artifact SHA-256 verification failed: {relative}")
        expected[relative] = (size, digest)
    expected["run_manifest.json"] = (
        manifest_path.stat().st_size,
        sha256_file(manifest_path),
    )

    checksum_records: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not relative or relative in checksum_records:
            raise ValueError(f"Invalid or duplicate checksum line: {line!r}")
        checksum_records[relative] = digest
    if set(checksum_records) != set(expected):
        raise ValueError("sha256sums.txt inventory differs from the finalized manifest")
    for relative, (_, digest) in expected.items():
        if checksum_records[relative] != digest:
            raise ValueError(f"sha256sums.txt mismatch: {relative}")


__all__ = [
    "environment_record",
    "finalize_manifest",
    "git_record",
    "input_hash_table",
    "sha256_file",
    "verify_finalized_manifest",
    "write_csv",
    "write_gzip_csv",
    "write_json",
]
