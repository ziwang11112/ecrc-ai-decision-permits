"""Portable no-model S11 rerun using the unchanged archived per-cell runners."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
PILOTS = ROOT / 'frozen/research_pilots'
PHASES = {'original_first100': 'ecrc_native_record_coverage_2026-09-15',
          'fixed_next100': 'ecrc_native_record_extension_2026-09-16',
          'constructed_boundaries': 'ecrc_airline_boundary_2026-09-16'}
COMMIT = '2174a603f6d014ef94473ffa95957f6ce27100db'

def load(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=PHASES, required=True)
    parser.add_argument('--tau2', type=Path, required=True, help='Pinned upstream checkout (no installation of tau2 required)')
    parser.add_argument('--out', type=Path, required=True, help='New output directory; never overwrite original evidence')
    parser.add_argument('--limit', type=int, help='Smoke only: use the first N contexts; omit for full phase')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1: parser.error('--limit must be positive')
    out=args.out.resolve()
    if out.exists(): parser.error('--out must not already exist')
    sys.dont_write_bytecode=True
    from verify_results import verify_integrity
    verify_integrity()
    upstream=args.tau2.resolve()
    mismatches=[name for name, expected in load(ROOT/'TAU2_REQUIRED_SHA256.json').items()
                if not (upstream/name).is_file() or sha(upstream/name)!=expected]
    if mismatches: raise RuntimeError('Pinned tau2 source mismatch: '+repr(mismatches[:10]))
    native=PILOTS/'ecrc_airline_pilot_2026-09-15'
    sys.path.insert(0,str(native))
    import bootstrap
    bootstrap.VENDOR=upstream
    source=PILOTS/('ecrc_airline_boundary_2026-09-16' if args.phase=='constructed_boundaries' else 'ecrc_native_record_coverage_2026-09-15')
    sys.path.insert(0,str(source))
    spec=importlib.util.spec_from_file_location('public_frozen_cell_runner',source/('run_boundary.py' if args.phase=='constructed_boundaries' else 'run_coverage.py'))
    runner=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    isolation=runner.inherited.setup()
    requests=load(ROOT/'inputs'/args.phase/'REQUESTS.json')
    cases=requests['cases'][:args.limit] if args.limit else requests['cases']
    out.mkdir(parents=True)
    write(out/'PUBLIC_RUN_METADATA.json',{'upstream_commit':COMMIT,'phase':args.phase,'smoke':args.limit is not None,
          'contexts':len(cases),'cells':len(cases)*len(runner.ARMS),'started_at':datetime.now(timezone.utc).isoformat(),
          'wrapper_sha256':sha(Path(__file__)),'source_provenance_sha256':sha(ROOT/'SOURCE_PROVENANCE.json'),
          'recorded_environment':'requirements-native.txt','python':sys.version,'isolation':isolation,
          'note':'Portable archival rerun. This is not a new independent cohort or official dialogue benchmark.'})
    from tau2.domains.airline.environment import get_environment
    before=get_environment().tools.db.model_dump(mode='json')
    before_file=out/'BEFORE_DB.json'
    write(before_file,before)
    if args.phase=='constructed_boundaries':
        from boundary_common import apply_patch, digest, write as fixture_write
        index=load(ROOT/'inputs/constructed_boundaries/FIXTURE_INDEX.json')
        if digest(before)!=index['base_db']['canonical_sha256']: raise RuntimeError('Fixture base differs from frozen base')
        fixtures={entry['case_id']:entry for entry in index['fixtures']}
    rows,comparisons=[],[]
    for i,case in enumerate(cases):
        cell_before,cell_file=before,before_file
        if args.phase=='constructed_boundaries':
            entry=fixtures[case['case_id']]
            cell_before=apply_patch(before,load(ROOT/'inputs/constructed_boundaries'/entry['patch_path']))
            cell_file=out/entry['before_path']
            fixture_write(cell_file,cell_before)
            if sha(cell_file)!=entry['before_file_sha256'] or digest(cell_before)!=entry['before_canonical_sha256']:
                raise RuntimeError('Reconstructed frozen fixture mismatch')
        hashes={}
        for arm in runner.ARMS[i%4:]+runner.ARMS[:i%4]:
            result,candidate,resolution,after=runner.one(case,arm,out/(case['case_id']+'__'+arm),cell_before,cell_file)
            rows.append(result)
            hashes[arm]={'candidates':candidate,'resolution':resolution,'after':after}
            if result['execution_error'] or result['native_errors'] or not result['case_evaluation']['metrics_valid']:
                raise RuntimeError('Invalid cell retained at '+str(out))
        comparisons.append({'case_id':case['case_id'],'same_resolution':len({h['resolution'] for h in hashes.values()})==1,
             'same_candidate_proposals':len({hashes[a]['candidates'] for a in runner.ARMS if a!='existing_rules_only'})==1,
             'rules_full_final_db_equal':hashes['qualification_ecrc']['after']==hashes['existing_rules_only']['after'],
             'claim_off_raw_final_db_equal':hashes['direct_native_dispatch']['after']==hashes['without_claim_evidence_requirement']['after'],
             'observable_hashes':hashes})
        write(out/'SUMMARY.json',{'phase':args.phase,'rows':rows,'comparisons':comparisons,'model_calls':0,'full_benchmark_run':False,'isolation':isolation})
        print(json.dumps({'contexts_complete':i+1,'contexts_planned':len(cases),'cells_complete':len(rows)}),flush=True)
    if any(not all(c[k] for k in ('same_resolution','same_candidate_proposals','rules_full_final_db_equal','claim_off_raw_final_db_equal')) for c in comparisons):
        raise RuntimeError('Paired comparison mismatch; all completed evidence retained')
    verify_integrity()

if __name__=='__main__': main()
