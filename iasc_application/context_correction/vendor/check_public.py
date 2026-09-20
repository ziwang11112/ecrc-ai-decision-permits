"""Verify packaging, reconstruction and result projection without execution."""
import argparse
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path
from build_public import project, content_fields
from reconstruct_catalog import reconstruct, CATALOG_SHA, RUNNER_SHA, OFFICIAL_SHA, sha, canonical
from review_frozen import PROTOCOL_SHA

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def audit_public_structure(bundle):
    """Recalculate from public inputs/events/results/starts, without SQLite or private source."""
    catalog = read(bundle / 'metadata/catalog_template.json')
    actual_manifest = {p: sha((bundle / 'application/workload' / p).read_bytes()) for p in catalog['runner_manifest']}
    assert actual_manifest == catalog['runner_manifest'] and sha(canonical(actual_manifest)) == RUNNER_SHA
    official_blob = (bundle / 'application/workload/sources/HumanEval.jsonl.gz').read_bytes()
    assert sha(official_blob) == OFFICIAL_SHA
    official = {r['task_id']: r for r in map(json.loads, gzip.decompress(official_blob).decode('utf-8').splitlines())}
    if (bundle / 'application/FINAL_PROTOCOL.json').exists():
        assert sha((bundle / 'application/FINAL_PROTOCOL.json').read_bytes()) == PROTOCOL_SHA
        protocol = read(bundle / 'application/FINAL_PROTOCOL.json')
        for path, expected in protocol['source_hashes'].items():
            assert sha((bundle / 'application' / path).read_bytes()) == expected
    tasks = sorted(official, key=lambda t: sha(('iasc-app-task-order-v1|' + t).encode()))
    assert [t['task_id'] for t in catalog['tasks']] == tasks
    assert len(tasks) == 164 and len(catalog['jobs']) == 656
    by_decision = {j['decision_id']: j for j in catalog['jobs']}
    by_task = {t: sorted([j for j in catalog['jobs'] if j['task_id'] == t], key=lambda j: j['rank']) for t in tasks}
    for task in catalog['tasks']:
        t = task['task_id']
        selected = sorted(range(task['source_record_count']), key=lambda i: sha(f'iasc-app-20260912-v1|{t}|{i}'.encode()))[:4]
        assert task['source_indices'] == selected
        assert [j['source_array_index'] for j in by_task[t]] == selected
        for rank, job in enumerate(by_task[t], 1):
            assert job['candidate_id'] == f'{t}::{selected[rank-1]}' and job['rank'] == rank
            assert job['test_sha256'] == sha(official[t]['test'].encode('utf-8'))
            binding = {k: job[k] for k in ('task_id', 'candidate_id', 'solution_sha256', 'test_sha256', 'runner_sha256')}
            digest = sha(canonical(binding))
            assert job['job_digest'] == digest and job['decision_id'] == 'verify:' + digest
            assert job['used_evidence_ids'] == ['job:' + digest]
    batches = {b['batch_id']: b for b in catalog['batches']}
    rows = []
    fingerprints = collections.defaultdict(set)
    for grid_path in sorted((bundle / 'results').glob('*/GRID_PLAN.public.json')):
        grid_root = grid_path.parent
        grid = read(grid_path)
        assert len(grid['cells']) == grid['planned_runs']
        for index, cell in enumerate(grid['cells'], 1):
            folder = grid_root / f'r{index:03d}'
            inp = read(folder / 'input_batch.json.public.json')
            summary = read(folder / 'run_summary.json.public.json')
            events = read(folder / 'client_events.jsonl.public.json')
            service = read(folder / 'service_runs/service_events.jsonl.public.json')
            batch_id = cell['batch']
            eligible = batches[batch_id]['task_ids']
            assert inp['batch_id'] == summary['batch_id'] == batch_id
            assert len(eligible) == 8 and inp['task_ids'] == eligible
            expected_candidates = {t: [j['candidate_id'] for j in by_task[t]] for t in eligible}
            assert inp['candidate_ids'] == expected_candidates
            expected_decisions = {j['decision_id'] for t in eligible for j in by_task[t]}
            assert set(inp['requests']) == expected_decisions and len(expected_decisions) == 32
            for decision, request in inp['requests'].items():
                job = by_decision[decision]
                assert request['proposal']['decision_id'] == decision
                assert request['proposal']['input_hash'] == job['job_digest']
                assert request['proposal']['model_hash'] == catalog['source_archive_sha256']
                assert request['evidence']['decision_id'] == decision
                assert [e['evidence_id'] for e in request['evidence']['items']] == ['job:' + job['job_digest']]
            input_hash = sha(canonical(inp))
            assert input_hash == summary['inputs_hash']
            fingerprints[(grid_root.name, batch_id)].add(input_hash)
            for key in ('arm', 'policy', 'condition'):
                assert summary[key] == cell[key]
            assert summary['passed_technical'], 'A technical failure is retained and needs explicit incomplete-trajectory audit'
            assert events and events[0]['event'] == 'trajectory_started'
            # Use the exported workflow elapsed observation for the declared
            # timely-feedback boundary; the summary is only a later cross-check.
            D = events[0]['deadline_seconds']; K = events[0]['budget']
            assert D == 5 and K == 16 and events[0]['task_ids'] == eligible
            assert all(a['perf_counter_ns'] <= b['perf_counter_ns'] for a, b in zip(events, events[1:]))
            commits = {e['idempotency_key']: e for e in service if e['event'] == 'result_commit_return'}
            assert len(commits) == sum(e['event'] == 'result_commit_return' for e in service)
            raw_by_digest = {}; physical_starts = 0
            for raw_path in sorted((folder / 'service_runs').glob('*/raw_result.json.public.json')):
                result = read(raw_path)
                digest = result['job_digest']
                assert digest not in raw_by_digest
                starts = read(raw_path.parent / 'work/actual_start_events.json.public.json')
                actual = [e for e in starts if e['kind'] == 'suite_started']
                assert len(actual) == 1 and result['actual_starts'] == 1 and result['actual_start_known']
                for key in ('job_digest', 'task_id', 'candidate_id', 'solution_sha256', 'test_sha256'):
                    assert actual[0][key] == result[key]
                assert actual[0]['pid'] == result['child_pid']
                job = by_decision['verify:' + digest]
                for key in ('task_id', 'candidate_id', 'solution_sha256', 'test_sha256', 'runner_sha256'):
                    assert result[key] == job[key]
                launch = read(raw_path.parent / 'work/launch.json.public.json')
                for key in ('job_digest', 'task_id', 'candidate_id', 'host_launch_perf_counter_ns', 'host_exit_perf_counter_ns'):
                    assert launch[key] == result[key]
                physical_starts += len(actual)
                raw_by_digest[digest] = result
            issued = {}; armed = {}; reconciled = {}; timely = set(); eventual = set()
            attempted = {t: [] for t in eligible}; solved = set(); cursor = 0
            budget_checkpoints = []; stop_derived = None
            for event in events:
                name = event['event']
                if name == 'issued':
                    decision = event['decision_id']; job = by_decision[decision]
                    assert decision in expected_decisions
                    assert event['request_hash'] == sha(canonical(inp['requests'][decision]))
                    active = [t for t in eligible if t not in solved and len(attempted[t]) < 4]
                    if cell['policy'] == 'depth_first':
                        next_task = active[0]
                    else:
                        next_task = next(eligible[(cursor+i) % 8] for i in range(8) if eligible[(cursor+i) % 8] in active)
                        cursor = (eligible.index(next_task) + 1) % 8
                    assert job['task_id'] == next_task and job['rank'] == len(attempted[next_task]) + 1
                    if event['route'] == 'alert':
                        assert event['permit_id'] not in issued
                        issued[event['permit_id']] = event
                elif name == 'armed':
                    operation = event['operation_id']; permit = event['permit_id']
                    assert operation not in armed and permit in issued
                    assert event['decision_id'] == issued[permit]['decision_id']
                    attempted[event['task_id']].append(event['candidate_id'])
                    assert event['launch_ordinal'] == len(armed) + 1
                    assert event['request_drop'] == (cell['condition'] == 'response_loss' and event['launch_ordinal'] % 4 == 0)
                    armed[operation] = event
                elif name == 'reconciled':
                    permit = event['permit_id']
                    assert permit in issued and permit not in reconciled
                    operation = next(k for k, e in armed.items() if e['permit_id'] == permit)
                    commit = commits[operation]; digest = commit['job_hash']
                    result = raw_by_digest[digest]
                    assert event['decision_id'] == 'verify:' + digest
                    assert event['effect_id'] == commit['effect_id'] and event['result_hash'] == commit['result_hash']
                    assert event['result'] == result
                    assert commit['perf_counter_ns'] <= event['perf_counter_ns']
                    reconciled[permit] = event
                    if result['status'] == 'pass':
                        solved.add(result['task_id']); eventual.add(result['task_id'])
                        if event['phase'] == 'primary' and event['elapsed_s'] <= D:
                            timely.add(result['task_id'])
                held = len(issued) - len(reconciled); committed = len(reconciled)
                assert 0 <= held and held + committed <= K
                budget_checkpoints.append({'event': name, 'held': held, 'committed': committed})
                if name == 'primary_stopped':
                    stop_derived = (held, committed)
            assert stop_derived is not None
            final_derived = (len(issued)-len(reconciled), len(reconciled))
            for filename, expected in [('stop_observed_snapshot.json.public.json', stop_derived),
                                       ('final_client_snapshot.json.public.json', final_derived)]:
                snap = read(folder / filename)
                assert (snap['reserved'], snap['committed']) == expected
                assert sum(r['reserved'] for r in snap['capacity_rows']) == expected[0]
                assert sum(r['committed'] for r in snap['capacity_rows']) == expected[1]
            assert len(raw_by_digest) == len(commits) == physical_starts
            assert set(commits) == set(armed)
            for event in service:
                if event['event'] in ('runner_invoked', 'job_start'):
                    operation = event['idempotency_key']
                    assert operation in armed
                    assert event['job_hash'] == armed[operation]['decision_id'][7:]
                    if event['event'] == 'job_start':
                        assert event['perf_counter_ns'] == raw_by_digest[event['job_hash']]['host_launch_perf_counter_ns']
            drops = [e for e in service if e['event'] == 'response_drop']
            caches = [e for e in service if e['event'] == 'cache_hit']
            assert len(drops) == sum(e['request_drop'] for e in armed.values())
            assert {e['idempotency_key'] for e in drops} == {k for k, e in armed.items() if e['request_drop']}
            assert len(caches) == sum(e['event'] == 'retry' for e in events)
            for event in drops + caches:
                operation = event['idempotency_key']
                assert event['effect_id'] == commits[operation]['effect_id']
                assert event['perf_counter_ns'] >= commits[operation]['perf_counter_ns']
            # Summaries are checked only after independently deriving the metrics.
            assert summary['n_timely_pass'] == len(timely)
            assert set(summary['timely_pass_task_ids']) == timely and set(summary['eventual_pass_task_ids']) == eventual
            assert summary['http_posts'] == len(armed) + len(caches)
            rows.append({'grid': grid_root.name, 'run_id': folder.name, 'batch_id': batch_id,
                         'arm': cell['arm'], 'policy': cell['policy'], 'condition': cell['condition'],
                         'eligible_tasks': 8, 'candidate_opportunities': 32, 'input_projection_sha256': input_hash,
                         'timely_tasks_recomputed': len(timely), 'eventual_tasks_recomputed': len(eventual),
                         'actual_starts_from_start_records': physical_starts,
                         'child_cpu_seconds_recomputed': sum(r['cpu_seconds'] for r in raw_by_digest.values()),
                         'suite_wall_seconds_recomputed': sum(r['wall_seconds'] for r in raw_by_digest.values()),
                         'launcher_wall_seconds_recomputed': sum(r['launcher_wall_seconds'] for r in raw_by_digest.values()),
                         'response_drops_from_service_events': len(drops), 'cache_hits_from_service_events': len(caches),
                         'stop_held_recomputed': stop_derived[0], 'stop_committed_recomputed': stop_derived[1],
                         'final_held_recomputed': final_derived[0], 'final_committed_recomputed': final_derived[1],
                         'max_held_plus_committed': max(x['held'] + x['committed'] for x in budget_checkpoints),
                         'feedback_dependent_policy_choices_checked': True, 'budget_checkpoints_checked': len(budget_checkpoints)})
    assert rows
    assert all(len(values) == 1 for values in fingerprints.values())
    csv_rows_checked = 0
    table_path = bundle / 'analysis/S9_runs.csv'
    if table_path.exists():
        comparisons = {'timely_tasks': 'timely_tasks_recomputed', 'actual_starts': 'actual_starts_from_start_records',
                       'response_drops': 'response_drops_from_service_events', 'cache_hits': 'cache_hits_from_service_events',
                       'stop_held': 'stop_held_recomputed', 'stop_committed': 'stop_committed_recomputed',
                       'final_held': 'final_held_recomputed', 'final_committed': 'final_committed_recomputed',
                       'eventual_pass_tasks': 'eventual_tasks_recomputed'}
        with table_path.open(newline='', encoding='utf-8') as stream:
            published = list(csv.DictReader(stream))
        for table_row in published:
            matches = [r for r in rows if r['batch_id'] == table_row['batch_id'] and
                       all(r[k] == table_row[k] for k in ('run_id', 'arm', 'policy', 'condition'))]
            assert len(matches) == 1
            derived = matches[0]
            for column, key in comparisons.items():
                assert int(table_row[column]) == derived[key], (table_row['run_id'], column)
            for column in ('child_cpu_seconds', 'suite_wall_seconds', 'launcher_wall_seconds'):
                assert abs(float(table_row[column]) - derived[column + '_recomputed']) < 1e-9
            csv_rows_checked += 1
    return {'runs': rows, 'input_matched_within_each_batch': True,
            'all_batches_have_32_candidate_opportunities': True,
            'analysis_run_rows_crosschecked_after_independent_derivation': csv_rows_checked,
            'scope': 'Recalculated from public input/client/service/result/start/checkpoint structures. No private archive, SQLite, run-summary count or S9 CSV supplies the derived metrics. Original result_hash remains an opaque author-held-byte reference.'}

