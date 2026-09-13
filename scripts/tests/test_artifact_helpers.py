"""Standard-library artifact-helper tests; toy archives, no study execution."""
from contextlib import redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1]


def load_helper(name):
    spec = importlib.util.spec_from_file_location("artifact_test_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


download = load_helper("download_artifact")
wrapper = load_helper("run_wrapper_qa")


class ArtifactHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="artifact-helper-test-", dir=os.environ.get("ECRC_TEST_TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0

    def make_archive(self, files=None, *, prefix="", manifest_list=False, rows=None, extra=(), symlink=None):
        self.counter += 1
        archive = self.root / ("toy-" + str(self.counter) + ".zip")
        files = {"a.txt": b"alpha", "nested/b.bin": b"\x00\x01\xfe"} if files is None else files
        if rows is None:
            rows = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    for name, data in files.items()]
        document = rows if manifest_list else {"files": rows}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # Deliberately duplicated ZIP name in one negative case.
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for name, data in files.items():
                    if name == symlink:
                        member = zipfile.ZipInfo(prefix + name)
                        member.create_system = 3
                        member.external_attr = (stat.S_IFLNK | 0o777) << 16
                        output.writestr(member, data)
                    else:
                        output.writestr(prefix + name, data)
                for name, data in extra:
                    output.writestr(prefix + name, data)
                output.writestr(prefix + "MANIFEST.json", json.dumps(document).encode("utf-8"))
        with zipfile.ZipFile(archive) as saved:
            members = len(saved.infolist())
        record = {"bytes": archive.stat().st_size, "sha256": download.sha256(archive),
                  "members": members, "prefix": prefix, "manifest": "MANIFEST.json"}
        return archive, record

    def assert_rejected_before_output(self, archive, record):
        destination = self.root / ("extract-" + str(self.counter))
        with self.assertRaises(ValueError):
            download.extract_verified(archive, record, destination)
        self.assertFalse(destination.exists(), "Invalid archive must not create an output directory")

    def test_valid_archive_extracts_exact_members(self):
        archive, record = self.make_archive()
        destination = self.root / "valid"
        self.assertEqual(download.extract_verified(archive, record, destination), destination)
        self.assertEqual((destination / "a.txt").read_bytes(), b"alpha")
        self.assertEqual((destination / "nested/b.bin").read_bytes(), b"\x00\x01\xfe")
        self.assertEqual({p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()},
                         {"a.txt", "nested/b.bin", "MANIFEST.json"})

    def test_prefixed_list_manifest_extracts_to_reported_bundle(self):
        archive, record = self.make_archive(prefix="Bundle/", manifest_list=True)
        destination = self.root / "prefixed"
        bundle = download.extract_verified(archive, record, destination)
        self.assertEqual(bundle, destination / "Bundle")
        self.assertEqual((bundle / "a.txt").read_bytes(), b"alpha")

    def test_deep_output_extracts_and_refuses_existing_destination_unchanged(self):
        archive, record = self.make_archive(prefix="Bundle/")
        deep_root = (self.root / "deep-output").resolve()
        destination = deep_root.joinpath(*("segment-" + str(i) + "-" + "x" * 64 for i in range(4)))
        self.assertGreater(len(str(destination / "Bundle/nested/b.bin")), 320)

        # Independent test I/O: do not validate io_path by calling itself.
        def disk_path(path):
            absolute = str(path.resolve())
            if os.name != "nt":
                return Path(absolute)
            return Path("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute)

        def cleanup_deep_tree():
            self.assertTrue(deep_root.is_relative_to(self.root.resolve()))
            self.assertNotEqual(deep_root, self.root.resolve())
            if disk_path(deep_root).exists():
                shutil.rmtree(disk_path(deep_root))

        self.addCleanup(cleanup_deep_tree)
        bundle = download.extract_verified(archive, record, destination)
        self.assertEqual(bundle, destination / "Bundle")
        self.assertEqual(disk_path(bundle / "a.txt").read_bytes(), b"alpha")
        self.assertEqual(disk_path(bundle / "nested/b.bin").read_bytes(), b"\x00\x01\xfe")
        sentinel = bundle / "keep.txt"
        disk_path(sentinel).write_bytes(b"preserve existing output")

        def inventory():
            base = disk_path(destination)
            return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in base.rglob("*") if p.is_file()}

        before = inventory()
        self.assertEqual(set(before), {"Bundle/a.txt", "Bundle/nested/b.bin", "Bundle/MANIFEST.json", "Bundle/keep.txt"})
        with self.assertRaises(FileExistsError):
            download.extract_verified(archive, record, destination)
        (self.root / "ARTIFACTS.json").write_text(json.dumps({"artifacts": {"toy": record}}), encoding="utf-8")
        with mock.patch.object(download, "ROOT", self.root), mock.patch.object(sys, "argv", ["download_artifact.py", "toy", "--output", str(destination)]), mock.patch.object(download.urllib.request, "urlopen") as network, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                download.main()
        self.assertEqual(raised.exception.code, 2)
        network.assert_not_called()
        self.assertEqual(inventory(), before)

    def test_rejects_outer_hash_mismatch(self):
        archive, record = self.make_archive()
        record["sha256"] = "0" * 64
        self.assert_rejected_before_output(archive, record)

    def test_rejects_outer_size_mismatch(self):
        archive, record = self.make_archive()
        record["bytes"] += 1
        self.assert_rejected_before_output(archive, record)

    def test_rejects_member_hash_mismatch_despite_valid_outer_hash(self):
        rows = [{"path": "a.txt", "bytes": 5, "sha256": "0" * 64}]
        archive, record = self.make_archive(files={"a.txt": b"alpha"}, rows=rows)
        self.assert_rejected_before_output(archive, record)

    def test_rejects_member_size_mismatch_despite_valid_outer_hash(self):
        rows = [{"path": "a.txt", "bytes": 99, "sha256": hashlib.sha256(b"alpha").hexdigest()}]
        archive, record = self.make_archive(files={"a.txt": b"alpha"}, rows=rows)
        self.assert_rejected_before_output(archive, record)

    def test_rejects_wrong_member_count(self):
        archive, record = self.make_archive()
        record["members"] += 1
        self.assert_rejected_before_output(archive, record)

    def test_rejects_unmanifested_extra_member(self):
        archive, record = self.make_archive(extra=(("extra.txt", b"unexpected"),))
        self.assert_rejected_before_output(archive, record)

    def test_rejects_missing_manifest_member(self):
        rows = [{"path": "missing.txt", "bytes": 5, "sha256": hashlib.sha256(b"alpha").hexdigest()}]
        archive, record = self.make_archive(files={"a.txt": b"alpha"}, rows=rows)
        self.assert_rejected_before_output(archive, record)

    def test_rejects_duplicate_manifest_rows(self):
        row = {"path": "a.txt", "bytes": 5, "sha256": hashlib.sha256(b"alpha").hexdigest()}
        archive, record = self.make_archive(files={"a.txt": b"alpha"}, rows=[row, dict(row)])
        self.assert_rejected_before_output(archive, record)

    def test_rejects_duplicate_zip_paths(self):
        archive, record = self.make_archive(extra=(("a.txt", b"alpha"),))
        self.assert_rejected_before_output(archive, record)

    def test_rejects_case_colliding_zip_paths(self):
        archive, record = self.make_archive(files={"same.txt": b"a", "SAME.txt": b"b"})
        self.assert_rejected_before_output(archive, record)

    def test_rejects_symlink_member(self):
        archive, record = self.make_archive(files={"link": b"../outside"}, symlink="link")
        self.assert_rejected_before_output(archive, record)

    def test_rejects_unsafe_member_paths_on_every_platform(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/drive.txt", "C:relative.txt",
                     "//server/share/file", r"\\server\share\file", r"nested\file.txt",
                     "nested/../file.txt", "./file.txt", "nested//file.txt", "folder/", "."):
            with self.subTest(name=name):
                archive, record = self.make_archive(files={name: b"payload"})
                self.assert_rejected_before_output(archive, record)

    def test_safe_relative_rejects_empty_path(self):
        with self.assertRaises(ValueError):
            download.safe_relative("")

    def test_rejects_windows_reserved_and_ambiguous_component_names(self):
        for name in ("CON", "nul.txt", "nested/AUX.log", "COM1", "LPT9.txt",
                     "nested/file.", "nested/file ", "folder./file.txt", "folder /file.txt"):
            with self.subTest(name=name):
                archive, record = self.make_archive(files={name: b"payload"})
                self.assert_rejected_before_output(archive, record)

    def test_rejects_file_used_as_parent_directory_including_case_collision(self):
        for files in ({"node": b"file", "node/child.txt": b"child"},
                      {"NODE": b"file", "node/child.txt": b"child"}):
            with self.subTest(paths=list(files)):
                archive, record = self.make_archive(files=files)
                self.assert_rejected_before_output(archive, record)

    def test_accepts_ordinary_nested_relative_path(self):
        self.assertEqual(download.safe_relative("nested/file.txt"), ("nested", "file.txt"))

    def test_extraction_refuses_existing_directory_without_changing_contents(self):
        archive, record = self.make_archive()
        destination = self.root / "existing"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            download.extract_verified(archive, record, destination)
        self.assertEqual(sentinel.read_bytes(), b"preserve")
        self.assertEqual(list(destination.iterdir()), [sentinel])

    def test_extraction_refuses_existing_file_without_changing_bytes(self):
        archive, record = self.make_archive()
        destination = self.root / "existing-file"
        destination.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            download.extract_verified(archive, record, destination)
        self.assertEqual(destination.read_bytes(), b"preserve")

    def test_download_cli_refuses_existing_output_before_network(self):
        (self.root / "ARTIFACTS.json").write_text(json.dumps({"artifacts": {"toy": {}}}), encoding="utf-8")
        destination = self.root / "existing"
        destination.mkdir()
        with mock.patch.object(download, "ROOT", self.root), mock.patch.object(sys, "argv", ["download_artifact.py", "toy", "--output", str(destination)]), mock.patch.object(download.urllib.request, "urlopen") as network, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                download.main()
        self.assertEqual(raised.exception.code, 2)
        network.assert_not_called()

    def test_wrapper_refuses_existing_output_before_copy_or_child(self):
        destination = self.root / "existing"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_bytes(b"preserve")
        with mock.patch.object(sys, "argv", ["run_wrapper_qa.py", "--output", str(destination)]), mock.patch.object(wrapper.shutil, "copyfile") as copy, mock.patch.object(wrapper.subprocess, "run") as child, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                wrapper.main()
        self.assertEqual(raised.exception.code, 2)
        copy.assert_not_called()
        child.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_wrapper_refuses_output_inside_source_mirror(self):
        destination = self.root / "iasc" / "new-output"
        with mock.patch.object(wrapper, "ROOT", self.root), mock.patch.object(sys, "argv", ["run_wrapper_qa.py", "--output", str(destination)]), mock.patch.object(wrapper.subprocess, "run") as child, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                wrapper.main()
        self.assertEqual(raised.exception.code, 2)
        child.assert_not_called()
        self.assertFalse(destination.exists())

    def test_wrapper_rejects_source_hash_mismatch_before_output(self):
        source = self.root / "source"
        source.mkdir()
        (source / "test.py").write_bytes(b"changed source")
        (source / "CODE_FREEZE.json").write_text(json.dumps({"files": {"test.py": "0" * 64}}), encoding="utf-8")
        destination = self.root / "fresh"
        with mock.patch.object(wrapper, "E2E", source), mock.patch.object(sys, "argv", ["run_wrapper_qa.py", "--output", str(destination)]), mock.patch.object(wrapper.subprocess, "run") as child:
            with self.assertRaisesRegex(ValueError, "Frozen source mismatch"):
                wrapper.main()
        child.assert_not_called()
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
