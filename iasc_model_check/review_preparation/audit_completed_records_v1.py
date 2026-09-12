"""Read saved v1 records and replay only the recorded 12-step negative trace.

No TLC/exact-checker import, subprocess, state-space exploration or client run.
Writes a new review artifact; never changes frozen inputs or existing runs.
"""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FREEZE_SHA = 'f88faba8a248ab51fe18bce8454776e1e57a723ca70494e022a26f71b8437a8d'

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def check(condition, message):
    if not condition:
        raise AssertionError(message)

freeze = read(HERE/'FREEZE.json')
check(sha(HERE/'FREEZE.json') == FREEZE_SHA, 'Unexpected freeze')
for name, expected in freeze['source_hashes'].items():
    check(sha(HERE/name) == expected, 'Frozen input changed: '+name)
baseline = read(HERE/'ARTIFACT_BASELINE.json')
preservation = {name: (ROOT/name).is_file() and sha(ROOT/name) == value for name,value in baseline.items()}
run = HERE/'runs/v1'
for engine in ('tlc','exact'):
    check(read(run/engine/'START.json')['freeze_sha256'] == FREEZE_SHA, 'Run freeze mismatch')

case_reports = []
for case in freeze['cases']:
    cid = case['id']
    td, ed = run/'tlc'/cid, run/'exact'/cid
    tr, er = read(td/'RESULT.json'), read(ed/'RESULT.json')
    log = (td/'stdout.txt').read_text(encoding='utf-8')
    check(sha(td/'stdout.txt') == tr['stdout_sha256'], 'stdout hash mismatch')
    check(sha(td/'stderr.txt') == tr['stderr_sha256'], 'stderr hash mismatch')
    check((td/'stderr.txt').stat().st_size == 0, 'Nonempty stderr needs investigation')
    for name in ('ECRCLifecycle.tla', cid+'.cfg'):
        check(sha(td/name) == freeze['source_hashes'][name], 'Executed source mismatch')
    for name,value in er['source_sha256'].items():
        check(value == freeze['source_hashes'][name], 'Exact source binding mismatch')
    coverage = {name: (int(a),int(b)) for name,a,b in re.findall(r'^<(\w+) line[^>]+>: (\d+):(\d+)$', log, re.M)}
    record = {'case':cid, 'tlc_status':tr['status'], 'exact_status':er['status'],
              'tlc_distinct':tr['distinct_states'], 'exact_discovered':er['unique_labeled_states_discovered'],
              'tlc_generated':tr['generated_states'], 'exact_generated':er['generated_states_including_initial'],
              'tlc_queue_remaining':tr['queue_remaining'],
              'warnings':[line for line in log.splitlines() if line.startswith('Warning:')],
              'fingerprint_estimates':[line.strip() for line in log.splitlines() if 'val =' in line],
              'tlc_seconds':tr['elapsed_seconds'], 'exact_seconds':er['search_elapsed_seconds'],
              'tlc_stdout_sha256':sha(td/'stdout.txt'), 'exact_result_sha256':sha(ed/'RESULT.json')}
    if not case['unsafe']:
        check(tr['returncode']==0 and not tr['timed_out'], 'Positive process failed')
        check(tr['status']==er['status']=='COMPLETE_PASS', 'Positive status failed')
        check('Model checking completed. No error has been found.' in log, 'Missing completion marker')
        check(tr['queue_remaining']==er['frontier_states_not_expanded']==0, 'Unfinished frontier')
        check(er['complete_reachable_graph'], 'Exact not complete')
        check(tr['distinct_states']==er['states_checked']==er['states_expanded']==er['unique_labeled_states_discovered'], 'Reachable count mismatch')
        check(tr['generated_states']==er['generated_states_including_initial'], 'Generated count mismatch')
        check(all(v==0 for v in er['invariant_violating_checked_states'].values()), 'Positive violation')
        check(er['invariant_state_check_count']==9*tr['distinct_states'], 'Invariant check count mismatch')
        for action, c in er['action_coverage'].items():
            check(coverage[action][1]==c['generated_edges'], 'Coverage edge mismatch: '+cid+'/'+action)
            check((c['generated_edges']==0)==(action=='UnsafeReleaseUnknown'), 'Uncovered normal action')
        for invariant in er['configured_invariants']:
            match=re.search(r'^<'+invariant+r' line[^>]+>\n\s+line[^:]+: (\d+)$',log,re.M)
            check(match is not None and int(match[1])==tr['distinct_states'], 'TLC invariant coverage mismatch')
        record.update(normal_action_families_covered=17, normal_action_edge_counts_match=True,
                      all_nine_invariants_checked_on_every_reachable_state=True,
                      tlc_depth_nodes=tr['reported_search_depth'],exact_depth_edges=er['maximum_discovered_shortest_path_depth_edges'])
    else:
        check(tr['status']==er['status']=='EXPECTED_COUNTEREXAMPLE', 'Negative status failed')
        check(tr['returncode']==12 and not tr['timed_out'], 'Unexpected negative process termination')
        check(all(er['invariant_violating_checked_states'][k]==0 for k in ('TypeOK','Accounting','BudgetBound')), 'Negative local invariant failure')
        check(not er['complete_reachable_graph'] and tr['queue_remaining']>0, 'Negative completeness misdescription')
        record['negative_counts_are_partial_and_not_required_equal']=True
    case_reports.append(record)

