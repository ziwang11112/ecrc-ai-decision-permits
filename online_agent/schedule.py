"""Reconstruct the published schedules without APIs or candidate execution."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent
STUDIES = ('primary', 'external', 'claude_v2')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def schedule(study='primary'):
    if study not in STUDIES:
        raise ValueError('unknown public study')
    spec = json.loads((ROOT / 'protocol' / (study + '_schedule_spec.json')).read_text(encoding='utf-8'))
    batches = spec['batches']
    if len(batches) != 24 or len({t for b in batches for t in b['task_ids']}) != 96:
        raise ValueError('expected 24 disjoint four-task batches')
    rows = []
    for batch in batches:
        if len(batch['task_ids']) != 4:
            raise ValueError('incorrect batch size')
        for repeat in range(spec['repeats']):
            for provider, model in spec['profiles'].items():
                for condition in spec['conditions']:
                    for arm in spec['arms']:
                        rows.append({'batch_id': batch['batch_id'], 'repeat': repeat,
                                     'provider': provider, 'model': model,
                                     'condition': condition, 'arm': arm})
    rows.sort(key=lambda row: hashlib.sha256((spec['seed'] + canonical(row)).encode()).hexdigest())
    for index, row in enumerate(rows):
        row.update(episode=f"{spec['episode_prefix']}-c{index:04}", storage_dir=f'c{index:04}')
    if len(rows) != spec['planned_trajectories']:
        raise ValueError('assignment count differs from the declared study')
    return rows


def verify_schedule(study):
    with (ROOT / 'protocol' / (study + '_schedule.csv')).open(encoding='utf-8', newline='') as stream:
        expected = list(csv.DictReader(stream))
    for row in expected:
        row['repeat'] = int(row['repeat'])
    actual = schedule(study)
    if expected != actual:
        raise ValueError('schedule differs from source-frozen assignment projection: ' + study)
    return len(actual)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', choices=STUDIES, default='primary')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        print(json.dumps({study: verify_schedule(study) for study in STUDIES}, sort_keys=True))
    else:
        rows = schedule(args.study)
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
