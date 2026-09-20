"""Offline S12 verification from saved transport records and optional raw SQL.

Standard library only. The default does not establish database completeness;
--raw-root adds the original independent SQL audit on disposable copies.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
ARMS = ('raw', 'volatile_count', 'durable_count', 'ecrc')
CHECKPOINTS = ('A_issued_or_queued', 'B_unknown_before_restart',
               'restarted_before_cleanup', 'A_expired_B_still_unknown',
               'after_C_D_before_B_recovery', 'mixed_final')
ECRC_STATES = [(1, 0, 0), (2, 0, 0), (2, 0, 0), (1, 0, 0), (1, 1, 1), (0, 2, 2)]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def auditor():
    spec = importlib.util.spec_from_file_location('s12_frozen_auditor', HERE / 'frozen/source/audit_run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def effects_from_transport(folder, case, audit):
    """Reconstruct unique effect records from actual public service responses."""
    rows = [json.loads(line) for line in (folder / 'PROXY.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    identities = {job['job_hash']: job['name'] for job in case['jobs']}
    decisions = {job['decision_id']: job['name'] for job in case['jobs']}
    effects = {}
    for event in rows:
        ack = event.get('upstream_response', {})
        if event.get('upstream_code') not in (200, 201) or 'effect_id' not in ack:
            continue
        effect = {key: ack[key] for key in ('effect_id', 'idempotency_key', 'payload_hash', 'payload', 'committed_at')}
        payload = effect['payload']
        require(effect['payload_hash'] == audit._hash(payload), f'{folder.name}: payload hash mismatch')
        effect['logical_job'] = decisions.get(payload.get('decision_id')) if case['arm'] == 'ecrc' else identities.get(payload.get('job_hash'))
        require(effect['logical_job'] in 'ABCD', f'{folder.name}: effect outside fixed input set')
        identity = effect['effect_id']
        require(identity not in effects or effects[identity] == effect, f'{folder.name}: changed response identity')
        effects[identity] = effect
    return sorted(effects.values(), key=lambda value: value['effect_id'])


def csv_row(case, effects):
    counts = Counter(effect['logical_job'] for effect in effects)
    expired = ['A'] if case['condition'] == 'mixed' else []
    eligible = [name for name in 'ABCD' if name not in expired]
    return {'arm': case['arm'], 'condition': case['condition'], 'input_jobs': '4',
            'distinct_effects': str(len(effects)), 'external_limit': str(case['external_limit']),
            'effects_over_limit': str(max(0, len(effects) - case['external_limit'])),
            'same_key_duplicate_effects': str(sum(max(0, n - 1) for n in Counter(e['idempotency_key'] for e in effects).values())),
            'queue_expired_jobs': ','.join(expired),
            'eligible_uncompleted_jobs': ','.join(name for name in eligible if not counts[name]),
            **{f'effect_{name}': str(counts[name]) for name in 'ABCD'}}


def verify_public_sources(raw_root):
    provenance = read(HERE / 'PROVENANCE.json')
    checked = 0
    for entry in provenance['entries']:
        paths = []
        if entry['public_path']:
            paths.append(HERE / entry['public_path'])
        if raw_root and entry['raw_archive_path']:
            paths.append(raw_root / entry['raw_archive_path'])
        for path in paths:
            require(sha(path) == entry['export_sha256'], f'Export hash mismatch: {path.name}')
            checked += 1
    return checked


def verify_raw_manifest(root):
    manifest = read(root / 'MANIFEST.json')
    for item in manifest['files']:
        path = root / item['path']
        require(path.resolve().is_relative_to(root.resolve()), 'Unsafe manifest path')
        require(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'], f'Raw manifest mismatch: {item["path"]}')
    return len(manifest['files'])


def verify(raw_root=None):
    audit = auditor()
    checks = verify_public_sources(raw_root)
    with (HERE / 'ALL_CELLS.csv').open(newline='', encoding='utf-8') as handle:
        expected_rows = list(csv.DictReader(handle))
    rows = []
    totals = Counter()
    retained_failures = []
    reports = []
    for batch in ('batch_01', 'batch_02'):
        expected_cells = {f'{condition}__{arm}' for condition in ('normal', 'mixed') for arm in ARMS}
        folders = [folder for folder in (HERE / 'runs' / batch).iterdir() if folder.is_dir()]
        require({folder.name for folder in folders} == expected_cells, f'{batch}: missing or extra cell')
        for folder in sorted(folders):
            case, trace, saved = (read(folder / name) for name in ('CASE.json', 'TRACE.json', 'AUDIT.json'))
            require([job['name'] for job in case['jobs']] == list('ABCD'), 'All four inputs must be retained')
            require(case['external_limit'] == 2 and trace['failure'] is None, f'{folder.name}: case or execution mismatch')
            effects = effects_from_transport(folder, case, audit)
            require(effects == sorted(saved['effects'], key=lambda value: value['effect_id']), f'{folder.name}: saved effects differ from transport')
            transport = audit._audit_transport(folder, effects, case)
            process = audit._audit_trace(folder, trace, case, effects, transport)
            require(transport['passed'], f'{folder.name}: transport audit failed')
            expected_failures = ['actual_process_restart_while_B_unknown_not_established'] if batch == 'batch_01' and case['condition'] == 'mixed' else []
            require(process['failures'] == expected_failures, f'{batch}/{folder.name}: unexpected process audit outcome')
            require(saved['technical_failures'] == expected_failures and saved['technical_audit_passed'] == (not expected_failures), 'Historical audit failure changed')
            if expected_failures:
                retained_failures.append(f'{batch}/{folder.name}')
            row = csv_row(case, effects)
            require(saved['effect_counts_by_job'] == {name: int(row[f'effect_{name}']) for name in 'ABCD'}, 'Saved input outcomes differ')
            if batch == 'batch_02':
                rows.append(row)
                totals.update(effects=len(effects), posts=transport['successful_upstream_posts'],
                              replays=transport['same_key_additional_post_count'],
                              withheld=transport['withheld_successful_post_responses'])
            reports.append({'batch': batch, 'cell': folder.name, 'effects': len(effects),
                            'technical_audit_passed': not expected_failures, 'expected_failures': expected_failures})
    require(sorted(rows, key=lambda r: (r['condition'], r['arm'])) == sorted(expected_rows, key=lambda r: (r['condition'], r['arm'])), 'ALL_CELLS.csv differs from reconstructed transport records')
    require(totals == {'effects': 20, 'posts': 24, 'replays': 4, 'withheld': 4}, 'Current aggregate changed')
    for name, expected in zip(CHECKPOINTS, ECRC_STATES):
        state = read(HERE / 'runs/batch_02/mixed__ecrc/checkpoints' / name / 'CLIENT_OBSERVATION.json')['state']
        require((state['reserved'], state['committed'], state['n_receipts']) == expected, f'Checkpoint changed: {name}')
    volatile = HERE / 'runs/batch_02/mixed__volatile_count/checkpoints'
    for checkpoint, count in (('B_unknown_before_restart', 1), ('restarted_before_cleanup', 0), ('mixed_final', 2)):
        require(read(volatile / checkpoint / 'CLIENT_OBSERVATION.json')['state']['first_submissions'] == count, 'Volatile restart counter differs')
    result = {'status': 'passed', 'classification': 'new publication QA of saved historical evidence; no experiment',
              'mode': 'transport/process records and saved checkpoint observations', 'current_cells': 8,
              'retained_prior_cells': 8, 'retained_failed_restart_audits': retained_failures,
              'current_totals': dict(totals), 'source_hashes_verified': checks,
              'all_cells_csv_recomputed': True, 'model_calls': 0, 'cells': reports}
    if raw_root:
        result['raw_manifest_files_verified'] = verify_raw_manifest(raw_root)
        with tempfile.TemporaryDirectory(prefix='s12-readonly-audit-') as temporary:
            copy = Path(temporary) / 'runs'
            shutil.copytree(raw_root / 'runs', copy)
            sql_reports = []
            for report in reports:
                cell = copy / report['batch'] / report['cell']
                fresh = audit.audit(cell)
                saved = read(cell / 'AUDIT.json')
                for key in ('technical_audit_passed', 'technical_failures', 'effect_counts_by_job', 'actual_effect_count', 'eligible_uncompleted_job_names', 'external_over_limit', 'same_key_duplicate_effects', 'client_accountability'):
                    require(fresh[key] == saved[key], f'{report["batch"]}/{report["cell"]}: SQL differs on {key}')
                sql_reports.append({'batch': report['batch'], 'cell': report['cell'], 'technical_audit_passed': fresh['technical_audit_passed']})
            checkpoint_databases = 0
            for database in sorted(copy.glob('*/**/checkpoints/**/*.sqlite')):
                # SQLite may create an empty WAL on first read of a backup.
                # Precreate only that empty file in the disposable copy, so the
                # unchanged original auditor can still enforce byte stability.
                wal = Path(str(database) + '-wal')
                if not wal.exists():
                    wal.touch()
                tables, source = audit._read_db(database)
                require(source['integrity_check'] == ['ok'] and source['file_bytes_unchanged_while_reading'], 'Checkpoint SQL integrity failure')
                checkpoint_databases += 1
                if database.name == 'client.sqlite' and 'mixed__ecrc' in database.parts and 'batch_02' in database.parts:
                    expected = ECRC_STATES[CHECKPOINTS.index(database.parent.name)]
                    actual = (sum(r['reserved'] for r in tables['capacity_state']), sum(r['committed'] for r in tables['capacity_state']), len(tables['receipt_log']))
                    require(actual == expected, 'SQL checkpoint responsibility sequence differs')
            result.update(mode='full SQL, transport, process and checkpoint audit', sql_cells=sql_reports,
                          checkpoint_databases_verified=checkpoint_databases)
        verify_raw_manifest(raw_root)
    return result, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', type=Path, help='Extracted raw release asset root containing MANIFEST.json and runs/')
    parser.add_argument('--json', type=Path, help='Optional QA result output, preferably outside the checkout')
    parser.add_argument('--csv', type=Path, help='Optional recomputed current eight-cell CSV')
    args = parser.parse_args()
    result, rows = verify(args.raw_root.resolve() if args.raw_root else None)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({key: value for key, value in result.items() if key not in ('cells', 'sql_cells')}, indent=2))


if __name__ == '__main__':
    main()
