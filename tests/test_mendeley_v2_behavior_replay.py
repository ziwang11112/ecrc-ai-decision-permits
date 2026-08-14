from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts import download_mendeley_v2_igt as downloader

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1] / "icair_2026" / "framework_v1"
sys.path.insert(0, str(FRAMEWORK_ROOT))

from e1.data import load_mendeley_behavior  # noqa: E402
from e1.provenance import (  # noqa: E402
    finalize_manifest,
    verify_finalized_manifest,
)


def _folders() -> list[dict[str, str]]:
    return [
        {
            "id": f"00000000-0000-0000-0000-{index:012x}",
            "name": f"s-{index:02d}",
            "created_date": "2026-01-01T00:00:00",
        }
        for index in range(1, 60)
    ]


def test_downloader_inventory_is_exact_and_igt_only() -> None:
    inventory = downloader._validate_inventory(list(reversed(_folders())))
    assert [folder["name"] for folder in inventory] == list(
        downloader.EXPECTED_FOLDERS
    )
    files = [
        {"filename": "EEG.csv"},
        {
            "filename": "IGT.csv",
            "id": "11111111-1111-1111-1111-111111111111",
            "folder_id": inventory[0]["id"],
            "size": 100,
            "status": "COMPLETED",
            "last_modified_date": "2026-01-01T00:00:00Z",
            "content_details": {
                "id": "22222222-2222-2222-2222-222222222222",
                "sha256_hash": "a" * 64,
                "size": 100,
                "content_type": "text/csv",
                "download_url": (
                    "https://data.mendeley.com/public-files/datasets/2pw2m39yct/"
                    "files/11111111-1111-1111-1111-111111111111/file_downloaded"
                ),
            },
        },
        {"filename": "processed_EEG.csv"},
    ]
    selected = downloader._select_igt_record(
        files, folder_name="s-01", folder_id=inventory[0]["id"]
    )
    assert selected["expected_size"] == 100
    with pytest.raises(ValueError, match="s-01..s-59"):
        downloader._validate_inventory(_folders()[:-1])
    with pytest.raises(ValueError, match="overlaps"):
        downloader._validate_target_root(downloader.LEGACY_V1_ROOT / "v2")


def _behavior_payload() -> bytes:
    rows = ["iteration,EEG sample,decision,win,lose,balance"]
    for trial in range(1, 201):
        choice = "ABCD"[(trial - 1) % 4]
        rows.append(f"{trial},{trial * 10},{choice},100,0,{2000 + trial * 100}")
    return ("\n".join(rows) + "\n").encode()


def test_official_v2_loader_requires_and_verifies_all_59_checksums(
    tmp_path: Path,
) -> None:
    root = tmp_path / "mendeley_igt_v2_behavior_only"
    behavior_dir = root / "IGT"
    metadata_dir = root / "metadata"
    behavior_dir.mkdir(parents=True)
    metadata_dir.mkdir()
    payload = _behavior_payload()
    digest = hashlib.sha256(payload).hexdigest()
    records = []
    for index in range(1, 60):
        path = behavior_dir / f"IGT_P{index:02d}.csv"
        path.write_bytes(payload)
        records.append(
            {
                "source_folder": f"s-{index:02d}",
                "source_filename": "IGT.csv",
                "destination": f"IGT/{path.name}",
                "expected_size": len(payload),
                "expected_sha256": digest,
            }
        )
    manifest_path = metadata_dir / "download_manifest_v2_igt_only.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_id": "2pw2m39yct",
                "version": 2,
                "doi": "10.17632/2pw2m39yct.2",
                "license": "CC BY 4.0",
                "source_url": "https://data.mendeley.com/datasets/2pw2m39yct/2",
                "download_policy": {
                    "allowed_source_filename": "IGT.csv",
                    "eeg_download_urls_requested": 0,
                    "eeg_files_downloaded": 0,
                    "processed_eeg_files_downloaded": 0,
                },
                "files": records,
            }
        ),
        encoding="utf-8",
    )
    frame, version = load_mendeley_behavior(
        behavior_dir, local_manifest=manifest_path
    )
    assert len(frame) == 11_800
    assert frame["dataset_id"].unique().tolist() == ["mendeley_igt_official_v2"]
    assert version["manifest_verification"]["n_files_verified"] == 59
    assert version["eeg_files_read"] == 0
    (behavior_dir / "IGT_P59.csv").write_text("corrupted\n", encoding="utf-8")
    with pytest.raises(ValueError, match="size differs"):
        load_mendeley_behavior(behavior_dir, local_manifest=manifest_path)


def test_finalized_evidence_checksum_gate_detects_mutation(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("frozen evidence\n", encoding="utf-8")
    finalize_manifest(
        tmp_path,
        manifest_payload={"experiment": "test"},
        artifact_paths=[artifact],
    )
    verify_finalized_manifest(tmp_path)
    artifact.write_text("mutated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="size verification failed"):
        verify_finalized_manifest(tmp_path)
