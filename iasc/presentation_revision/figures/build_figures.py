"""Build five manuscript figures from copied frozen inputs; no new experiment.

Capture once: python build_figures.py --capture-from PATH_TO_REPRODUCIBILITY_BUNDLE
Rebuild independently: python build_figures.py
"""
from pathlib import Path
import argparse, csv, hashlib, json, shutil, sqlite3, tempfile
from collections import defaultdict
from decimal import Decimal
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import journal_style as style

HERE = Path(__file__).resolve().parent
DATA = HERE / 'data'
INPUT = DATA / 'input'
COHORTS = [('many_labs_igt', 'Development'), ('mendeley_igt_official_v2', 'External')]
MODELS = [('hist_gradient_boosting', 'HGB'), ('regularised_logistic', 'Logistic'), ('history_baseline', 'History')]
BASES = [('eight_per_episode', '8/episode'), ('eight_per_100_planned', '8/100 planned')]
PHASES = {
    'expired_unarmed_cleanup': ['issued_unarmed_before_expiry', 'expired_unarmed_cancelled', 'cancelled_replay_no_dispatch', 'released_budget_reused', 'final'],
    'accepted_timeout_cleanup_recovery': ['sink_committed_client_timed_out', 'cleanup_retained_unknown_grant', 'after_unknown_recovery_competition', 'final'],
}
STATIC = {
    'discrimination.csv': 'figures/data/analysis/a1_discrimination_decomposition.csv',
    'discrimination_ci.csv': 'figures/data/analysis/a1_discrimination_bootstrap.csv',
    'interval_algebra.csv': 'figures/data/analysis/a3_interval_algebra.csv',
    'candidate.csv': 'reproduce_analysis/qa/iasc_experiment_extension_2026-09-11/sequence/out/frozen_candidate_summary.csv',
    'online_estimates.csv': 'reproduce_analysis/qa/iasc_experiment_extension_2026-09-11/online/out/online_estimates.csv',
    'online_intervals.csv': 'reproduce_analysis/qa/iasc_experiment_extension_2026-09-11/online/out/online_intervals.csv',
    'participant_equal.csv': 'statistics/out/paired_comparisons.csv',
    'S8_PROTOCOL.md': 'end_to_end/PROTOCOL.md',
    'S8_PROTOCOL_AMENDMENTS.md': 'end_to_end/PROTOCOL_AMENDMENTS.md',
    'ecrc_e2e.py': 'end_to_end/ecrc_e2e.py',
    'ordinary_e2e.py': 'end_to_end/ordinary_e2e.py',
    'S6_PROTOCOL.md': 'runtime/PROTOCOL.md',
    'online_PROTOCOL.md': 'reproduce_analysis/qa/iasc_experiment_extension_2026-09-11/online/PROTOCOL.md',
    'statistics_PROTOCOL.md': 'statistics/PROTOCOL.md',
    'sequence_PROTOCOL.md': 'reproduce_analysis/qa/iasc_experiment_extension_2026-09-11/sequence/PROTOCOL.md',
}
INDEX = []


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def rows(name):
    with (INPUT / name).open(encoding='utf-8', newline='') as f: return list(csv.DictReader(f))
def one(items, **key):
    selected = [r for r in items if all(r[k] == v for k, v in key.items())]
    assert len(selected) == 1, (key, len(selected))
    return selected[0]
def write_csv(path, records):
    keys = list(dict.fromkeys(k for r in records for k in r))
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys); writer.writeheader(); writer.writerows(records)


