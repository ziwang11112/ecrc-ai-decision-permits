"""Post-run extraction and replay of the retained TLC counterexample.

The independently written exact enumerator replays the separately generated
TLC trace; this does not launch another search or any concrete client.
"""
from pathlib import Path
import csv
import hashlib
import json
import re
import sys
sys.dont_write_bytecode = True
from exact_check import FiniteModel, SET_NAMES, ACTIONS

HERE = Path(__file__).resolve().parent
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def parse_value(text):
    if text == 'TRUE': return True
    if text == 'FALSE': return False
    if text.startswith('{') and text.endswith('}'):
        return sorted(int(v.strip()) for v in text[1:-1].split(',') if v.strip())
    return int(text)

def encode(model, fields):
    state = 0
    for index, name in enumerate(SET_NAMES):
        for op in fields[name]:
            if not 1 <= op <= model.n: raise ValueError('Operation outside fixed domain')
            state |= 1 << (model.shifts[index] + op - 1)
    state |= fields['heldCount'] << model.hc_shift
    state |= fields['committedCount'] << model.cc_shift
    if fields['clientUp']: state |= model.client_bit
    if fields['sinkUp']: state |= model.sink_bit
    return state

def main():
    run = HERE / 'runs/v1'
    freeze = read(HERE/'FREEZE.json')
    for name, digest in freeze['source_hashes'].items():
        if sha(HERE/name) != digest: raise ValueError('Changed frozen source: ' + name)
    for branch in ('tlc', 'exact'):
        if read(run/branch/'START.json')['freeze_sha256'] != sha(HERE/'FREEZE.json'):
            raise ValueError('Run provenance differs: ' + branch)
    log_path = run/'tlc/unsafe_2_1/stdout.txt'
    log = log_path.read_text(encoding='utf-8')
    blocks = re.findall(r'State (\d+): <([^>\n]+)>\n(.*?)(?=\nState \d+:|The coverage statistics)', log, re.S)
    if not blocks: raise ValueError('No raw TLC counterexample found')
    model = FiniteModel(2, 1, True)
    expected_fields = set(SET_NAMES) | {'heldCount', 'committedCount', 'clientUp', 'sinkUp'}
    trace = []
    for number, label, content in blocks:
        fields = {name: parse_value(value.strip()) for name, value in re.findall(r'/\\ (\w+) = ([^\n]+)', content)}
        if set(fields) != expected_fields: raise ValueError('Incomplete state record')
        packed = encode(model, fields)
        if model.describe(packed) != {**fields, 'local_count': fields['heldCount']+fields['committedCount'],
                                     'distinct_effect_count': len(fields['effects']), 'exact_packed_state': packed}:
            raise ValueError('State encoding not round-trip exact')
        trace.append(dict(tlc_state=int(number), label=label, state=fields, packed=packed))
    if [row['tlc_state'] for row in trace] != list(range(1, len(trace)+1)): raise ValueError('Missing trace state')
    if trace[0]['packed'] != model.initial: raise ValueError('Wrong initial state')
    edges, first_blocked = [], None
    for before, after in zip(trace, trace[1:]):
        family = after['label'].split()[0]
        matches = [(code, dst) for code, dst in model.successors(before['packed'])
                   if ACTIONS[code//4] == family and dst == after['packed']]
        if len(matches) != 1: raise ValueError('Non-unique or invalid counterexample transition')
        code = matches[0][0]
        positive_matches = [(candidate, dst) for candidate, dst in model.successors(before['packed'], unsafe_override=False)
                            if candidate == code and dst == after['packed']]
        if not positive_matches and first_blocked is None:
            first_blocked = dict(tlc_state=after['tlc_state'], action=family)
        edges.append(dict(from_state=before['tlc_state'], to_state=after['tlc_state'], action=family,
                          operation=code%4+1 if code//4 < 14 else None,
                          independent_guard_and_successor_match=True))
    if first_blocked != {'tlc_state': 8, 'action': 'UnsafeReleaseUnknown'}:
        raise ValueError('Unexpected positive/negative divergence')
    for row in trace:
        state = row['state']
        if state['heldCount'] != len(state['held']) or state['committedCount'] != len(state['committed']):
            raise ValueError('Counterexample depends on incorrect local accounting')
        if set(state['held']) & set(state['committed']) or not 0 <= state['heldCount']+state['committedCount'] <= 1:
            raise ValueError('Counterexample breaks local quota')
    last = trace[-1]['state']
    if not (len(last['effects']) == 2 and last['heldCount'] == 1 and last['committedCount'] == 0):
        raise ValueError('Missing target violation')
    exact_trace = read(run/'exact/unsafe_2_1/COUNTEREXAMPLE.json')['trace']
    same = [row['packed'] for row in trace] == [row['state']['exact_packed_state'] for row in exact_trace]
    result = dict(status='PASS', source_tlc_log_sha256=sha(log_path), model_sha256=sha(HERE/'ECRCLifecycle.tla'),
                  replay_checker_sha256=sha(HERE/'exact_check.py'), extraction_script_sha256=sha(Path(__file__)),
                  trace=trace, edges=edges, transition_count=len(edges), states=len(trace),
                  positive_first_disabled_step=first_blocked, same_state_sequence_as_exact_counterexample=same,
                  local_accounting_and_quota_hold_at_every_step=True,
                  final_effect_count=2, final_held=1, final_committed=0, quota=1,
                  interpretation='A finite model counterexample. Effect 1 commits before unsafe release; ACK 1 remains pending. No LoseAcknowledgement step occurs. Not a concrete client failure or exact replay of the paper schematic.')
    write(run/'TLC_COUNTEREXAMPLE_REPLAY.json', result)
    with (run/'COUNTEREXAMPLE.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['state', 'action', 'operation', 'held_count', 'committed_count', 'effect_count', 'held', 'effects', 'pending_acks'])
        for index, row in enumerate(trace):
            state = row['state']; edge = edges[index-1] if index else None
            writer.writerow([row['tlc_state'], edge['action'] if edge else 'Init', edge['operation'] if edge else '',
                             state['heldCount'], state['committedCount'], len(state['effects']),
                             json.dumps(state['held']), json.dumps(state['effects']), json.dumps(state['acknowledgements'])])
    rows = []
    for case in freeze['cases']:
        tc = read(run/'tlc'/case['id']/'RESULT.json')
        ex = read(run/'exact'/case['id']/'RESULT.json')
        log = (run/'tlc'/case['id']/'stdout.txt').read_text(encoding='utf-8')
        if sha(run/'tlc'/case['id']/'stdout.txt') != tc['stdout_sha256']: raise ValueError('Log digest mismatch')
        rows.append(dict(case=case['id'], n=case['n'], capacity=case['capacity'], unsafe=case['unsafe'],
                         tlc_status=tc['status'], exact_status=ex['status'],
                         tlc_distinct=tc['distinct_states'], exact_discovered=ex['unique_labeled_states_discovered'],
                         exact_checked=ex['states_checked'], tlc_generated=tc['generated_states'],
                         exact_generated=ex['generated_states_including_initial'],
                         tlc_depth_states=tc['reported_search_depth'],
                         exact_depth_edges=ex['maximum_discovered_shortest_path_depth_edges'],
                         tlc_wrapper_seconds=tc['elapsed_seconds'], exact_search_seconds=ex['search_elapsed_seconds'],
                         memory='TLC configured 2 GiB heap + reported 64 MiB offheap; peak memory not measured.',
                         warnings=[line for line in log.splitlines() if line.startswith('Warning:')],
                         fingerprint_estimate_lines=[line.strip() for line in log.splitlines() if 'calculated (optimistic)' in line or 'based on the actual fingerprints' in line],
                         action_coverage=ex['action_coverage']))
    write(run/'RESULT_SUMMARY.json', dict(cases=rows, counterexample_replay='TLC_COUNTEREXAMPLE_REPLAY.json',
         comparison_status=read(run/'exact/TLC_COMPARISON.json')['status'],
         scope='Fixed finite abstraction only; negative counts reflect early termination and are not complete state spaces. Times have different measurement scopes and are not speed comparisons.'))
    print(json.dumps({'replay_status': 'PASS', 'trace_transitions': len(edges),
                      'same_tlc_exact_trace': same, 'normal_distinct_states': [r['tlc_distinct'] for r in rows if not r['unsafe']]}))

if __name__ == '__main__': main()
