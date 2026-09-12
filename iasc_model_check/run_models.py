"""Run the fixed TLC cases once, preserving complete logs and failed runs."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--public-only', action='store_true',
                        help='Reproduce models without checking unavailable author manuscript artifacts')
    args = parser.parse_args()
    if not args.run_id.replace('_', '').isalnum(): raise SystemExit('Simple run ID required')
    freeze = read(HERE / 'FREEZE.json')
    for name, digest in freeze['source_hashes'].items():
        if sha(HERE / name) != digest: raise SystemExit('Freeze mismatch: ' + name)
    manifest = read(HERE / 'tools/TOOLCHAIN.json')
    java = HERE / 'tools' / manifest['java']['java_executable_relative']
    jar = HERE / 'tools' / manifest['tlc']['jar']
    if sha(java) != manifest['java']['java_executable_sha256'] or sha(jar) != manifest['tlc']['jar_sha256']:
        raise SystemExit('Toolchain hash mismatch')
    base = HERE / 'runs' / args.run_id / 'tlc'
    base.mkdir(parents=True, exist_ok=False)
    write(base / 'START.json', dict(utc=datetime.now(timezone.utc).isoformat(), freeze_sha256=sha(HERE/'FREEZE.json')))
    results = []
    for case in freeze['cases']:
        directory = base / case['id']
        directory.mkdir()
        for name in ('ECRCLifecycle.tla', case['id'] + '.cfg'):
            shutil.copy2(HERE / name, directory / name)
        command = [str(java), '-Xmx2g', '-cp', str(jar), 'tlc2.TLC',
                   '-workers', '1', '-fp', '0', '-coverage', '1',
                   '-metadir', str(directory / 'states'), '-config', case['id'] + '.cfg',
                   'ECRCLifecycle.tla']
        print(json.dumps({'starting': case['id'], 'utc': datetime.now(timezone.utc).isoformat()}), flush=True)
        write(directory / 'COMMAND.json', dict(command=command, cwd=str(directory), case=case))
        start = time.perf_counter()
        timed_out = False
        with (directory / 'stdout.txt').open('w', encoding='utf-8') as out, (directory / 'stderr.txt').open('w', encoding='utf-8') as err:
            p = subprocess.Popen(command, cwd=directory, stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            try: code = p.wait(timeout=case['timeout_seconds'])
            except subprocess.TimeoutExpired:
                timed_out = True
                p.kill()
                code = p.wait(timeout=30)
        elapsed = time.perf_counter() - start
        log = (directory / 'stdout.txt').read_text(encoding='utf-8', errors='replace')
        err = (directory / 'stderr.txt').read_text(encoding='utf-8', errors='replace')
        stats = re.findall(r'([\d,]+) states generated, ([\d,]+) distinct states found, ([\d,]+) states left on queue', log)
        counts = dict(zip(('generated_states', 'distinct_states', 'queue_remaining'),
                          (int(s.replace(',', '')) for s in stats[-1]))) if stats else {}
        depths = re.findall(r'The depth of the complete state graph search is (\d+)', log)
        clean = ('Model checking completed. No error has been found.' in log and code == 0 and not timed_out
                 and counts.get('queue_remaining') == 0)
        witness = ('Invariant EffectCountBound is violated.' in log and 'State 1:' in log
                   and not timed_out and code != 0)
        status = ('EXPECTED_COUNTEREXAMPLE' if witness else 'NOT_CONFIRMED') if case['unsafe'] else ('COMPLETE_PASS' if clean else 'INCOMPLETE_OR_FAILURE')
        result = dict(case=case, status=status, returncode=code, timed_out=timed_out,
                      elapsed_seconds=elapsed, **counts,
                      reported_search_depth=int(depths[-1]) if depths else None,
                      exhaustive_positive=bool(clean and not case['unsafe']),
                      exhaustive_negative=False if case['unsafe'] else None,
                      stdout_sha256=sha(directory/'stdout.txt'), stderr_sha256=sha(directory/'stderr.txt'),
                      stderr_nonempty=bool(err.strip()), completed_utc=datetime.now(timezone.utc).isoformat())
        write(directory / 'RESULT.json', result)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    baseline = read(HERE / 'ARTIFACT_BASELINE.json')
    preservation = ({name: (ROOT / name).is_file() and sha(ROOT / name) == digest for name, digest in baseline.items()}
                    if not args.public_only else {})
    all_expected = (len(results) == 3 and all(r['status'] ==
                    ('EXPECTED_COUNTEREXAMPLE' if r['case']['unsafe'] else 'COMPLETE_PASS') for r in results))
    suite_pass = all_expected and (args.public_only or (bool(preservation) and all(preservation.values())))
    summary = dict(results=results, preservation=preservation,
                   all_preserved=all(preservation.values()) if preservation else None,
                   artifact_check_skipped_for_public_reproduction=args.public_only,
                   tlc_suite_pass=suite_pass, independent_check_pending=True,
                   manuscript_addition_decided=False)
    write(base / 'SUMMARY.json', summary)
    print(json.dumps({'tlc_suite_pass': suite_pass, 'independent_check_pending': True}), flush=True)
    raise SystemExit(0 if suite_pass else 1)

if __name__ == '__main__': main()
