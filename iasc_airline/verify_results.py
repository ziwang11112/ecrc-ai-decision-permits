"""Offline stdlib-only S11 integrity, independent qualification and count checks."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
ARMS=('direct_native_dispatch','qualification_ecrc','existing_rules_only','without_claim_evidence_requirement')
PHASES={'original_first100':(300,(59,59,182)), 'fixed_next100':(300,(70,58,172)), 'constructed_boundaries':(16,(5,5,6))}
FIELDS=('selected_candidate_count','eligible_count','ineligible_count','unresolved_candidate_count',
        'eligible_completed','eligible_missed','ineligible_executed','unresolved_executed')

def read(path):
    if path.suffix=='.gz': return json.loads(gzip.decompress(path.read_bytes()))
    return json.loads(path.read_text(encoding='utf-8'))
def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(data): return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def check(condition,message):
    if not condition: raise ValueError(message)

def verify_integrity():
    records=read(ROOT/'SOURCE_PROVENANCE.json')['copied_files']
    frozen={}
    for metadata in sorted((ROOT/'provenance').glob('*/FREEZE_METADATA.json')):
        frozen.update(read(metadata)['original_sources'])
    for item in records:
        data=(ROOT/item['path']).read_bytes()
        check(len(data)==item['bytes'] and sha(data)==item['sha256'],'Packaged source changed: '+item['path'])
        if 'source_sha256' in item: check(sha(gzip.decompress(data))==item['source_sha256'],'Lossless source mismatch: '+item['path'])
        elif item['source_workspace_relative_path'] in frozen:
            check(item['sha256']==frozen[item['source_workspace_relative_path']],'Original pre-run freeze mismatch: '+item['path'])
    return len(records)

def apply_patch(base,patch):
    result=deepcopy(base)
    for op in patch['operations']:
        parent=result
        for key in op['path'][:-1]: parent=parent[key]
        key=op['path'][-1]
        check(parent[key]==op['before'],'Fixture patch precondition failed')
        parent[key]=deepcopy(op['after'])
    return result

def verify():
    sys.dont_write_bytecode=True
    files=verify_integrity()
    audit_path=ROOT/'frozen/research_pilots/ecrc_permission_business_2026-09-15/independent_audit.py'
    spec=importlib.util.spec_from_file_location('saved_s11_independent_policy',audit_path)
    audit=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    base=read(ROOT/'inputs/BASE_DB.json.gz')
    index=read(ROOT/'inputs/constructed_boundaries/FIXTURE_INDEX.json')
    check(sha(canonical(base))==index['base_db']['canonical_sha256'],'Base DB mismatch')
    fixtures={entry['case_id']:entry for entry in index['fixtures']}
    missing={'no_supported_explicit_cancellation_reason','unknown_flight_status','invalid_creation_time'}
    denominators={}
    output={'verified':True,'source_files_checked':files,'new_experiment':False,'model_calls':0,'phases':{}}
    all_bookings=set()
    combined=defaultdict(Counter)
    for phase,(contexts,expected_categories) in PHASES.items():
        requests=read(ROOT/'inputs'/phase/'REQUESTS.json')['cases']
        cases={c['case_id']:c for c in requests}
        summary=read(ROOT/'results'/phase/'SUMMARY.json.gz')
        rows=summary['rows']
        expected={(cid,arm) for cid in cases for arm in ARMS}
        check(len(requests)==len(cases)==contexts,'Request count/identity mismatch')
        check(len(rows)==contexts*4 and {(r['case_id'],r['arm']) for r in rows}==expected,'Missing/duplicate/undeclared cell')
        check(not summary['technical_failure'] and not summary['matching_failure'] and summary['sources_unchanged'],'Saved technical failure')
        check(summary['model_calls']==0 and not summary['full_benchmark_run'],'Scope mismatch')
        categories={}
        bookings=set()
        reason_sets=defaultdict(set)
        for cid,case in cases.items():
            request=case['request']; clause=request['cancellation']; rid=clause['selector']['ids'][0]
            db=base
            if phase=='constructed_boundaries':
                entry=fixtures[cid]
                db=apply_patch(base,read(ROOT/'inputs/constructed_boundaries'/entry['patch_path']))
                check(sha(canonical(db))==entry['before_canonical_sha256'],'Fixture canonical hash mismatch')
            reservation=db['reservations'][rid]
            user=db['users'][request['user_id']]
            check(reservation['user_id']==request['user_id'] and rid in user['reservations'],'Ownership mismatch')
            allowed,basis=audit._cancel_rule(reservation,db,clause['reason'])
            category='eligible' if allowed else ('unresolved_required_information' if basis in missing else 'unresolved_or_transfer' if basis=='already_flown_requires_transfer' else 'ineligible')
            categories[cid]=(category,basis)
            bookings.add((request['user_id'],rid)); reason_sets[(request['user_id'],rid)].add(clause['reason'])
        if phase!='constructed_boundaries':
            check(len(bookings)==100 and not (all_bookings & bookings),'Cohort identity overlap/count mismatch')
            check(all(reasons=={'health','other','unspecified'} for reasons in reason_sets.values()),'Repeated reason grid mismatch')
            all_bookings.update(bookings)
        totals=defaultdict(Counter)
        for row in rows:
            ev=row['case_evaluation']; cid=row['case_id']; arm=row['arm']
            check(not row['execution_error'] and not row['native_errors'] and ev['metrics_valid'],'Invalid saved cell')
            check(row['model_calls']==0 and not row['full_task_success_established'] and not row['native_receipt_registered'],'Unsupported success/scope label')
            check(row['native_evaluation']['all_recorded_tool_responses_reproduced'] and row['native_evaluation']['actor_final_db_match_verified'],'Replay failure')
            check(len(ev['candidates'])==1,'Candidate grid mismatch')
            candidate=ev['candidates'][0]
            check((candidate['category'],candidate['policy_basis'])==categories[cid],'Independent qualification mismatch: '+phase+'/'+cid)
            reconstructed=Counter(selected_candidate_count=1)
            cat=candidate['category']; executed=int(candidate['executed'])
            reconstructed['eligible_count']=int(cat=='eligible')
            reconstructed['ineligible_count']=int(cat=='ineligible')
            reconstructed['unresolved_candidate_count']=int(cat.startswith('unresolved'))
            reconstructed['eligible_completed']=int(cat=='eligible')*executed
            reconstructed['eligible_missed']=int(cat=='eligible')*(1-executed)
            reconstructed['ineligible_executed']=int(cat=='ineligible')*executed
            reconstructed['unresolved_executed']=int(cat.startswith('unresolved'))*executed
            for key in FIELDS: check(reconstructed[key]==int(ev[key]),'Per-cell arithmetic mismatch: '+phase+'/'+cid+'/'+key)
            reconstructed['native_writes']=row['native_writes']
            reconstructed['missing_information_count']=int(cat=='unresolved_required_information')
            reconstructed['transfer_required_count']=int(cat=='unresolved_or_transfer')
            totals[arm].update(reconstructed)
            if phase!='constructed_boundaries': combined[arm].update(reconstructed)
        for arm in ARMS:
            t=totals[arm]
            check(tuple(t[k] for k in ('eligible_count','ineligible_count','unresolved_candidate_count'))==expected_categories,'Audited category denominator mismatch')
            check(t['eligible_completed']==expected_categories[0] and not t['eligible_missed'],'Eligible completion mismatch')
            ungated=arm in (ARMS[0],ARMS[3])
            check(t['ineligible_executed']==(expected_categories[1] if ungated else 0),'Ineligible dispatch mismatch')
            check(t['unresolved_executed']==(expected_categories[2] if ungated else 0),'Unresolved dispatch mismatch')
            check(t['native_writes']==(contexts if ungated else expected_categories[0]),'Native writes mismatch')
        for pair in summary['comparisons']:
            check(all(pair[k] for k in ('all_cells_complete','same_resolution','same_candidate_proposals','rules_full_final_db_equal','claim_off_raw_final_db_equal')),'Saved paired comparison mismatch')
        output['phases'][phase]={'contexts':contexts,'cells':len(rows),'arms':dict(totals)}
    check(len(all_bookings)==200,'Combined booking denominator mismatch')
    csv_path=ROOT/'results/supplement/combined_native_summary/COHORT_COMPARISON.csv'
    with csv_path.open(encoding='utf-8-sig',newline='') as f: table=list(csv.DictReader(f))
    pooled=[row for row in table if row['study_phase']=='combined_native_records' and not row['reason']]
    if not pooled:
        pooled=[row for row in table if row['study_phase'].startswith('combined') and not row['reason']]
    check(len(pooled)==4,'Combined published CSV grid mismatch')
    for row in pooled:
        for key in FIELDS:
            check(int(row[key])==combined[row['arm']][key],'Published CSV mismatch: '+key)
    output['primary']={'distinct_reservations':200,'request_contexts':600,'cells':2400,'eligible':129,'ineligible':117,'unresolved':354,'missing_information':200,'transfer_required':154,'arms':dict(combined)}
    boundary_csv=ROOT/'results/supplement/constructed_boundaries/CASE_METRICS.csv'
    with boundary_csv.open(encoding='utf-8-sig',newline='') as f: boundary=list(csv.DictReader(f))
    for arm in (ARMS[0],ARMS[3]):
        rows=[r for r in boundary if r['arm']==arm]
        check(sum(int(r['raw_successful_cancel_calls']) for r in rows)==16,'Boundary writes changed')
        check(sum(int(r['raw_status_transitions_to_cancelled']) for r in rows)==15,'Repeated-write distinction lost')
        check(sum(int(r['raw_repeated_cancel_calls']) for r in rows)==1,'Repeated-write count changed')
    output['boundary_raw_effect_check']={'contexts':16,'cells':64,'direct_and_ablation_writes_each':16,'new_cancelled_status_transitions_each':15,'repeated_writes_each':1}
    output['limits']='Checks archived integrity, recomputes policy categories from frozen synthetic DB/requests independently of production checker, and recounts saved execution evidence. Does not reexecute native tools or prove dialogue success.'
    return output

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    result=verify()
    content=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(content,encoding='utf-8')
    print(content,end='')

if __name__=='__main__': main()
