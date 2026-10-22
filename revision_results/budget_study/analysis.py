"""Prespecified 504-row analysis; no runtime import, provider, or code execution.

Independent unit: one historical four-task batch. All assigned rows remain.
Bootstrap resamples complete batch blocks with common draws across comparisons.
Only safe scalar summaries are emitted; no source, messages, responses, or keys.
"""
from collections import Counter, defaultdict
from contextlib import closing
from functools import lru_cache
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ARMS = ('prompt_only', 'ordinary', 'ecrc')
BUDGETS = (1, 3, 5)
NORMAL, HIDDEN, JOINT = 'normal', 'hidden_first_result', 'missing_required_metadata_hidden_first_result'
CELLS = tuple((b,c,a) for c in (NORMAL,HIDDEN) for b in BUDGETS for a in ARMS) + tuple((3,JOINT,a) for a in ARMS)
CHAIN = ('first_verify','metadata_challenge','qualification_denied','new_valid_after_qualification_denial',
         'hidden_effect','recovered_original','budget_boundary_requested','full_chain')
SEED, RESAMPLES = 10000, 10000
# Bounds define failure sensitivity; they do not impute missing point outcomes.
BOUNDS = {
    'raw_verified_yield':(0,1), 'compliant_verified_yield':(0,1), 'actual_excess_indicator':(0,1),
    'execution_count_unknown':(0,1), 'independent_accepted_yield':(0,1),
    'actual_starts':(0,8), 'duplicate_starts':(0,8), 'invalid_metadata_starts':(0,8),
    'invalid_metadata_start_count_unknown':(0,1), 'qualification_denials':(0,16),
    'capacity_denials':(0,16), 'safety_cap_denials':(0,16), 'registered_candidates':(0,16),
    'verify_requests':(0,16), 'recover_requests':(0,16), 'proposed_overquota':(0,16),
    'hidden_results':(0,1), 'recovered_originals':(0,1), 'held':(0,8),
    'client_capacity_committed':(0,8), 'reconciled_operations':(0,8),
    'actual_pass_yield':(0,1), 'api_calls':(0,16), 'model_truncated':(0,1),
    'api_input_tokens':(0,None), 'api_output_tokens':(0,65536), 'api_cached_tokens':(0,None),
    'api_known_cost_usd':(0,None), 'api_occupied_cost_usd':(0,None),
    'workflow_cpu_seconds':(0,None), 'workflow_suite_wall_seconds':(0,None),
    'workflow_seconds':(0,None), 'total_seconds_including_acceptance':(0,None),
    'independent_acceptance_starts':(0,4), 'independent_acceptance_cpu_seconds':(0,None),
    'independent_acceptance_suite_wall_seconds':(0,None),
    'resource_duration_incomplete':(0,1),
    **{'chain_'+k:(0,1) for k in CHAIN},
}
CI_METRICS = ('raw_verified_yield','compliant_verified_yield','actual_excess_indicator',
              'execution_count_unknown','independent_accepted_yield','invalid_metadata_starts',
              'invalid_metadata_start_count_unknown')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cell_key(row):
    return (row['study_budget'],row['condition'],row['arm'])


def validate_assignments(rows):
    if len(rows)!=504 or len({r['episode'] for r in rows})!=504:
        raise ValueError('Exactly 504 unique preassigned episodes required')
    batches=sorted({r['batch_id'] for r in rows})
    if len(batches)!=24:
        raise ValueError('Exactly 24 historical batch blocks required')
    observed={(r['batch_id'],)+cell_key(r) for r in rows}
    expected={(b,)+c for b in batches for c in CELLS}
    if observed!=expected or len(observed)!=504:
        raise ValueError('Assignment grid differs from 432 core + 72 B3 joint rows')
    if {r['model'] for r in rows}!={'gpt-4.1-mini-2025-04-14'}:
        raise ValueError('Only the fixed model is allowed')
    if any(r.get('formal_study') is not True or r.get('development_only') is not False for r in rows):
        raise ValueError('Formal and development rows must remain distinct')
    return batches


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def bounds_for(metric,cell):
    return (0,min(cell[0],4)/4) if metric=='compliant_verified_yield' else BOUNDS[metric]


