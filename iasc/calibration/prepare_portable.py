"""Copy existing audit inputs and adapt paths/output plumbing only; source workspace required."""
from pathlib import Path
import csv
import difflib
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ORIGINAL = ROOT / "qa/iasc_pro_review_2026-09-11"
SOURCE = ROOT / "experiment_reproducibility/icair_2026/framework_v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not (HERE / "input").exists() and not (HERE / "archived").exists()
    original_audit = json.loads((ORIGINAL / "calibration_audit.json").read_text())
    old_hashes = {name.replace("\\", "/"): value for name, value in original_audit["input_hashes"].items()}
    rows = []

    def copy(path, target):
        dest = HERE / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        source_rel = path.relative_to(ROOT).as_posix()
        digest = sha(path)
        assert digest == sha(dest)
        recorded = old_hashes.get(source_rel)
        if recorded is not None:
            assert digest == recorded
        rows.append({"path": target, "source_path": source_rel, "bytes": dest.stat().st_size,
                     "sha256": digest, "original_audit_sha256": recorded,
                     "matches_original_audit": digest == recorded if recorded else None})

    for name in ("CALIBRATION_CHECK.md", "calibration_audit.json", "calibration_selected_audit.csv",
                 "calibration_reconstructed_grids.csv", "calibration_grid_summary.csv", "calibration_grid_activity.csv", "check_calibration.py"):
        copy(ORIGINAL / name, "archived/" + name)
    copy(ORIGINAL / "CALIBRATION_CHECK.md", "CALIBRATION_CHECK.md")
    for name in ("predictions.csv.gz", "experiment_config.json", "outer_fold_assignments.csv",
                 "outer_fold_operating_points.csv", "frozen_operating_points.csv", "code_hashes.csv"):
        copy(SOURCE / "evidence_v2" / name, "input/evidence/" + name)
    for name in ("__init__.py", "config.py", "routing.py", "models.py"):
        copy(SOURCE / "e1" / name, "input/source/e1/" + name)
    historic = list(csv.DictReader((SOURCE / "evidence_v2/code_hashes.csv").open(newline="")))
    original_entry = next(row for row in historic if row["path"].endswith("/run_e1.py"))
    current = SOURCE / "run_e1.py"
    provenance = {"source_path": current.relative_to(ROOT).as_posix(), "current_bytes": current.stat().st_size,
                  "current_sha256": sha(current), "historical_bytes": int(original_entry["bytes"]),
                  "historical_sha256": original_entry["sha256"], "matches_historical_manifest": sha(current) == original_entry["sha256"],
                  "copied_or_imported": False, "needed_for_portable_audit": False,
                  "note": "Current entrypoint was only hashed in the original audit; its hash does not match the original E1 manifest. No source equivalence is claimed."}
    (HERE / "input/ENTRYPOINT_PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    manifest = {"purpose": "Portable copy of the original calibration audit, without changing the analysis",
                "files": rows, "original_audit_input_hashes": original_audit["input_hashes"], "entrypoint": provenance}
    (HERE / "input/SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    original = (ORIGINAL / "check_calibration.py").read_text()
    adapted = original.replace("from pathlib import Path\n", "from pathlib import Path\nimport argparse\n", 1)
    adapted = adapted.replace('ROOT = HERE.parents[1]\nSOURCE = ROOT / "experiment_reproducibility/icair_2026/framework_v1"\nEVIDENCE = SOURCE / "evidence_v2"',
                              'ROOT = HERE\nSOURCE = HERE / "input/source"\nEVIDENCE = HERE / "input/evidence"', 1)
    adapted = adapted.replace("def main():\n", "def main(out):\n    out.mkdir(parents=True, exist_ok=False)\n", 1)
    adapted = adapted.replace('SOURCE / "run_e1.py", Path(__file__)',
                              'SOURCE / "e1/__init__.py", HERE / "input/SOURCE_MANIFEST.json", HERE / "input/ENTRYPOINT_PROVENANCE.json", Path(__file__)', 1)
    for name in ("calibration_selected_audit.csv", "calibration_reconstructed_grids.csv", "calibration_grid_summary.csv", "calibration_audit.json"):
        adapted = adapted.replace('HERE / "' + name + '"', 'out / "' + name + '"')
    adapted = adapted.replace('    config_values = json.loads', '''    source_manifest = json.loads((HERE / "input/SOURCE_MANIFEST.json").read_text())
    for entry in source_manifest["files"]:
        assert sha(HERE / entry["path"]) == entry["sha256"]
    config_values = json.loads''', 1)
    adapted = adapted.replace('    (out / "calibration_audit.json").write_text', '''    report["original_audit_input_hashes"] = source_manifest["original_audit_input_hashes"]
    report["portable_input_manifest_sha256"] = sha(HERE / "input/SOURCE_MANIFEST.json")
    report["entrypoint_provenance"] = source_manifest["entrypoint"]
    report["entrypoint_required_or_executed"] = False
    for entry in source_manifest["files"]:
        assert sha(HERE / entry["path"]) == entry["sha256"]
    (out / "calibration_audit.json").write_text''', 1)
    adapted = adapted.replace('if __name__ == "__main__":\n    main()', '''if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    main(args.out.resolve())''', 1)
    assert adapted != original and 'SOURCE / "run_e1.py"' not in adapted
    (HERE / "check_calibration.py").write_text(adapted, encoding="utf-8")
    diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), adapted.splitlines(keepends=True),
                                       fromfile="archived/check_calibration.py", tofile="check_calibration.py"))
    (HERE / "PORTABILITY_ONLY.diff").write_text(diff, encoding="utf-8")
    print(json.dumps({"copied_files": len(rows), "total_copied_bytes": sum(row["bytes"] for row in rows),
                      "entrypoint_matches_historical_manifest": provenance["matches_historical_manifest"]}, indent=2))


if __name__ == "__main__":
    main()