# Parse the entire printed TLC counterexample, retaining each global state.
log=(run/'tlc/unsafe_2_1/stdout.txt').read_text(encoding='utf-8')
chunks=re.findall(r'^State (\d+): <([^>]+)>\n(.*?)(?=^State \d+:|^The coverage statistics)',log,re.M|re.S)
trace=[]
for index,action,body in chunks:
    state={}
    for name,value in re.findall(r'^/\\ (\w+) = (.+)$',body,re.M):
        if value.startswith('{'):
            state[name]=[] if value=='{}' else [int(x.strip()) for x in value[1:-1].split(',')]
        elif value in ('TRUE','FALSE'):
            state[name]=value=='TRUE'
        else:
            state[name]=int(value)
    check(len(state)==16,'Incomplete printed TLC state')
    trace.append({'tlc_state_number':int(index),'action':'Init' if action=='Initial predicate' else action.split()[0],'state':state})
exact_trace=read(run/'exact/unsafe_2_1/COUNTEREXAMPLE.json')['trace']
check(len(trace)==len(exact_trace)==13,'Unexpected trace length')
initial=trace[0]['state']
check(all(v==[] for k,v in initial.items() if isinstance(v,list)),'Nonempty initial set')
check(initial['heldCount']==initial['committedCount']==0 and initial['clientUp'] and initial['sinkUp'],'Wrong initial flags/counters')
for ordinal,row in enumerate(trace):
    state=row['state']; other=exact_trace[ordinal]
    check(row['action']==other['action']['name'],'Witness action disagreement')
    check(all(value==other['state'][key] for key,value in state.items()),'Witness state disagreement')
    check(state['heldCount']==len(state['held']) and state['committedCount']==len(state['committed']),'Trace accounting mismatch')
    check(not set(state['held']) & set(state['committed']),'Trace overlap')
    check(state['heldCount']+state['committedCount']<=1,'Trace ledger exceeded capacity')
    if ordinal==0:
        continue
    prior=trace[ordinal-1]['state']
    expected={k:(v.copy() if isinstance(v,list) else v) for k,v in prior.items()}
    o=other['action']['operation']; a=row['action']
    def add(field): expected[field]=sorted(set(expected[field])|{o})
    def remove(field): expected[field]=sorted(set(expected[field])-{o})
    if a=='ReceiveRaw':
        check(prior['clientUp'] and o not in prior['received'],'Raw guard'); add('received')
    elif a=='IssueAction':
        check(prior['clientUp'] and o in prior['received'] and o not in prior['issued']+prior['denied'] and prior['heldCount']+prior['committedCount']<1,'Issue guard')
        add('issued');add('held');expected['heldCount']+=1
    elif a=='Arm':
        check(prior['clientUp'] and o in prior['issued'] and o in prior['held'] and o not in prior['armed']+prior['expired'],'Arm guard');add('armed')
    elif a=='ExpirePermit':
        check(o in prior['issued'] and o not in prior['expired'],'Expiry guard');add('expired')
    elif a=='Send':
        check(prior['clientUp'] and o in prior['armed'] and o not in prior['receipts']+prior['requests'],'Send guard');add('requests')
    elif a=='CommitEffect':
        check(prior['sinkUp'] and o in prior['requests'] and o not in prior['effects'],'Sink guard')
        add('effects');remove('requests');add('acknowledgements')
    elif a=='UnsafeReleaseUnknown':
        check(prior['clientUp'] and o in prior['expired'] and o in prior['armed'] and o in prior['held'] and o not in prior['receipts'],'Unsafe guard')
        remove('held');expected['heldCount']-=1
    else:
        raise AssertionError('Unexpected action in saved trace: '+a)
    check(expected==state,'Wrong next state at '+str(ordinal))
