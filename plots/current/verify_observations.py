"""Recalculate current S8 checkpoint and S6 latency summaries, standard library only."""
from pathlib import Path
from collections import defaultdict
from statistics import median
from decimal import Decimal
import argparse, csv, hashlib, json

HERE = Path(__file__).resolve().parent

def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))

def verify():
    for record in json.loads((HERE/'SOURCE_MANIFEST.json').read_text())['files']:
        assert hashlib.sha256((HERE/record['path']).read_bytes()).hexdigest()==record['sha256'], record['path']
    checkpoints=rows(HERE/'data/S8_CHECKPOINT_COUNTS.csv')
    assert len(checkpoints)==42
    groups=defaultdict(list)
    for row in checkpoints:
        path=HERE/'data/checkpoint_audits'/row['scenario']/row['repetition']/row['implementation']/'snapshots'/row['checkpoint']/'audit.json'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row['source_sha256']
        audit=json.loads(path.read_text())
        counts=tuple(int(row[name]) for name in ['S_held','C_committed','X_effects','receipts'])
        assert counts==tuple(audit[name] for name in ['reserved','committed','effects','receipts'])
        groups[row['checkpoint']].append((row['implementation'],row['repetition'],counts))
    table2=[]
    for name, group in groups.items():
        assert {(a,b) for a,b,_ in group}=={(a,b) for a in ['ecrc','ordinary'] for b in ['rep-0','rep-1','rep-2']}
        assert len(group)==6 and len({x[2] for x in group})==1
        table2.append(dict(zip(['checkpoint','S','C','X','receipts'],[name,*group[0][2]])))
    runs=rows(HERE/'data/S6_performance_runs.csv')
    assert len(runs)==30 and sum(int(r['n_timed_requests']) for r in runs)==1920
    table3=[]
    for workers in [1,4,8]:
        for arm in ['ecrc','ordinary']:
            group=[r for r in runs if int(r['workers'])==workers and r['arm']==arm]
            assert len(group)==5 and len({r['rep'] for r in group})==5
            p95=[Decimal(r['p95_latency_ms']) for r in group]
            table3.append({'workers':workers,'implementation':arm,'median_p95_ms':str(median(p95)),
                           'min_p95_ms':str(min(p95)),'max_p95_ms':str(max(p95))})
    return {'status':'PASS','scope':'Saved checkpoint audit counts and timing observations; no new service runs.',
            'S8_checkpoints':42,'Table2':table2,'S6_runs':30,'S6_timed_requests':1920,'Table3':table3}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    result=verify()
    if args.out:
        if args.out.exists(): parser.error('Choose a fresh report path')
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
