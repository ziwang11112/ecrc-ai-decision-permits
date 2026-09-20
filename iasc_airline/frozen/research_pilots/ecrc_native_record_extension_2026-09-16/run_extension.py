"""Use the frozen previous native runner with only input/output root redirected."""
import argparse
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parents[1]
PRIOR=ROOT.parent/'ecrc_native_record_coverage_2026-09-15'
QA=WORKSPACE/'qa/iasc_followup_experiments_2026-09-16'
spec=importlib.util.spec_from_file_location('frozen_native_coverage_runner',PRIOR/'run_coverage.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.ROOT=ROOT
original_manifest=runner.manifest

def manifest():
    sources,vendor=original_manifest()
    paths=[PRIOR/'run_coverage.py',QA/'independent_audit.py']
    paths.extend(sorted((PRIOR/'review/postrun_01').glob('*.py')))
    paper=WORKSPACE/'output/iasc_comparator_revision_2026-09-16'
    paths.extend([paper/'main.tex',paper/'main.pdf',paper/'references.bib'])
    paths.extend(sorted((paper/'content').glob('*.tex')))
    paths.extend(sorted((paper/'tables').glob('*.tex')))
    paths.extend(sorted((paper/'figures').glob('*.pdf')))
    for p in paths:
        sources[str(p.resolve())]=runner.sha(p)
    return sources,vendor

runner.manifest=manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','run'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--freeze',type=Path)
    args=parser.parse_args()
    if args.mode=='prepare':
        runner.prepare(args.out.resolve())
    else:
        if args.freeze is None: parser.error('run requires --freeze')
        runner.batch(args.out.resolve(),args.freeze.resolve())
