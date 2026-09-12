"""Inventory the complete portable supplement without modifying any inputs/results."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
entries = []
for path in sorted(HERE.rglob("*")):
    if not path.is_file() or "__pycache__" in path.parts or path.name == "PACKAGE_MANIFEST.json":
        continue
    data = path.read_bytes()
    entries.append({"path": path.relative_to(HERE).as_posix(), "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()})
(HERE / "PACKAGE_MANIFEST.json").write_text(json.dumps({"files": entries}, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"files": len(entries), "total_bytes": sum(row["bytes"] for row in entries)}, indent=2))
