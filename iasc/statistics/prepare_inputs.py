"""Copy the minimum frozen inputs; never modifies original sources."""
from pathlib import Path
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = {
    "online_participant_statistics.csv.gz": "qa/iasc_experiment_extension_2026-09-11/online/out/online_participant_statistics.csv.gz",
    "online_estimates.csv": "qa/iasc_experiment_extension_2026-09-11/online/out/online_estimates.csv",
    "frozen_participant_statistics.csv.gz": "qa/iasc_experiment_extension_2026-09-11/sequence/out/frozen_participant_statistics.csv.gz",
    "a4_permission_grid.csv": "submission_v2/analysis/out/a4_permission_grid.csv",
    "online_PROTOCOL.md": "qa/iasc_experiment_extension_2026-09-11/online/PROTOCOL.md",
    "sequence_PROTOCOL.md": "qa/iasc_experiment_extension_2026-09-11/sequence/PROTOCOL.md",
    "CALIBRATION_CHECK.md": "qa/iasc_pro_review_2026-09-11/CALIBRATION_CHECK.md",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = HERE / "input"
    assert not target.exists(), "Preserve existing copied inputs"
    target.mkdir()
    rows = []
    for name, relative in SOURCES.items():
        original = ROOT / relative
        before = sha(original)
        shutil.copyfile(original, target / name)
        assert sha(original) == sha(target / name) == before
        rows.append({"name": name, "source_relative_path": relative, "sha256": before,
                     "bytes": original.stat().st_size})
    (target / "INPUT_MANIFEST.json").write_text(json.dumps({"inputs": rows}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
