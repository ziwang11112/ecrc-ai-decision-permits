"""Source-view regressions using toy manifests; no study execution."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "source_view_under_test", Path(__file__).resolve().parents[1] / "verify_source_view.py")
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)

# Deliberately independent of the verifier's group/base mapping.
INVENTORIES = [
    ("iasc/SOURCE_MIRROR_MANIFEST.json", "iasc"),
    ("iasc/statistics/PACKAGE_MANIFEST.json", "iasc/statistics"),
    ("iasc/presentation_revision/GIT_MIRROR.json", "iasc/presentation_revision"),
    ("iasc_model_check/PUBLIC_MANIFEST.json", "iasc_model_check"),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SourceViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="source-view-test-", dir=os.environ.get("ECRC_TEST_TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repository"
        self.root.mkdir()
        self.view = {"historical_inventories": []}
        for manifest_name, base in INVENTORIES:
            historical, mapped = [], []
            for filename, status in [("kept.txt", "included"), ("changed.txt", "overlay"),
                                     ("removed.txt", "omitted")]:
                original = (base + "/" + filename + ": original").encode()
                row = {"path": filename, "sha256": sha(original)}
                if not manifest_name.endswith("GIT_MIRROR.json"):
                    row["bytes"] = len(original)
                historical.append(row)
                entry = {"path": base + "/" + filename,
                         "historical_sha256": sha(original), "status": status}
                if status != "omitted":
                    current = original if status == "included" else original + b"; overlay"
                    path = self.root / entry["path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(current)
                    if status == "overlay":
                        entry["current_sha256"] = sha(current)
                mapped.append(entry)
            manifest = self.root / manifest_name
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"files": historical}), encoding="utf-8")
            self.view["historical_inventories"].append({
                "manifest": manifest_name, "manifest_sha256": sha(manifest.read_bytes()),
                "files": mapped})
        self.save_view(self.view)

    def save_view(self, view):
        (self.root / "SOURCE_VIEW.json").write_text(json.dumps(view), encoding="utf-8")

    def reject_view(self, mutate, message):
        view = copy.deepcopy(self.view)
        mutate(view)
        self.save_view(view)
        with self.assertRaisesRegex(ValueError, message):
            verifier.verify(self.root)

    def change_historical(self, mutate):
        view = copy.deepcopy(self.view)
        group = view["historical_inventories"][0]
        path = self.root / group["manifest"]
        manifest = json.loads(path.read_text())
        mutate(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        group["manifest_sha256"] = sha(path.read_bytes())
        self.save_view(view)

    def test_valid_four_manifests_all_statuses_and_formats(self):
        before = {p.relative_to(self.root): sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        result = verifier.verify(self.root)
        self.assertIs(result["passed"], True)
        self.assertEqual(result["inventory_entries"], {"included": 4, "overlay": 4, "omitted": 4})
        self.assertEqual(before, {p.relative_to(self.root): sha(p.read_bytes())
                                  for p in self.root.rglob("*") if p.is_file()})

    def test_order_does_not_define_mapping_identity(self):
        view = copy.deepcopy(self.view)
        view["historical_inventories"].reverse()
        for group in view["historical_inventories"]:
            group["files"].reverse()
        self.save_view(view)
        self.assertTrue(verifier.verify(self.root)["passed"])

    def test_missing_included_or_omitted_mapping_is_rejected(self):
        for index in (0, 2):
            with self.subTest(index=index):
                self.reject_view(lambda v: v["historical_inventories"][0]["files"].pop(index), "coverage mismatch")

    def test_missing_and_empty_inventory_groups_are_rejected(self):
        self.reject_view(lambda v: v["historical_inventories"].pop(), "four known manifests")
        self.reject_view(lambda v: v.update(historical_inventories=[]), "four known manifests")

    def test_unknown_and_duplicate_groups_are_rejected(self):
        self.reject_view(lambda v: v["historical_inventories"][0].update(manifest="other/MANIFEST.json"), "four known manifests")
        self.reject_view(lambda v: v["historical_inventories"].append(copy.deepcopy(v["historical_inventories"][0])), "Duplicate historical inventory")

    def test_original_hash_binding_is_required_for_every_status(self):
        for index in range(3):
            with self.subTest(index=index):
                self.reject_view(lambda v: v["historical_inventories"][0]["files"][index].update(historical_sha256="0" * 64), "Historical hash binding mismatch")

    def test_status_typos_and_non_strings_are_rejected(self):
        for status in ("include_typo", "", None, [], 1):
            with self.subTest(status=status):
                self.reject_view(lambda v: v["historical_inventories"][0]["files"][0].update(status=status), "Unknown source-view status")

    def test_included_cannot_override_changed_file_digest(self):
        row = self.view["historical_inventories"][0]["files"][0]
        (self.root / row["path"]).write_bytes(b"changed")
        self.reject_view(lambda v: v["historical_inventories"][0]["files"][0].update(current_sha256=sha(b"changed")), "Only overlays")

    def test_omitted_cannot_declare_current_digest(self):
        self.reject_view(lambda v: v["historical_inventories"][0]["files"][2].update(current_sha256="0" * 64), "Only overlays")

    def test_overlay_requires_valid_current_digest(self):
        self.reject_view(lambda v: v["historical_inventories"][0]["files"][1].pop("current_sha256"), "Invalid SHA-256")
        for value in (None, "", "a" * 63, "A" * 64, "g" * 64, 1):
            with self.subTest(value=value):
                self.reject_view(lambda v: v["historical_inventories"][0]["files"][1].update(current_sha256=value), "Invalid SHA-256")

    def test_duplicate_and_case_colliding_mapping_paths_are_rejected(self):
        for case_change in (False, True):
            def mutate(view):
                row = copy.deepcopy(view["historical_inventories"][0]["files"][0])
                if case_change:
                    row["path"] = row["path"].upper()
                view["historical_inventories"][0]["files"].append(row)
            with self.subTest(case_change=case_change):
                self.reject_view(mutate, "Duplicate or case-colliding mapping")

    def test_historical_duplicate_rows_are_rejected_even_with_matching_manifest_hash(self):
        self.change_historical(lambda m: m["files"].append(copy.deepcopy(m["files"][0])))
        with self.assertRaisesRegex(ValueError, "Duplicate or case-colliding historical"):
            verifier.verify(self.root)

    def test_wrong_mapping_base_is_rejected(self):
        self.reject_view(lambda v: v["historical_inventories"][0]["files"][0].update(path="other/kept.txt"), "coverage mismatch")

    def test_unsafe_or_noncanonical_mapping_paths_are_rejected(self):
        for path in ("../outside", "/absolute", "C:/drive", "C:relative", r"\\host\share\file",
                     r"iasc\kept.txt", "iasc/../kept.txt", "iasc//kept.txt", "./iasc/kept.txt",
                     "iasc/kept.txt/", ".", "", "iasc/NUL", "iasc/file.", "iasc/file ", "iasc/\x00file"):
            with self.subTest(path=path):
                self.reject_view(lambda v: v["historical_inventories"][0]["files"][0].update(path=path), "relative path")

    def test_unsafe_manifest_group_path_is_rejected(self):
        self.reject_view(lambda v: v["historical_inventories"][0].update(manifest="../MANIFEST.json"), "relative path")

    def test_unsafe_historical_member_is_rejected_even_with_matching_manifest_hash(self):
        self.change_historical(lambda m: m["files"][0].update(path="../outside"))
        with self.assertRaisesRegex(ValueError, "relative path"):
            verifier.verify(self.root)

    def test_symlink_escape_is_rejected(self):
        row = self.view["historical_inventories"][0]["files"][0]
        path = self.root / row["path"]
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symlink creation is unavailable: " + str(error))
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            verifier.verify(self.root)

    def test_historical_manifest_hash_mismatch_is_rejected(self):
        self.reject_view(lambda v: v["historical_inventories"][0].update(manifest_sha256="0" * 64), "Historical manifest changed")

    def test_missing_or_changed_selected_file_is_rejected(self):
        path = self.root / self.view["historical_inventories"][0]["files"][0]["path"]
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Selected source mismatch"):
            verifier.verify(self.root)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Selected source mismatch"):
            verifier.verify(self.root)

    def test_present_omitted_file_is_rejected(self):
        path = self.root / self.view["historical_inventories"][0]["files"][2]["path"]
        path.write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "Excluded file remains present"):
            verifier.verify(self.root)

    def test_malformed_mapping_container_is_rejected(self):
        for value in (None, {}, ["not an object"]):
            with self.subTest(value=value):
                self.reject_view(lambda v: v["historical_inventories"][0].update(files=value), "list of objects")


if __name__ == "__main__":
    unittest.main()
