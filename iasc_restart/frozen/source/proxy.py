"""Common, predeclared response-withholding window; effects stay in unchanged sink."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import threading
import urllib.error
import urllib.request
from urllib.parse import unquote
from common import canonical


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--job-hash', required=True)
    parser.add_argument('--condition', required=True)
    parser.add_argument('--log', required=True)
    args = parser.parse_args()
    lock = threading.Lock()
    state = {'released': args.condition == 'normal', 'blocked_keys': set()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path == '/release':
                state['released'] = True
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
                return
            self.forward()

        def do_GET(self):
            self.forward()

        def forward(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
            value = json.loads(body) if body else None
            if value:
                payload = value.get('payload', {})
                if (payload.get('job_hash') == args.job_hash
                        or payload.get('decision_id') == 'job-' + args.job_hash):
                    state['blocked_keys'].add(value['idempotency_key'])
                key = value.get('idempotency_key')
            else:
                key = unquote(self.path.split('/effects/', 1)[-1])
            req = urllib.request.Request(args.upstream + self.path, data=body,
                                         headers={'Content-Type': 'application/json'}, method=self.command)
            try:
                response = urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                returned = response.read()
                code = response.status
            drop = not state['released'] and key in state['blocked_keys']
            with lock, open(args.log, 'a', encoding='utf-8') as handle:
                handle.write(canonical({'method': self.command, 'path': self.path, 'key': key,
                                        'request': value,
                                        'upstream_code': code, 'withheld': drop,
                                        'upstream_response': json.loads(returned)}) + '\n')
            if drop:
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(returned)))
            self.end_headers()
            self.wfile.write(returned)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    print(canonical({'event': 'ready', 'pid': os.getpid(), 'port': server.server_port}), flush=True)
    server.serve_forever(poll_interval=.1)


if __name__ == '__main__':
    main()