def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from strings(value)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--app-root', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--public-only', action='store_true', help='Use only public files; do not read the private archive or original run records')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.out.resolve()
    if not args.public_only and (args.app_root is None or args.source is None):
        parser.error('--app-root and --source are required unless --public-only')
    bundle = args.bundle.resolve()
    if output.is_relative_to(bundle):
        raise ValueError('Write QA report outside the immutable public bundle')
    app = args.app_root.resolve() if args.app_root else None
    inventory = json.loads((bundle / 'PUBLIC_INVENTORY.json').read_text(encoding='utf-8'))
    expected_paths = {r['path'] for r in inventory} | {'PUBLIC_INVENTORY.json'}
    actual_paths = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    assert expected_paths == actual_paths
    for row in inventory:
        data = (bundle / row['path']).read_bytes()
        assert len(data) == row['bytes'] and sha(data) == row['sha256']
    forbidden_names = {'catalog.json', 'bound_catalog.json', 'bound_job.json', 'payload.json'}
    assert not any(p.name in forbidden_names or '.sqlite' in p.name or p.suffix == '.log' for p in bundle.rglob('*') if p.is_file())
    selected_text_hashes = set()
    if not args.public_only:
        blob = reconstruct(bundle, args.source)
        assert sha(blob) == CATALOG_SHA
        catalog = json.loads(blob)
        selected_text_hashes = {sha(j['solution'].encode('utf-8')) for j in catalog['jobs'] if len(j['solution']) >= 40}
    scanned = 0
    for directory in ('metadata', 'results', 'audits'):
        for path in (bundle / directory).rglob('*.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            assert not content_fields(data), path
            assert all(sha(text.encode('utf-8')) not in selected_text_hashes for text in strings(data) if len(text) >= 40), path
            scanned += 1
    # An adversarial extra source/output/message field must not survive export.
    marker = 'def private_candidate(x):\n    return x + 123456789\n'
    probe = {'solution': marker, 'message': marker, 'candidate_stdout_base64': marker,
             'status': 'pass', 'result': {'solution': marker, 'status': 'fail', 'cpu_seconds': 0.1},
             'ack_json': json.dumps({'job_result': {'solution': marker, 'status': 'pass'}})}
    assert marker not in json.dumps(project(probe))
    preserved_events = 0
    preserved_results = 0
    for manifest_path in ([] if args.public_only else (bundle / 'results').rglob('PROJECTION_MANIFEST.json')):
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for row in manifest:
            source = app / row['source_path']
            original_blob = source.read_bytes()
            public = json.loads((bundle / row['public_path']).read_text(encoding='utf-8'))
            assert sha(original_blob) == row['source_sha256']
            if source.name == 'client_events.jsonl':
                original = [json.loads(l) for l in original_blob.decode().splitlines()]
                assert len(original) == len(public)
                for old, new in zip(original, public):
                    for key in ('event', 'perf_counter_ns', 'elapsed_s', 'task_id', 'candidate_id', 'decision_id',
                                'permit_id', 'operation_id', 'effect_id', 'request_hash', 'result_hash', 'launch_ordinal', 'request_drop'):
                        if key in old:
                            assert new[key] == old[key], (source, key)
                    preserved_events += 1
            if source.name == 'raw_result.json':
                original = json.loads(original_blob)
                for key in ('status', 'candidate_id', 'task_id', 'job_digest', 'actual_starts', 'actual_start_known',
                            'cpu_seconds', 'wall_seconds', 'launcher_wall_seconds', 'host_launch_perf_counter_ns',
                            'host_exit_perf_counter_ns', 'solution_sha256', 'test_sha256', 'runner_sha256'):
                    assert public[key] == original[key], (source, key)
                preserved_results += 1
    structure = audit_public_structure(bundle)
    report = {'checks_passed': True, 'public_inventory_entries': len(inventory),
              'metadata_result_json_files_checked': scanned,
              'client_events_with_causal_bindings_preserved': preserved_events,
              'job_results_with_status_cost_hash_bindings_preserved': preserved_results,
              'injected_source_output_fields_excluded': True,
              'selected_full_program_strings_absent_from_metadata_results': None if args.public_only else True,
              'reconstructed_private_catalog_sha256': None if args.public_only else CATALOG_SHA, 'runner_sha256': RUNNER_SHA,
              'public_only_mode': args.public_only, 'independent_public_recalculation': structure,
              'private_catalog_written': False, 'candidate_code_executed': False,
              'limits': 'Allowlist/projection plus exact-string checks; not a byte-complete public raw-evidence audit. Original result_hash requires author-held original bytes.'}
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'independent_public_recalculation'}, sort_keys=True))
    print(json.dumps({'public_runs_independently_recalculated':len(structure['runs']),
                      'input_matched_within_each_batch':structure['input_matched_within_each_batch']}, sort_keys=True))

if __name__ == '__main__':
    main()
