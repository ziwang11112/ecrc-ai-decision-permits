"""Download a pinned study archive, verify every member, then extract fresh output.

Standard library only. This downloads saved evidence; it executes no study code.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath
import argparse
import hashlib
import json
import shutil
import stat
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(name):
    path = PurePosixPath(name)
    if (not name or not path.parts or "\\" in name or ":" in name or path.is_absolute()
            or PureWindowsPath(name).drive or ".." in path.parts
            or str(path) != name or name.endswith("/")
            or any(PureWindowsPath(part).is_reserved() or part.endswith((".", " ")) for part in path.parts)):
        raise ValueError("Unsafe archive member: " + repr(name))
    return path.parts


def extract_verified(archive_path, record, destination):
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("Choose a fresh output directory: " + str(destination))
    if (archive_path.stat().st_size != record["bytes"]
            or sha256(archive_path) != record["sha256"]):
        raise ValueError("Release size/SHA-256 mismatch; nothing extracted")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != record["members"] or len(set(n.casefold() for n in names)) != len(names):
            raise ValueError("Unexpected member count or duplicate archive paths")
        for info in infos:
            safe_relative(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Archive symlinks are not supported")
        normalized = {name.casefold() for name in names}
        for name in names:
            if any(str(parent).casefold() in normalized for parent in PurePosixPath(name).parents):
                raise ValueError("An archive member is also used as a directory")
        if archive.testzip() is not None:
            raise ValueError("Archive CRC failure")
        prefix = record["prefix"]
        manifest_name = prefix + record["manifest"]
        manifest = json.loads(archive.read(manifest_name))
        rows = manifest if isinstance(manifest, list) else manifest["files"]
        expected = {prefix + row["path"] for row in rows} | {manifest_name}
        if len(rows) + 1 != len(expected) or set(names) != expected:
            raise ValueError("Member inventory differs from manifest")
        for row in rows:
            safe_relative(row["path"])
            blob = archive.read(prefix + row["path"])
            if len(blob) != row["bytes"] or hashlib.sha256(blob).hexdigest() != row["sha256"]:
                raise ValueError("Member hash/size mismatch: " + row["path"])
        # No output is created before the entire archive passes verification.
        destination.mkdir(parents=True, exist_ok=False)
        for info in infos:
            target = destination.joinpath(*safe_relative(info.filename))
            if not target.resolve().is_relative_to(destination):
                raise ValueError("Extraction path escaped output directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    return destination / prefix


def main():
    records = json.loads((ROOT / "ARTIFACTS.json").read_text(encoding="utf-8"))["artifacts"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", choices=records)
    parser.add_argument("--output", type=Path, help="Fresh extraction directory; defaults to artifacts/STUDY")
    parser.add_argument("--archive", type=Path, help="Verify an already downloaded ZIP instead of using the network")
    args = parser.parse_args()
    output = args.output or ROOT / "artifacts" / args.study
    if output.exists():
        parser.error("Choose a fresh output directory: " + str(output))
    record = records[args.study]
    with tempfile.TemporaryDirectory(prefix="ecrc-artifact-") as temp:
        archive = args.archive
        if archive is None:
            archive = Path(temp) / record["filename"]
            request = urllib.request.Request(record["url"], headers={"User-Agent": "ECRC-public-artifact"})
            with urllib.request.urlopen(request, timeout=60) as response, archive.open("xb") as target:
                shutil.copyfileobj(response, target)
        bundle = extract_verified(archive, record, output)
    print(json.dumps({"status": "PASS", "study": args.study, "tag": record["tag"],
                      "sha256": record["sha256"], "verified_members": record["members"],
                      "bundle": str(bundle)}, indent=2))


if __name__ == "__main__":
    main()
