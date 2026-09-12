"""Build a local reviewable S9 add-on via explicit source and typed-result lists.

Never copies raw run directories, candidate records, databases or output logs.
Run roots must be completed snapshots; no formal candidate execution occurs.
"""
import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from reconstruct_catalog import CATALOG_SHA, RUNNER_SHA, sha, canonical
from review_frozen import PROTOCOL_SHA, verify_frozen

HERE = Path(__file__).resolve().parent
FIXED_FILES = [
    'application_common.py', 'prepare_legacy.py', 'run_grid.py', 'run_workflow.py', 'freeze_protocol.py', 'PILOT_PLAN.md',
    'service/verification_service.py', 'service/frozen_service.py', 'service/README.md',
    'legacy/request_template.json', 'legacy/SOURCE_MANIFEST.json',
    'workload/job_runner.py', 'workload/sandbox/run_sandbox.sh', 'workload/sandbox/sandbox_bootstrap.py',
    'workload/sandbox/sandbox_guard.py', 'workload/sandbox/suite_worker.py',
    'workload/prepare_workload.py', 'workload/run_qa.py', 'workload/README.md',
    'workload/batches.json', 'workload/RUNTIME_FEASIBILITY.json',
    'workload/sources/HumanEval.jsonl.gz', 'workload/sources/HUMANEVAL_LICENSE',
    'workload/sources/candidate_download_recipe.json',
]
HISTORY_FILES = [
    'DEVELOPMENT_HISTORY.md', 'service/PATH_COMPATIBILITY_FIX.md',
    'service/history/verification_service_v1.py',
    'workload/rebind_runner.py', 'workload/rebind_runner_v2.py',
    'workload/qa_revision_v1/job_runner.py', 'workload/qa_revision_v1/suite_worker.py',
    'workload/qa_revision_v1/manifest.json', 'workload/qa_revision_v2/job_runner.py',
    'workload/qa_revision_v2/manifest.json',
    'workload/qa_reference_v1/summary.json', 'workload/qa_reference_v2/summary.json',
    'workload/qa_reference_v3/summary.json', 'workload/qa_selftest_v3/summary.json',
    'workload/qa_development_serial_v1/summary.json', 'workload/qa_development_serial_v2/summary.json',
    'workload/qa_infrastructure_branches_v1/summary.json',
    'development/integration_v1/SUMMARY.json', 'development/integration_v2/SUMMARY.json',
]
ANALYSIS_CSV = ('S9_runs.csv', 'S9_jobs.csv', 'S9_cells.csv', 'S9_paired_batches.csv')
NUMERIC = set('budget deadline_seconds recovery_backoff_seconds started_at_counter_ns n_timely_pass n_tasks http_posts n_receipts n_armed n_receipted n_jobs reserved committed capacity_limit state_revision policy_revision pre_state_revision post_state_revision sequence_no effect_id ordinal perf_counter_ns elapsed_s cpu_seconds wall_seconds launcher_wall_seconds host_launch_perf_counter_ns host_exit_perf_counter_ns actual_starts child_pid pid host_pid service_pid launcher_returncode wait_status suite_timeout_seconds candidate_stdout_bytes candidate_stderr_bytes status_code planned_runs observed_runs technical_failures elapsed_wall_seconds model_calls automatic_reruns parallel_trajectories'.split())
BOOLEAN = set('passed_technical actual_start_known candidate_stdout_truncated candidate_stderr_truncated recorded_after_runner_return created all_runs_retained'.split())
STRINGS = set('run_id batch_id partition arm policy condition candidate_id task_id decision_id job_digest job_hash result_hash solution_sha256 test_sha256 runner_sha256 catalog_sha256 formal_protocol_sha256 inputs_hash status event kind phase idempotency_key permit_id permit_hash payload_hash reservation_id receipt_id route state resource scope_key policy_id timestamp_source recorded_at committed_at'.split())
LISTS = set('eligible_task_ids timely_pass_task_ids eventual_pass_task_ids task_ids candidate_ids used_evidence_ids permitted_claim_ids admitted_evidence_ids excluded_evidence_ids'.split())
NESTED = set('result job_result failure final_snapshot snapshot capacity_rows jobs attempted'.split())
NUMERIC.update(('launch_ordinal', 'retry_due_counter_ns'))
BOOLEAN.add('request_drop')
STRINGS.update(('operation_id', 'request_hash', 'batch', 'error_type', 'policy_hash', 'evidence_hash',
                'proposal_hash', 'reason_code', 'executed_at', 'reconciled_at', 'expires_at', 'issued_at'))
