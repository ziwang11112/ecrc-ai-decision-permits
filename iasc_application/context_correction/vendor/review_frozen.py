"""Read-only freeze verification. Does not read evaluation trajectories."""
import argparse
import hashlib
import json
from pathlib import Path

PROTOCOL_SHA = 'ab396792ad4058ad0418ccbabdf0f963723d77ddf0b8c75c613e4e757b5bdc9d'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_frozen(app):
    app = Path(app).resolve()
    protocol_path = app / 'FINAL_PROTOCOL.json'
    if sha(protocol_path) != PROTOCOL_SHA:
        raise ValueError('Pinned formal protocol changed')
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    freeze = json.loads((app / 'FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    assert freeze['protocol_sha256'] == PROTOCOL_SHA
    assert freeze['source_snapshot_files'] == protocol['source_hashes']
    assert protocol['frozen'] is True
    assert (protocol['planned_runs'], protocol['budget'], protocol['deadline_seconds'], protocol['recovery_backoff_seconds']) == (144, 16, 5, 1.0)
    assert protocol['evaluation_batch_ids'] == [f'evaluation_{i:02d}' for i in range(1, 19)]
    assert protocol['arms'] == ['ecrc', 'ordinary']
    assert protocol['policies'] == ['depth_first', 'round_robin']
    assert protocol['conditions'] == ['normal', 'response_loss']
    for relative, expected in protocol['source_hashes'].items():
        live = (app / relative).resolve()
        live.relative_to(app)
        snapshot = (app / 'frozen_source' / relative).resolve()
        snapshot.relative_to((app / 'frozen_source').resolve())
        assert sha(live) == sha(snapshot) == expected, relative
    for relative, expected in freeze['input_files'].items():
        path = (app / relative).resolve()
        path.relative_to(app)
        assert sha(path) == expected, relative
    return {'protocol_sha256': PROTOCOL_SHA, 'freeze_manifest_sha256': sha(app / 'FREEZE_MANIFEST.json'),
            'frozen_source_files_verified': len(protocol['source_hashes']),
            'frozen_input_files_verified': len(freeze['input_files']),
            'planned_runs': 144, 'budget': 16, 'deadline_seconds': 5, 'recovery_backoff_seconds': 1.0,
            'evaluation_results_read': False, 'candidate_code_executed': False, 'checks_passed': True}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app-root', type=Path, default=Path(__file__).resolve().parent.parent)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    report = verify_frozen(a.app_root)
    if a.out:
        a.out.resolve().relative_to(Path(__file__).resolve().parent)
        with a.out.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write('\n')
    print(json.dumps(report, sort_keys=True))

if __name__ == '__main__':
    main()
