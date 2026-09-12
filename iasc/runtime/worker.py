import argparse,json,sys
from delivery import run_one
from fixture import ARM_AT,DONE_AT

def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=['ecrc','ordinary'],required=True);p.add_argument('--db',required=True);p.add_argument('--fixture',required=True);p.add_argument('--url',required=True);p.add_argument('--stop-at',default='');p.add_argument('--start-gate',action='store_true');p.add_argument('--drop',action='store_true');p.add_argument('--at',default=ARM_AT);p.add_argument('--finish-at',default=DONE_AT);a=p.parse_args()
    if a.arm=='ecrc':from ecrc_adapter import Adapter
    else:from ordinary_adapter import Adapter
    adapter=Adapter(a.db);permit=json.load(open(a.fixture))['permits'][0]
    def hook(name):
        if a.stop_at==name:
            print(json.dumps({'event':'checkpoint','name':name}),flush=True)
            sys.stdin.readline()
    if a.start_gate:
        print(json.dumps({'event':'start_ready'}),flush=True);sys.stdin.readline()
    try:
        receipt=run_one(adapter,permit,a.url,a.at,a.finish_at,a.drop,hook)
        print(json.dumps({'event':'done','receipt':receipt}),flush=True)
    except Exception as exc:
        print(json.dumps({'event':'error','error_type':type(exc).__name__,'message':str(exc)}),flush=True);return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
