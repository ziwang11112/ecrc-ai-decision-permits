"""Add reviewed result prose, aggregate audit fields and figures to a local bundle.

No arbitrary raw audit records are copied. No candidate or service executes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')

def numbers(mapping):
    if not isinstance(mapping, dict) or not all(isinstance(k, str) and type(v) in (int, float) and math.isfinite(v) for k,v in mapping.items()):
        raise ValueError('Expected aggregate numeric audit mapping')
    return mapping

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--qa-root', type=Path, required=True)
    a = p.parse_args()
    bundle = a.bundle.resolve(); bundle.relative_to(HERE)
    qa = a.qa_root.resolve()
    if (bundle / 'FINAL_RESULTS.md').exists():
        raise FileExistsError('Addendum already exists; do not overwrite reviewed outputs')
    sources = {
        'csv_comparison': 'statistics/formal_v1/S9_COMPARISON.json',
        'raw_adapter': 'statistics/formal_v1/normalized/RAW_AUDIT.json',
        'normalized_core': 'statistics/formal_v1/core/AUDIT.json',
        'contract': 'contract/formal_contract_v1/AUDIT.json'}
    data = {k:read(qa/v) for k,v in sources.items()}
    for key, row in data.items():
        if row.get('failures', row.get('errors', [])):
            raise ValueError('Nonempty audit failures need explicit review: ' + key)
    comparison, raw, core, contract = (data[k] for k in sources)
    assert comparison['status'] == 'PASS' and raw['status'] == 'RAW_ADAPTER_PASS'
    assert core['status'] == 'NORMALIZED_CORE_PASS' and contract['verdict'] == 'PASS'
    for name, expected in comparison['compared_csv_sha256'].items():
        if name not in ('S9_runs.csv','S9_jobs.csv','S9_cells.csv','S9_paired_batches.csv'):
            raise ValueError('Unexpected audit CSV name')
        assert sha(bundle/'analysis'/name) == expected
    selected = {
        'csv_comparison': {'status': comparison['status'], 'checks': comparison['checks'], 'failure_count': 0,
            'compared_rows': numbers(comparison['compared_rows']), 'totals': numbers(comparison['totals']),
            'compared_csv_sha256': comparison['compared_csv_sha256'],
            'comparison_float_tolerance': numbers(comparison['comparison_float_tolerance']),
            'deadline_note': 'Deadline membership uses exact <= D; numeric tolerance applies only to saved float comparison.'},
        'raw_adapter': {'status': raw['status'], 'checks': raw['checks'], 'failure_count': 0,
            'runs_checked':len(raw['runs']), 'sampling_valid':raw['sampling_valid'],
            'supervisor_result_evidence_checked':raw['supervisor_result_evidence_checked'],
            'original_source_file_hash_entries':len(raw['source_files_sha256'])},
        'normalized_core': {'status':core['status'], 'checks':core['checks'], 'failure_count':0,
            'sampling_algorithm_independently_recomputed':core['coverage_limits']['sampling_algorithm_independently_recomputed'],
            'test_semantics_independently_verified':core['coverage_limits']['test_semantics_independently_verified'],
            'result_evidence_cross_checked_to_supervisor':core['coverage_limits']['result_evidence_cross_checked_to_supervisor'],
            'original_normalized_input_hash_entries':len(core['input_files_sha256'])},
        'contract': {'status':contract['verdict'], 'checks':contract['checks'], 'failure_count':0,
            'protocol_sha256':contract['protocol_sha256'], 'check_categories':numbers(contract['check_categories']),
            'totals':numbers(contract['totals']), 'drain_count':contract['drain_count'],
            'timeout_count':contract['timeout_count'], 'max_final_held':contract['max_final_held'],
            'max_stop_held':contract['max_stop_held'], 'unique_candidate_jobs':contract['unique_candidate_jobs'],
            'candidates_observed_in_both_arms':contract['candidates_observed_in_both_arms'],
            'outcome_inconsistency_count':len(contract['outcome_inconsistencies']),
            'late_host_launches':contract['late_host_launches'], 'late_primary_feedback':contract['late_primary_feedback']}}
    for key, row in selected.items():
        row['source_path_relative_to_qa_root'] = sources[key]
        row['original_source_sha256'] = sha(qa / sources[key])
    audit = {'schema_version':1, 'audit_summaries':selected,
        'scope':'Selected aggregate fields from independent saved-evidence audits; no raw record bodies or arbitrary failure text copied.',
        'overlap':'Check counts overlap across auditors and are not independent statistical observations.',
        'not_performed':['candidate execution','model fitting','bootstrap','general-correctness proof'],
        'public_boundary':'Original-result hash checks summarized here used author-held original bytes. Public projections cannot regenerate full original result_hash after text/path removal.'}
    backup = HERE / 'PUBLIC_INVENTORY.before_addendum_v1.json'
    with backup.open('xb') as stream:
        stream.write((bundle / 'PUBLIC_INVENTORY.json').read_bytes())
    write(bundle/'audits/INDEPENDENT_AUDITS.json', audit)
    shutil.copyfile(HERE/'FINAL_RESULTS.md', bundle/'FINAL_RESULTS.md')
    shutil.copyfile(HERE/'README.md', bundle/'README.md')
    shutil.copyfile(HERE/'augment_formal.py', bundle/'augment_formal.py')
    figure_sources = []
    for name in ('S9_application_results.pdf','S9_application_results.png'):
        source = qa/'analysis_formal_v1/figures'/name
        destination = bundle/'analysis/figures'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():raise FileExistsError(destination)
        shutil.copyfile(source,destination)
        figure_sources.append({'name':name,'sha256':sha(source),'bytes':source.stat().st_size})
    write(bundle/'metadata/ADDENDUM_PROVENANCE.json', {'version':1,
        'prior_public_inventory_sha256':sha(backup),
        'audit_summary':'audits/INDEPENDENT_AUDITS.json','figures':figure_sources,
        'result_prose_sha256':sha(bundle/'FINAL_RESULTS.md'),
        'augmentation_script_sha256':sha(bundle/'augment_formal.py'),
        'candidate_code_executed':False,'source_and_freeze_files_modified':False,
        'source_summary_sha256':sha(qa/'analysis_formal_v1/S9_SUMMARY.json')})
    inventory = [{'path':x.relative_to(bundle).as_posix(),'bytes':x.stat().st_size,'sha256':sha(x)}
                 for x in sorted(bundle.rglob('*')) if x.is_file() and x.name != 'PUBLIC_INVENTORY.json']
    # The previous inventory is preserved outside the distributable bundle.
    with (bundle/'PUBLIC_INVENTORY.json').open('w',encoding='utf-8',newline='\n') as stream:
        json.dump(inventory,stream,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps({'bundle':str(bundle),'inventory_entries':len(inventory),
                      'inventory_sha256':sha(bundle/'PUBLIC_INVENTORY.json'),
                      'candidate_code_executed':False},sort_keys=True))

if __name__ == '__main__':
    main()
