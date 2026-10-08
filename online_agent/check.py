"""Offline public-package verification; never launch subprocesses or use a network.

Run in a fresh interpreter: python online_agent/check.py
Only inert strings and clearly labelled fabricated runner results are used.
"""
from pathlib import Path
import hashlib
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT))


def main():
    provenance = json.loads((ROOT / 'SOURCE_PROVENANCE.json').read_text(encoding='utf-8'))
    for row in provenance['files']:
        path = (ROOT / row['public_path']).resolve()
        if not path.is_relative_to(ROOT) or path.is_symlink():
            raise ValueError('unsafe public provenance path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['public_sha256']:
            raise ValueError('public source hash mismatch: ' + row['public_path'])
    for path in ROOT.rglob('*.py'):
        compile(path.read_bytes(), str(path), 'exec')
    from schedule import STUDIES, verify_schedule
    for study in STUDIES:
        verify_schedule(study)
    from vendor.adapters import verify_frozen
    verify_frozen()
    suite = unittest.TestSuite()
    for folder in (ROOT / 'runtime/tests', ROOT / 'tests'):
        suite.addTests(unittest.defaultTestLoader.discover(str(folder), top_level_dir=str(folder)))
    # Tripwires make accidental real model transport or sandbox launch fail.
    with patch('subprocess.Popen', side_effect=AssertionError('offline check forbids process launch')), \
         patch('socket.socket.connect', side_effect=AssertionError('offline check forbids networking')), \
         patch('socket.socket.connect_ex', side_effect=AssertionError('offline check forbids networking')):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
