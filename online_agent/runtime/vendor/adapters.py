"""Hash-checked loading of unchanged frozen adapters and their small dependencies."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

HERE = Path(__file__).resolve().parent


def verify_frozen():
    manifest = json.loads((HERE / 'FROZEN_MANIFEST.json').read_text(encoding='utf-8'))
    for row in manifest:
        path = HERE / row['copied_path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('frozen vendor hash mismatch: ' + row['copied_path'])
    return manifest


def load_adapter(arm):
    verify_frozen()
    if arm not in ('ordinary', 'ecrc'):
        raise ValueError('no permit adapter for prompt-only')
    end = HERE / 'legacy/end_to_end'
    package = end / 'legacy_snapshot'
    for name in ('legacy_snapshot.ecrc_adapter', 'legacy_snapshot.ordinary_adapter'):
        if name in sys.modules and not Path(sys.modules[name].__file__).resolve().is_relative_to(HERE):
            raise RuntimeError('conflicting frozen dependency namespace; use a fresh interpreter')
    name = '_online_frozen_' + arm
    if name in sys.modules:
        return sys.modules[name].Adapter
    sys.path.insert(0, str(end))
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, end / (arm + '_e2e.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.Adapter


TEMPLATE = json.loads((HERE / 'legacy/request_template.json').read_text(encoding='utf-8'))
