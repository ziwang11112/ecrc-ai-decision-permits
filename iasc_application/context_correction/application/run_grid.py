"""Run every predeclared cell; retain setup and technical failures without retry."""
from pathlib import Path
import argparse,itertools,json,sys,time,traceback
from application_common import HERE,canonical,file_sha,read,write
from run_workflow import run_one

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['development','evaluation'],required=True)
    p.add_argument('--out',required=True);p.add_argument('--protocol');a=p.parse_args()
    destination=Path(a.out).resolve()
    if destination.exists():raise FileExistsError('Fresh grid output directory required')
    destination.mkdir(parents=True)
    catalog=HERE/'bound_catalog.json'
    if a.stage=='evaluation':
        assert a.protocol,'Frozen protocol required'
        fp=read(a.protocol);assert fp['frozen']
        batches=fp['evaluation_batch_ids'];deadline=fp['deadline_seconds'];budget=fp['budget'];backoff=fp['recovery_backoff_seconds']
    else:
        fp=None;batches=['development_01'];deadline=5;budget=16;backoff=1.0
    cells=[]
    for bi,batch in enumerate(batches):
        conditions=['normal','response_loss'] if bi%2==0 else ['response_loss','normal']
        policies=['depth_first','round_robin'] if bi%2==0 else ['round_robin','depth_first']
        for ci,condition in enumerate(conditions):
            for pi,policy in enumerate(policies):
                arms=['ecrc','ordinary'] if (bi+ci+pi)%2==0 else ['ordinary','ecrc']
                for arm in arms:cells.append({'batch':batch,'condition':condition,'policy':policy,'arm':arm})
    write(destination/'GRID_PLAN.json',{'stage':a.stage,'planned_runs':len(cells),'cells':cells,
          'catalog_sha256':file_sha(catalog),'protocol_sha256':file_sha(a.protocol) if a.protocol else None,
          'parallel_trajectories':1,'automatic_reruns':0})
    started=time.time();rows=[]
    for index,c in enumerate(cells,1):
        # Short disk names avoid Windows MAX_PATH in nested runner receipts.
        # Scientific identity remains explicit in GRID_PLAN and each summary.
        name=f'r{index:03d}'
        try:
            row=run_one(catalog_path=catalog,batch_id=c['batch'],arm=c['arm'],policy=c['policy'],condition=c['condition'],
                        budget=budget,deadline=deadline,backoff=backoff,out=destination/name,formal_protocol=a.protocol)
        except BaseException as exc:
            folder=destination/name;folder.mkdir(exist_ok=True)
            row={'run_id':name,'batch_id':c['batch'],'arm':c['arm'],'policy':c['policy'],'condition':c['condition'],
                 'passed_technical':False,'failure':{'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}}
            write(folder/'setup_failure.json',row)
        rows.append(row)
        with (destination/'outcomes.jsonl').open('a',encoding='utf-8') as f:f.write(canonical(row)+'\n')
        progress={'finished':index,'planned':len(cells),'failed_technical':sum(not x['passed_technical'] for x in rows),
                  'elapsed_wall_seconds':round(time.time()-started,3),'last':{k:row.get(k) for k in ['run_id','n_timely_pass','n_tasks','http_posts','passed_technical']}}
        write(destination/'PROGRESS.json',progress);print(canonical(progress),flush=True)
    summary={'stage':a.stage,'planned_runs':len(cells),'observed_runs':len(rows),'all_runs_retained':len(rows)==len(cells),
             'technical_failures':sum(not x['passed_technical'] for x in rows),'elapsed_wall_seconds':time.time()-started,
             'model_calls':0,'automatic_reruns':0}
    write(destination/'SUMMARY.json',summary);print(canonical(summary),flush=True)
    return int(summary['technical_failures']>0)

if __name__=='__main__':raise SystemExit(main())
