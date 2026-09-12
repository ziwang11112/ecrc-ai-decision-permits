"""Read-only SANY preparation and immutable model/checker input freeze."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def preserve():
    if (HERE / 'ARTIFACT_BASELINE.json').exists(): return
    files = [p for p in (ROOT / 'output/iasc_overleaf').rglob('*') if p.is_file()]
    files += [ROOT / 'output' / name for name in (
        'AIR-014_IASC_Manuscript.pdf', 'AIR-014_IASC_Overleaf.zip',
        'AIR-014_IASC_Supplementary_Figures.pdf', 'AIR-014_IASC_Code_and_Reproducibility.zip',
        'AIR-014_IASC_S9_Code_and_Results.zip', 'AIR-014_IASC_S9_SHA256SUMS.txt')]
    old = ROOT / 'research_pilots/iasc_application_2026-09-12/legacy/end_to_end'
    files += sorted(old.rglob('*.py'))
    write(HERE / 'ARTIFACT_BASELINE.json', {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['parse', 'freeze'])
    args = parser.parse_args()
    preserve()
    if args.action == 'parse':
        manifest = read(HERE / 'tools/TOOLCHAIN.json')
        java = HERE / 'tools' / manifest['java']['java_executable_relative']
        jar = HERE / 'tools' / manifest['tlc']['jar']
        if sha(java) != manifest['java']['java_executable_sha256'] or sha(jar) != manifest['tlc']['jar_sha256']:
            raise SystemExit('Toolchain hash mismatch')
        directory = HERE / 'preparation'
        directory.mkdir(exist_ok=True)
        index = len(list(directory.glob('SANY_*.json'))) + 1
        command = [str(java), '-cp', str(jar), 'tla2sany.SANY', 'ECRCLifecycle.tla']
        p = subprocess.run(command, cwd=HERE, text=True, encoding='utf-8', errors='replace',
                           capture_output=True, timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        log = p.stdout + '\n' + p.stderr
        passed = (p.returncode == 0 and 'Semantic processing of module ECRCLifecycle' in log
                  and not any(token in log for token in ('*** Errors:', 'Fatal errors', 'Parse Error')))
        result = dict(command=command, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr,
                      model_sha256=sha(HERE / 'ECRCLifecycle.tla'), passed=passed,
                      state_space_exploration=False, utc=datetime.now(timezone.utc).isoformat())
        write(directory / f'SANY_{index:02d}.json', result)
        print(log)
        raise SystemExit(0 if passed else 1)
    if (HERE / 'FREEZE.json').exists(): raise SystemExit('Freeze already exists; do not overwrite')
    review = read(HERE / 'MODEL_REVIEW.json')
    if review.get('verdict') != 'PASS': raise SystemExit('Model review must pass before freeze')
    for name, digest in review['bindings'].items():
        if sha(HERE / name) != digest: raise SystemExit('Model review binding mismatch: ' + name)
    parses = [read(p) for p in (HERE / 'preparation').glob('SANY_*.json')]
    if not any(p['passed'] and p['model_sha256'] == sha(HERE/'ECRCLifecycle.tla') for p in parses):
        raise SystemExit('No successful SANY check for current model')
    names = ['PROTOCOL.md', 'ECRCLifecycle.tla', 'normal_2_1.cfg', 'normal_3_2.cfg', 'unsafe_2_1.cfg',
             'prepare_model.py', 'run_models.py', 'exact_check.py', 'SOURCE_MAPPING.md',
             'MODEL_REVIEW.json', 'CHECKPOINT_PREFIX_MAPPING.md', 'REVIEW_REQUIREMENTS.md', 'ARTIFACT_BASELINE.json',
             'tools/TOOLCHAIN.json', 'tools/run_tlc.py']
    freeze = dict(frozen_utc=datetime.now(timezone.utc).isoformat(),
                  source_hashes={name: sha(HERE / name) for name in names},
                  cases=[dict(id='normal_2_1', n=2, capacity=1, unsafe=False, timeout_seconds=600),
                         dict(id='normal_3_2', n=3, capacity=2, unsafe=False, timeout_seconds=600),
                         dict(id='unsafe_2_1', n=2, capacity=1, unsafe=True, timeout_seconds=120)],
                  workers=1, fingerprint_index=0, heap='2g',
                  positive_search='full reachable-state search; no state/depth constraints',
                  negative_search='stop at first EffectCountBound counterexample',
                  independent_check='exact Python state equality, same fixed instances',
                  manuscript_changed=False)
    write(HERE / 'FREEZE.json', freeze)
    print(json.dumps({'frozen_files': len(names), 'cases': len(freeze['cases']), 'sha256': sha(HERE/'FREEZE.json')}))

if __name__ == '__main__': main()
