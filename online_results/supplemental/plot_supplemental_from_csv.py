"""Offline reconstruction of the two supplementary result figures.

Reads only the two frozen aggregate CSVs supplied beside this script.
The per-run aggregation audit is documented in ../README.md. No network,
provider SDK, original research workspace, or credentials are required.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import platform

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
BLUE='#28618A'
GRAY='#555555'
BLACK='#111111'
ARMS=[('direct_native_dispatch','Direct dispatch'),
      ('qualification_ecrc','ECRC'),
      ('existing_rules_only','Business rules'),
      ('without_claim_evidence_requirement','Claim-evidence ablation')]
POLICIES=[('depth_first','Depth-first'),('round_robin','Round-robin')]
CLIENTS=[('ecrc','ECRC'),('ordinary','Contract-matched')]
HASHES={
    'airline_plot_data.csv':'57f05d93beaa480ee9cd945bdb52a561094009ee3ac74acf623cc7dc3c4cd728',
    'verification_plot_data.csv':'70de91d6eea6821b02eb4a4e392a26443fc05f19f9c6cd06c5382608e87db992',
}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_csv(directory,name):
    path=directory/name
    if sha(path)!=HASHES[name]:
        raise ValueError('Frozen input hash mismatch: '+name)
    with path.open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))

def verified_data(directory):
    airline=read_csv(directory,'airline_plot_data.csv')
    categories={'Eligible completed':129,'Known-ineligible':117,
                'Missing information':200,'Transfer required':154}
    assert len(airline)==16
    assert {(r['arm'],r['category']) for r in airline}=={(a,c) for a,_ in ARMS for c in categories}
    for r in airline:
        for field in ('executed','category_total'): r[field]=int(r[field])
        r['percent']=float(r['percent'])
        assert r['condition']==dict(ARMS)[r['arm']]
        assert r['category_total']==categories[r['category']]
        assert 0<=r['executed']<=r['category_total']
        assert math.isclose(r['percent'],100*r['executed']/r['category_total'],abs_tol=1e-10)
    verification=read_csv(directory,'verification_plot_data.csv')
    assert len(verification)==8
    assert {(r['response'],r['policy'],r['client']) for r in verification}=={
        (c,p,a) for c in ('normal','response_loss') for p,_ in POLICIES for a,_ in CLIENTS}
    for r in verification:
        for field in ('batches','eligible_tasks','timely_tasks','eventual_tasks','suite_starts'):
            r[field]=int(r[field])
        r['launcher_seconds']=float(r['launcher_seconds'])
        assert r['batches']==18 and r['eligible_tasks']==144
        assert 0<=r['timely_tasks']<=r['eventual_tasks']<=144
        assert r['client_label']==dict(CLIENTS)[r['client']]
    assert sum(r['suite_starts'] for r in verification)==1769
    return airline,verification

def style():
    font_manager.findfont('Arial', fallback_to_default=False)
    plt.rcParams.update({
        'font.family': 'Arial', 'font.size': 10, 'text.color': 'black',
        'axes.labelcolor': 'black', 'xtick.color': 'black', 'ytick.color': 'black',
        'axes.edgecolor': BLACK, 'axes.linewidth': .65, 'figure.facecolor': 'white',
        'savefig.facecolor': 'white', 'pdf.fonttype': 42, 'ps.fonttype': 42,
        'svg.fonttype': 'none', 'svg.hashsalt': 'ecrc-results-2026-10-07',
    })


def clean_axis(ax, max_x, ticks):
    ax.set_xlim(0, max_x)
    ax.set_ylim(-.55, 3.55)
    ax.set_xticks(ticks)
    ax.spines[['left', 'right', 'top']].set_visible(False)
    ax.tick_params(axis='y', length=0, pad=10)
    ax.tick_params(axis='x', length=3, width=.65)
    ax.set_axisbelow(True)
    ax.grid(axis='x', color='#E0E4E7', linewidth=.65)
    for y in (.5, 1.5, 2.5):
        ax.axhline(y, color='#E8EBEE', linewidth=.6, zorder=0)


def save(fig, name, out):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = fig.bbox
    outside = []
    for t in fig.findobj(matplotlib.text.Text):
        if not t.get_visible() or not t.get_text():
            continue
        box = t.get_window_extent(renderer)
        if box.x0 < -1 or box.y0 < -1 or box.x1 > bounds.x1 + 1 or box.y1 > bounds.y1 + 1:
            outside.append(t.get_text())
    assert not outside, (name, 'text outside figure', outside)
    for ext in ('pdf', 'svg', 'png'):
        kwargs = {'dpi': 300}
        if ext == 'pdf':
            kwargs['metadata'] = {'Title': name.replace('_', ' '), 'Creator': 'Matplotlib; frozen saved data', 'CreationDate': None, 'ModDate': None}
        elif ext == 'svg':
            kwargs['metadata'] = {'Date': None, 'Title': name.replace('_', ' ')}
        fig.savefig(out / f'{name}.{ext}', **kwargs)
    plt.close(fig)


def airline_plot(data, out):
    fig = plt.figure(figsize=(16.5/2.54, 4.25))
    axa = fig.add_axes([.295, .20, .215, .64])
    axb = fig.add_axes([.59, .20, .365, .64])
    for ax in (axa, axb):
        clean_axis(ax, 100, [0, 50, 100])
    axa.set_yticks([3, 2, 1, 0], ['Direct dispatch', 'ECRC', 'Business rules', 'Claim-evidence\nablation'])
    axb.set_yticks([])
    axa.set_xlabel('Completed (%)', labelpad=6)
    axb.set_xlabel('Executed (%)', labelpad=6)
    fig.text(.295, .89, 'A', fontsize=10, fontweight='bold')
    fig.text(.59, .89, 'B', fontsize=10, fontweight='bold')
    fig.text(.335, .89, 'Eligible requests', fontsize=10)
    fig.text(.63, .89, 'Other requests', fontsize=10)
    categories = [('Known-ineligible', .25, 'o', BLACK, BLACK),
                  ('Missing information', 0, 's', GRAY, 'white'),
                  ('Transfer required', -.25, '^', BLUE, BLUE)]
    lookup = {(r['arm'], r['category']): r for r in data}
    for i, (arm, _) in enumerate(ARMS):
        y = 3 - i
        r = lookup[arm, 'Eligible completed']
        axa.plot(r['percent'], y, 'o', color=BLUE, ms=6, clip_on=False, zorder=4)
        axa.annotate(f"{r['executed']}/{r['category_total']}", (r['percent'], y),
                     xytext=(-8, 0), textcoords='offset points', ha='right', va='center', fontsize=10)
        for category, dy, marker, edge, face in categories:
            r = lookup[arm, category]
            x = r['percent']
            axb.plot(x, y + dy, marker=marker, color=edge, markerfacecolor=face,
                     markersize=5.5, markeredgewidth=1.0, linestyle='', clip_on=False, zorder=4)
            dx, ha = (-8, 'right') if x == 100 else (8, 'left')
            axb.annotate(f"{r['executed']}/{r['category_total']}", (x, y + dy),
                         xytext=(dx, 0), textcoords='offset points', ha=ha, va='center', fontsize=10)
    handles = [Line2D([], [], marker=m, linestyle='', color=e, markerfacecolor=f,
                      markersize=5.5, label=c) for c, _, m, e, f in categories]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.5, .015),
               ncol=3, frameon=False, handletextpad=.45, columnspacing=1.25, fontsize=10)
    save(fig, 'airline_results', out)


def verification_plot(data, out):
    fig = plt.figure(figsize=(16.5/2.54, 5.45))
    axa = fig.add_axes([.34, .55, .60, .315])
    axb = fig.add_axes([.34, .13, .60, .315])
    legend = [Line2D([], [], marker='o', color=BLUE, linestyle='', markersize=5.7,
                     label='Timely (within 5 s)'),
              Line2D([], [], marker='s', color=GRAY, markerfacecolor='white', linestyle='',
                     markersize=5.7, label='Eventual (including late)')]
    fig.legend(handles=legend, loc='upper center', bbox_to_anchor=(.5, .995), ncol=2,
               frameon=False, fontsize=10, handletextpad=.45, columnspacing=1.5)
    labels = ['Depth-first\nECRC', 'Depth-first\nContract-matched',
              'Round-robin\nECRC', 'Round-robin\nContract-matched']
    lookup = {(r['response'], r['policy'], r['client']): r for r in data}
    for ax, response in [(axa, 'normal'), (axb, 'response_loss')]:
        clean_axis(ax, 144, [0, 36, 72, 108, 144])
        ax.set_yticks([3, 2, 1, 0], labels)
        for i, (p, a) in enumerate([(p, a) for p, _ in POLICIES for a, _ in CLIENTS]):
            r = lookup[response, p, a]
            y = 3 - i
            xt, xe = r['timely_tasks'], r['eventual_tasks']
            yt, ye = y + .20, y - .20
            ax.plot([xt, xe], [yt, ye], color=GRAY, linewidth=.75, zorder=2)
            ax.plot(xt, yt, 'o', color=BLUE, markersize=5.7, zorder=4)
            ax.plot(xe, ye, 's', color=GRAY, markerfacecolor='white', markersize=5.7, markeredgewidth=1.0, zorder=4)
            ax.annotate(str(xt), (xt, yt), xytext=(7, 0), textcoords='offset points', va='center', fontsize=10)
            ax.annotate(str(xe), (xe, ye), xytext=(7, 0), textcoords='offset points', va='center', fontsize=10)
    fig.text(.035, .90, 'A', fontsize=10, fontweight='bold')
    fig.text(.035, .48, 'B', fontsize=10, fontweight='bold')
    fig.text(.075, .90, 'Normal response', fontsize=10)
    fig.text(.075, .48, 'Response lost after result commit', fontsize=10)
    axb.set_xlabel('Tasks with reconciled suite-pass feedback (of 144)', labelpad=7)
    save(fig, 'verification_results', out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=HERE)
    parser.add_argument('--output-dir',type=Path,default=Path('figures'))
    args=parser.parse_args()
    airline,verification=verified_data(args.input_dir)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    style()
    airline_plot(airline,args.output_dir)
    verification_plot(verification,args.output_dir)
    names=[n+'.'+e for n in ('airline_results','verification_results') for e in ('pdf','png','svg')]
    manifest={
        'schema':'portable-supplemental-render-v1',
        'source_scope':'All conditions from audited frozen aggregate snapshots; no re-estimation or new experiments',
        'input_sha256':HASHES,'script_sha256':sha(__file__),
        'output_sha256':{n:sha(args.output_dir/n) for n in names},
        'runtime_versions':{'python':platform.python_version(),'matplotlib':matplotlib.__version__},
        'font_family':'Arial','configured_font_sizes_pt':[10],'text_color':'black',
        'width_cm':16.5,'png_dpi':300,'API_calls':0,
        'airline_plotted_counts':16,'verification_plotted_counts':16,
        'panel_mapping':{'airline_results':{'A':'Eligible requests','B':'Other requests'},
                         'verification_results':{'A':'Normal response','B':'Response lost after result commit'}},
    }
    (args.output_dir/'rendering_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'rendered','output_files':names+['rendering_manifest.json'],'API_calls':0}))

if __name__=='__main__': main()