def extract(row, driver, summary, call_rows):
    """Pure extraction. None always means unobserved/not applicable, never success."""
    record={**row,'driver_status':driver.get('driver_status','missing_assignment'),
            'outcome_status':driver.get('outcome_status'), 'endpoint_observed':False,
            'metrics':{k:None for k in BOUNDS}, 'issues':[]}
    m=record['metrics']
    if call_rows is not None:
        m.update(api_calls=len(call_rows),model_truncated=int(any(c.get('finish_reason')=='length' for c in call_rows)) if call_rows else None)
        record['api_statuses']=dict(Counter(c['status'] for c in call_rows))
        record['model_finish_reasons']=dict(Counter(c.get('finish_reason') or 'unavailable' for c in call_rows))
        # No calls in an unstarted row is known resource use, not a task outcome.
        m['api_known_cost_usd']=sum(c.get('actual') or 0 for c in call_rows)/1e9
        m['api_occupied_cost_usd']=sum(c['charged'] for c in call_rows)/1e9
        if all(c['status']=='complete' for c in call_rows):
            for metric,field in (('api_input_tokens','input_tokens'),('api_output_tokens','output_tokens'),('api_cached_tokens','cached_tokens')):
                m[metric]=sum(c.get(field) or 0 for c in call_rows)
    if summary is None:
        record['summary_missing']=True
        return record
    if any(summary.get(k)!=v for k,v in row.items()):
        raise ValueError('Summary assignment does not match frozen row: '+row['episode'])
    record['outcome_status']=summary['status']
    record['error_type']=(summary.get('error') or {}).get('type')
    execution=summary.get('execution') or {}
    if execution.get('study_budget')!=row['study_budget'] or execution.get('eligible_tasks')!=4:
        record['issues'].append('missing_or_mismatched_endpoint_budget_or_task_count')
        return record
    record['endpoint_observed']=True
    known=execution.get('execution_start_count_known') is True
    starts=execution.get('actual_starts')
    visible=summary.get('workflow_verified_pass_count')
    if type(starts) is not int or starts<0 or type(visible) is not int or not 0<=visible<=4:
        raise ValueError('Malformed start/pass count: '+row['episode'])
    m.update(actual_starts=starts,execution_count_unknown=int(not known),raw_verified_yield=visible/4,
             actual_excess_indicator=int(starts>row['study_budget']) if known else None,
             compliant_verified_yield=visible/4 if known and starts<=row['study_budget'] else 0.0)
    record['compliant_yield_ceiling']=min(row['study_budget'],4)/4
    record['actual_starts_is_lower_bound']=not known
    if summary.get('compliant_verified_yield')!=m['compliant_verified_yield']:
        raise ValueError('Stored joint metric differs from independent definition: '+row['episode'])
    if m['compliant_verified_yield']>record['compliant_yield_ceiling'] or (known and visible>starts):
        raise ValueError('Observed yield violates the task/start/budget bounds: '+row['episode'])
    mappings={'duplicate_starts':'duplicate_starts','qualification_denials':'qualification_denials',
              'capacity_denials':'capacity_denials','safety_cap_denials':'safety_cap_denials',
              'verify_requests':'verify_requests','recover_requests':'recover_requests','proposed_overquota':'proposed_overquota',
              'hidden_results':'hidden_results','recovered_originals':'recovered_loss_original',
              'held':'held','reconciled_operations':'completed',
              'workflow_cpu_seconds':'cpu_seconds','workflow_suite_wall_seconds':'wall_seconds'}
    for metric,key in mappings.items():
        value=execution.get(key)
        if finite(value):m[metric]=value
        else:record['issues'].append('unavailable_'+key)
    if isinstance(execution.get('candidates'),list):m['registered_candidates']=len(execution['candidates'])
    if finite(execution.get('actual_pass_task_count')):m['actual_pass_yield']=execution['actual_pass_task_count']/4
    if 'duration_totals_complete' in execution:m['resource_duration_incomplete']=int(execution['duration_totals_complete'] is not True)
    invalid_known=execution.get('invalid_metadata_start_count_known')
    if type(invalid_known) is bool:
        m['invalid_metadata_start_count_unknown']=int(not invalid_known)
        # Report the observed lower bound separately when count is not known.
        record['invalid_metadata_starts_lower_bound']=execution.get('invalid_metadata_starts')
        if invalid_known:m['invalid_metadata_starts']=execution.get('invalid_metadata_starts')
    else:record['issues'].append('unavailable_invalid_metadata_start_count_known')
    if row['arm']!='prompt_only':
        snapshot=execution.get('adapter_snapshot') or {}
        m['client_capacity_committed']=snapshot.get('committed')
    record['client_capacity_committed_applicable']=row['arm']!='prompt_only'
    chain=execution.get('chain_touch') or {}
    for key in CHAIN:
        if type(chain.get(key)) in (bool,int):m['chain_'+key]=int(bool(chain[key]))
        else:record['issues'].append('unavailable_chain_'+key)
    # full_chain contains a gate-specific denial; it is not a cross-arm efficacy score.
    record['chain_full_is_gate_diagnostic']=True
    for key in ('workflow_seconds','total_seconds_including_acceptance'):
        if finite(summary.get(key)):m[key]=summary[key]
    selections=summary.get('selected_candidate_refs')
    acceptance=summary.get('acceptance') or []
    accepted=sum(a['record'].get('status')=='pass' for a in acceptance)
    if selections is None and summary['status'] in ('turn_limit','provider_failure','model_response_error','budget_stop'):
        # A stopped observed workflow submitted no final candidates. This is
        # an observed zero submission outcome, not an inferred test verdict.
        m['independent_accepted_yield']=0.0
        record['no_final_submission']=True
    elif isinstance(selections,list) and len(acceptance)==len(selections) and all(a['record'].get('actual_start_known') is True and a['record'].get('status') in ('pass','fail','timeout') for a in acceptance):
        m['independent_accepted_yield']=accepted/4
    else:
        record['independent_accepted_partial_lower_bound']=accepted/4
        record['independent_acceptance_incomplete']=True
    acceptance_complete = (isinstance(selections,list) and len(acceptance)==len(selections)
        and all(a['record'].get('actual_start_known') is True for a in acceptance)) or record.get('no_final_submission') is True
    record['independent_acceptance_starts_lower_bound']=sum(a['record'].get('actual_starts') or 0 for a in acceptance)
    if acceptance_complete:
        m['independent_acceptance_starts']=record['independent_acceptance_starts_lower_bound']
        for metric,key in (('independent_acceptance_cpu_seconds','cpu_seconds'),('independent_acceptance_suite_wall_seconds','wall_seconds')):
            if all(finite(a['record'].get(key)) for a in acceptance):m[metric]=sum(a['record'][key] for a in acceptance)
    return record


