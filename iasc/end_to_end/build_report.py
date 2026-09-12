"""Generate the editable S8 table and report solely from a completed run."""
import argparse,csv,hashlib,json
from pathlib import Path
from collections import Counter
HERE=Path(__file__).resolve().parent
PHASES={
 'distinct_contenders':('Distinct contenders: after competition','after_competition'),
 'mixed_claim_fallback':('Unsupported claim: after release','unsupported_claim_released'),
 'kill_during_issuance':('Issuance kill: after rollback','after_inflight_issue_kill'),
 'kill_after_issue_resume':('Issue/arm gap: early cleanup','early_cleanup_retained'),
 'expired_unarmed_cleanup':('Expiry: after unarmed cleanup','expired_unarmed_cancelled'),
 'accepted_timeout_cleanup_recovery':('ACK timeout: after cleanup','cleanup_retained_unknown_grant')}
def write(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);a=parser.parse_args();out=a.out.resolve()
    traces=[]
    for path in sorted(out.glob('*/*/*/trace.json')):
        trace=json.load(open(path,encoding='utf-8'))
        input_path=path.parent/'input.json'
        trace['observed_input_sha256']=hashlib.sha256(input_path.read_bytes()).hexdigest() if input_path.exists() else None
        source=HERE/'inputs'/f"{trace['scenario']}.json"
        trace['input_matches_source']=trace['observed_input_sha256']==trace['input_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
        traces.append(trace)
    if len(traces)!=36:raise ValueError('S8 report expects all 36 primary traces, including failures')
    inventory=Counter((r['scenario'],r['arm']) for r in traces)
    if any(inventory[(s,arm)]!=3 for s in PHASES for arm in ('ordinary','ecrc')):raise ValueError('planned scenario/arm inventory differs')
    fair=[]
    for s in PHASES:
        for rep in range(3):
            pair=[r for r in traces if r['scenario']==s and r['rep']==rep]
            fair.append({'scenario':s,'rep':rep,'input_sha256_match':all(r['input_matches_source'] for r in pair) and len({r['observed_input_sha256'] for r in pair})==1,'sha256':pair[0]['observed_input_sha256']})
    write(out/'INFORMATION_MATCH.json',{'all_match':all(r['input_sha256_match'] for r in fair),'pairs':len(fair),'results':fair,'compared':'original raw policy/proposal/evidence files; not winning IDs or generated IDs'})
    table=[]
    for s,(label,checkpoint) in PHASES.items():
        arms={arm:[r for r in traces if r['scenario']==s and r['arm']==arm] for arm in ('ordinary','ecrc')}
        states=[]
        for r in arms['ordinary']+arms['ecrc']:
            match=[p for p in r['phases'] if p['phase']==checkpoint]
            if match:states.append(tuple(match[0][k] for k in ('permits','reserved','effects','receipts')))
        observed='; '.join('/'.join(map(str,row)) for row in sorted(set(states))) if states else 'unobserved'
        row={'scenario':s,'checkpoint':checkpoint,'observed_P_H_E_R':observed,'checkpoint_observations':len(states)}
        for arm,group in arms.items():
            row[arm+'_passed']=sum(r['passed'] for r in group)
            row[arm+'_planned']=len(group)
            row[arm+'_final_effects']=';'.join(map(str,sorted({r['final'].get('effects',-1) for r in group})))
        table.append(row)
    with (out/'S8_state_table.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    lines=[r'\begin{table}[!htbp]',r'\centering',r'\caption{New raw-request issuance and delivery experiment. $P/H/E/R$ denotes registered permits, held units, durable sink effects and local receipts at the named checkpoint; $P$ includes non-action and cancelled permits retained for audit. Checkpoints were read from saved client and sink databases. Final columns give passed/planned runs and effects per run. Each scenario has three runs per implementation; concurrent winners may differ.}',r'\label{tab:e2e-state}',r'\small',r'\begin{tabular}{p{0.36\linewidth}ccc}',r'\hline',r'Scenario / checkpoint & $P/H/E/R$ & Ordinary & ECRC \\',r'\hline']
    for row in table:
        label=PHASES[row['scenario']][0]
        ordinary=f"{row['ordinary_passed']}/{row['ordinary_planned']}; {row['ordinary_final_effects']}"
        ecrc=f"{row['ecrc_passed']}/{row['ecrc_planned']}; {row['ecrc_final_effects']}"
        lines.append(f"{label} & {row['observed_P_H_E_R']} & {ordinary} & {ecrc} "+r'\\')
    lines += [r'\hline',r'\end{tabular}',r'\end{table}']
    (out/'S8_results_table.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    passed=sum(r['passed'] for r in traces);effects=sum(r['final'].get('effects',0) for r in traces)
    allphases=[p for r in traces for p in r['phases']]
    summary={'primary_runs':36,'passed':passed,'failed':36-passed,'effects_across_primary_runs':effects,
             'recorded_database_checkpoint_pairs':len(allphases),'checkpoint_checks':sum(p['checks'] for p in allphases),
             'input_pairs_matched':all(r['input_sha256_match'] for r in fair),
             'source_manifest_sha256':hashlib.sha256((out/'RUN_MANIFEST.json').read_bytes()).hexdigest()}
    write(out/'REPORT_SUMMARY.json',summary)
    text=f'''# S8 raw-request experiment: observed results

## Methods snippet

We added a post hoc raw-request experiment with a new atomic issuance wrapper. For ECRC, reservation, claim fallback/release, registration and full permit persistence were enclosed in one new SQLite issuance transaction around the frozen adjudicator; this does not change the transaction guarantees claimed for the archived implementation. A conventional JSON/relational implementation independently performed issuance from the same raw policy, proposal and evidence records without ECRC validation functions. Both used the same trusted, separately persisted loopback HTTP sink and durable-grant delivery contract. Eight distinct alert decisions competed for two units; a mixed scenario additionally exercised four review contenders at one review unit and an unsupported-claim release. Six checkpoint-based scenarios were run three times per implementation (36 runs), including issuance interruption, post-issuance recovery, expired-unarmed cleanup and a real client timeout caused by delaying an acknowledgement after sink commit. Cleanup could release an expired unarmed permit only while atomically preventing later dispatch; it retained armed grants with unknown outcomes. Policy clocks were injected, while effect and reconciliation times were observed wall-clock values. This fixed-schema, single-policy experiment reports correctness observations, not performance or fault probabilities.

## Results snippet generated from this run

Of the 36 planned runs, {passed} met the declared outcome checks and {36-passed} failed. The saved final databases contained {effects} synthetic effects across the runs. The original raw input hashes matched in every paired arm/run: {summary['input_pairs_matched']}. Supplementary Table S8 reports the actual checkpoint states and final outcomes, including failures if present. The harness saved {len(allphases)} client/sink checkpoint pairs for independent database inspection; this count is an audit inventory, not an additional experimental sample size. Concurrent admission identities were not required to match across implementations.

## Limits retained

Issuance atomicity is newly implemented. Evidence is authorization evidence; the experiment does not verify the computational provenance of a predictor. Budgets are cumulative within one policy revision and scope. The sink's effect is a durable synthetic record, not participant notification or benefit. Post-arm grants remain irrevocable and unknown outcomes may retain capacity indefinitely. The selected checkpoints do not exhaust execution interleavings or estimate deployment reliability. Independent source-informed implementations share transport and sink. The old S6 timing values are unchanged and this extension makes no timing comparison.
'''
    (out/'MANUSCRIPT_SNIPPETS.md').write_text(text,encoding='utf-8');print(json.dumps(summary))
if __name__=='__main__':main()
