"""Full predeclared loopback service/crash-recovery comparison."""
from pathlib import Path
import sys,subprocess,os,json,sqlite3,time,threading,queue,csv,hashlib,platform,argparse,statistics,traceback,copy
from concurrent.futures import ThreadPoolExecutor
from fixture import make_fixture,ARM_AT,DONE_AT,EXPIRED_AT
from delivery import run_one
HERE=Path(__file__).resolve().parent
ARMS=('ordinary','ecrc')
SCENARIOS=('normal','crash_after_intent','crash_after_ack','drop_after_commit','crash_before_local_commit','crash_after_local_commit','concurrent_retries','sink_restart_after_lost_ack','temporary_outage')
BOUNDARIES=('changed_permit','expired_before_arm','revoked_before_arm','non_action','revoked_after_arm','expired_after_arm')
FLAGS=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path,data):Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def csvout(path,rows):
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def adapter_type(arm):
    if arm=='ecrc':from ecrc_adapter import Adapter
    else:from ordinary_adapter import Adapter
    return Adapter

class Process:
    def __init__(self,args,log):
        self.log=Path(log);self.lines=[];self.q=queue.Queue()
        self.p=subprocess.Popen([sys.executable,*map(str,args)],cwd=HERE,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=FLAGS)
        def drain():
            for line in self.p.stdout:
                self.lines.append(line);self.q.put(line)
        self.reader=threading.Thread(target=drain,daemon=True);self.reader.start()
    def event(self,expected,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:line=self.q.get(timeout=min(.1,max(.001,deadline-time.monotonic())))
            except queue.Empty:
                if self.p.poll() is not None:raise RuntimeError('process ended before '+expected+': '+self.p.stderr.read())
                continue
            row=json.loads(line)
            if row['event']==expected:return row
            if row['event']=='error':raise RuntimeError(str(row))
        raise TimeoutError(expected)
    def release(self):self.p.stdin.write('\n');self.p.stdin.flush()
    def stop(self,kill=False):
        if self.p.poll() is None:
            self.p.kill() if kill else self.p.terminate()
        code=self.p.wait(timeout=15);self.reader.join(timeout=2)
        self.log.write_text(''.join(self.lines)+'\nSTDERR\n'+self.p.stderr.read(),encoding='utf-8')
        return code
    def done(self):
        row=self.event('done');code=self.p.wait(timeout=20);assert code==0
        self.stop();return row

def start_service(folder):
    s=Process([HERE/'service.py','--db',folder/'sink.sqlite','--port','0'],folder/f'service-{time.time_ns()}.log')
    ready=s.event('ready');s.url=f"http://127.0.0.1:{ready['port']}";return s
def worker(arm,folder,url,extra=()):
    return Process([HERE/'worker.py','--arm',arm,'--db',folder/'client.sqlite','--fixture',folder/'fixture/fixture.json','--url',url,*extra],folder/f'worker-{time.time_ns()}.log')
def effects(folder):
    with sqlite3.connect(folder/'sink.sqlite') as c:
        c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute('SELECT * FROM effects ORDER BY effect_id')]
def check_state(adapter,folder,*,complete):
    state=adapter.snapshot();sink=effects(folder)
    for row in state['capacity_rows']:
        assert row['reserved']>=0 and row['committed']>=0
        assert row['reserved']+row['committed']<=row['capacity_limit']
    assert state['reserved']+state['committed']<=state['capacity_limit']
    assert len(sink)==len({r['idempotency_key'] for r in sink})
    if complete:
        assert state['reserved']==0
        assert state['n_armed']==0
        assert len(sink)==state['n_receipts']==state['n_receipted']==state['committed']
        lookup={r['idempotency_key']:r for r in sink}
        for job in state['jobs']:
            ack=json.loads(job['ack_json']);actual=lookup[job['idempotency_key']]
            assert ack['effect_id']==actual['effect_id'] and ack['payload_hash']==actual['payload_hash']==job['payload_hash']
            assert json.loads(actual['payload_json'])==json.loads(job['payload_json'])
            receipt=json.loads(job['receipt_json'])
            assert receipt['service_effect_id']==actual['effect_id']
            assert receipt['permit_id']==job['permit_id'] and receipt['permit_hash']==job['permit_hash']
            from datetime import datetime
            timestamp=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
            assert timestamp(receipt['executed_at'])==timestamp(actual['committed_at'])
            assert timestamp(receipt['reconciled_at'])>=timestamp(actual['committed_at'])
    return state,sink

