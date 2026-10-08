"""Offline, portable renderer for the two primary shared-budget figures.

Reads only two included sanitized CSVs. No provider SDK, network operation,
private workspace, credentials, ledger or original experimental directory.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter
import numpy as np

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input-dir',type=Path,default=Path(__file__).resolve().parent,
                    help='Directory containing the two included CSVs (default: script directory).')
parser.add_argument('--output-dir',type=Path,default=Path('figures'),
                    help='Output directory, relative to the current directory unless absolute (default: figures).')
args=parser.parse_args()
INPUT_HASHES={
    'primary_recomputed_metrics.csv':'d11b36150ff1e0e63741f217f82dc949bc4180a77209ddf1e16534d0a01a2982',
    'primary_job_distribution.csv':'ec23dec08305eb19a4d65497ea5f257dad021b2d6dc64c57077d899da35f5d3c',
}
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def csvread(name):
    path=args.input_dir/name
    if sha(path)!=INPUT_HASHES[name]:
        raise ValueError('Numeric snapshot hash mismatch: '+name)
    with path.open(encoding='utf-8',newline='') as stream:
        return list(csv.DictReader(stream))

ARMS=['prompt_only','ordinary','ecrc']
ARM_LABEL={'prompt_only':'Prompt only','ordinary':'Conventional control','ecrc':'ECRC'}
MODELS=['openai','luna']
COND=['normal','hidden_first_result']
COLORS={'prompt_only':'#454545','ordinary':'#7B6692','ecrc':'#28618A'}
MARKERS={'prompt_only':'o','ordinary':'s','ecrc':'D'}
computed=csvread('primary_recomputed_metrics.csv')
distribution=csvread('primary_job_distribution.csv')
for row in computed:
    for field in ['estimate','ci95_low','ci95_high']:
        row[field]=float(row[field])
        assert math.isfinite(row[field]) and 0<=row[field]<=1
    assert row['ci95_low']<=row['estimate']<=row['ci95_high']
for row in distribution:
    for field in ['jobs','trajectories','planned']:
        row[field]=int(row[field])
    assert row['planned']==48 and 0<=row['jobs']<=8 and 0<=row['trajectories']<=48
metric_keys={(p,c,a,m) for p in MODELS for c in COND for a in ARMS
             for m in ['raw_verified_yield','compliant_verified_yield','actual_excess_rate']}
assert len(computed)==36 and {(r['provider'],r['condition'],r['arm'],r['metric']) for r in computed}==metric_keys
job_keys={(p,c,a,j) for p in MODELS for c in COND for a in ARMS for j in range(9)}
assert len(distribution)==108 and {(r['provider'],r['condition'],r['arm'],r['jobs']) for r in distribution}==job_keys
for provider in MODELS:
    for condition in COND:
        for arm in ARMS:
            cell=[r for r in distribution if (r['provider'],r['condition'],r['arm'])==(provider,condition,arm)]
            assert sum(r['trajectories'] for r in cell)==48
            excess=sum(r['trajectories'] for r in cell if r['jobs']>3)/48
            reported=next(r['estimate'] for r in computed if (r['provider'],r['condition'],r['arm'],r['metric'])==(provider,condition,arm,'actual_excess_rate'))
            assert math.isclose(excess,reported,abs_tol=1e-12)

font_path=font_manager.findfont('Arial',fallback_to_default=False)
plt.rcParams.update({'font.family':'Arial','font.size':10,'axes.labelsize':10,
                    'xtick.labelsize':9.5,'ytick.labelsize':10,'pdf.fonttype':42,'ps.fonttype':42,
                    'text.color':'black','axes.labelcolor':'black','xtick.color':'black','ytick.color':'black',
                    'axes.linewidth':.6,'axes.spines.top':False,'axes.spines.right':False,
                    'axes.titleweight':'normal','axes.titlesize':10})
figdir=Path(args.output_dir);figdir.mkdir(parents=True,exist_ok=True)

def save_figure(fig,name):
    """Keep a fixed journal width and reject clipping of any text label."""
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    outside=[]
    for text in fig.findobj(matplotlib.text.Text):
        if text.get_visible() and text.get_text():
            bbox=text.get_window_extent(renderer)
            if bbox.x0 < -1 or bbox.y0 < -1 or bbox.x1 > fig.bbox.x1+1 or bbox.y1 > fig.bbox.y1+1:
                outside.append(text.get_text())
    assert not outside,(name,'text outside figure',outside)
    for ext in ['pdf','png']:
        options={'metadata':{'CreationDate':None,'ModDate':None}} if ext=='pdf' else {}
        fig.savefig(figdir/(name+'.'+ext),dpi=300,facecolor='white',**options)
    plt.close(fig)

fig,axes=plt.subplots(2,2,figsize=(16.5/2.54,10.8/2.54),sharey=True)
JOB_FILLS={'prompt_only':'#DBDFE3','ordinary':'#DED3EB','ecrc':'#C7DEED'}
BUBBLE_AREA_PER_COUNT=7.5
plotted_job_bins=[]
for i,provider in enumerate(MODELS):
    for j,condition in enumerate(COND):
        ax=axes[i,j]
        ax.axvspan(3.5,8.5,color='#F5F2F7',zorder=0)
        for y,arm in enumerate(ARMS):
            for jobs in range(9):
                r=next(r for r in distribution if (r['provider'],r['condition'],r['arm'],r['jobs'])==(provider,condition,arm,jobs))
                n=r['trajectories']
                plotted_job_bins.append({'provider':provider,'condition':condition,'arm':arm,
                                         'jobs':jobs,'count':n,'marker_area_pt2':BUBBLE_AREA_PER_COUNT*n})
                if n:
                    # Scatter marker area is proportional to the count, with
                    # no minimum-area offset. Small-count labels sit above
                    # their marker so their exact values remain readable.
                    ax.scatter(jobs,y,s=BUBBLE_AREA_PER_COUNT*n,marker='o',
                               facecolor=JOB_FILLS[arm],edgecolor=COLORS[arm],
                               linewidths=.65,zorder=3)
                    if n>=16:
                        ax.text(jobs,y,str(n),ha='center',va='center',fontsize=9.5,color='black',zorder=4)
                    else:
                        ax.annotate(str(n),(jobs,y),xytext=(0,7),textcoords='offset points',
                                    ha='center',va='bottom',fontsize=9.5,color='black',zorder=4)
        ax.set_xlim(-.6,8.6);ax.set_ylim(2.55,-.67)
        ax.set_xticks(range(9))
        ax.set_yticks(range(3));ax.set_yticklabels(['Prompt only','Conventional\ncontrol','ECRC'])
        ax.axvline(3.5,color='black',linewidth=.9,linestyle=(0,(3,2)),zorder=2)
        ax.grid(axis='x',color='#E3E3E3',linewidth=.5);ax.set_axisbelow(True)
        ax.spines[['left','right','top']].set_visible(False)
        ax.tick_params(axis='y',length=0,pad=7);ax.tick_params(axis='x',length=0,pad=5)
        ax.text(0,1.12,'ABCD'[2*i+j],transform=ax.transAxes,ha='left',va='bottom',fontsize=10,fontweight='bold')
        ax.text(6,1.12,'Above quota',transform=ax.get_xaxis_transform(),ha='center',va='bottom',fontsize=9.5)
fig.subplots_adjust(left=.22,right=.985,bottom=.17,top=.815,wspace=.13,hspace=.78)
for x,label in [(.4,'Normal response'),(.80,'First result hidden')]:
    fig.text(x,.952,label,ha='center',va='top',fontsize=10,fontweight='bold')
fig.text(.025,.872,'GPT-4.1 mini',ha='left',va='center',fontsize=10,fontweight='bold')
fig.text(.025,.435,'GPT-6 Luna',ha='left',va='center',fontsize=10,fontweight='bold')
fig.text(.59,.096,'New verification jobs per trajectory',ha='center',fontsize=10)
fig.text(.5,.028,'Circle area and labels: trajectory count (n = 48 per row).',ha='center',fontsize=9.5)
save_figure(fig,'shared_agent_jobs')

fig,axes=plt.subplots(2,2,figsize=(16.5/2.54,10.8/2.54),sharex=True,sharey=True)
for i,condition in enumerate(COND):
    for j,metric in enumerate(['raw_verified_yield','compliant_verified_yield']):
        ax=axes[i,j]
        if j==1:
            ax.axvline(.75,color='black',linestyle=(0,(2,2)),linewidth=.8)
        for m,provider in enumerate(MODELS):
            for k,arm in enumerate(ARMS):
                r=next(r for r in computed if (r['provider'],r['condition'],r['arm'],r['metric'])==(provider,condition,arm,metric))
                y=m+(k-1)*.20;p=r['estimate']
                ax.errorbar(p,y,xerr=[[p-r['ci95_low']],[r['ci95_high']-p]],fmt=MARKERS[arm],
                            color=COLORS[arm],markersize=5.3,capsize=2.3,linewidth=1.2,zorder=3,clip_on=False)
        ax.set_xlim(0,1);ax.set_ylim(1.5,-.5);ax.set_xticks(np.linspace(0,1,5));ax.xaxis.set_major_formatter(PercentFormatter(1))
        ax.set_yticks([0,1]);ax.set_yticklabels(['GPT-4.1 mini','GPT-6 Luna'])
        ax.grid(axis='x',color='#E4E4E4',linewidth=.5);ax.set_axisbelow(True)
        ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0)
        ax.text(0,1.07,'ABCD'[2*i+j],transform=ax.transAxes,ha='left',va='bottom',fontsize=10,fontweight='bold')
        if j==0:ax.text(-.56,1.07,'Normal response' if i==0 else 'First result\nhidden',transform=ax.transAxes,
                       ha='left',va='bottom',fontsize=10,fontweight='bold')
handles=[Line2D([],[],color=COLORS[a],marker=MARKERS[a],linestyle='none',label=ARM_LABEL[a]) for a in ARMS]
fig.legend(handles=handles,loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.5,1),fontsize=10,handletextpad=.4,columnspacing=1.0)
fig.subplots_adjust(left=.20,right=.957,bottom=.15,top=.785,hspace=.48,wspace=.20)
fig.text(.372,.882,'Raw verified yield',ha='center',fontsize=10,fontweight='bold')
fig.text(.782,.882,'Compliant verified yield',ha='center',fontsize=10,fontweight='bold')
fig.text(.58,.035,'Share of four eligible tasks',ha='center',fontsize=10)
save_figure(fig,'shared_agent_yield')


output_names=['shared_agent_'+name+'.'+extension for name in ['jobs','yield'] for extension in ['pdf','png']]
manifest={
    'schema':'portable-shared-budget-render-v1',
    'input_sha256':INPUT_HASHES,
    'script_sha256':sha(Path(__file__)),
    'output_sha256':{name:sha(figdir/name) for name in output_names},
    'runtime_versions':{'numpy':np.__version__,'matplotlib':matplotlib.__version__},
    'configured_dimensions_cm':{'shared_agent_jobs':[16.5,10.8],'shared_agent_yield':[16.5,10.8]},
    'configured_minimum_font_pt':{'shared_agent_jobs':9.5,'shared_agent_yield':9.5},
    'matplotlib_backend':'Agg','font_family':'Arial','font_file':Path(font_path).name,'font_sha256':sha(Path(font_path)),'png_dpi':300,
    'jobs_panel_mapping':{'A':'GPT-4.1 mini / normal','B':'GPT-4.1 mini / hidden first result','C':'GPT-6 Luna / normal','D':'GPT-6 Luna / hidden first result'},
    'yield_panel_mapping':{'A':'normal / raw','B':'normal / compliant','C':'hidden first result / raw','D':'hidden first result / compliant'},
    'data_equivalence':{'job_bins_validated':108,'metric_estimates_and_intervals_shown':24,'zero_count_encoding':'no circle'},
    'jobs_area_encoding':{'scope':'same proportional marker-area scale for all arms and panels',
                          'matplotlib_marker_area_pt2_per_count':BUBBLE_AREA_PER_COUNT,'minimum_area_offset':0,
                          'small_count_labels':'counts below 16 printed above marker; other counts centered'},
    'validated_job_bins':plotted_job_bins,
    'API_calls':0,'raw_private_inputs_required':False,
    'scope':'Redraws the complete primary-study plots from audited numeric snapshots; does not rerun agents or re-estimate the bootstrap.'
}
(figdir/'rendering_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':'rendered','output_files':output_names+['rendering_manifest.json'],'API_calls':0}))
