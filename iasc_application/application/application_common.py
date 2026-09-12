"""Shared catalog/input preparation only; issuance stays in the two frozen clients."""
from pathlib import Path
import copy,hashlib,json
HERE=Path(__file__).resolve().parent
BINDING_FIELDS=('task_id','candidate_id','solution_sha256','test_sha256','runner_sha256')
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode('utf-8')).hexdigest()
def file_sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def job_binding(job):return {k:job[k] for k in BINDING_FIELDS}
def prepare_bound_catalog():
    original=read(HERE/'workload/catalog.json')
    jobs=original['jobs']
    out={**original,'permitted_claim_ids':['run_verification'],'jobs':[]}
    for job in jobs:
        assert hashlib.sha256(job['solution'].encode()).hexdigest()==job['solution_sha256']
        assert hashlib.sha256(job['test'].encode()).hexdigest()==job['test_sha256']
        h=digest(job_binding(job))
        out['jobs'].append({**job,'job_hash':h,'decision_id':'verify:'+h})
    assert len({j['decision_id'] for j in out['jobs']})==len(out['jobs'])
    write(HERE/'bound_catalog.json',out)
    return out
def make_raw_request(job,batch_id,budget,source_hash):
    r=copy.deepcopy(read(HERE/'legacy/request_template.json'))
    decision=job['decision_id'];h=job['job_hash']
    policy=r['policy']
    policy.update(policy_id='iasc-app-verification-v1',issuer_id='trusted-verification-workflow',
                  alert_capacity=budget,review_capacity=0,revision=1,
                  approved_models=[{'model_id':'archived-llama31-8b-proposals','model_hash':source_hash}],
                  allowed_routes=['alert','abstain','no_action'],
                  evidence_rules=[{'allowed_schema_versions':['1.0'],'allowed_sources':['sealed-job-catalog'],
                                   'evidence_type':'verification_job','max_age_seconds':86400,'use_allowed':True}],
                  claim_rules=[{'claim_id':'run_verification','reason_codes':[],
                                'required_evidence_types':['verification_job'],'routes':['alert']}],
                  blocked_claim_ids=['general_program_correctness','production_benefit'])
    r['proposal'].update(decision_id=decision,subject_id=batch_id,session_id='verification-episode-v1',
                        input_hash=h,model_id='archived-llama31-8b-proposals',model_hash=source_hash,
                        model_version='published-sanitized-cache',score=.8,uncertainty=.2,
                        validation_scope_id='official-humaneval-finite-suite')
    r['evidence'].update(decision_id=decision)
    r['evidence']['items']=[{'evidence_id':'job:'+h,'evidence_type':'verification_job',
                           'source':'sealed-job-catalog','schema_version':'1.0',
                           'observed_at':'2026-09-12T12:00:03.000000Z',
                           'available_at':'2026-09-12T12:00:04.000000Z',
                           'provenance_hash':h,'requested_for_use':True}]
    return r

if __name__=='__main__':
    c=prepare_bound_catalog();print(canonical({'jobs':len(c['jobs']),'bound_catalog_sha256':file_sha(HERE/'bound_catalog.json')}))