def recovery_case(out,arm,scenario,rep):
    folder=out/'recovery'/f'{scenario}-{arm}-{rep}';folder.mkdir(parents=True)
    fixture=make_fixture(folder/'fixture');adapter=adapter_type(arm)(folder/'client.sqlite');adapter.seed(fixture)
    service=start_service(folder);w=None;crashes=[]
    try:
        url=service.url
        checkpoint={'crash_after_intent':'after_intent','crash_after_ack':'after_ack','crash_before_local_commit':'before_commit','crash_after_local_commit':'after_commit'}.get(scenario)
        if checkpoint:
            w=worker(arm,folder,url,['--stop-at',checkpoint]);event=w.event('checkpoint');assert event['name']==checkpoint
            crashes.append({'pid':w.p.pid,'checkpoint':checkpoint,'exit_code':w.stop(kill=True)});w=None
        elif scenario in ('drop_after_commit','sink_restart_after_lost_ack'):
            w=worker(arm,folder,url,['--drop']);err=w.event('error');assert err['error_type'] in ('RemoteDisconnected','URLError','ConnectionResetError')
            assert w.p.wait(timeout=10)==2;w.stop();w=None
        elif scenario=='temporary_outage':
            crashes.append({'pid':service.p.pid,'checkpoint':'service_before_send','exit_code':service.stop(kill=True)})
            w=worker(arm,folder,url);err=w.event('error');assert err['error_type']=='URLError'
            assert w.p.wait(timeout=10)==2;w.stop();w=None
        elif scenario=='concurrent_retries':
            workers=[worker(arm,folder,url,['--start-gate']) for _ in range(8)]
            try:
                for child in workers:child.event('start_ready')
                for child in workers:child.release()
                for child in workers:child.done()
            finally:
                for child in workers:child.stop()
        else:
            w=worker(arm,folder,url);w.done();w=None
        mid,mid_sink=check_state(adapter,folder,complete=False)
        if scenario in ('crash_after_intent','temporary_outage'):
            assert len(mid_sink)==0 and mid['reserved']==1 and mid['n_armed']==1 and mid['n_receipts']==0
        elif scenario in ('crash_after_ack','drop_after_commit','crash_before_local_commit','sink_restart_after_lost_ack'):
            assert len(mid_sink)==1 and mid['reserved']==1 and mid['n_armed']==1 and mid['n_receipts']==0
        else:assert len(mid_sink)==mid['n_receipts']==mid['committed']==1 and mid['reserved']==0
        if scenario=='sink_restart_after_lost_ack':
            crashes.append({'pid':service.p.pid,'checkpoint':'service_after_commit_no_ack','exit_code':service.stop(kill=True)})
        if scenario in ('sink_restart_after_lost_ack','temporary_outage'):service=start_service(folder)
        started=time.perf_counter();w=worker(arm,folder,service.url);w.done();w=None;recovery_ms=(time.perf_counter()-started)*1000
        final,sink=check_state(adapter,folder,complete=True);assert len(sink)==1
        write(folder/'trace.json',{'arm':arm,'scenario':scenario,'rep':rep,'crashes':crashes,'intermediate':mid,'intermediate_effects':mid_sink,'final':final,'effects':sink,'recovery_ms_including_worker_start':recovery_ms})
        return dict(arm=arm,scenario=scenario,rep=rep,intermediate_effects=len(mid_sink),intermediate_receipts=mid['n_receipts'],intermediate_reserved=mid['reserved'],intermediate_committed=mid['committed'],final_effects=len(sink),final_receipts=final['n_receipts'],final_reserved=final['reserved'],final_committed=final['committed'],duplicate_effects=0,omitted_effects=0,receipt_mismatches=0,oversubscription=0,crashes=len(crashes),recovery_ms_including_worker_start=recovery_ms)
    finally:
        if w:w.stop(kill=True)
        service.stop()

def boundary_case(out,arm,name):
    folder=out/'boundary'/f'{name}-{arm}';folder.mkdir(parents=True)
    fixture=make_fixture(folder/'fixture',include_nonaction=True);adapter=adapter_type(arm)(folder/'client.sqlite');adapter.seed(fixture);service=start_service(folder)
    permit=copy.deepcopy(fixture['permits'][0]);at=ARM_AT;accepted=name in ('revoked_after_arm','expired_after_arm')
    try:
        if name=='changed_permit':permit['permitted_claim_ids']=['forged_claim']
        if name=='expired_before_arm':at=permit['expires_at']
        if name=='revoked_before_arm':adapter.revoke()
        if name=='non_action':permit=fixture['permits'][1]
        if accepted:
            adapter.arm(permit,ARM_AT)
            if name=='revoked_after_arm':adapter.revoke()
            else:at=permit['expires_at']
        error=None
        try:run_one(adapter,permit,service.url,at,at)
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        state,sink=check_state(adapter,folder,complete=accepted)
        if accepted:assert error is None and len(sink)==1
        else:assert error and not sink and state['n_jobs']==state['n_receipts']==0
        write(folder/'trace.json',{'arm':arm,'case':name,'expected_accept':accepted,'error':error,'state':state,'sink':sink,'policy_clock':at})
        return dict(arm=arm,case=name,expected_accept=accepted,actual_accept=error is None,effects=len(sink),receipts=state['n_receipts'],unauthorized_effects=0,passed=True)
    finally:service.stop()

def percentile(values,q):
    v=sorted(values);position=(len(v)-1)*q;lo=int(position);hi=min(lo+1,len(v)-1);return v[lo]+(v[hi]-v[lo])*(position-lo)
