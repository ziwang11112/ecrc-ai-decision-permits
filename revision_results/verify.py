"""Recompute revision tables from saved scalar evidence. No model or candidate runs."""
import ast
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE / 'primary'))
from calculations import cell_rows, analyses, external_bounds


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readcsv(path, typed=True):
    rows = list(csv.DictReader(path.read_text(encoding='utf-8-sig').splitlines()))
    if typed:
        for row in rows:
            for key, value in row.items():
                try:
                    parsed = ast.literal_eval(value)
                    if type(parsed) in (int, float, bool):
                        row[key] = parsed
                except (ValueError, SyntaxError):
                    pass
    return rows


def equal(actual, expected, label):
    if isinstance(actual, list):
        assert len(actual) == len(expected), label
        for i, (a, e) in enumerate(zip(actual, expected)):
            equal(a, e, label + ':' + str(i))
    elif isinstance(actual, dict):
        assert set(actual) == set(expected), (label, set(actual) ^ set(expected))
        for key in actual:
            equal(actual[key], expected[key], label + '.' + key)
    elif type(actual) in (int, float) and type(expected) in (int, float):
        assert math.isfinite(actual) and math.isfinite(expected), label
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (label, actual, expected)
    else:
        assert actual == expected, (label, actual, expected)


def percentile(values, q):
    values = sorted(values)
    position = (len(values)-1)*q
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi]-values[lo])*(position-lo)


def check_primary():
    base = HERE / 'primary'
    rows = readcsv(base / 'primary_trajectory_resource_projection.csv')
    assert len(rows) == 576
    assert Counter(r['status'] for r in rows) == {'finished':559,'model_response_error':15,'turn_limit':2}
    equal(cell_rows(rows), readcsv(base/'primary_group_results.csv'), 'primary cells')
    result = analyses(rows)
    for values, name in zip(result, ('primary_recomputed_metrics.csv', 'primary_recomputed_contrasts.csv',
            'primary_error_completion_sensitivity.csv', 'primary_leave_one_batch_influence.csv',
            'primary_leave_one_batch_summary.csv')):
        equal(values, readcsv(base/name), name)
    equal([r for r in rows if r['status'] != 'finished'], readcsv(base/'primary_termination_details.csv'), 'terminations')
    external = readcsv(REPO/'online_results/external_trajectory_scalars.csv', typed=False)
    external_cells, contrasts = external_bounds(external)
    equal(external_cells, readcsv(base/'external_missing_endpoint_bounds.csv'), 'external bounds')
    equal(contrasts, readcsv(base/'external_missing_contrast_bounds.csv'), 'external contrast bounds')
    return {'trajectories':576, 'groups':12, 'terminations':17, 'paired_contrasts':24,
            'batch_resamples':10000, 'sensitivity_rows':8, 'batch_omission_rows':192}


