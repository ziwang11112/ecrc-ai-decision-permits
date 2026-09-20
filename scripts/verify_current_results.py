"""Run compact saved-result checks without API, model or candidate execution."""
from pathlib import Path
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
COMMANDS=[
    ('S6/S8 observations','plots/current/verify_observations.py'),
    ('S9-C retained results','iasc_application/context_correction/verify_current.py'),
    ('S10 saved evidence','iasc_model_check/portable_reproduce.py'),
    ('S11 qualification','iasc_airline/verify_results.py'),
    ('S12 restart witness','iasc_restart/verify.py'),
]

def main():
    reports=[]
    for label, entry in COMMANDS:
        proc=subprocess.run([sys.executable,'-B',str(ROOT/entry)],cwd=ROOT,capture_output=True,
                            text=True,encoding='utf-8',errors='replace')
        if proc.returncode:
            print(proc.stdout);print(proc.stderr,file=sys.stderr)
            raise SystemExit(label+' verification failed')
        reports.append({'study':label,'command':entry,'exit_code':proc.returncode,'stdout':proc.stdout.strip()})
    print(json.dumps({'status':'PASS','scope':'Compact saved evidence; see study guides for full event/SQL audits and fresh execution.',
                      'checks':reports},indent=2))

if __name__=='__main__':
    main()