def performance(out,arm,workers,rep):
    folder=out/'performance'/f'w{workers}-{arm}-{rep}';folder.mkdir(parents=True)
    fixture=make_fixture(folder/'fixture',n=64,warmup=True);adapter=adapter_type(arm)(folder/'client.sqlite');adapter.seed(fixture);service=start_service(folder)
    try:
        run_one(adapter,fixture['permits'][-1],service.url,ARM_AT,DONE_AT)
        def one(p):
            t=time.perf_counter();r=run_one(adapter,p,service.url,ARM_AT,DONE_AT)
            return {'arm':arm,'workers':workers,'rep':rep,'permit_id':p['permit_id'],'latency_ms':(time.perf_counter()-t)*1000}
        t=time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:requests=list(pool.map(one,fixture['permits'][:-1]))
        elapsed=time.perf_counter()-t;state,sink=check_state(adapter,folder,complete=True);assert len(sink)==65
        write(folder/'trace.json',{'state':state,'effects':sink});csvout(folder/'request_latencies.csv',requests)
        service.stop()
        for path in (folder/'client.sqlite',folder/'sink.sqlite'):
            with sqlite3.connect(path) as c:c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        lat=[r['latency_ms'] for r in requests]
        return dict(arm=arm,workers=workers,rep=rep,n_timed_requests=64,elapsed_seconds=elapsed,throughput_requests_per_second=64/elapsed,median_latency_ms=statistics.median(lat),p95_latency_ms=percentile(lat,.95),max_latency_ms=max(lat),client_database_bytes=(folder/'client.sqlite').stat().st_size,sink_database_bytes=(folder/'sink.sqlite').stat().st_size,effects_including_warmup=len(sink),final_reserved=state['reserved']),requests
    finally:service.stop()

def main(out,reps):
    assert not out.exists(),'Use a fresh output directory; retain prior runs'
    out.mkdir(parents=True)
    paths=[HERE/n for n in ['fixture.py','ecrc_adapter.py','ordinary_adapter.py','delivery.py','worker.py','service.py','run_experiment.py','PROTOCOL.md','PROTOCOL_SERVICE.md']]+list((HERE/'source_snapshot').rglob('*.py'))
    inputs={p.relative_to(HERE).as_posix():sha(p) for p in sorted(paths)}
    recovery=[];bounds=[];perf=[];requests=[]
    try:
        for rep in range(1,reps+1):
            arms=ARMS if rep%2 else ARMS[::-1]
            for scenario in SCENARIOS:
                for arm in arms:
                    row=recovery_case(out,arm,scenario,rep);recovery.append(row)
                print(f'recovery {rep}/{reps} {scenario} passed both arms',flush=True)
        for name in BOUNDARIES:
            for arm in ARMS:bounds.append(boundary_case(out,arm,name))
        for rep in range(1,reps+1):
            for w in (1,4,8):
                for arm in (ARMS if rep%2 else ARMS[::-1]):
                    row,raw=performance(out,arm,w,rep);perf.append(row);requests+=raw
                print(f'performance {rep}/{reps} workers={w} passed both arms',flush=True)
        csvout(out/'recovery_results.csv',recovery);csvout(out/'boundary_results.csv',bounds);csvout(out/'performance_runs.csv',perf);csvout(out/'request_latencies.csv',requests)
        summary=[]
        for arm in ARMS:
            for w in (1,4,8):
                local=[r for r in perf if r['arm']==arm and r['workers']==w]
                row={'arm':arm,'workers':w,'repetitions':len(local)}
                for metric in ['p95_latency_ms','median_latency_ms','throughput_requests_per_second','client_database_bytes']:
                    x=[r[metric] for r in local];row.update({metric+'_median':statistics.median(x),metric+'_min':min(x),metric+'_max':max(x)})
                summary.append(row)
        csvout(out/'performance_summary.csv',summary)
        deterministic=[{k:v for k,v in r.items() if k!='recovery_ms_including_worker_start'} for r in recovery]
        write(out/'deterministic_outcomes.json',{'recovery':deterministic,'boundary':bounds,'performance_integrity':[{'arm':r['arm'],'workers':r['workers'],'rep':r['rep'],'n_timed_requests':r['n_timed_requests'],'effects':r['effects_including_warmup'],'final_reserved':r['final_reserved']} for r in perf]})
        assert all(sha(HERE/n)==h for n,h in inputs.items()),'Code/input changed during experiment'
        write(out/'manifest.json',{'protocol':'post hoc engineering extension','python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'repetitions':reps,'inputs':inputs,'recovery_runs':len(recovery),'boundary_cases':len(bounds),'performance_runs':len(perf),'timed_requests':len(requests),'outputs':{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()}})
        print(json.dumps({'recovery_runs':len(recovery),'boundary_cases':len(bounds),'performance_runs':len(perf),'timed_requests':len(requests),'all_integrity_checks_passed':True}),flush=True)
    except Exception:
        write(out/'FAILURE.json',{'traceback':traceback.format_exc(),'completed_recovery':recovery,'completed_boundary':bounds,'completed_performance':perf});raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--reps',type=int,default=5);a=p.parse_args();main(a.out.resolve(),a.reps)
