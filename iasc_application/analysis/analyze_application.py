"""Recalculate application outcomes and observed costs from per-job records."""
from pathlib import Path
import argparse, collections, csv, hashlib, json, sqlite3, statistics

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def lines(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):Path(p).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def csvwrite(p,rows):
    with Path(p).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--grid',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    plan=read(a.grid/'GRID_PLAN.json');rows=[];jobs=[];source_manifest={}
    for ri,cell in enumerate(plan['cells'],1):
        folder=a.grid/f'r{ri:03d}'
        summary=read(folder/'run_summary.json')
        assert summary['passed_technical'], 'Retained technical failures require explicit analysis; do not silently omit: '+str(folder)
        events=lines(folder/'client_events.jsonl');service=lines(folder/'service_runs/service_events.jsonl')
        start=summary['started_at_counter_ns'];D=summary['deadline_seconds']
        reconciled=[e for e in events if e['event']=='reconciled']
        timely={e['task_id'] for e in reconciled if e['result']['status']=='pass' and e['phase']=='primary' and (e['perf_counter_ns']-start)/1e9<=D}
        eventual={e['task_id'] for e in reconciled if e['result']['status']=='pass'}
        assert len(timely)==summary['n_timely_pass']
        commits={e['idempotency_key']:e for e in service if e['event']=='result_commit_return'}
        armed={e['operation_id']:e for e in events if e['event']=='armed'}
        rec_by_effect={e['effect_id']:e for e in reconciled}
        connection=sqlite3.connect((folder/'sink.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        connection.row_factory=sqlite3.Row
        result_rows=connection.execute('SELECT * FROM job_results ORDER BY effect_id').fetchall()
        assert connection.execute('SELECT COUNT(*) FROM run_aborts').fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM effects').fetchone()[0]==len(result_rows)
        connection.close()
        durable=set();counts=collections.Counter();starts=0;cpu=wall=launcher=0.0;newjobs=[]
        for row in result_rows:
            result=json.loads(row['result_json']);key=row['idempotency_key']
            assert hashlib.sha256(canonical(result).encode()).hexdigest()==row['result_hash']
            # Locate by retained relative attempt name, not an unverified external absolute path.
            attempt=folder/'service_runs'/Path(row['run_dir']).name
            raw=read(attempt/'raw_result.json');assert raw==result
            start_events=read(attempt/'work/actual_start_events.json')
            actual=sum(e['kind']=='suite_started' for e in start_events)
            assert actual==row['actual_starts']==result['actual_starts']==1
            starts+=actual;counts[result['status']]+=1
            cpu+=result['cpu_seconds'];wall+=result['wall_seconds'];launcher+=result['launcher_wall_seconds']
            commit_s=(commits[key]['perf_counter_ns']-start)/1e9
            if result['status']=='pass' and commit_s<=D:durable.add(result['task_id'])
            rec=rec_by_effect[row['effect_id']]
            assert rec['result_hash']==row['result_hash']
            jr={k:summary[k] for k in ['run_id','batch_id','arm','policy','condition']}
            jr.update(task_id=result['task_id'],candidate_id=result['candidate_id'],operation_id=key,
                effect_id=row['effect_id'],status=result['status'],result_hash=row['result_hash'],
                solution_sha256=result['solution_sha256'],test_sha256=result['test_sha256'],runner_sha256=result['runner_sha256'],
                launch_ordinal=armed[key]['launch_ordinal'],actual_starts=actual,child_cpu_seconds=result['cpu_seconds'],
                suite_wall_seconds=result['wall_seconds'],launcher_wall_seconds=result['launcher_wall_seconds'],
                launcher_start_elapsed_s=(result['host_launch_perf_counter_ns']-start)/1e9,
                result_commit_elapsed_s=commit_s,reconciled_elapsed_s=(rec['perf_counter_ns']-start)/1e9,
                reconciled_phase=rec['phase'],response_dropped=any(e['event']=='response_drop' and e['idempotency_key']==key for e in service))
            jobs.append(jr);newjobs.append(jr)
        stop=read(folder/'stop_observed_snapshot.json');final=read(folder/'final_client_snapshot.json')
        r={k:summary[k] for k in ['run_id','batch_id','arm','policy','condition']}
        r.update(eligible_tasks=len(summary['eligible_task_ids']),timely_tasks=len(timely),durable_pass_tasks_by_deadline=len(durable),
            eventual_pass_tasks=len(eventual),jobs=len(result_rows),actual_starts=starts,pass_jobs=counts['pass'],
            fail_jobs=counts['fail'],timeout_jobs=counts['timeout'],http_posts=summary['http_posts'],
            response_drops=sum(e['event']=='response_drop' for e in service),cache_hits=sum(e['event']=='cache_hit' for e in service),
            primary_retries=sum(e['event']=='retry' and e['phase']=='primary' for e in events),
            drain_retries=sum(e['event']=='retry' and e['phase']=='drain' for e in events),
            child_cpu_seconds=cpu,suite_wall_seconds=wall,launcher_wall_seconds=launcher,
            observed_stop_elapsed_s=next(e['elapsed_s'] for e in events if e['event']=='primary_stopped'),
            all_feedback_complete_elapsed_s=next(e['elapsed_s'] for e in events if e['event']=='trajectory_complete'),
            stop_held=stop['reserved'],stop_committed=stop['committed'],final_held=final['reserved'],final_committed=final['committed'],
            late_host_launches=sum(j['launcher_start_elapsed_s']>D for j in newjobs),
            denied_decisions=sum(e['event']=='issued' and e['route']!='alert' for e in events),
            timely_task_ids='|'.join(sorted(timely)),eventual_task_ids='|'.join(sorted(eventual)))
        assert r['actual_starts']==r['jobs']==r['final_committed']
        # A valid permit issued across D can remain unarmed and held. Retain
        # that state rather than assuming every run ends at zero held units.
        assert r['jobs']+r['final_held']<=summary['budget']
        rows.append(r)
        for path in [folder/'run_summary.json',folder/'client_events.jsonl',folder/'sink.sqlite',folder/'service_runs/service_events.jsonl']:
            source_manifest[path.relative_to(a.grid).as_posix()]=sha(path)
    groups=[]
    sums=['eligible_tasks','timely_tasks','durable_pass_tasks_by_deadline','eventual_pass_tasks','jobs','actual_starts',
        'pass_jobs','fail_jobs','timeout_jobs','http_posts','response_drops','cache_hits','primary_retries','drain_retries',
        'child_cpu_seconds','suite_wall_seconds','launcher_wall_seconds','late_host_launches','denied_decisions']
    for condition in ['normal','response_loss']:
        for policy in ['depth_first','round_robin']:
            for arm in ['ecrc','ordinary']:
                subset=[r for r in rows if (r['condition'],r['policy'],r['arm'])==(condition,policy,arm)]
                g=dict(condition=condition,policy=policy,arm=arm,batches=len(subset))
                g.update({k:sum(r[k] for r in subset) for k in sums})
                g.update(timely_percent=100*g['timely_tasks']/g['eligible_tasks'],
                    median_batch_complete_s=statistics.median(r['all_feedback_complete_elapsed_s'] for r in subset),
                    max_stop_held=max(r['stop_held'] for r in subset),max_final_held=max(r['final_held'] for r in subset))
                groups.append(g)
    pairs=[]
    for contrast,match,differing,left,right in [('round_robin_minus_depth_first',['arm','condition'],'policy','round_robin','depth_first'),
            ('ecrc_minus_ordinary',['policy','condition'],'arm','ecrc','ordinary'),
            ('response_loss_minus_normal',['arm','policy'],'condition','response_loss','normal')]:
        for leftrow in [r for r in rows if r[differing]==left]:
            rightrow=next(r for r in rows if r['batch_id']==leftrow['batch_id'] and r[differing]==right and all(r[k]==leftrow[k] for k in match))
            pair=dict(contrast=contrast,batch_id=leftrow['batch_id'],arm=leftrow['arm'] if 'arm' in match else 'paired',
                policy=leftrow['policy'] if 'policy' in match else 'paired',condition=leftrow['condition'] if 'condition' in match else 'paired')
            pair.update({k+'_difference':leftrow[k]-rightrow[k] for k in ['timely_tasks','eventual_pass_tasks','jobs','child_cpu_seconds','launcher_wall_seconds']})
            pairs.append(pair)
    csvwrite(a.out/'S9_runs.csv',rows);csvwrite(a.out/'S9_jobs.csv',jobs);csvwrite(a.out/'S9_cells.csv',groups);csvwrite(a.out/'S9_paired_batches.csv',pairs)
    summary={'planned_runs':plan['planned_runs'],'observed_runs':len(rows),'source_grid_sha256':sha(a.grid/'GRID_PLAN.json'),
        'protocol_sha256':plan['protocol_sha256'],'totals':{k:sum(r[k] for r in rows) for k in sums},
        'max_final_held':max(r['final_held'] for r in rows),'max_stop_held':max(r['stop_held'] for r in rows),
        'launcher_wall_median_seconds':statistics.median(j['launcher_wall_seconds'] for j in jobs),
        'launcher_wall_max_seconds':max(j['launcher_wall_seconds'] for j in jobs),'cells':groups,
        'scope':'All counts are finite-suite acceptance and observed resources on this host. Reused tasks across cells are not independent extra tasks.'}
    write(a.out/'S9_SUMMARY.json',summary);write(a.out/'SOURCE_MANIFEST.json',source_manifest)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
