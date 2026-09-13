"""Check the shipped package's declared byte inventory without executing experiments."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
manifest = json.loads((ROOT / 'FILE_MANIFEST.json').read_text(encoding='utf-8'))
expected = {row['path']: row for row in manifest['files']}
actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob('*')
          if path.is_file() and path.name != 'FILE_MANIFEST.json'}
assert actual == set(expected), {'missing': sorted(set(expected) - actual),
                                 'extra': sorted(actual - set(expected))}
for name, row in expected.items():
    data = (ROOT / name).read_bytes()
    assert len(data) == row['bytes'], name
    assert hashlib.sha256(data).hexdigest() == row['sha256'], name
print(json.dumps({'passed': True, 'verified_files': len(expected),
                  'scope': 'Shipped file bytes, not new scientific execution.'}))