check(trace[7]['action']=='UnsafeReleaseUnknown' and trace[6]['state']['effects']==[1], 'Unexpected release/effect ordering')
check(trace[-1]['state']['effects']==[1,2] and trace[-1]['state']['held']==[2] and trace[-1]['state']['committed']==[], 'Wrong counterexample endpoint')

# Check correspondence against already saved positive witnesses, not new search.
witnesses=read(run/'exact/normal_3_2/WITNESSES.json')
saved_states=[row['state'] for group in witnesses.values() for rows in group.values() for row in rows]
core={'received':[1],'issued':[1],'denied':[],'committed':[],'receipts':[],'committedCount':0}
projections={
    'issued_unarmed':dict(held=[1],heldCount=1,armed=[],cancelled=[],effects=[],expired=[]),
    'cancelled_unarmed':dict(held=[],heldCount=0,armed=[],cancelled=[1],effects=[],expired=[1]),
    'effect_unreconciled':dict(held=[1],heldCount=1,armed=[1],cancelled=[],effects=[1],expired=[]),
    'expired_effect_unreconciled':dict(held=[1],heldCount=1,armed=[1],cancelled=[],effects=[1],expired=[1])}
prefix_matches={name:any(all(s[k]==v for k,v in (core|projection).items()) for s in saved_states) for name,projection in projections.items()}
check(all(prefix_matches.values()),'No already-saved matching witness projection')

for name,value in freeze['source_hashes'].items():
    check(sha(HERE/name)==value,'Frozen file changed during audit')
out={'verdict':'PASS','audit_kind':'Read-only bindings, complete-output coverage and saved-trace audit; no state-space rerun',
     'freeze_sha256':FREEZE_SHA,'frozen_files_verified':len(freeze['source_hashes']),
     'baseline_files_verified':len(preservation),'baseline_all_preserved':all(preservation.values()),
     'baseline_mismatches':[k for k,v in preservation.items() if not v], 'cases':case_reports,
     'negative_saved_trace_states':13,'negative_saved_trace_transitions_independently_validated':12,
     'tlc_exact_negative_states_identical':True,'negative_trace':trace,
     'negative_first_effect_before_unsafe_release':True,'negative_ack_loss_transition_present':False,
     'saved_positive_witness_projections_match_s8_prefixes':prefix_matches,
     'prefix_scope':'Existence of matching persistent projections, not reconstruction of network state or full source refinement',
     'script_sha256':sha(Path(__file__))}
destination=HERE/'FINAL_MODEL_REVIEW_RECORDS.json'
check(not destination.exists(),'Do not overwrite completed audit')
destination.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k not in ('negative_trace','cases')},ensure_ascii=False,indent=2))
