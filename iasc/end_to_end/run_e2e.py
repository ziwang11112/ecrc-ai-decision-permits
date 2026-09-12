"""Checkpoint-based 6 x 3 x 2 raw-input experiment; retains every failed run."""
from pathlib import Path
import argparse,csv,hashlib,json,os,platform,queue,shutil,sqlite3,subprocess,sys,threading,time,traceback
from build_inputs import AT,LATER,EARLY,SCENARIOS
from audit_e2e import audit
HERE=Path(__file__).resolve().parent
FLAGS=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
def write(path,data):Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def adapter_type(arm):
    if arm=='ecrc':from ecrc_e2e import Adapter
    else:from ordinary_e2e import Adapter
    return Adapter
class Process:
    def __init__(self,args,log):
        self.log=Path(log);self.lines=[];self.q=queue.Queue();self.saved=False
        self.p=subprocess.Popen([sys.executable,*map(str,args)],cwd=HERE,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=FLAGS)
        def drain():
            for line in self.p.stdout:self.lines.append(line);self.q.put(line)
        self.reader=threading.Thread(target=drain,daemon=True);self.reader.start()
    def event(self,expected,timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:line=self.q.get(timeout=.1)
            except queue.Empty:
                if self.p.poll() is not None:raise RuntimeError(f'child ended before {expected}: '+''.join(self.lines))
                continue
            row=json.loads(line)
            if row['event']==expected:return row
            if row['event']=='error':raise RuntimeError(str(row))
        raise TimeoutError(expected)
    def release(self):self.p.stdin.write('\n');self.p.stdin.flush()
    def finish(self,expected='done'):
        row=self.event(expected);code=self.p.wait(timeout=30);self.save()
        if code != (2 if expected=='error' else 0):raise RuntimeError(f'unexpected worker exit {code}')
        return {**row,'pid':self.p.pid,'exit_code':code}
    def kill(self):
        if self.p.poll() is None:self.p.kill()
        code=self.p.wait(timeout=15);self.save();return {'pid':self.p.pid,'exit_code':code,'actual_termination':code!=0}
    def save(self):
        if self.saved:return
        self.reader.join(timeout=2)
        self.log.write_text(''.join(self.lines)+'\nSTDERR\n'+self.p.stderr.read(),encoding='utf-8');self.saved=True
def backup(source,destination):
    src=sqlite3.connect(str(source));dst=sqlite3.connect(str(destination))
    try:src.backup(dst)
    finally:dst.close();src.close()
def run_case(out,scenario,rep,arm):
    folder=out/scenario/f'rep-{rep}'/arm;folder.mkdir(parents=True,exist_ok=False)
    shutil.copy2(HERE/'inputs'/f'{scenario}.json',folder/'input.json')
    inputs=json.load(open(folder/'input.json',encoding='utf-8'))['requests']
    metadata={'scenario':scenario,'rep':rep,'arm':arm,'input_sha256':sha(folder/'input.json')};write(folder/'case.json',metadata)
    adapter=adapter_type(arm)(folder/'client.sqlite',inputs[0]['policy'])
    service=Process([HERE/'service_e2e.py','--db',folder/'sink.sqlite','--port',0],folder/'service.log')
    children=[];phases=[];events=[];failure=None;expected_received=set()
    def launch(index,*,resume=False,at=AT,stop='',gate=False,delay=False):
        args=[HERE/'worker_e2e.py','--arm',arm,'--db',folder/'client.sqlite','--url',url,'--at',at]
        if resume:args+=['--decision',inputs[index]['proposal']['decision_id']]
        else:
            args+=['--input',folder/'input.json','--index',index]
            expected_received.add(inputs[index]['proposal']['decision_id'])
        if stop:args+=['--stop-at',stop]
        if gate:args+=['--start-gate']
        if delay:args+=['--delay-ack']
        p=Process(args,folder/f'worker-{len(children):03d}.log');children.append(p);return p
    def phase(name):
        target=folder/'snapshots'/name;target.mkdir(parents=True,exist_ok=False)
        backup(folder/'client.sqlite',target/'client.sqlite');backup(folder/'sink.sqlite',target/'sink.sqlite')
        expected=sorted(expected_received)
        write(target/'snapshot_meta.json',{'phase':name,'expected_decisions':expected,'arm':arm})
        result=audit(target/'client.sqlite',target/'sink.sqlite',arm,folder/'input.json',expected_decisions=expected)
        phases.append({'phase':name,**result});write(target/'audit.json',result)
        assert result['passed'],result['findings']
        return result
    def group(indices,*,resume_indices=(),at=AT):
        workers=[launch(i,resume=i in resume_indices,at=at,gate=True) for i in indices]
        for p in workers:p.event('start_ready')
        for p in workers:p.release()
        for p in workers:events.append(p.finish())
    try:
        ready=service.event('ready');url=f"http://127.0.0.1:{ready['port']}"
        if scenario=='distinct_contenders':
            group(range(8));phase('after_competition');group(range(8),resume_indices=range(8))
        elif scenario=='mixed_claim_fallback':
            events.append(launch(0).finish());state=phase('unsupported_claim_released')
            assert state['effects']==state['reserved']==state['committed']==0 and state['released']==1
            group(range(1,9));phase('after_mixed_competition');group(range(9),resume_indices=range(9))
        elif scenario=='kill_during_issuance':
            p=launch(0,stop='after_reservation');events.append(p.event('checkpoint'));events.append(p.kill())
            state=phase('after_inflight_issue_kill')
            assert state['requests']==1 and state['permits']==state['reserved']==state['committed']==state['effects']==0
            group(range(8),resume_indices=(0,));phase('after_recovery_competition');group(range(8),resume_indices=range(8))
        elif scenario=='kill_after_issue_resume':
            p=launch(0,stop='after_issue_commit');events.append(p.event('checkpoint'));events.append(p.kill())
            state=phase('after_issue_before_arm_kill')
            assert state['permits']==state['reserved']==1 and state['effects']==0
            events.append({'cleanup':adapter.cleanup(EARLY),'at':EARLY});state=phase('early_cleanup_retained')
            assert state['reserved']==1 and state['cancelled']==0
            group(range(8),resume_indices=(0,),at=EARLY);phase('after_recovery_competition');group(range(8),resume_indices=range(8),at=EARLY)
        elif scenario=='expired_unarmed_cleanup':
            p=launch(0,stop='after_issue_commit');events.append(p.event('checkpoint'));events.append(p.kill())
            phase('issued_unarmed_before_expiry')
            events.append({'cleanup':adapter.cleanup(LATER),'at':LATER});state=phase('expired_unarmed_cancelled')
            assert state['cancelled']==state['released']==1 and state['reserved']==state['effects']==0
            events.append(launch(0,resume=True,at=LATER).finish());phase('cancelled_replay_no_dispatch')
            group(range(1,9),at=LATER);phase('released_budget_reused');group(range(9),resume_indices=range(9),at=LATER)
        elif scenario=='accepted_timeout_cleanup_recovery':
            event=launch(0,delay=True).finish(expected='error');events.append(event)
            assert event['error_type'] in ('TimeoutError','URLError') and 'timed out' in event['message'].lower()
            state=phase('sink_committed_client_timed_out')
            assert state['effects']==state['reserved']==state['armed']==1 and state['receipts']==state['committed']==0
            events.append({'cleanup':adapter.cleanup(LATER),'at':LATER});state=phase('cleanup_retained_unknown_grant')
            assert state['reserved']==state['armed']==1 and state['cancelled']==0
            group(range(8),resume_indices=(0,),at=LATER);phase('after_unknown_recovery_competition');group(range(8),resume_indices=range(8),at=LATER)
        final=phase('final')
        expected=3 if scenario=='mixed_claim_fallback' else 2
        assert final['effects']==final['receipts']==final['committed']==expected
        assert final['reserved']==final['armed']==0 and final['effect_routes']['alert']==2
        assert final['effect_routes']['review']==(1 if scenario=='mixed_claim_fallback' else 0)
        assert final['requests']==final['permits']==len(inputs)
        assert final['cancelled']==(1 if scenario=='expired_unarmed_cleanup' else 0)
        assert final['released']==(1 if scenario in ('expired_unarmed_cleanup','mixed_claim_fallback') else 0)
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    finally:
        for p in children:
            if p.p.poll() is None:p.kill()
            else:p.save()
        service.kill()
        try:final=audit(folder/'client.sqlite',folder/'sink.sqlite',arm,folder/'input.json',expected_decisions=[r['proposal']['decision_id'] for r in inputs])
        except Exception as exc:final={'passed':False,'findings':[str(exc)]}
        result={**metadata,'passed':failure is None and final['passed'],'failure':failure,'events':events,'phases':phases,'final':final}
        write(folder/'trace.json',result)
    return {**metadata,'passed':result['passed'],'failure':json.dumps(failure) if failure else '',
            **{k:final.get(k) for k in ('requests','permits','effects','receipts','reserved','committed','released','cancelled','armed')}}
def source_manifest():
    paths=list(HERE.glob('*.py'))+[HERE/'PROTOCOL.md',HERE/'PROTOCOL_AMENDMENTS.md']+list((HERE/'legacy_snapshot').rglob('*.py'))+list((HERE/'inputs').glob('*.json'))
    return {str(p.relative_to(HERE)).replace('\\','/'):sha(p) for p in sorted(paths)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--repetitions',type=int,default=3)
    p.add_argument('--scenarios',nargs='*',choices=SCENARIOS);p.add_argument('--arms',nargs='*',choices=('ordinary','ecrc'));p.add_argument('--formal',action='store_true');a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);initial=source_manifest()
    if a.formal:
        if a.repetitions!=3 or a.scenarios or a.arms:raise ValueError('formal suite must contain all 36 cases')
        frozen=json.load(open(HERE/'CODE_FREEZE.json',encoding='utf-8'))['files']
        if frozen!=initial:raise ValueError('code/input differs from reviewed freeze')
    write(out/'RUN_MANIFEST.json',{'formal':a.formal,'python':sys.version,'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'command':sys.argv,'files':initial})
    rows=[]
    for rep in range(a.repetitions):
        arms=a.arms or (('ordinary','ecrc') if rep%2==0 else ('ecrc','ordinary'))
        for scenario in a.scenarios or SCENARIOS:
            for arm in arms:
                try:
                    row=run_case(out,scenario,rep,arm)
                except BaseException as exc:
                    # Setup failures also retain one planned row and do not
                    # suppress subsequent cases in the declared denominator.
                    folder=out/scenario/f'rep-{rep}'/arm;folder.mkdir(parents=True,exist_ok=True)
                    metadata={'scenario':scenario,'rep':rep,'arm':arm,'input_sha256':sha(HERE/'inputs'/f'{scenario}.json')}
                    failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
                    write(folder/'trace.json',{**metadata,'passed':False,'failure':failure,'events':[],'phases':[],
                          'final':{'passed':False,'findings':['setup failed before complete durable evidence']}})
                    row={**metadata,'passed':False,'failure':json.dumps(failure),
                         **{k:None for k in ('requests','permits','effects','receipts','reserved','committed','released','cancelled','armed')}}
                rows.append(row);print(json.dumps(row),flush=True)
                with (out/'outcomes.csv').open('w',newline='',encoding='utf-8') as f:
                    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    final=source_manifest();summary={'planned_runs':len(rows),'passed_runs':sum(r['passed'] for r in rows),'failed_runs':sum(not r['passed'] for r in rows),'source_unchanged':initial==final}
    write(out/'SUMMARY.json',summary);print(json.dumps(summary),flush=True)
    if not summary['source_unchanged'] or summary['failed_runs']:return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
