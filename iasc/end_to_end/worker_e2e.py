"""One raw request worker; recovery only reads the durable request journal."""
import argparse,json,sys,urllib.request
def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',required=True);p.add_argument('--db',required=True);p.add_argument('--url',required=True)
    p.add_argument('--input');p.add_argument('--index',type=int);p.add_argument('--decision');p.add_argument('--at',required=True)
    p.add_argument('--stop-at',default='');p.add_argument('--start-gate',action='store_true');p.add_argument('--delay-ack',action='store_true')
    a=p.parse_args()
    if a.arm=='ecrc':from ecrc_e2e import Adapter
    else:from ordinary_e2e import Adapter
    adapter=Adapter(a.db)
    def hook(name):
        if a.stop_at==name:
            print(json.dumps({'event':'checkpoint','name':name}),flush=True);sys.stdin.readline()
    try:
        if a.input:
            raw=json.load(open(a.input,encoding='utf-8'))['requests'][a.index]
            decision=raw['proposal']['decision_id'];adapter.ingest(raw,a.at)
        else:
            decision=a.decision
            if adapter.get_request(decision) is None:raise ValueError('recovery raw request missing from durable journal')
        if a.start_gate:
            print(json.dumps({'event':'start_ready','decision_id':decision}),flush=True);sys.stdin.readline()
        permit=adapter.issue(decision,a.at,hook)
        if permit is None:
            print(json.dumps({'event':'done','decision_id':decision,'outcome':'cancelled'}),flush=True);return 0
        if permit['route'] not in ('alert','review'):
            print(json.dumps({'event':'done','decision_id':decision,'outcome':'nonaction','route':permit['route']}),flush=True);return 0
        job=adapter.arm(permit,a.at);hook('after_arm')
        if job['state']=='receipted':
            receipt=json.loads(job['receipt_json'])
        else:
            data=json.dumps({'idempotency_key':job['idempotency_key'],'payload':json.loads(job['payload_json'])},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
            headers={'Content-Type':'application/json'}
            if a.delay_ack:headers['X-Test-Delay-Response']='1'
            req=urllib.request.Request(a.url+'/effects',data=data,headers=headers,method='POST')
            with urllib.request.urlopen(req,timeout=.2 if a.delay_ack else 5) as response:ack=json.loads(response.read())
            hook('after_ack')
            receipt=adapter.finish(permit['permit_id'],ack,a.at,before_commit=lambda:hook('before_reconcile_commit'))
        print(json.dumps({'event':'done','decision_id':decision,'outcome':'receipted','permit_id':permit['permit_id'],'effect_id':receipt['service_effect_id']}),flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'event':'error','error_type':type(exc).__name__,'message':str(exc)}),flush=True);return 2
if __name__=='__main__':raise SystemExit(main())
