"""Shared frozen idempotent sink with one new post-commit ACK-delay hook."""
import argparse,json,os,time
from pathlib import Path
from legacy_snapshot.service import EffectLedger,EffectHandler,EffectServer
class DelayedHandler(EffectHandler):
    def reply(self,code,value):
        if code in (200,201) and self.command=='POST' and self.headers.get('X-Test-Delay-Response')=='1':
            time.sleep(1.0)
        return super().reply(code,value)
def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--port',type=int,default=0);a=p.parse_args()
    ledger=EffectLedger(a.db);server=EffectServer(('127.0.0.1',a.port),ledger)
    server.RequestHandlerClass=DelayedHandler
    print(json.dumps({'event':'ready','port':server.server_port,'pid':os.getpid()}),flush=True)
    try:server.serve_forever(poll_interval=.1)
    finally:server.server_close()
if __name__=='__main__':main()