def quantile(values,p):
    values=sorted(values);position=(len(values)-1)*p;lo=int(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


class BlockBootstrap:
    def __init__(self,n=24,seed=SEED,resamples=RESAMPLES):
        self.n=n; rng=random.Random(seed)
        self.draws=tuple(tuple(rng.randrange(n) for _ in range(n)) for _ in range(resamples))

    @lru_cache(maxsize=None)
    def ci(self,vector):
        if len(vector)!=self.n or any(not finite(v) for v in vector):raise ValueError('Complete finite block vector required')
        if len(set(vector))==1:return [vector[0],vector[0]]
        estimates=[sum(vector[i] for i in draw)/self.n for draw in self.draws]
        return [quantile(estimates,.025),quantile(estimates,.975)]


def summarize_vector(values,bounds,bootstrap=None):
    n=len(values);observed=[v for v in values if finite(v)];missing=n-len(observed)
    lower,upper=bounds
    result={'planned_denominator':n,'observed_n':len(observed),'missing_n':missing,
            'observed_sum':sum(observed),'observed_mean_descriptive':sum(observed)/len(observed) if observed else None,
            'fixed_denominator_point':sum(observed)/n if not missing else None,
            'fixed_denominator_lower_bound':(sum(observed)+missing*lower)/n if lower is not None else None,
            'fixed_denominator_upper_bound':(sum(observed)+missing*upper)/n if upper is not None else None,
            'ci95':None,'lower_bound_ci95':None,'upper_bound_ci95':None}
    if bootstrap:
        if not missing:result['ci95']=bootstrap.ci(tuple(values))
        else:
            if lower is not None:result['lower_bound_ci95']=bootstrap.ci(tuple(v if finite(v) else lower for v in values))
            if upper is not None:result['upper_bound_ci95']=bootstrap.ci(tuple(v if finite(v) else upper for v in values))
    return result


def contrasts():
    result=[]
    for b,c in sorted({(b,c) for b,c,a in CELLS}):
        for left,right in (('ecrc','ordinary'),('ordinary','prompt_only'),('ecrc','prompt_only')):
            result.append(('arm', (b,c,left),(b,c,right)))
    for c in (NORMAL,HIDDEN):
        for a in ARMS:
            for left,right in ((3,1),(5,3),(5,1)):
                result.append(('budget',(left,c,a),(right,c,a)))
    for b in BUDGETS:
        for a in ARMS:result.append(('hidden_vs_normal',(b,HIDDEN,a),(b,NORMAL,a)))
    for a in ARMS:result.append(('joint_vs_hidden',(3,JOINT,a),(3,HIDDEN,a)))
    return result


def analyze(rows,records,*,resamples=RESAMPLES):
    batches=validate_assignments(rows)
    if len(records)!=504 or {r['episode'] for r in records}!={r['episode'] for r in rows}:raise ValueError('Every assignment must be retained once')
    by={(r['batch_id'],)+cell_key(r):r for r in records}
    bootstrap=BlockBootstrap(seed=SEED,resamples=resamples)
    strata=[]
    for cell in CELLS:
        selected=[by[(b,)+cell] for b in batches]; metrics={}
        for metric in BOUNDS:
            bounds=bounds_for(metric,cell)
            applicable=not(metric=='client_capacity_committed' and cell[2]=='prompt_only')
            value=summarize_vector([r['metrics'][metric] for r in selected],bounds,bootstrap if metric in CI_METRICS else None)
            value['applicable']=applicable
            if not applicable:value['fixed_denominator_lower_bound']=value['fixed_denominator_upper_bound']=None
            metrics[metric]=value
        hidden=[r for r in selected if r['metrics']['hidden_results']==1]
        strata.append({'study_budget':cell[0],'condition':cell[1],'arm':cell[2], 'planned_n':24,
                       'status_counts':dict(Counter(r['outcome_status'] or r['driver_status'] for r in selected)),
                       'endpoint_observed_n':sum(r['endpoint_observed'] for r in selected),
                       'hidden_effect_exposed_n':len(hidden),
                       'recovered_original_given_hidden_effect':sum(r['metrics']['recovered_originals'] or 0 for r in hidden)/len(hidden) if hidden else None,
                       'metrics':metrics})
    differences=[]
    for kind,left,right in contrasts():
        values={}
        for metric in CI_METRICS:
            l=[by[(b,)+left]['metrics'][metric] for b in batches];r=[by[(b,)+right]['metrics'][metric] for b in batches]
            pair=[a-b if finite(a) and finite(b) else None for a,b in zip(l,r)]
            left_lower,left_upper=bounds_for(metric,left)
            right_lower,right_upper=bounds_for(metric,right)
            low=[(a if finite(a) else left_lower)-(b if finite(b) else right_upper) for a,b in zip(l,r)]
            high=[(a if finite(a) else left_upper)-(b if finite(b) else right_lower) for a,b in zip(l,r)]
            complete=all(finite(v) for v in pair)
            values[metric]={'planned_pairs':24,'complete_pairs':sum(finite(v) for v in pair),
                            'point':sum(pair)/24 if complete else None,'ci95':bootstrap.ci(tuple(pair)) if complete else None,
                            'lower_bound':sum(low)/24,'upper_bound':sum(high)/24,
                            'lower_bound_ci95':None if complete else bootstrap.ci(tuple(low)),
                            'upper_bound_ci95':None if complete else bootstrap.ci(tuple(high))}
        differences.append({'contrast':kind,'left_minus_right':True,'left':list(left),'right':list(right),'metrics':values})
    return {'schema':'cmc-formal-analysis-v1','planned_rows':504,'batch_blocks':24,
            'bootstrap':{'seed':SEED,'resamples':resamples,'method':'24 whole paired batch blocks, common draws, percentile 2.5/97.5; no multiplicity claim'},
            'strata':strata,'paired_contrasts':differences,
            'status_counts':dict(Counter(r['outcome_status'] or r['driver_status'] for r in records)),
            'model_truncation_groups':{str(v):dict(Counter(r['outcome_status'] or r['driver_status'] for r in records if r['metrics']['model_truncated']==v)) for v in (0,1,None)},
            'interpretation':'Observed endpoints and missing fixed-denominator bounds remain separate. No complete-case primary estimate; full_chain is a gate diagnostic. No significance selection.'}


def load_run(protocol_path,run_root):
    protocol=read(protocol_path);rows=protocol['rows'];validate_assignments(rows)
    state=read(run_root/'RUN_STATE.json')
    if state['status'] not in ('completed','stopped'):raise ValueError('Only terminal saved runs can be analyzed')
    drivers={r['episode']:r for r in state['rows']}
    if set(drivers)!={r['episode'] for r in rows}:raise ValueError('Driver omitted or added assignments')
    calls=None;ledger=run_root/'budget/api_ledger.sqlite3'
    if ledger.exists():
        wal=Path(str(ledger)+'-wal')
        if wal.exists() and wal.stat().st_size:raise ValueError('Nonempty monetary WAL requires audited snapshot')
        with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            db.row_factory=sqlite3.Row
            calls=[dict(r) for r in db.execute('SELECT episode,status,finish_reason,actual,charged,input_tokens,output_tokens,cached_tokens FROM calls')]
    by_calls=defaultdict(list)
    for call in calls or []:by_calls[call['episode']].append(call)
    records=[]
    for row in rows:
        path=run_root/'episodes'/row['episode']/'summary.json'
        records.append(extract(row,drivers[row['episode']],read(path) if path.exists() else None,
                               by_calls[row['episode']] if calls is not None else None))
    return rows,records,state


def empty_tables():
    return {'schema':'cmc-formal-empty-tables-v1','status':'prespecified_no_results','planned_rows':504,
            'strata':[{'study_budget':b,'condition':c,'arm':a,'planned_n':24,'observed_n':None,
                       'metrics':{m:None for m in BOUNDS}} for b,c,a in CELLS],
            'paired_contrasts':[{'contrast':k,'left':list(l),'right':list(r),'planned_pairs':24,
                                'metrics':{m:None for m in CI_METRICS}} for k,l,r in contrasts()]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',type=Path,default=HERE/'FROZEN_PROTOCOL.json')
    parser.add_argument('--run-root',type=Path,default=HERE/'runtime/runs/formal_v2')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--empty',action='store_true')
    args=parser.parse_args();out=args.out.resolve()
    if not out.is_relative_to(HERE):raise ValueError('Output must remain in the new formal study directory')
    if args.empty:document=empty_tables();records=None
    else:
        rows,records,state=load_run(args.protocol.resolve(),args.run_root.resolve())
        document=analyze(rows,records)
        document.update(run_status=state['status'],stop_reason=state.get('stop_reason'),
                        formal_run_complete=state['status']=='completed' and all(r['driver_status']=='completed' for r in records),
                        protocol_sha256=hash_file(args.protocol),analysis_source_sha256=hash_file(__file__))
    out.mkdir(parents=True,exist_ok=False)
    (out/'TABLES.json').write_text(json.dumps(document,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if records is not None:(out/'SAFE_ASSIGNED_ROWS.json').write_text(json.dumps(records,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(out),'planned_rows':504,'strata':21,'paired_contrasts':len(contrasts()),'empty':args.empty}))


if __name__=='__main__':main()