def check_local_runtime():
    base = HERE / 'local_runtime'
    raw = readcsv(base/'request_timings.csv')
    runs = readcsv(base/'benchmark_runs.csv')
    summary = readcsv(base/'benchmark_summary.csv')
    assert len(raw) == 6000 and len(runs) == 30 and len(summary) == 6
    assert json.loads((base/'FAILURES.json').read_text()) == []
    for r in runs:
        group = [x for x in raw if all(x[k] == r[k] for k in ('arm','run','phase'))]
        assert len(group) == r['n_requests'] == 200
        assert len({x['request_index'] for x in group}) == len({x['permit_id'] for x in group}) == 200
        values = [x['latency_ms'] for x in group]
        for x in group:
            equal(x['latency_ms'], (x['ended_ns']-x['started_ns'])/1e6, 'elapsed latency')
        for label, value in (('p50', percentile(values,.5)), ('p95',percentile(values,.95)),
                             ('min',min(values)),('max',max(values))):
            equal(r['request_' + label + '_ms'], value, 'run ' + label)
        assert r['held'] == 210 and r['spent'] == r['intents'] == r['receipts'] == 0
        assert r['state_checks_passed'] is True
    for s in summary:
        group = [r for r in runs if (r['arm'],r['phase']) == (s['arm'],s['phase'])]
        assert len(group) == s['runs'] == 5
        for q in ('p50','p95'):
            values = [r['request_' + q + '_ms'] for r in group]
            for name, value in (('median',statistics.median(values)),('min',min(values)),('max',max(values))):
                equal(s['request_' + q + '_ms_across_run_' + name], value, 'across runs')
    boundaries = readcsv(base/'boundary_summary.csv')
    traces = list((base/'boundary').glob('*/trace.json'))
    assert len(boundaries) == len(traces) == 14
    when = lambda text: datetime.fromisoformat(text.replace('Z','+00:00'))
    for path in traces:
        trace = json.loads(path.read_text())
        assert trace['passed'] is True and trace['service_dispatch_performed'] is False
        state = trace['state']
        assert state['request_count'] == state['permit_count'] == 1
        assert state['spent'] == state['receipt_count'] == 0
        row = next(r for r in boundaries if (r['arm'],r['case'],r['repetition']) ==
                   (trace['arm'],trace['case'],trace['repetition']))
        for field, key in (('held','held'),('spent','spent'),('intents','intent_count'),('receipts','receipt_count')):
            equal(row[field], state[key], 'boundary summary')
        events = trace['events']
        if trace['case'] == 'lock_crosses_expiry':
            expiry = when(trace['expiry'])
            assert when(events['supplied_at']) < expiry < when(events['release_started']['utc'])
            assert expiry < when(events['lock_acquired']['utc']) <= when(events['commit_returned']['utc']) <= when(events['returned']['utc'])
            assert events['job']['armed_at'] == events['supplied_at']
            assert state['held'] == state['intent_count'] == 1
        elif trace['case'] == 'arm_before_cleanup_revocation':
            assert events['original_job'] == events['repeated_job']
            assert state['held'] == state['intent_count'] == 1
        elif trace['case'] == 'cleanup_before_arm':
            assert state['held'] == state['intent_count'] == 0
            assert trace['expected_error'] is not None
        else:
            assert state['held'] == 1 and state['intent_count'] == 0 and trace['expected_error'] is not None
    return {'timed_requests':6000,'runs':30,'summary_rows':6,'boundary_traces':14,
            'scope':'Saved timing recomputation and trace consistency; original SQLite snapshots are not included.'}


def main():
    manifest = json.loads((HERE/'MANIFEST.json').read_text())
    for name, expected in manifest['files_sha256'].items():
        assert sha(HERE/name) == expected, 'Checksum mismatch: ' + name
    for row in json.loads((HERE/'PROVENANCE.json').read_text())['files']:
        assert sha(HERE/row['path']) == row['public_sha256'], row['path']
    process = subprocess.run([sys.executable,'-B',str(HERE/'budget_study/reproduce.py')],
                             capture_output=True,text=True,check=True)
    formal = json.loads(process.stdout)
    assert formal['verified'] is True
    primary, runtime = check_primary(), check_local_runtime()
    with tempfile.TemporaryDirectory(prefix='ecrc-review-tables-') as temporary:
        subprocess.run([sys.executable,'-B',str(HERE/'build_review_tables.py'),
                        '--r1-data',str(HERE/'budget_study'),
                        '--primary-contrasts',str(HERE/'primary/primary_recomputed_contrasts.csv'),
                        '--out',temporary],capture_output=True,text=True,check=True)
        for expected in sorted((HERE/'review_tables').glob('*.csv')):
            assert expected.read_bytes() == (Path(temporary)/expected.name).read_bytes(), expected.name
    print(json.dumps({'verified':True,'budget_study':formal,'primary_reanalysis':primary,
                      'local_runtime':runtime,'review_tables_recomputed':4,
                      'model_calls':0,'candidate_executions':0},indent=2))


if __name__ == '__main__':
    main()
