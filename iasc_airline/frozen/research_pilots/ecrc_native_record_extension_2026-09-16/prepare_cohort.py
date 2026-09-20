"""Freeze the next fixed structural ranks without inspecting qualifications."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parents[1]
PRIOR=ROOT.parent/'ecrc_native_record_coverage_2026-09-15'
QA=WORKSPACE/'qa/iasc_followup_experiments_2026-09-16'
SEED='ecrc-native-record-coverage-v1'
START_RANK, END_RANK = 101, 200
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def rank_hash(*ids):
    return hashlib.sha256(json.dumps([SEED,*ids],ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()

def build():
    original=read(PRIOR/'COHORT_SELECTION.json')
    pool=original['all_available_accounts_ranked']
    assert original['seed']==SEED and len(pool)==418
    assert pool==sorted(pool,key=lambda x:(x['account_selection_hash'],x['user_id']))
    for rank,row in enumerate(pool,1):
        assert row['account_rank']==rank
        assert row['account_selection_hash']==rank_hash(row['user_id'])
        choices=row['owned_reservation_choices']
        assert choices==sorted(choices,key=lambda x:(x['selection_hash'],x['reservation_id']))
        assert all(x['selection_hash']==rank_hash(row['user_id'],x['reservation_id']) for x in choices)
        assert row['selected_reservation_id']==choices[0]['reservation_id']
        assert row['reservation_selection_hash']==choices[0]['selection_hash']
    selected=deepcopy(pool[START_RANK-1:END_RANK])
    previous=original['selected_accounts']
    assert previous==pool[:100] and len(selected)==100
    assert not ({x['user_id'] for x in selected}&{x['user_id'] for x in previous})
    assert not ({x['selected_reservation_id'] for x in selected}&{x['selected_reservation_id'] for x in previous})
    assert not ({x['user_id'] for x in selected}&set(original['excluded_accounts_union']))
    sources=dict(original['source_files'])
    extra=[PRIOR/'COHORT_SELECTION.json',PRIOR/'REQUESTS.json',PRIOR/'PROTOCOL.md',
           PRIOR/'prepare_cohort.py',PRIOR/'run_coverage.py',Path(__file__).resolve(),
           ROOT/'PROTOCOL.md',QA/'SELECTION_STRUCTURAL_VALIDATION.json',QA/'EXTENSION_PRIOR_EXPOSURE.json']
    for p in extra:
        sources[str(p.resolve())]=sha(p)
    for p,h in sources.items():
        assert sha(Path(p))==h,p
    selection=deepcopy(original)
    selection.update(schema_version='controlled_native_record_followup_selection_v1',
        cohort_id='native_extension_ranks_101_200',rank_range=[START_RANK,END_RANK],
        expected_selected_accounts=100,declared_cases=300,account_limit=100,
        selection_script=str(Path(__file__).resolve()),selection_script_sha256=sha(Path(__file__)),
        source_files=sources,selected_accounts=selected,
        previous_cohort_path=str(PRIOR/'COHORT_SELECTION.json'),
        previous_cohort_sha256=sha(PRIOR/'COHORT_SELECTION.json'),
        prior_exposure_audit_path=str(QA/'EXTENSION_PRIOR_EXPOSURE.json'),
        prior_exposure_audit_sha256=sha(QA/'EXTENSION_PRIOR_EXPOSURE.json'),
        sample_size_basis='Fixed follow-up resource budget of 100 accounts, selected after the first batch results were known; not a power calculation or positive-count stopping rule.')
    selection['selection_rule']['sampling']='Fixed original global ranks 101 through 200 inclusive; original seed, exclusions, structural universe and first owned reservation per account remain unchanged. No new eligibility screen or replacement.'
    selection['counts']['selected_accounts']=100
    selection['counts']['scripted_requests']=300
    selection['exposure_interpretation']='Inherited original exclusions describe the original sampling universe; the separately frozen current-log exposure audit is disclosed without changing that fixed sequence. No never-seen or independent-holdout claim.'
    selection['interpretation']=[
        'Prospective follow-up grid specified after the first-batch results; the two studies are reported separately.',
        'Unmodified records from the same synthetic native database, with author-written requests; not additional official tasks or a new independent dataset.',
        'Three reason conditions share each account and reservation; execution arms and call replays do not increase independent sample size.',
        'Sampling reuses only previously archived identifiers, ownership associations and hash ranks, without selecting on business qualification.',
        'Every planned cell is retained, including errors, unsupported actions, unresolved requests and ties.',
        'The current-log exposure audit cannot rule out historical full-database access; no hidden test-set or unseen-data claim.'
    ]
    cases=[]
    for row in selected:
        uid,rid=row['user_id'],row['selected_reservation_id']
        for template in original['templates']:
            reason=template['reason']
            cases.append({'case_id':f"record_{row['account_rank']:03d}_{reason}",'task_id':None,
                'kind':'controlled_native_record_followup_request','native_full_goal_in_scope':False,
                'account_rank':row['account_rank'],'paired_account_id':uid,'paired_reservation_id':rid,
                'reason_template':reason,'request':{'user_id':uid,
                    'user_statement':template['statement'].format(reservation_id=rid),
                    'cancellation':{'selector':{'kind':'ids','ids':[rid]},'reason':reason}}})
    requests={'schema_version':'controlled_native_record_followup_requests_v1',
        'cohort_id':selection['cohort_id'],'source_commit':original['source_commit'],
        'source_split':'controlled_followup_not_official_tasks','source_population_size':500,
        'scope':'Initial cancellation module on 100 fixed additional native reservations, three scripted reason templates, four unchanged configurations.',
        'selection_basis':selection['selection_rule']['sampling'],
        'selected_accounts':100,'unique_selected_reservations':len({x['selected_reservation_id'] for x in selected}),
        'sample_size_basis':selection['sample_size_basis'],'templates':original['templates'],
        'cases':cases,'limitations':selection['interpretation']}
    assert len(cases)==300 and requests['unique_selected_reservations']==100
    return selection,requests

def generate():
    outputs=[ROOT/'COHORT_SELECTION.json',ROOT/'REQUESTS.json']
    assert not any(p.exists() for p in outputs),'Frozen outputs already exist; use --verify'
    for p,obj in zip(outputs,build()):
        with p.open('x',encoding='utf-8',newline='\n') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2)
            f.write('\n')
    print(json.dumps({'prepared':True,'ranks':[START_RANK,END_RANK],'accounts':100,'requests':300,'cells':1200}))

def verify():
    expected=build()
    assert expected==(read(ROOT/'COHORT_SELECTION.json'),read(ROOT/'REQUESTS.json'))
    print(json.dumps({'verified':True,'accounts':100,'requests':300,'selection_sha256':sha(ROOT/'COHORT_SELECTION.json')}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    verify() if args.verify else generate()
