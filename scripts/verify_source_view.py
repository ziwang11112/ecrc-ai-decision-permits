"""Verify the current selected source view against explicit historical mappings."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    view = json.loads((ROOT/'SOURCE_VIEW.json').read_text(encoding='utf-8'))
    counts = {}
    for group in view['historical_inventories']:
        path = ROOT/group['manifest']
        if hashlib.sha256(path.read_bytes()).hexdigest() != group['manifest_sha256']:
            raise ValueError('Historical manifest changed: '+group['manifest'])
        for row in group['files']:
            path = ROOT/row['path']
            if not path.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Source-view path escapes repository')
            counts[row['status']] = counts.get(row['status'],0)+1
            if row['status']=='omitted':
                if path.exists():
                    raise ValueError('Excluded file remains present: '+row['path'])
            else:
                expected = row.get('current_sha256',row['historical_sha256'])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                    raise ValueError('Selected source mismatch: '+row['path'])
    print(json.dumps({'passed':True,'inventory_entries':counts,
                      'scope':'Selected source files and explicit omissions; overlapping inventories are not unique-file counts.'},indent=2))


if __name__=='__main__':
    main()
