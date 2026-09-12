"""Portable Figures 4/5 from saved experiment outputs, without new experiments.

Capture once: python build_fig4_fig5.py --capture-from WORKSPACE_ROOT
Rebuild package: python build_fig4_fig5.py --out rebuilt
Requires matplotlib, numpy, Pillow; PyMuPDF is recommended for PDF verification.
The accompanying journal_style.py is an unchanged copy of the prior figure code.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import platform
import shutil
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import journal_style as style

HERE = Path(__file__).resolve().parent
BLUE, BLACK = style.BLUE, style.BLACK
COHORTS = [('many_labs_igt','Dev'),('mendeley_igt_official_v2','External')]
MODELS = [('hist_gradient_boosting','HGB'),('regularised_logistic','logistic'),('history_baseline','history')]
BASES = [('eight_per_episode','8 per episode',0.13,BLUE),('eight_per_100_planned','8 per 100 planned decisions',-0.13,'white')]
COMPONENTS = [('trusted_permit_claim_binding','Claim/evidence faults'),('stateful_receipt_verification','Receipt/state faults')]

def capture(root, data):
    root=Path(root).resolve(); data.mkdir(parents=True,exist_ok=True)
    old=root/'qa/iasc_submission_redraw_2026-09-11/figures/data/fig1_fig4'
    shutil.copytree(old,data/'legacy',dirs_exist_ok=True)
    sources={
        'component_summary.csv':'system_baseline/component_summary.csv',
        'clean_control_results.csv':'system_baseline/clean_control_results.csv',
        'system_run_manifest.json':'system_baseline/run_manifest.json',
        'system_PROTOCOL.md':'system_baseline/PROTOCOL.md',
        'frozen_candidate_summary.csv':'sequence/out/frozen_candidate_summary.csv',
        'sequence_PROTOCOL.md':'sequence/PROTOCOL.md',
        'online_intervals.csv':'online/out/online_intervals.csv',
        'online_estimates.csv':'online/out/online_estimates.csv',
        'online_PROTOCOL.md':'online/PROTOCOL.md',
    }
    provenance=[]
    base=root/'qa/iasc_experiment_extension_2026-09-11'
    for name,rel in sources.items():
        src=base/rel; dst=data/name; shutil.copyfile(src,dst)
        provenance.append(dict(original=src.relative_to(root).as_posix(),snapshot=name,sha256=style.sha(src)))
    for p in sorted((data/'legacy').rglob('*')):
        if p.is_file():
            original=old/p.relative_to(data/'legacy')
            provenance.append(dict(original=original.relative_to(root).as_posix(),snapshot=p.relative_to(data).as_posix(),sha256=style.sha(p)))
    (data/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf8')

def one(rows, **criteria):
    selected=[r for r in rows if all(r.get(k)==v for k,v in criteria.items())]
    assert len(selected)==1,(criteria,len(selected))
    return selected[0]

def write_csv(path, rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)

def figure4(records, components, clean):
    # Capacity and latency panels are retained from the archived figure builder.
    fig=style.figure4(records); fig.set_size_inches(style.WIDTH,3.8)
    a=fig.axes[0];a.clear();a.axis('off');a.set(xlim=(0,1),ylim=(0,1))
    a.text(.64,.98,'Claim/\nevidence',ha='center',va='top',fontsize=8)
    a.text(.88,.98,'Receipt/\nstate',ha='center',va='top',fontsize=8)
    a.plot([0,1],[.80,.80],color=BLACK,lw=.6)
    plotted=[]
    display=[('Full ECRC','Full ECRC'),('Independent semantic','Ordinary semantic\n(matched baseline)'),('Ordinary log','Schema-only\nnegative control'),('Claim/evidence binding off','Claim/evidence\nbinding off'),('Receipt/state off','Receipt/state off')]
    for y,(series,label) in zip([.71,.565,.42,.275,.13],display):
        a.text(.015,y,label,ha='left',va='center',fontsize=8,fontweight='bold' if series in ('Full ECRC','Independent semantic') else 'normal')
        for x,(component,metric) in zip([.64,.88],COMPONENTS):
            if series=='Independent semantic':
                row=one(components,expected_component=component)
                num=int(row['new_independent_detected']);den=int(row['n_cases'])
                source='component_summary.csv'
            else:
                row=one(records,record_type='fault_detection',series=series,metric=metric)
                num=int(float(row['numerator']));den=int(float(row['denominator']))
                source='legacy/fig4_source_data.csv'
            a.text(x,y,f'{num}/{den}',ha='center',va='center',fontsize=9)
            plotted.append(dict(panel='a',series=series,metric=metric,numerator=num,denominator=den,source=source))
    a.plot([0,1],[.045,.045],color=BLACK,lw=.6)
    for text in list(fig.texts):
        if text.get_text().startswith('Clean controls:'):text.remove()
    assert len(clean)==1 and clean[0]['new_independent_accepted']=='True'
    assert int(clean[0]['new_n_findings'])==0
    n=int(clean[0]['n_permits']);assert n==int(clean[0]['n_receipts'])
    clean_pairs={(int(float(r['numerator'])),int(float(r['denominator']))) for r in records if r['record_type']=='clean_control'}
    assert len(clean_pairs)==1
    passed,count=next(iter(clean_pairs))
    assert passed == count == n == 32
    fig.text(.017,.098,'All five validators accepted one clean trace',fontsize=8)
    fig.text(.017,.047,f'containing {n} permit/receipt pairs.',fontsize=8)
    for row in records:
        if row['record_type'] in ('capacity_integrity','tail_latency'):
            plotted.append(dict(row,panel='b' if row['record_type']=='capacity_integrity' else 'c'))
    return fig,plotted

def figure5(candidates, intervals):
    fig=plt.figure(figsize=(style.WIDTH,4.0))
    axes=[style.tidy(fig.add_axes([left,.24,.205,.61])) for left in (.265,.515,.765)]
    ys=[5.5,4.5,3.5,2.,1.,0.]
    for ax,title in zip(axes,['(a) Candidate AUROC','(b) Alert precision','(c) Alert coverage']):
        ax.set_ylim(-.55,6.05);ax.set_yticks([]);ax.set_title(title,loc='left',fontsize=9,pad=13,fontweight='bold')
        ax.spines['left'].set_visible(False);ax.axhline(2.75,color='#CCCCCC',lw=.5,zorder=0)
    axes[0].set(xlim=(.435,.635),xticks=[.45,.50,.55,.60],xlabel='Pair-weighted AUROC')
    axes[1].set(xlim=(-.10,.22),xticks=[-.10,0,.10,.20],xlabel='Pacing - FIFO')
    axes[2].set(xlim=(-.044,.008),xticks=[-.04,-.02,0],xlabel='Pacing - FIFO')
    for ax in axes:ax.xaxis.label.set_size(8)
    axes[0].axvline(.5,color='#777777',ls='--',lw=.6,zorder=0)
    for ax in axes[1:]:ax.axvline(0,color='#777777',ls='--',lw=.6,zorder=0)
    fig.text(.012,.9,'Cohort / model\n(candidate n)',fontsize=8,va='top')
    plotted=[]
    for y,(dataset,cohort,model,model_label) in zip(ys,[(d,c,m,l) for d,c in COHORTS for m,l in MODELS]):
        row=one(candidates,dataset_id=dataset,model_name=model,region='alert_candidates')
        n=int(row['n_eligible']);total=int(row['n_participants'])
        fig.text(.245,.24+.61*(y+.55)/6.60,f'{cohort} {model_label} ({n})',ha='right',va='center',fontsize=8)
        est,lo,hi=[float(row[k]) for k in ('within_auroc_pair_weighted','within_auroc_pair_weighted_ci_low','within_auroc_pair_weighted_ci_high')]
        assert 0<=lo<=est<=hi<=1 and n<=total
        axes[0].errorbar(est,y,xerr=[[est-lo],[hi-est]],fmt='o',color=BLUE,ecolor=BLUE,ms=4,elinewidth=.75,capsize=2,capthick=.7)
        plotted.append(dict(panel='a',dataset_id=dataset,model_name=model,capacity_basis='candidate_set_before_capacity',estimate=est,ci_low=lo,ci_high=hi,n_eligible=n,n_participants=total,source='frozen_candidate_summary.csv',quantity='within_auroc_pair_weighted'))
        for panel,metric,ax in [('b','alert_precision',axes[1]),('c','alert_coverage',axes[2])]:
            for basis,label,offset,face in BASES:
                quantity='delta_paced_minus_fifo__'+metric
                row=one(intervals,dataset_id=dataset,model_name=model,capacity_basis=basis,quantity=quantity)
                est,lo,hi=[float(row[k]) for k in ('estimate','ci_low','ci_high')]
                assert np.isfinite([est,lo,hi]).all() and lo<=est<=hi
                ax.errorbar(est,y+offset,xerr=[[est-lo],[hi-est]],fmt='o',color=BLUE,mfc=face,mec=BLUE,mew=.8,ms=4,ecolor=BLUE,elinewidth=.7,capsize=2,capthick=.7)
                plotted.append(dict(panel=panel,dataset_id=dataset,model_name=model,capacity_basis=basis,estimate=est,ci_low=lo,ci_high=hi,n_participants=total,source='online_intervals.csv',quantity=quantity))
    handles=[Line2D([],[],marker='o',color=BLUE,mfc=face,mec=BLUE,lw=0,ms=4,label=label) for _,label,_,face in BASES]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.61,.072),ncol=2,fontsize=8,columnspacing=1.1,handletextpad=.4)
    fig.text(.012,.042,'Intervals: conditional 95% participant-cluster intervals. Candidate n applies to panel (a) only.',fontsize=8)
    assert len(plotted)==30
    return fig,plotted

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture-from',type=Path);parser.add_argument('--data',type=Path,default=HERE/'data');parser.add_argument('--out',type=Path,default=HERE);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.capture_from:capture(args.capture_from,args.data)
    provenance=json.loads((args.data/'provenance.json').read_text(encoding='utf8'))
    for row in provenance:assert style.sha(args.data/row['snapshot'])==row['sha256'],row
    font_path=style.setup()
    records,old_checks=style.validate_sources(args.data/'legacy')
    comp=style.read_csv(args.data/'component_summary.csv');clean=style.read_csv(args.data/'clean_control_results.csv')
    for component,metric in COMPONENTS:
        new=one(comp,expected_component=component)
        old=one(records,record_type='fault_detection',series='Full ECRC',metric=metric)
        assert int(new['archived_full_ECRC_detected'])==int(float(old['numerator']))
        assert int(new['n_cases'])==int(float(old['denominator']))
    candidate=style.read_csv(args.data/'frozen_candidate_summary.csv');intervals=style.read_csv(args.data/'online_intervals.csv')
    fig4,p4=figure4(records,comp,clean);fig5,p5=figure5(candidate,intervals)
    write_csv(args.out/'fig4_plot_values.csv',p4);write_csv(args.out/'fig5_plot_values.csv',p5)
    manifest=dict(python=platform.python_version(),matplotlib=style.matplotlib.__version__,numpy=np.__version__,style=dict(font='Arial',font_path_at_build=str(font_path),width_inches=6.5,minimum_font_pt=8,text_color=BLACK,data_color=BLUE),provenance=provenance,upstream_numeric_checks=old_checks,original_capacity_and_latency_data_unchanged=True,figure5_panel_a_cells=6,figure5_panels_b_c_cells_each=12,figure5_delta_direction='paced minus fifo',independent_clean_unit='one complete accepted trace, 32 permits and 32 receipts',experiments_or_models_run=False,script_sha256=style.sha(__file__),style_helper_sha256=style.sha(style.__file__))
    manifest['fig4']=style.export(fig4,args.out/'fig4');manifest['fig5']=style.export(fig5,args.out/'fig5')
    manifest['plot_values']={name:style.sha(args.out/name) for name in ['fig4_plot_values.csv','fig5_plot_values.csv']}
    (args.out/'fig4_fig5_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:manifest[k] for k in ['fig4','fig5']},indent=2))

if __name__=='__main__':main()
