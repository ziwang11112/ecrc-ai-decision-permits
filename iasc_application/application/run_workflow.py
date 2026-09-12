"""Run one resettable, serial, live-feedback verification trajectory."""
from pathlib import Path
import argparse,json,queue,sqlite3,subprocess,sys,threading,time,urllib.request
from application_common import HERE,canonical,digest,file_sha,make_raw_request,read,write
sys.path.insert(0,str(HERE/'legacy/end_to_end'))
POLICY_CLOCK='2026-09-12T12:00:05.000000Z'

def choose_next(task_ids,by_task,attempted,solved,policy,cursor):
    active=[t for t in task_ids if t not in solved and len(attempted[t])<len(by_task[t])]
    if not active:return None,cursor
    if policy=='depth_first':task=active[0]
    else:
        task=next(task_ids[(cursor+i)%len(task_ids)] for i in range(len(task_ids)) if task_ids[(cursor+i)%len(task_ids)] in active)
        cursor=(task_ids.index(task)+1)%len(task_ids)
    return by_task[task][len(attempted[task])],cursor

def run_one(*,catalog_path,batch_id,arm,policy,condition,budget,deadline,backoff,out,formal_protocol=None):
    out=Path(out)
    if out.exists():raise FileExistsError('Fresh run directory required: '+str(out))
    out.mkdir(parents=True)
    catalog=read(catalog_path)
    batches={b['batch_id']:b for b in catalog['batches']}
    batch=batches[batch_id]
    if batch['partition']=='evaluation':
        if not formal_protocol:raise ValueError('Evaluation requires a frozen formal protocol')
        fp=read(formal_protocol)
        assert fp['frozen'] is True and fp['catalog_sha256']==file_sha(catalog_path)
        assert (budget,deadline,backoff)==(fp['budget'],fp['deadline_seconds'],fp['recovery_backoff_seconds'])
        assert arm in fp['arms'] and policy in fp['policies'] and condition in fp['conditions']
        for n,h in fp['source_hashes'].items():assert file_sha(HERE/n)==h,n
    task_ids=batch['task_ids']
    by_task={t:sorted([j for j in catalog['jobs'] if j['task_id']==t],key=lambda j:j['rank']) for t in task_ids}
    assert all(len(j)==4 for j in by_task.values())
    source_hash=catalog['source_archive_sha256']
    requests={j['decision_id']:make_raw_request(j,batch_id,budget,source_hash) for js in by_task.values() for j in js}
    inp={'batch_id':batch_id,'partition':batch['partition'],'task_ids':task_ids,
         'candidate_ids':{t:[j['candidate_id'] for j in by_task[t]] for t in task_ids},'requests':requests}
    write(out/'input_batch.json',inp)
    if arm=='ecrc':from ecrc_e2e import Adapter
    elif arm=='ordinary':from ordinary_e2e import Adapter
    else:raise ValueError(arm)
    adapter=Adapter(out/'client.sqlite',next(iter(requests.values()))['policy'])
    service_log=(out/'service_stdout.jsonl').open('w',encoding='utf-8')
    service_err=(out/'service_stderr.log').open('w',encoding='utf-8')
    cmd=[sys.executable,'-B',str(HERE/'service/verification_service.py'),'--catalog',str(Path(catalog_path).resolve()),
         '--db',str((out/'sink.sqlite').resolve()),'--runout',str((out/'service_runs').resolve()),'--port','0']
    proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=service_err,text=True,encoding='utf-8',bufsize=1,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    messages=queue.Queue()
    def capture():
        for line in proc.stdout:
            service_log.write(line);service_log.flush()
            try:messages.put(json.loads(line))
            except json.JSONDecodeError:pass
    capture_thread=threading.Thread(target=capture,daemon=True)
    capture_thread.start()
    def stop_service():
        if proc.poll() is None:proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        capture_thread.join(timeout=5)
        service_log.close();service_err.close()
    try:
        ready=messages.get(timeout=30)
        assert ready['event']=='ready',ready
    except BaseException as exc:
        write(out/'setup_failure.json',{'type':type(exc).__name__,'message':str(exc)})
        stop_service()
        raise
    base='http://127.0.0.1:'+str(ready['port'])
    start=time.perf_counter_ns();attempted={t:[] for t in task_ids};solved=set();cursor=0
    pending=None;failure=None;outcomes=[];events=[];requests_posted=0
    def event(name,**extra):
        now=time.perf_counter_ns()
        e={'event':name,'perf_counter_ns':now,'elapsed_s':(now-start)/1e9,**extra}
        events.append(e)
        with (out/'client_events.jsonl').open('a',encoding='utf-8') as f:f.write(canonical(e)+'\n')
        return e
    def elapsed():return (time.perf_counter_ns()-start)/1e9
    def post(intent,drop):
        nonlocal requests_posted
        headers={'Content-Type':'application/json'}
        if drop:headers['X-Test-Drop-Response']='1'
        body=canonical({'idempotency_key':intent['idempotency_key'],'payload':json.loads(intent['payload_json'])}).encode()
        requests_posted+=1
        request=urllib.request.Request(base+'/effects',data=body,headers=headers,method='POST')
        with urllib.request.urlopen(request,timeout=20) as response:return json.loads(response.read())
    def finish(job,permit,ack,phase):
        result=ack['job_result']
        assert ack['result_hash']==digest(result),'result hash mismatch'
        for k in ('task_id','candidate_id','solution_sha256','test_sha256'):
            assert result[k]==job[k],k
        assert result['status'] in ('pass','fail','timeout'),result
        adapter.finish(permit['permit_id'],ack,POLICY_CLOCK)
        e=event('reconciled',phase=phase,task_id=job['task_id'],candidate_id=job['candidate_id'],
                decision_id=job['decision_id'],permit_id=permit['permit_id'],effect_id=ack['effect_id'],
                result_hash=ack['result_hash'],result=result)
        outcomes.append(e)
        if result['status']=='pass':solved.add(job['task_id'])
    try:
        event('trajectory_started',task_ids=task_ids,budget=budget,deadline_seconds=deadline)
        while elapsed()<deadline:
            job,cursor=choose_next(task_ids,by_task,attempted,solved,policy,cursor)
            if job is None:break
            raw=requests[job['decision_id']]
            adapter.ingest(raw,POLICY_CLOCK)
            permit=adapter.issue(job['decision_id'],POLICY_CLOCK)
            event('issued',task_id=job['task_id'],candidate_id=job['candidate_id'],decision_id=job['decision_id'],
                  permit_id=permit['permit_id'],route=permit['route'],request_hash=digest(raw))
            if permit['route']!='alert':break
            # Issuance finishing after D may hold an unarmed unit; do not start work.
            if elapsed()>=deadline:
                event('deadline_before_arm',decision_id=job['decision_id']);break
            intent=adapter.arm(permit,POLICY_CLOCK)
            attempted[job['task_id']].append(job['candidate_id'])
            ordinal=sum(map(len,attempted.values()))
            drop=condition=='response_loss' and ordinal%4==0
            event('armed',task_id=job['task_id'],candidate_id=job['candidate_id'],decision_id=job['decision_id'],
                  permit_id=permit['permit_id'],operation_id=intent['idempotency_key'],launch_ordinal=ordinal,request_drop=drop)
            try:
                ack=post(intent,drop)
            except Exception as exc:
                event('transport_error',decision_id=job['decision_id'],error_type=type(exc).__name__,message=str(exc))
                retry_due=time.perf_counter_ns()+int(backoff*1e9)
                pending=(job,permit,intent,retry_due)
                # All arms use the same serial recovery opportunity. Only an
                # observed HTTP failure initiates this predeclared backoff.
                if elapsed()+backoff>=deadline:break
                time.sleep(backoff)
                if elapsed()>=deadline:break
                event('retry',phase='primary',decision_id=job['decision_id'])
                ack=post(intent,False)
                pending=None
            finish(job,permit,ack,'primary')
        stop=event('primary_stopped')
        write(out/'stop_observed_snapshot.json',adapter.snapshot())
        if pending:
            job,permit,intent,retry_due=pending
            # Drain only the already authorized work. It does not make new
            # candidate choices or contribute to the primary deadline metric.
            remaining=(retry_due-time.perf_counter_ns())/1e9
            if remaining>0:time.sleep(remaining)
            event('retry',phase='drain',decision_id=job['decision_id'])
            finish(job,permit,post(intent,False),'drain')
            pending=None
        event('trajectory_complete')
    except BaseException as exc:
        import traceback
        failure={'category':'unclassified_workflow_failure','type':type(exc).__name__,
                 'message':str(exc),'traceback':traceback.format_exc()}
        event('workflow_failure',failure=failure)
    finally:
        snap=adapter.snapshot();write(out/'final_client_snapshot.json',snap)
        stop_service()
    timely={e['task_id'] for e in outcomes if e['result']['status']=='pass' and e['phase']=='primary' and e['elapsed_s']<=deadline}
    summary={'run_id':out.name,'batch_id':batch_id,'partition':batch['partition'],'arm':arm,'policy':policy,'condition':condition,
             'budget':budget,'deadline_seconds':deadline,'recovery_backoff_seconds':backoff,'started_at_counter_ns':start,
             'eligible_task_ids':task_ids,'inputs_hash':digest(inp),'catalog_sha256':file_sha(catalog_path),
             'formal_protocol_sha256':file_sha(formal_protocol) if formal_protocol else None,
             'timely_pass_task_ids':sorted(timely),'eventual_pass_task_ids':sorted(solved),
             'n_timely_pass':len(timely),'n_tasks':len(task_ids),'http_posts':requests_posted,
             'attempted':attempted,'final_snapshot':snap,'failure':failure,'passed_technical':failure is None}
    write(out/'run_summary.json',summary)
    return {k:v for k,v in summary.items() if k not in ('final_snapshot','attempted')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',default=str(HERE/'bound_catalog.json'));p.add_argument('--batch',required=True)
    p.add_argument('--arm',choices=['ecrc','ordinary'],required=True);p.add_argument('--policy',choices=['depth_first','round_robin'],required=True)
    p.add_argument('--condition',choices=['normal','response_loss'],required=True);p.add_argument('--budget',type=int,default=16)
    p.add_argument('--deadline',type=float,required=True);p.add_argument('--backoff',type=float,required=True);p.add_argument('--out',required=True)
    p.add_argument('--formal-protocol')
    a=p.parse_args();result=run_one(catalog_path=a.catalog,batch_id=a.batch,arm=a.arm,policy=a.policy,condition=a.condition,
             budget=a.budget,deadline=a.deadline,backoff=a.backoff,out=a.out,formal_protocol=a.formal_protocol)
    print(canonical(result),flush=True)
    raise SystemExit(0 if result['passed_technical'] else 1)