NUMERIC.update(('alert_capacity', 'review_capacity', 'revision', 'review_band_width', 'score_threshold',
                'uncertainty_threshold', 'score', 'uncertainty', 'max_age_seconds'))
BOOLEAN.update(('requested_for_use', 'use_allowed'))
STRINGS.update(('input_hash', 'model_hash', 'model_id', 'model_version', 'proposed_action', 'proposed_at',
                'session_id', 'subject_id', 'validation_scope_id', 'capacity_scope', 'effective_from',
                'failure_mode', 'issuer_id', 'created_at', 'evidence_id', 'evidence_type', 'source',
                'schema_version', 'observed_at', 'available_at', 'provenance_hash', 'claim_id'))
LISTS.update(('allowed_routes', 'blocked_claim_ids', 'allowed_schema_versions', 'allowed_sources',
              'reason_codes', 'required_evidence_types', 'routes'))
NESTED.update(('policy', 'proposal', 'evidence', 'approved_models', 'claim_rules', 'evidence_rules', 'items'))
SAFE_TEXT = re.compile(r'[A-Za-z0-9_./:+-]{1,180}\Z')

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')

def project(value):
    """Closed field/type projection: no arbitrary JSON strings or free text."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, item in value.items():
        if key in NUMERIC and (item is None or (type(item) in (int, float) and math.isfinite(item))):
            out[key] = item
        elif key in BOOLEAN and type(item) is bool:
            out[key] = item
        elif key in STRINGS and (item is None or (isinstance(item, str) and SAFE_TEXT.fullmatch(item))):
            out[key] = item
        elif key in LISTS and isinstance(item, list):
            out[key] = [x for x in item if isinstance(x, str) and SAFE_TEXT.fullmatch(x)]
        elif key == 'candidate_ids' and isinstance(item, dict):
            out[key] = {k: [x for x in v if isinstance(x, str) and SAFE_TEXT.fullmatch(x)]
                        for k, v in item.items() if re.fullmatch(r'HumanEval/\d+', k) and isinstance(v, list)}
        elif key == 'requests' and isinstance(item, dict):
            out[key] = {k: project(v) for k, v in item.items() if re.fullmatch(r'verify:[0-9a-f]{64}', k)}
        elif key in NESTED:
            if key == 'failure':
                out[key] = {'present': item is not None}
            elif key == 'attempted' and isinstance(item, dict):
                out[key] = {k: [x for x in v if isinstance(x, str) and SAFE_TEXT.fullmatch(x)] for k, v in item.items()
                            if re.fullmatch(r'HumanEval/\d+', k) and isinstance(v, list)}
            elif isinstance(item, dict):
                out[key] = project(item)
            elif isinstance(item, list):
                out[key] = [project(x) for x in item if isinstance(x, dict)]
        elif key in ('permit_json', 'payload_json', 'receipt_json', 'ack_json') and isinstance(item, str):
            # Decode only named receipt records, then apply the same closed
            # projection; no nested arbitrary JSON text survives publication.
            try:
                out[key[:-5] + '_projection'] = project(json.loads(item))
            except (ValueError, TypeError):
                out[key[:-5] + '_projection'] = {'decode_failed': True}
    return out

def content_fields(obj, prefix=''):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = prefix + '/' + key
            if key in ('solution', 'candidate_stdout_base64', 'candidate_stderr_base64'):
                found.append(path)
            elif isinstance(value, (dict, list)):
                found.extend(content_fields(value, path))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(content_fields(value, prefix + '/*'))
    return sorted(set(found))

def audit_paths(app, completed_roots):
    groups = collections.defaultdict(list)
    checked = []
    # Do not inspect other active evaluation roots. Only completed explicitly
    # selected grids and pre-existing development/workload/service artifacts.
    roots = [app / 'workload', app / 'service', app / 'development', *completed_roots]
    candidates = {app / 'bound_catalog.json'}
    for root in roots:
        candidates.update(root.rglob('*'))
    for path in sorted(candidates):
        if not path.is_file() or HERE in path.parents:
            continue
        relative = path.relative_to(app).as_posix()
        if path.name in ('catalog.json', 'bound_catalog.json', 'bound_job.json', 'payload.json'):
            fields = content_fields(read(path))
            if fields:
                groups['embedded_candidate_source'].append(relative)
                checked.append({'path': relative, 'content_fields': fields})
        elif path.suffix == '.log' or path.name.endswith('_console.log'):
            groups['untrusted_output_or_exception_log_excluded'].append(relative)
        elif '.sqlite' in path.name or path.suffix == '.db':
            groups['database_excluded_uninspected_blob_fields'].append(relative)
        elif path.name in ('final_client_snapshot.json', 'stop_observed_snapshot.json', 'run_summary.json'):
            groups['nested_receipt_or_result_json_requires_projection'].append(relative)
    return {'scope': 'Workload/service/development and explicitly selected completed grids only; no active evaluation scan. Paths only; no candidate body copied.',
            'groups': dict(groups), 'confirmed_json_content_fields': checked,
            'additional_exclusions': ['The separately stored 73,874,142-byte source member outside this application directory.',
                'All raw JSON/JSONL is excluded unless specifically copied as trusted source metadata or exported through the typed projection.',
                'sandbox_output/stdout.log contains Base64 candidate stdout/stderr in trusted result JSON; it is excluded along with candidate output logs.',
                'Nested ack_json/receipt_json/result_json strings and arbitrary exception messages are not copied.']}

def completed_grid(app, run_root):
    run_root = run_root.resolve()
    run_root.relative_to(app)
    if not (run_root / 'SUMMARY.json').exists():
        raise ValueError('Completed grid SUMMARY.json required: ' + str(run_root))
    root_summary = read(run_root / 'SUMMARY.json')
    if root_summary.get('observed_runs') != root_summary.get('planned_runs'):
        raise ValueError('Grid is incomplete; do not package a live run')
    return root_summary

def export_run(app, run_root, out):
    run_root = run_root.resolve()
    completed_grid(app, run_root)
    name = run_root.relative_to(app).as_posix().replace('/', '__')
    destination = out / 'results' / name
    manifest = []
    sources = list(run_root.glob('r*/run_summary.json'))
    sources += list(run_root.glob('r*/input_batch.json'))
    sources += list(run_root.glob('r*/setup_failure.json'))
    sources += list(run_root.glob('r*/client_events.jsonl'))
    sources += list(run_root.glob('r*/service_runs/service_events.jsonl'))
    sources += list(run_root.glob('r*/service_runs/*/raw_result.json'))
    sources += list(run_root.glob('r*/service_runs/*/work/actual_start_events.json'))
    sources += list(run_root.glob('r*/service_runs/*/work/launch.json'))
    sources += list(run_root.glob('r*/stop_observed_snapshot.json'))
    sources += list(run_root.glob('r*/final_client_snapshot.json'))
    sources += [run_root / 'SUMMARY.json']
    for source in sorted(set(sources)):
        relative = source.relative_to(run_root)
        blob = source.read_bytes()
        if source.suffix == '.jsonl':
            data = [json.loads(line) for line in blob.decode('utf-8').splitlines() if line]
        else:
            data = json.loads(blob)
        exported = [project(x) for x in data] if isinstance(data, list) else project(data)
        target = destination / (relative.as_posix() + '.public.json')
        write(target, exported)
        manifest.append({'source_path': source.relative_to(app).as_posix(), 'source_sha256': sha(blob),
                         'public_path': target.relative_to(out).as_posix(), 'public_sha256': sha(target.read_bytes()),
                         'transform': 'typed field projection v1; not byte-identical to original receipt'})
    write(destination / 'PROJECTION_MANIFEST.json', manifest)
    write(destination / 'ORIGINAL_FILE_SHA256.json', [
        {'source_path': p.relative_to(app).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
        for p in sorted(run_root.rglob('*')) if p.is_file()])
    # Grid plan is projected cell-by-cell, never copied wholesale.
    grid = read(run_root / 'GRID_PLAN.json')
    write(destination / 'GRID_PLAN.public.json', {'stage': grid.get('stage'), 'planned_runs': grid.get('planned_runs'),
           'cells': [project(x) for x in grid['cells']], 'source_sha256': sha((run_root / 'GRID_PLAN.json').read_bytes())})
    return len(manifest)

def include_analysis(script, result_dir, out, formal, plot_script=None):
    """Explicit names and code-free CSV cells; no arbitrary output directory copy."""
    records = []
    target_root = out / 'analysis'
    target_root.mkdir()
    if script.name != 'analyze_application.py':
        raise ValueError('Expected the reviewed analysis script basename')
    shutil.copyfile(script, target_root / script.name)
    records.append({'source_name': script.name, 'sha256': sha(script.read_bytes()), 'kind': 'analysis_source'})
    if plot_script is not None:
        if plot_script.name != 'plot_application.py':
            raise ValueError('Expected reviewed plotting source basename')
        shutil.copyfile(plot_script, target_root / plot_script.name)
        records.append({'source_name': plot_script.name, 'sha256': sha(plot_script.read_bytes()), 'kind': 'plotting_source'})
    if result_dir is not None:
        for name in ANALYSIS_CSV:
            source = result_dir / name
            with source.open(newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            if not rows:
                raise ValueError('Empty analysis table: ' + name)
            for row in rows:
                for key, value in row.items():
                    if not re.fullmatch(r'[a-zA-Z0-9_]+', key) or value is None:
                        raise ValueError('Unexpected analysis CSV schema')
                    if value and not re.fullmatch(r'[A-Za-z0-9_./:+|\-]+', value):
                        raise ValueError('Unexpected free text in analysis CSV')
            if formal and name == 'S9_runs.csv' and len(rows) != 144:
                raise ValueError('Formal analysis requires all 144 run rows')
            shutil.copyfile(source, target_root / name)
            records.append({'source_name': name, 'sha256': sha(source.read_bytes()), 'rows': len(rows), 'kind': 'code_free_analysis_table'})
        source = result_dir / 'SOURCE_MANIFEST.json'
        hashes = read(source)
        if not all(isinstance(k, str) and re.fullmatch(r'[A-Za-z0-9_./-]+', k)
                   and isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for k, v in hashes.items()):
            raise ValueError('Unexpected analysis source manifest')
        shutil.copyfile(source, target_root / 'SOURCE_MANIFEST.json')
        records.append({'source_name': source.name, 'sha256': sha(source.read_bytes()), 'kind': 'original_analysis_input_hashes'})
    write(target_root / 'PUBLIC_ANALYSIS_PROVENANCE.json', {'files': records,
          'raw_analysis_reproduction': 'Original analyze_application.py uses author-held SQLite/raw records. Public projections and CSVs support preserved-field checks; complete result_hash verification requires private originals.',
          'summary_policy': 'S9_SUMMARY.json is not copied automatically; all four explicitly checked CSVs are retained.'})

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=HERE.parent)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, action='append', default=[])
    parser.add_argument('--formal', action='store_true', help='Require pinned freeze and a completed 144-cell evaluation')
    parser.add_argument('--analysis-script', type=Path)
    parser.add_argument('--analysis-output', type=Path)
    parser.add_argument('--plot-script', type=Path)
    args = parser.parse_args()
    app = args.app_root.resolve()
    out = args.out.resolve()
    out.relative_to(HERE)  # Packaging outputs remain within assigned public/.
    if out.exists():
        raise FileExistsError('Fresh output directory required')
    run_roots = [(p if p.is_absolute() else app / p).resolve() for p in args.run_root]
    completed = [completed_grid(app, p) for p in run_roots]
    freeze_report = verify_frozen(app) if args.formal else None
    if args.formal:
        formal_grids = [p for p, summary in zip(run_roots, completed) if summary.get('stage') == 'evaluation']
        if len(formal_grids) != 1 or completed_grid(app, formal_grids[0]).get('observed_runs') != 144:
            raise ValueError('Exactly one completed 144-cell formal grid required')
        grid = read(formal_grids[0] / 'GRID_PLAN.json')
        if grid['protocol_sha256'] != PROTOCOL_SHA:
            raise ValueError('Formal grid protocol binding differs')
    if (args.analysis_output or args.plot_script) and not args.analysis_script:
        raise ValueError('--analysis-output/--plot-script require the reviewed --analysis-script')
    catalog_path = app / 'workload/catalog.json'
    if sha(catalog_path.read_bytes()) != CATALOG_SHA:
        raise ValueError('Frozen catalog changed')
    catalog = read(catalog_path)
    actual_manifest = {p: sha((app / 'workload' / p).read_bytes()) for p in catalog['runner_manifest']}
    if actual_manifest != catalog['runner_manifest'] or sha(canonical(actual_manifest)) != RUNNER_SHA:
        raise ValueError('Frozen runner changed')
    out.mkdir(parents=True)
    copy_list = FIXED_FILES + HISTORY_FILES + [p.relative_to(app).as_posix() for p in (app / 'legacy/end_to_end').rglob('*.py')]
    if args.formal:
        copy_list += ['FINAL_PROTOCOL.json', 'FREEZE_MANIFEST.json']
        protocol = read(app / 'FINAL_PROTOCOL.json')
        missing = set(protocol['source_hashes']) - set(copy_list)
        if missing:
            raise ValueError('Frozen source omitted from explicit whitelist: ' + repr(sorted(missing)))
    for relative in sorted(set(copy_list)):
        source = app / relative
        target = out / 'application' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for name in ('reconstruct_catalog.py', 'build_public.py', 'review_frozen.py', 'check_public.py', 'README.md'):
        shutil.copyfile(HERE / name, out / name)
    template = {**catalog, 'jobs': [{k: v for k, v in j.items() if k not in ('solution', 'test')} for j in catalog['jobs']]}
    if content_fields(template):
        raise ValueError('Source field remains in metadata template')
    write(out / 'metadata/catalog_template.json', template)
    write(out / 'metadata/SOURCE_PATH_AUDIT.json', audit_paths(app, run_roots))
    copied_manifest = {relative: sha((app / relative).read_bytes()) for relative in sorted(set(copy_list))}
    write(out / 'metadata/TRUSTED_SOURCE_FILES.json', copied_manifest)
    projections = sum(export_run(app, p, out) for p in run_roots)
    if freeze_report:
        write(out / 'metadata/FREEZE_REVIEW.json', freeze_report)
    if args.analysis_script:
        include_analysis(args.analysis_script.resolve(), args.analysis_output.resolve() if args.analysis_output else None,
                         out, args.formal, args.plot_script.resolve() if args.plot_script else None)
    write(out / 'metadata/PROVENANCE.json', {
        'runner_sha256': RUNNER_SHA, 'full_private_catalog_sha256': CATALOG_SHA,
        'source_archive_sha256': catalog['source_archive_sha256'],
        'candidate_source_redistribution_license': 'unspecified; candidate code excluded',
        'candidate_source_recipe': 'application/workload/sources/candidate_download_recipe.json',
        'official_tests_license': 'MIT; application/workload/sources/HUMANEVAL_LICENSE',
        'all_tasks_previously_exposed': True, 'candidate_code_executed_by_packager': False,
        'projected_result_files': projections,
        'frozen_protocol_present_at_build': (app / 'FINAL_PROTOCOL.json').exists(),
        'protocol_policy': 'Formal mode includes reviewed pinned FINAL_PROTOCOL/FREEZE_MANIFEST and verifies every source byte. Independent audit output still requires explicit metadata review.',
        'formal_mode': args.formal, 'protocol_sha256': PROTOCOL_SHA if args.formal else None})
    inventory = [{'path': p.relative_to(out).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                 for p in sorted(out.rglob('*')) if p.is_file()]
    write(out / 'PUBLIC_INVENTORY.json', inventory)
    print(json.dumps({'bundle': str(out), 'files_before_inventory': len(inventory), 'projected_result_files': projections,
                      'runner_sha256': RUNNER_SHA, 'catalog_sha256': CATALOG_SHA,
                      'candidate_code_executed': False}, sort_keys=True))

if __name__ == '__main__':
    main()
