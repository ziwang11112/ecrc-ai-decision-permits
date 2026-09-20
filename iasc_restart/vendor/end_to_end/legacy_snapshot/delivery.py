"""Shared HTTP transport, identical for both compared implementations."""
import json,urllib.request

def run_one(adapter,permit,base_url,at,finish_at,drop=False,hook=None):
    hook=hook or (lambda name:None)
    job=adapter.arm(permit,at)
    hook('after_intent')
    if job['state']=='receipted':return json.loads(job['receipt_json'])
    data=json.dumps({'idempotency_key':job['idempotency_key'],'payload':json.loads(job['payload_json'])},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    headers={'Content-Type':'application/json'}
    if drop:headers['X-Test-Drop-Response']='1'
    req=urllib.request.Request(base_url+'/effects',data=data,headers=headers,method='POST')
    with urllib.request.urlopen(req,timeout=5) as response:ack=json.loads(response.read())
    hook('after_ack')
    receipt=adapter.finish(permit['permit_id'],ack,finish_at,before_commit=lambda:hook('before_commit'))
    hook('after_commit')
    return receipt
