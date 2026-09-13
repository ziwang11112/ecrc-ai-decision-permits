"""Verify the selected source view against all four historical inventories."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_INVENTORIES = {
    "iasc/SOURCE_MIRROR_MANIFEST.json": "iasc",
    "iasc/statistics/PACKAGE_MANIFEST.json": "iasc/statistics",
    "iasc/presentation_revision/GIT_MIRROR.json": "iasc/presentation_revision",
    "iasc_model_check/PUBLIC_MANIFEST.json": "iasc_model_check",
}
STATUSES = {"included", "omitted", "overlay"}


def relative_path(name):
    """Accept one canonical, portable POSIX relative file path."""
    if not isinstance(name, str):
        raise ValueError("Path must be a string")
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or str(path) != name
            or "\\" in name or ":" in name or ".." in path.parts
            or any(ord(char) < 32 for char in name)
            or any(PureWindowsPath(part).is_reserved() or part.endswith((".", " "))
                   for part in path.parts)):
        raise ValueError("Unsafe or noncanonical relative path: " + repr(name))
    return path


def contained_path(root, name):
    path = root.joinpath(*relative_path(name).parts)
    if not path.resolve().is_relative_to(root):
        raise ValueError("Source-view path escapes repository: " + name)
    return path


def digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid SHA-256 digest: " + repr(value))
    return value


def records(value, label):
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(label + " must be a list of objects")
    return value


def unique_rows(rows, label):
    indexed, folded = {}, set()
    for row in rows:
        name = relative_path(row.get("path")).as_posix()
        if name.casefold() in folded:
            raise ValueError("Duplicate or case-colliding " + label + " path: " + name)
        indexed[name] = row
        folded.add(name.casefold())
    return indexed


def verify(root):
    """Read only; an explicit root supports isolated fixture tests."""
    root = Path(root).resolve()
    view = json.loads(contained_path(root, "SOURCE_VIEW.json").read_text(encoding="utf-8"))
    groups = records(view.get("historical_inventories"), "Historical inventories")
    by_manifest = {}
    for group in groups:
        name = relative_path(group.get("manifest")).as_posix()
        if name in by_manifest:
            raise ValueError("Duplicate historical inventory: " + name)
        by_manifest[name] = group
    if set(by_manifest) != set(HISTORICAL_INVENTORIES):
        raise ValueError("Historical inventory groups must match the four known manifests")

    counts = {}
    for name, base in HISTORICAL_INVENTORIES.items():
        group = by_manifest[name]
        raw = contained_path(root, name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest(group.get("manifest_sha256")):
            raise ValueError("Historical manifest changed: " + name)
        manifest = json.loads(raw)
        historical = unique_rows(records(manifest.get("files"), "Historical files"), "historical")
        expected = {}
        for relative, record in historical.items():
            full_name = (PurePosixPath(base) / relative).as_posix()
            contained_path(root, full_name)
            expected[full_name] = digest(record.get("sha256"))
        mapped = unique_rows(records(group.get("files"), "Mapped files"), "mapping")
        if set(mapped) != set(expected):
            raise ValueError("Historical mapping coverage mismatch: " + name
                             + "; missing=" + repr(sorted(set(expected) - set(mapped)))
                             + "; extra=" + repr(sorted(set(mapped) - set(expected))))

        for relative, original_digest in expected.items():
            row = mapped[relative]
            path = contained_path(root, relative)
            if digest(row.get("historical_sha256")) != original_digest:
                raise ValueError("Historical hash binding mismatch: " + relative)
            status = row.get("status")
            if not isinstance(status, str) or status not in STATUSES:
                raise ValueError("Unknown source-view status: " + repr(status))
            if status == "overlay":
                current_digest = digest(row.get("current_sha256"))
            else:
                if "current_sha256" in row:
                    raise ValueError("Only overlays may declare current_sha256: " + relative)
                current_digest = original_digest
            counts[status] = counts.get(status, 0) + 1
            if status == "omitted":
                if path.exists() or path.is_symlink():
                    raise ValueError("Excluded file remains present: " + relative)
            elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != current_digest:
                raise ValueError("Selected source mismatch: " + relative)
    return {"passed": True, "inventory_entries": counts,
            "scope": "Complete historical mappings, selected source files and explicit omissions; overlapping inventories are not unique-file counts."}


def main():
    print(json.dumps(verify(ROOT), indent=2))


if __name__ == "__main__":
    main()
