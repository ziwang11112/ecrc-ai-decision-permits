"""Run one bounded, eight-cell synthetic S12 replay in a fresh external folder.

This is new QA, never a replacement for the historical evidence. Stdlib only;
the only HTTP traffic is between locally started service/proxy/client processes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New directory outside this code package; must not exist')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.is_relative_to(HERE):
        raise ValueError('Choose an output directory outside iasc_restart to preserve historical records')
    out.mkdir(parents=True, exist_ok=False)
    runtime = out / 'runtime'
    source = runtime / 'research_pilots/ecrc_mixed_workflow_dev_2026-09-15'
    shutil.copytree(HERE / 'frozen/source', source)
    shutil.copy2(HERE / 'PROTOCOL.md', source / 'PROTOCOL.md')
    shutil.copytree(HERE / 'vendor/raw_task_baseline_2026-09-14', runtime / 'research_pilots/raw_task_baseline_2026-09-14')
    shutil.copytree(HERE / 'vendor/end_to_end', runtime / 'output/AIR-014_IASC_Reproducibility/end_to_end')
    def manifest():
        return {p.relative_to(runtime).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(runtime.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    before = manifest()
    qa = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', 'test_direct_adapter'], cwd=source,
                        capture_output=True, text=True, encoding='utf-8',
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (out / 'QA_LOG.txt').write_text(qa.stdout + '\n' + qa.stderr, encoding='utf-8')
    if qa.returncode:
        raise RuntimeError('Original 13-test development QA failed; inspect QA_LOG.txt')
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location('s12_original_runner', source / 'run_development.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Call unchanged run_cell, bypassing only the historical manifest() function,
    # whose protected-manuscript paths are intentionally absent from this export.
    cases = [{'arm': arm, 'condition': condition} for condition in ('normal', 'mixed')
             for arm in (module.ARMS if condition == 'normal' else tuple(reversed(module.ARMS)))]
    write(out / 'FREEZE.json', {'sources': before, 'cases': cases, 'python': sys.version,
          'classification': 'new bounded portability QA; not historical or confirmatory evidence'})
    results = [module.run_cell(out / 'runs' / (case['condition'] + '__' + case['arm']), **case) for case in cases]
    unchanged = before == manifest()
    passed = unchanged and all(result['failure'] is None and result['audit'].get('technical_audit_passed') for result in results)
    write(out / 'SUMMARY.json', {'classification': 'new bounded portability QA; do not aggregate with either historical batch',
          'sources_unchanged': unchanged, 'technical_audits_passed': passed, 'cells': results, 'model_calls': 0,
          'model_api_cost_usd': 0, 'portable_changes': 'New wrapper stages original directory layout and freezes runtime files; manuscript guard removed from new QA only. Original client, service, runner run_cell, tests and auditor are byte-identical.'})
    print(json.dumps({'classification': 'new QA only', 'completed_cells': len(results), 'passed': passed, 'model_calls': 0}))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