def capture(bundle):
    assert not (DATA / 'input_manifest.json').exists(), 'Capture already exists; rebuild without --capture-from'
    INPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    def copy(source_relative, destination_relative):
        src, dst = bundle / source_relative, INPUT / destination_relative
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
        h = sha(src); assert h == sha(dst)
        manifest.append(dict(source='AIR-014_IASC_Reproducibility/' + source_relative,
                             snapshot=dst.relative_to(HERE).as_posix(), sha256=h, bytes=dst.stat().st_size))
    for name, rel in STATIC.items(): copy(rel, name)
    for scenario, phases in PHASES.items():
        for rep in range(3):
            for arm in ('ecrc', 'ordinary'):
                root = f'end_to_end/out/{scenario}/rep-{rep}/{arm}'
                copy(root + '/case.json', f's8/{scenario}/rep-{rep}/{arm}/case.json')
                for phase in phases + ['current_final']:
                    folder = root if phase == 'current_final' else root + '/snapshots/' + phase
                    target = f's8/{scenario}/rep-{rep}/{arm}/{phase}'
                    if phase != 'current_final': copy(folder + '/snapshot_meta.json', target + '/snapshot_meta.json')
                    for name in ('client.sqlite', 'sink.sqlite'):
                        for suffix in ('', '-wal', '-shm'):
                            if (bundle / folder / (name + suffix)).exists(): copy(folder + '/' + name + suffix, target + '/' + name + suffix)
    (DATA / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def evidence(fig, panel, source, key, transformation, evidence_type):
    records = read_json(DATA / 'input_manifest.json')
    matching = [r for r in records if r['snapshot'] == source]
    INDEX.append(dict(manuscript_item=f'Figure {fig}', panel=panel, source_file=matching[0]['source'] if matching else source,
                      local_snapshot=source, row_key_or_filter=json.dumps(key, sort_keys=True),
                      transformation=transformation, evidence_type=evidence_type,
                      source_sha256=matching[0]['sha256'] if matching else sha(HERE/source.split('#')[0]) if (HERE/source.split('#')[0]).is_file() else 'not-applicable-schematic'))


def arrow(ax, start, end, color='black', linestyle='-'):
    ax.annotate('', xy=end, xytext=start, arrowprops=dict(arrowstyle='->', color=color, lw=.8, linestyle=linestyle, shrinkA=2, shrinkB=2))


def fig1():
    fig = plt.figure(figsize=(style.WIDTH, 3.6))
    ax = fig.add_axes([.035, .08, .94, .86]); ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis('off')
    ax.text(0, 1, 'Illustrative budget = 1; two distinct requests A and B', va='top', fontweight='bold')
    x = [.065, .29, .53, .765, .955]
    top = ['A authorized;\nunit held', 'Sink commits A;\nresponse lost;\nlocally unknown', 'Timeout releases\nthe held unit', 'B authorized;\nsink commits B', '2 effects\nfor 1 unit']
    bottom = ['A authorized;\nunit held', 'Sink commits A;\nresponse lost;\nlocally unknown', 'Keep unit held;\nB is not admitted', 'Reconcile A;\nheld to committed', '1 effect\nfor 1 unit']
    for y, title, texts in [(.65, '(a) Timeout-release counterexample', top), (.23, '(b) Retain until reconciled', bottom)]:
        ax.text(0, y + .19, title, fontweight='bold', va='center')
        for i, (xx, text) in enumerate(zip(x, texts)):
            align = 'left' if i == 0 else 'right' if i == 4 else 'center'
            ax.text(xx if i not in (0,4) else (0 if i==0 else 1), y, text, ha=align, va='center', fontsize=10)
        for left, right in zip([.18, .40, .65, .875], [.21, .435, .67, .90]):
            arrow(ax, (left, y), (right, y))
    ax.plot([0, 1], [.445, .445], color='#AAAAAA', lw=.6)
    fig.text(.035, .025, 'Illustrative counterexample, not an observed failure of either full implementation.', fontsize=9.5)
    exported = [{'chain': chain, 'event_order': i+1, 'event': text.replace('\n', ' '), 'budget': 1,
                 'evidence_type': 'illustrative; not observed experimental failure'}
                for chain, texts in [('timeout_release', top), ('retain_until_reconciled', bottom)] for i, text in enumerate(texts)]
    write_csv(DATA / 'fig1_illustrative_events.csv', exported)
    evidence(1, 'a/b', 'build_figures.py#fig1', {'budget': 1, 'distinct_requests': ['A','B']},
             'Constructed illustrative event chains; no observed outcome or full-implementation failure used.', 'illustrative counterexample')
    evidence(1, 'b', 'data/input/S8_PROTOCOL.md', {'rule':'retain unknown armed grants'},
             'Specified retention rule used in the illustrative chain; values are hypothetical, not an observed experiment.', 'specified recovery rule applied illustratively')
    return style.save(fig, 1, 'budget_responsibility')


def fig2():
    fig = plt.figure(figsize=(style.WIDTH, 4.25))
    ax = fig.add_axes([.025, .06, .95, .9]); ax.axis('off'); ax.set(xlim=(0,1), ylim=(0,1))
    xs = [.08, .285, .495, .705, .92]
    ax.text(0, .995, 'Raw-request lifecycle (S8)', va='top', fontweight='bold')
    labels = ['Durable raw\nrequest journal', 'Atomic issuance\ncommit', 'Issued,\nunarmed', 'Arm commit\n(durable intent)', 'Separate sink\ncommit']
    for x, label in zip(xs, labels): ax.text(x, .81, label, ha='center', va='center', fontsize=10)
    for l, r in zip(xs[:-1], xs[1:]): arrow(ax, (l+.073,.81), (r-.077,.81))
    ax.text(xs[1], .64, 'Complete permit,\nreservation and\nregistry bound', ha='center', va='center', fontsize=9.5)
    ax.text(xs[3], .64, 'Authorization becomes\nirrevocable; retain held\nif outcome is unknown', ha='center', va='center', fontsize=9.5)
    ax.text(xs[4], .48, 'Independent\npersistent effect', ha='center', va='center', fontsize=9.5)
    arrow(ax, (xs[4],.735), (xs[4],.545))
    ax.text(.62, .275, 'Local reconciliation commit', fontweight='bold', ha='center')
    ax.text(.62, .175, 'Verify sink acknowledgement;\nreceipt + held-to-committed + completion', ha='center', va='center', fontsize=9.5)
    arrow(ax, (.92,.43), (.92,.30)); arrow(ax, (.92,.30), (.85,.30))
    # Only unarmed expiry takes the cancellation branch.
    ax.plot([xs[2],xs[2],.16],[.735,.46,.46],color='black',lw=.8)
    ax.text(.33, .405, 'Unarmed at expiry (S8)', ha='center', va='center', fontsize=9.5)
    ax.text(.13, .265, 'Atomic cancel\nand release', ha='center', va='center', fontsize=10)
    arrow(ax, (.16,.46), (.16,.34))
    ax.text(.13, .12, 'Later arm / dispatch\nforbidden', ha='center', va='center', fontsize=9.5)
    ax.plot([.395,.395], [.59,.96], color=style.GREY, ls=(0,(3,3)), lw=.8)
    ax.text(.47, .96, 'Preissued-permit entry (S6)', va='top', fontsize=9.5)
    fig.text(.025, .015, 'Separate transaction boundaries; S8 uses synthetic requests, not the full behavioral replay.', fontsize=9.5)
    states = [dict(state=label.replace('\n',' '), scope='S8; S6 begins with preissued permits') for label in labels]
    states.extend([dict(state='Unarmed expiry: atomic cancel/release; future dispatch forbidden', scope='S8'),
                   dict(state='Local reconcile: receipt, commitment and completion in one local transaction', scope='S6/S8')])
    write_csv(DATA / 'fig2_lifecycle_states.csv', states)
    for source in ('S8_PROTOCOL.md', 'S8_PROTOCOL_AMENDMENTS.md', 'ecrc_e2e.py', 'ordinary_e2e.py', 'S6_PROTOCOL.md'):
        evidence(2, 'lifecycle', 'data/input/' + source, {'boundary':'journal/issue/arm/sink/reconcile/cleanup'},
                 'Qualitative state/transaction schematic from implementation and locked protocols; no behavioral-to-S8 pipeline implied.', 'specified implementation boundary')
    return style.save(fig, 2, 'lifecycle_boundaries')


def read_db(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True); db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {n:[dict(r) for r in db.execute('SELECT * FROM "'+n+'"')] for n in names}
    finally: db.close()


def stage_wrap(text, limit=13):
    output, line = [], ''
    parts = text.split('_')
    for i, word in enumerate(parts):
        token = word + ('_' if i < len(parts)-1 else '')
        if line and len(line + token) > limit: output.append(line); line=''
        line += token
    if line: output.append(line)
    return '\n'.join(output)


def fig3():
    counts = []
    # Never open archival input DBs directly: even read-only SQLite may touch a SHM file.
    with tempfile.TemporaryDirectory(prefix='iasc_plot_s8_') as tmp:
        clone = Path(tmp) / 's8'; shutil.copytree(INPUT / 's8', clone)
        for scenario, phases in PHASES.items():
            for rep in range(3):
                for arm in ('ecrc','ordinary'):
                    root = clone / scenario / f'rep-{rep}' / arm
                    for phase in phases + ['current_final']:
                        folder = root / phase
                        if phase != 'current_final':
                            meta = read_json(folder / 'snapshot_meta.json'); assert meta['phase'] == phase and meta['arm'] == arm
                        c,s = read_db(folder/'client.sqlite'), read_db(folder/'sink.sqlite')
                        budgets = c['capacity_state'] if arm == 'ecrc' else c['budgets']
                        record = dict(scenario=scenario, repetition=rep, implementation=arm, phase=phase,
                                      permits=sum(bool(r['permit_json']) for r in c['requests']),
                                      held=sum(r['reserved' if arm=='ecrc' else 'held'] for r in budgets),
                                      committed=sum(r['committed' if arm=='ecrc' else 'spent'] for r in budgets),
                                      effects=len(s['effects']), receipts=len(c['receipt_log' if arm=='ecrc' else 'receipts']))
                        counts.append(record)
                        prefix = f'data/input/s8/{scenario}/rep-{rep}/{arm}/{phase}'
                        for name in ('client.sqlite','sink.sqlite'):
                            evidence(3, 'a' if scenario.startswith('expired') else 'b', prefix+'/'+name,
                                     {'scenario':scenario,'rep':rep,'implementation':arm,'phase':phase},
                                     'Direct counts/sums from copied SQLite state; all 2 implementations x 3 repetitions; no run selection.', 'saved observed checkpoint' if phase!='current_final' else 'saved observed final DB')
    assert len(counts) == 66
    for scenario in PHASES:
        for rep in range(3):
            for arm in ('ecrc','ordinary'):
                a=one(counts, scenario=scenario,repetition=rep,implementation=arm,phase='final')
                b=one(counts, scenario=scenario,repetition=rep,implementation=arm,phase='current_final')
                assert all(a[k]==b[k] for k in ('permits','held','committed','effects','receipts'))
    write_csv(DATA/'fig3_checkpoint_counts.csv', counts)
    summary=[]
    fig=plt.figure(figsize=(style.WIDTH, 5.8))
    for panel,(scenario,phases),bottom,title_y in zip(('a','b'),PHASES.items(),(.565,.085),(.974,.502)):
        ax=fig.add_axes([.19,bottom,.79,.265]); ax.set(xlim=(-.5,len(phases)-.5),ylim=(-.5,3.5)); ax.invert_yaxis(); ax.axis('off')
        fig.text(.025,title_y, '('+panel+') '+scenario, fontsize=10, fontweight='bold')
        metrics=['held','committed','effects','receipts']; display=['Held units','Committed units','Sink effects','Local receipts']
        for y,(metric,label) in enumerate(zip(metrics,display)):
            ax.text(-.64,y,label,ha='right',va='center',fontsize=9.5)
            for x,phase in enumerate(phases):
                selected=[r for r in counts if r['scenario']==scenario and r['phase']==phase];assert len(selected)==6
                values=[r[metric] for r in selected]; lo,hi=min(values),max(values)
                text=str(lo) if lo==hi else f'{lo}-{hi}'
                ax.add_patch(Rectangle((x-.46,y-.42),.92,.84,facecolor=style.PALE if hi>0 else 'white',edgecolor='#B8B8B8',lw=.5))
                ax.text(x,y,text,ha='center',va='center',fontsize=11)
                summary.append(dict(scenario=scenario,phase=phase,metric=metric,n_observations=6,min=lo,max=hi,display=text))
        for x,phase in enumerate(phases):ax.text(x,-.64,stage_wrap(phase),ha='center',va='bottom',fontsize=9.5)
    fig.text(.025,.013,'Each cell: common count (or min-max) across both implementations and all three repeats.',fontsize=9.5)
    write_csv(DATA/'fig3_plot_data.csv',summary)
    return style.save(fig,3,'observed_cleanup_states')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture-from',type=Path);parser.add_argument('--only',default='1,2,3,4,5');args=parser.parse_args()
    DATA.mkdir(exist_ok=True)
    if args.capture_from:capture(args.capture_from.resolve())
    for r in read_json(DATA/'input_manifest.json'):assert sha(HERE/r['snapshot'])==r['sha256'],r
    style.configure();outputs=[]
    mapping={1:fig1,2:fig2,3:fig3}
    if any(x in args.only.split(',') for x in ('4','5')):
        from statistical_figures import fig4,fig5
        mapping.update({4:fig4,5:fig5})
    for number in [int(x) for x in args.only.split(',')]:outputs.extend(mapping[number]())
    write_csv(HERE/'figure_evidence_index.csv',INDEX)
    (HERE/'figure_evidence_index.json').write_text(json.dumps(INDEX,indent=2)+'\n',encoding='utf-8')
    manifest={'width_inches':style.WIDTH,'minimum_font_pt':9.5,'font':'Arial','text_color':'black','dpi_png_tiff':600,
              'evidence_scope':'Illustrative/specified state diagrams, saved checkpoint counts and frozen paired intervals; no new training, experiment or bootstrap.',
              'input_manifest_sha256':sha(DATA/'input_manifest.json'),'outputs':outputs,
              'source_hashes':{p.name:sha(p) for p in HERE.glob('*.py')}}
    (HERE/'build_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'figures':len(outputs)//4,'exports':len(outputs)},indent=2))


if __name__=='__main__':main()
