"""Freeze the exploratory evaluation once, after development review."""
from pathlib import Path
from datetime import datetime, timezone
import math, platform, shutil, sqlite3, sys
from application_common import HERE, file_sha, read, write

def main():
    target=HERE/'FINAL_PROTOCOL.json'
    if target.exists():raise FileExistsError('Do not overwrite a frozen protocol')
    catalog=read(HERE/'bound_catalog.json')
    calibration=HERE/'workload/qa_development_serial_v2/summary.json'
    timing=read(calibration)
    assert timing['jobs']==80 and timing['all_start_states_known']
    assert timing['counts']['infrastructure_error']==0
    deadline=max(5,math.ceil(1.5*16*timing['launcher_wall_median_seconds']))
    assert deadline==5
    assert read(HERE/'development/integration_v2/SUMMARY.json')['technical_failures']==0
    qa=HERE.parents[1]/'qa/iasc_application_pilot_2026-09-12'
    audit=qa/'statistics/integration_v2_audit/AUDIT.json'
    boundary=qa/'contract/mock_boundary_v3/MOCK_BOUNDARY_QA.json'
    assert read(audit)['status']=='DEVELOPMENT_NORMALIZED_CORE_PASS'
    assert read(boundary)['passed'] and read(boundary)['workflow_sha256']==file_sha(HERE/'run_workflow.py')
    sources=[HERE/n for n in ['application_common.py','run_workflow.py','run_grid.py','prepare_legacy.py',
                              'freeze_protocol.py','legacy/request_template.json','legacy/SOURCE_MANIFEST.json',
                              'service/verification_service.py','service/frozen_service.py','workload/prepare_workload.py']]
    sources+=list((HERE/'legacy/end_to_end').rglob('*.py'))
    sources += [HERE/'workload'/n for n in catalog['runner_manifest']]
    source_hashes={p.relative_to(HERE).as_posix():file_sha(p) for p in sorted(set(sources))}
    snapshot=HERE/'frozen_source'
    if snapshot.exists():raise FileExistsError('Fresh source snapshot required')
    for name in source_hashes:
        dest=snapshot/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(HERE/name,dest)
    batch_ids=[b['batch_id'] for b in catalog['batches'] if b['partition']=='evaluation']
    assert len(batch_ids)==18
    protocol={
        'schema_version':1,'frozen':True,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'study_type':'post hoc exploratory controlled application experiment; no unseen-task or confirmatory claim',
        'question':'Finite-suite accepted tasks with feedback reconciled under a cumulative verification-count budget and deadline.',
        'catalog_sha256':file_sha(HERE/'bound_catalog.json'),
        'workload_catalog_sha256':file_sha(HERE/'workload/catalog.json'),
        'source_archive_sha256':catalog['source_archive_sha256'],
        'official_data_sha256':file_sha(HERE/'workload/sources/HumanEval.jsonl.gz'),
        'runner_sha256':catalog['runner_sha256'],'source_hashes':source_hashes,
        'evaluation_batch_ids':batch_ids,'eligible_tasks_per_batch':8,'candidate_opportunities_per_task':4,
        'arms':['ecrc','ordinary'],'policies':['depth_first','round_robin'],
        'conditions':['normal','response_loss'],'planned_runs':144,'parallel_trajectories':1,
        'budget':16,'budget_unit':'one issued cumulative verification-job unit, not a CPU, money or reusable-slot bound',
        'deadline_seconds':deadline,'deadline_rule':'max(5,ceil(1.5*16*median(all 80 serial development launcher_wall_seconds)))',
        'calibration_sha256':file_sha(calibration),
        'calibration_median_launcher_wall_seconds':timing['launcher_wall_median_seconds'],
        'pre_freeze_development_checks':{
            'independent_normalized_audit':{'sha256':file_sha(audit),'checks':read(audit)['checks'],'scope':'Eight development cells only'},
            'mock_deadline_drain_and_freeze_guard':{'sha256':file_sha(boundary),'cases':len(read(boundary)['cases'])+len(read(boundary)['freeze_guard_cases']),'scope':'Mock-only branch checks; no actual candidate execution'}},
        'recovery_backoff_seconds':1.0,
        'loss_rule':'Lose the first response after durable result commit on every fourth newly armed job; successful cached retry does not execute again. An infrastructure failure ends the run and is retained.',
        'primary_metric':'Distinct eligible tasks with official-suite-pass result checked and reconciled in the primary phase at observed elapsed_s <= D; denominator is all eight eligible tasks.',
        'deadline_boundary':'No new iteration or arm is deliberately initiated after observing D. An arm or host launcher already in progress may cross D. Primary feedback timestamp, not start, determines timely completion. Service startup and input/client setup precede the trajectory clock.',
        'cleanup':'Drain only already authorized pending feedback at the original retry due time; do not select new candidates or add drain feedback to primary completion.',
        'order':'Use run_grid.py counterbalance by batch parity for policy/condition order and batch+condition+policy position parity for arm order. One trajectory at a time.',
        'warmup':'None. Host/WSL cold-launch costs after trajectory start are retained. Development first-launch overhead was observed; D is not changed from the timing rule.',
        'policy_feedback':'Both policies stop a task only after reconciled pass, preserve candidate hash rank, and execute their own full trajectory.',
        'secondary_metrics':['durable pass count by observed commit-return timestamp <= D','eventual reconciled pass count',
            'actual trusted child starts','HTTP posts and cached retries','completed pass/fail/timeout jobs','infrastructure and workflow failures',
            'child CPU seconds','supervised suite wall seconds','host launcher wall seconds','held/committed units at recorded stop and final checkpoints'],
        'statistical_reporting':'All 18 batch pairs; descriptive paired differences and absolute counts. No inferential confidence intervals, significance tests or runtime-superiority claims.',
        'stopping':'Run the fixed 144-cell grid once without automatic reruns, extensions or outcome-based exclusions. Preserve every setup, workflow and infrastructure failure. Any implementation defect requires a versioned amendment and rerun of all affected comparisons.',
        'inclusion_gate':'Actual suite execution, independent finite-suite outcomes, auditable bindings/costs, and feedback-dependent choices must all work. Ties, unfavorable policy results or ordinary/ECRC equality do not disqualify inclusion. If evidence remains fragile or merely synthetic, leave manuscript unchanged.',
        'limits':['Previously exposed HumanEval tasks and published sanitized candidate programs; no fresh model generations or generation-cost estimates.',
            'Finite official suites can miss defects; no general correctness, production-loss avoidance or field-intervention effect.',
            'Only post-result-commit response loss while service stays alive; no exactly-once CPU guarantee through service failure before result commit.',
            'A held unknown outcome and committed outcome each consume one permanent unit. Delayed feedback does not remove an additional reusable slot.',
            'One installed Windows/WSL environment; declared engineering quota, deadline and injected failure frequency. Policy clock is fixed and separate from observed monotonic deadline time.'],
        'runtime':{'python':sys.version,'platform':platform.platform(),'sqlite':sqlite3.sqlite_version},
        'candidate_code_redistribution':'Do not include candidate bodies in the public add-on. Publish exact source download recipe, hashes and code-free results.'
    }
    write(target,protocol)
    write(HERE/'FREEZE_MANIFEST.json',{'protocol_sha256':file_sha(target),'source_snapshot_files':source_hashes,
        'input_files':{n:file_sha(HERE/n) for n in ['PILOT_PLAN.md','bound_catalog.json','workload/catalog.json',
            'workload/qa_development_serial_v2/summary.json','development/integration_v2/SUMMARY.json']}})
    print(target)
    print(file_sha(target))

if __name__=='__main__':main()
