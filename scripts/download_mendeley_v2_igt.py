#!/usr/bin/env python3
"""Download only the 59 official Mendeley v2 IGT behavior CSV files.

The downloader has an exact filename allowlist (``IGT.csv``), a one MiB file
size ceiling, and a fixed 59-folder inventory.  It never requests an EEG or
processed_EEG download URL.  Every payload is checked against the size and
SHA-256 published by the Mendeley public API before it is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

DATASET_ID = "2pw2m39yct"
VERSION = 2
DOI = "10.17632/2pw2m39yct.2"
LICENSE = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
DATASET_URL = f"https://data.mendeley.com/datasets/{DATASET_ID}/{VERSION}"
API_BASE = "https://data.mendeley.com/public-api"
FOLDERS_API_URL = f"{API_BASE}/datasets/{DATASET_ID}/folders/{VERSION}"
FILES_API_BASE = f"{API_BASE}/datasets/{DATASET_ID}/files"
EXPECTED_FOLDERS = tuple(f"s-{index:02d}" for index in range(1, 60))
EXPECTED_HEADER = ("iteration", "EEG sample", "decision", "win", "lose", "balance")
MAX_BEHAVIOR_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parents[2]
DEFAULT_TARGET_ROOT = (
    WORKSPACE_ROOT / "data" / "raw" / "external" / "mendeley_igt_v2_behavior_only"
)
LEGACY_V1_ROOT = WORKSPACE_ROOT / "data" / "raw" / "igt_eeg"


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/json, text/csv;q=0.9, */*;q=0.1",
            "User-Agent": "ecrc-ai-decision-permits-mendeley-v2-igt/1.0",
        },
    )


def _read_json(url: str) -> Any:
    with urlopen(_request(url), timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _folder_files_url(folder_id: str) -> str:
    query = urlencode({"folder_id": folder_id, "version": VERSION})
    return f"{FILES_API_BASE}?{query}"


def _validate_download_url(url: str, file_id: str) -> None:
    parsed = urlparse(url)
    expected_path = f"/public-files/datasets/{DATASET_ID}/files/{file_id}/file_downloaded"
    if parsed.scheme != "https" or parsed.netloc != "data.mendeley.com":
        raise ValueError(f"Refusing non-Mendeley download URL: {url}")
    if parsed.path != expected_path or parsed.query or parsed.fragment:
        raise ValueError(f"Unexpected Mendeley download path for file {file_id}: {url}")


def _validate_target_root(target_root: Path) -> Path:
    target = target_root.resolve()
    legacy = LEGACY_V1_ROOT.resolve()
    if target == legacy or target.is_relative_to(legacy) or legacy.is_relative_to(target):
        raise ValueError(
            f"Refusing target that overlaps the version-1 tree: {target} versus {legacy}"
        )
    return target


def _validate_inventory(folders: Any) -> list[dict[str, str]]:
    if not isinstance(folders, list):
        raise ValueError("Mendeley folders response is not a list")
    normalized: list[dict[str, str]] = []
    for folder in folders:
        if not isinstance(folder, dict):
            raise ValueError("Mendeley folder record is not an object")
        folder_id = str(folder.get("id", ""))
        name = str(folder.get("name", ""))
        if not folder_id or not re.fullmatch(r"[0-9a-f-]{36}", folder_id):
            raise ValueError(f"Invalid folder id for {name!r}: {folder_id!r}")
        normalized.append(
            {
                "id": folder_id,
                "name": name,
                "created_date": str(folder.get("created_date", "")),
            }
        )
    names = [folder["name"] for folder in normalized]
    ids = [folder["id"] for folder in normalized]
    if len(names) != len(set(names)) or len(ids) != len(set(ids)):
        raise ValueError("Duplicate folder name or id in Mendeley inventory")
    if set(names) != set(EXPECTED_FOLDERS) or len(names) != len(EXPECTED_FOLDERS):
        missing = sorted(set(EXPECTED_FOLDERS) - set(names))
        extra = sorted(set(names) - set(EXPECTED_FOLDERS))
        raise ValueError(f"Expected exactly s-01..s-59; missing={missing}, extra={extra}")
    return sorted(normalized, key=lambda folder: folder["name"])


def _select_igt_record(files: Any, *, folder_name: str, folder_id: str) -> dict[str, Any]:
    if not isinstance(files, list):
        raise ValueError(f"{folder_name}: files response is not a list")
    selected = [item for item in files if item.get("filename") == "IGT.csv"]
    if len(selected) != 1:
        raise ValueError(f"{folder_name}: expected exactly one IGT.csv, found {len(selected)}")
    item = selected[0]
    details = item.get("content_details")
    if not isinstance(details, dict):
        raise ValueError(f"{folder_name}: IGT.csv lacks content_details")
    file_id = str(item.get("id", ""))
    item_folder_id = str(item.get("folder_id", ""))
    expected_size = int(details.get("size", -1))
    outer_size = int(item.get("size", -2))
    expected_sha256 = str(details.get("sha256_hash", "")).lower()
    download_url = str(details.get("download_url", ""))
    if item_folder_id != folder_id:
        raise ValueError(f"{folder_name}: folder id mismatch")
    if item.get("status") != "COMPLETED":
        raise ValueError(f"{folder_name}: IGT.csv is not COMPLETED")
    if expected_size != outer_size or not 0 < expected_size <= MAX_BEHAVIOR_BYTES:
        raise ValueError(f"{folder_name}: unsafe or inconsistent IGT.csv size {expected_size}")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError(f"{folder_name}: invalid API SHA-256")
    if not re.fullmatch(r"[0-9a-f-]{36}", file_id):
        raise ValueError(f"{folder_name}: invalid file id")
    _validate_download_url(download_url, file_id)
    return {
        "file_id": file_id,
        "content_id": str(details.get("id", "")),
        "expected_size": expected_size,
        "expected_sha256": expected_sha256,
        "download_url": download_url,
        "content_type": str(details.get("content_type", "")),
        "created_date": str(details.get("created_date", "")),
        "last_modified_date": str(item.get("last_modified_date", "")),
    }


def _download_verified(record: dict[str, Any], destination: Path) -> tuple[str, bytes]:
    expected_size = int(record["expected_size"])
    expected_sha256 = str(record["expected_sha256"])
    if destination.exists():
        actual_size = destination.stat().st_size
        actual_sha256 = _sha256_file(destination)
        if actual_size != expected_size or actual_sha256 != expected_sha256:
            raise FileExistsError(
                f"Refusing to overwrite mismatched existing file: {destination}"
            )
        return "verified_existing", destination.read_bytes()

    with urlopen(
        _request(str(record["download_url"])), timeout=REQUEST_TIMEOUT_SECONDS
    ) as response:
        payload = response.read(expected_size + 1)
    actual_size = len(payload)
    actual_sha256 = _sha256_bytes(payload)
    if actual_size != expected_size:
        raise ValueError(
            f"{destination.name}: API size={expected_size}, download size={actual_size}"
        )
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"{destination.name}: API SHA-256={expected_sha256}, "
            f"download SHA-256={actual_sha256}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if destination.stat().st_size != expected_size:
            raise
        if _sha256_file(destination) != expected_sha256:
            raise
        return "verified_existing_after_race", destination.read_bytes()
    return "downloaded_verified", payload


def _inspect_csv(payload: bytes, *, filename: str) -> dict[str, Any]:
    text = payload.decode("utf-8-sig")
    reader = csv.reader(text.splitlines())
    try:
        header = tuple(next(reader))
    except StopIteration as error:
        raise ValueError(f"{filename}: empty CSV") from error
    if header != EXPECTED_HEADER:
        raise ValueError(f"{filename}: unexpected schema {header!r}")
    rows = list(reader)
    if len(rows) != 200 or any(len(row) != len(header) for row in rows):
        raise ValueError(f"{filename}: expected exactly 200 six-column rows")
    return {"header": list(header), "n_rows": len(rows)}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def download(target_root: Path) -> Path:
    target = _validate_target_root(target_root)
    folders = _validate_inventory(_read_json(FOLDERS_API_URL))
    behavior_dir = target / "IGT"
    manifest_path = target / "metadata" / "download_manifest_v2_igt_only.json"
    file_records: list[dict[str, Any]] = []

    for folder in folders:
        folder_name = folder["name"]
        folder_id = folder["id"]
        files_api_url = _folder_files_url(folder_id)
        selected = _select_igt_record(
            _read_json(files_api_url), folder_name=folder_name, folder_id=folder_id
        )
        participant_number = int(folder_name.removeprefix("s-"))
        destination = behavior_dir / f"IGT_P{participant_number:02d}.csv"
        status, payload = _download_verified(selected, destination)
        csv_record = _inspect_csv(payload, filename=destination.name)
        relative_destination = destination.relative_to(target).as_posix()
        file_records.append(
            {
                "source_folder": folder_name,
                "folder_id": folder_id,
                "folder_created_date": folder["created_date"],
                "source_filename": "IGT.csv",
                "file_id": selected["file_id"],
                "content_id": selected["content_id"],
                "files_api_url": files_api_url,
                "download_url": selected["download_url"],
                "destination": relative_destination,
                "expected_size": selected["expected_size"],
                "actual_size": len(payload),
                "expected_sha256": selected["expected_sha256"],
                "actual_sha256": _sha256_bytes(payload),
                "content_type": selected["content_type"],
                "created_date": selected["created_date"],
                "last_modified_date": selected["last_modified_date"],
                "csv_header": csv_record["header"],
                "n_rows": csv_record["n_rows"],
                "status": status,
            }
        )
        print(f"{folder_name}: {status} -> {relative_destination}", flush=True)

    names = {record["source_folder"] for record in file_records}
    if len(file_records) != 59 or names != set(EXPECTED_FOLDERS):
        raise AssertionError("Downloaded inventory is not exactly 59 IGT files")
    manifest = {
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "doi": DOI,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "source_url": DATASET_URL,
        "folders_api_url": FOLDERS_API_URL,
        "root_files_api_url": (
            f"{FILES_API_BASE}?{urlencode({'folder_id': 'root', 'version': VERSION})}"
        ),
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_root": str(target),
        "download_policy": {
            "allowed_source_filename": "IGT.csv",
            "expected_folders": "s-01..s-59",
            "maximum_allowed_file_bytes": MAX_BEHAVIOR_BYTES,
            "eeg_download_urls_requested": 0,
            "eeg_files_downloaded": 0,
            "processed_eeg_files_downloaded": 0,
        },
        "summary": {
            "n_folders": len(folders),
            "n_behavior_files": len(file_records),
            "n_behavior_rows": sum(int(record["n_rows"]) for record in file_records),
            "total_behavior_bytes": sum(
                int(record["actual_size"]) for record in file_records
            ),
            "all_api_sizes_verified": True,
            "all_api_sha256_verified": True,
            "schema": list(EXPECTED_HEADER),
        },
        "files": file_records,
    }
    _write_json_atomic(manifest_path, manifest)
    print(f"manifest: {manifest_path}", flush=True)
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-root",
        type=Path,
        default=DEFAULT_TARGET_ROOT,
        help="Dedicated version-2 behavior-only directory (must not overlap v1).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    download(args.target_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
