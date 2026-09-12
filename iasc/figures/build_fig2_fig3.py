"""Rebuild Figures 2 and 3 from archived aggregate CSVs using Matplotlib.

Usage: python build_fig2_fig3.py --source data/analysis --out .
No model fitting, random sampling, or generative-image service is used.
"""
from pathlib import Path
import argparse
import hashlib
import json
from decimal import Decimal

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.font_manager import findfont, FontProperties
import numpy as np
import pandas as pd

BLUE='#24557A'
BLACK='#202020'
GREY='#888888'
FILES=['a1_discrimination_decomposition.csv','a1_discrimination_bootstrap.csv',
       'a2_allocator_comparison.csv','a2_allocator_bootstrap.csv',
       'a3_interval_algebra.csv','a4_permission_grid.csv','a5_denial_by_quintile.csv']
MODELS=['HGB','logistic','history']
LABEL={'HGB':'HGB','logistic':'Logistic','history':'History'}
COHORTS=['development','external']
CLABEL={'development':'Development','external':'External replay'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def style():
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','Helvetica','Liberation Sans'],
        'font.size':9,'axes.labelsize':9,'axes.titlesize':9,'xtick.labelsize':8,
        'ytick.labelsize':8.5,'legend.fontsize':8,'text.color':'black',
        'axes.labelcolor':'black','xtick.color':'black','ytick.color':'black',
        'axes.edgecolor':'black','axes.linewidth':.6,'lines.linewidth':.9,
        'xtick.major.width':.6,'ytick.major.width':.6,'xtick.major.size':3,
        'ytick.major.size':3,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none',
        'svg.hashsalt':'ecrc-iasc-data-redraw-20260911','savefig.facecolor':'white',
        'figure.facecolor':'white','legend.frameon':False,'axes.unicode_minus':False})

def tidy(ax):
    ax.spines[['top','right']].set_visible(False)
    ax.tick_params(direction='out',pad=3)
    return ax

def save(fig,out,name):
    result={}
    for ext,kwargs in [('pdf',{'metadata':{'CreationDate':None,'ModDate':None,'Creator':'Matplotlib; local archived data'}}),
                       ('svg',{'metadata':{'Date':None}}),('png',{'dpi':600}),('tiff',{'dpi':1200,'pil_kwargs':{'compression':'tiff_lzw'}})]:
        path=out/f'{name}.{ext}'
        fig.savefig(path,**kwargs)
        result[path.name]=sha(path)
    plt.close(fig)
    return result

def one(frame,**selector):
    mask=np.ones(len(frame),dtype=bool)
    for key,value in selector.items():mask &= frame[key].eq(value).to_numpy()
    result=frame.loc[mask]
    assert len(result)==1,selector
    return result.iloc[0]

def fig2(data,out):
    dec,boot,alloc,aboot=[data[f] for f in FILES[:4]]
    fig=plt.figure(figsize=(6.5,3.5))
    axes=[tidy(fig.add_axes(b)) for b in [[.115,.235,.258,.66],[.442,.235,.164,.66],[.690,.235,.292,.66]]]
    positions=[6.4,5.4,4.4,2.7,1.7,.7]
    rows=[(c,m) for c in COHORTS for m in MODELS]
    source=[]
    for ax in axes:
        ax.set_ylim(.15,7.35)
        ax.spines['left'].set_visible(False)
        ax.set_yticks(positions)
        ax.tick_params(axis='y',length=0)
        ax.axhline(3.55,color='#dddddd',lw=.5,zorder=0)
    axes[0].set_yticklabels([LABEL[m] for c,m in rows])
    axes[1].set_yticklabels([]);axes[2].set_yticklabels([])
    for y,(cohort,model) in zip(positions,rows):
        r=one(dec,cohort=cohort,model_label=model)
        ci=one(boot,cohort=cohort,model_label=model,metric='within_participant_auroc_stratified')
        axes[0].hlines(y,r.within_participant_auroc_stratified,r.pooled_auroc,color=GREY,lw=.7)
        axes[0].errorbar(r.within_participant_auroc_stratified,y,
            xerr=[[r.within_participant_auroc_stratified-ci.ci_low],[ci.ci_high-r.within_participant_auroc_stratified]],
            fmt='o',color=BLUE,ms=4,capsize=2,elinewidth=.8,markeredgewidth=.7,zorder=3)
        axes[0].plot(r.pooled_auroc,y,'o',mfc='white',mec=BLACK,ms=4,mew=.8,zorder=4)
        share=float(r.share_participants_auroc_below_0_5)*100
        axes[1].plot(share,y,'o',color=BLACK,ms=3.5)
        axes[1].annotate(f'{share:.1f}',(share,y),xytext=(4,0),textcoords='offset points',va='center',fontsize=8)
        item={'cohort':cohort,'model':model,'pooled_auroc':r.pooled_auroc,
              'within_auroc':r.within_participant_auroc_stratified,'within_ci_low':ci.ci_low,'within_ci_high':ci.ci_high,
              'below_0_5_percent':share,'eligible_participants':int(r.n_participants_eligible)}
        for offset,basis,filled in [(.14,'per_episode',True),(-.14,'per_100_decisions_8',False)]:
            arr=one(alloc,cohort=cohort,model_label=model,capacity_basis=basis,allocator='chronological')
            ranked=one(alloc,cohort=cohort,model_label=model,capacity_basis=basis,allocator='score_ranked')
            ci=one(aboot,cohort=cohort,model_label=model,capacity_basis=basis,
                   quantity='delta_chronological_minus_score_ranked__alert_precision')
            point=ranked.alert_precision-arr.alert_precision
            low,high=-ci.ci_high,-ci.ci_low
            axes[2].errorbar(point,y+offset,xerr=[[point-low],[high-point]],fmt='o',
                color=BLUE if filled else BLACK,mfc=BLUE if filled else 'white',ms=3.5,
                capsize=2,elinewidth=.7,markeredgewidth=.7,zorder=3)
            item.update({basis+'_contrast':point,basis+'_ci_low':low,basis+'_ci_high':high})
        source.append(item)
    for ax,title in zip(axes,['(a) Discrimination','(b) Estimates < 0.5','(c) Allocation contrast']):
        ax.set_title(title,loc='left',fontweight='bold',pad=9)
    for y,label in [(7.0,'Development'),(3.3,'External replay')]:
        axes[0].text(-.42,y,label,transform=axes[0].get_yaxis_transform(),fontsize=8.5,fontweight='bold',va='center')
    axes[0].set_xlim(.44,.84);axes[0].set_xticks([.5,.6,.7,.8]);axes[0].set_xlabel('AUROC')
    axes[0].axvline(.5,color=GREY,ls=(0,(2,2)),lw=.6,zorder=0)
    axes[1].set_xlim(0,87);axes[1].set_xticks([0,40,80]);axes[1].set_xlabel('Participants (%)')
    axes[2].set_xlim(-.17,.16);axes[2].set_xticks([-.15,0,.15]);axes[2].set_xticklabels(['-0.15','0','0.15'])
    axes[2].axvline(0,color=GREY,ls=(0,(2,2)),lw=.6,zorder=0)
    axes[2].set_xlabel('Change in alert precision')
    common={'loc':'upper left','bbox_to_anchor':(-.04,-.23),'borderaxespad':0,'handlelength':1,'handletextpad':.35,'labelspacing':.3}
    axes[0].legend(handles=[Line2D([],[],ls='none',marker='o',mfc='white',mec=BLACK,ms=4,label='Pooled'),
                            Line2D([],[],ls='none',marker='o',color=BLUE,ms=4,label='Within participant')],**common)
    axes[2].legend(handles=[Line2D([],[],ls='none',marker='o',color=BLUE,ms=4,label='Eight units per episode'),
                            Line2D([],[],ls='none',marker='o',mfc='white',mec=BLACK,ms=4,label='Eight units per 100 decisions')],**common)
    fig.text(.442,.078,'Descriptive only;\nsee sequence controls.',fontsize=8,va='center')
    pd.DataFrame(source).to_csv(out/'fig2_plot_data.csv',index=False,float_format='%.17g')
    return save(fig,out,'fig2')

def fig3(data,out):
    algebra=data['a3_interval_algebra.csv'];grid=data['a4_permission_grid.csv'];quint=data['a5_denial_by_quintile.csv']
    fig=plt.figure(figsize=(6.5,3.9))
    axes=np.array([fig.add_axes(r) for r in [[.195,.59,.295,.27],[.63,.59,.345,.27],[.11,.17,.38,.27],[.63,.17,.345,.27]]]).reshape(2,2)
    a,b,c,d=axes.flat
    for ax in axes.flat:tidy(ax)
    source=[]
    # Exact policy intervals; empirical estimates are not used to set the regions.
    for i,model in enumerate(MODELS):
        r=one(algebra,cohort='external',model_label=model)
        tau=Decimal(str(round(float(r.prompt_threshold),2)));delta=Decimal('.03')
        low,high=tau-delta,tau+delta;y=2-i
        a.add_patch(Rectangle((.45,y-.32),.10,.64,facecolor='#e4e4e4',edgecolor='none',zorder=0))
        a.plot([float(low),float(high)],[y,y],color=GREY,lw=5,solid_capstyle='butt',zorder=2)
        a.plot([float(high),1],[y,y],color=BLUE,lw=5,solid_capstyle='butt',zorder=2)
        a.plot(float(high),y,'o',mfc='white',mec=BLUE,ms=3,mew=.6,zorder=3)
        union_width=max(Decimal(0),min(Decimal('.55'),Decimal(1))-max(Decimal('.45'),low))
        source.append({'panel':'a','model':model,'threshold':str(tau),'review_low':str(low),'review_high':str(high),
                       'gate_low':'.45','gate_high':'.55','action_union_overlap_width':str(union_width),
                       'legacy_max_component_width':r.ambiguity_action_overlap_width})
    a.plot(.55,1,'o',color=BLACK,ms=3,zorder=5)
    a.annotate('0.55 singleton',xy=(.55,1),xytext=(.70,1.43),fontsize=8,ha='center',arrowprops=dict(arrowstyle='-',lw=.6,color=BLACK))
    a.set_xlim(.35,1.01);a.set_ylim(-.5,2.55);a.set_xticks([.4,.6,.8,1.0]);a.set_xlabel('Proposal score')
    a.set_yticks([2,1,0]);a.set_yticklabels([LABEL[m]+' (τ='+f'{float(one(algebra,cohort="external",model_label=m).prompt_threshold):.2f}'+')' for m in MODELS],fontsize=8)
    a.tick_params(axis='y',length=0);a.spines['left'].set_visible(False)
    a.legend(handles=[Patch(facecolor='#e4e4e4',label='Ambiguity gate'),Line2D([],[],color=GREY,lw=4,label='Review'),Line2D([],[],color=BLUE,lw=4,label='Alert')],
        loc='upper left',bbox_to_anchor=(-.01,1.22),borderaxespad=0,ncol=3,columnspacing=.7,handlelength=.7,handletextpad=.3,fontsize=8)
    arms=[('separate_capacity_8_2','8+2 arrival','o'),('shared_capacity_10','Pooled 10','s'),
          ('separate_capacity_score_priority','8+2 score priority','^'),('capacity_off','No cap','D')]
    for arm,label,marker in arms:
        r=one(grid,cohort='external',model_label='HGB',arm=arm)
        b.plot(r.alert_coverage,r.alert_precision,marker=marker,ms=4.5,mfc='white',mec=BLUE,mew=.9,ls='none',label=label)
        source.append({'panel':'b','arm':arm,'precision':r.alert_precision,'coverage':r.alert_coverage})
    b.set_xlim(0,.42);b.set_ylim(.635,.795);b.set_xticks([0,.2,.4]);b.set_yticks([.65,.70,.75])
    b.set_xlabel('Proxy-positive alert coverage');b.set_ylabel('Alert precision')
    b.legend(loc='lower right',bbox_to_anchor=(1.03,-.025),handlelength=.8,handletextpad=.35,labelspacing=.25,borderaxespad=0)
    for j,cohort in enumerate(COHORTS):
        q=quint[(quint.cohort==cohort)&(quint.model_label=='HGB')].sort_values('quintile')
        assert len(q)==5
        color=BLACK if j==0 else BLUE;marker='o' if j==0 else '^';ls='-' if j==0 else '--'
        x=q.quintile.to_numpy()
        c.plot(x,q.denial_rate.to_numpy()*100,color=color,marker=marker,ls=ls,ms=3.8,label=CLABEL[cohort])
        d.bar(x+(j-.5)*.34,q.candidacy_share.to_numpy()*100,width=.31,facecolor='white' if j==0 else '#a9bdd0',
              edgecolor=BLACK,linewidth=.6,hatch='' if j else '///',label=CLABEL[cohort])
        for _,r in q.iterrows():source.append({'panel':'c/d','cohort':cohort,'quintile':int(r.quintile),
            'denial_rate':r.denial_rate,'candidacy_share':r.candidacy_share,'n_candidates':int(r.n_alert_candidates),'n_denied':int(r.n_denied)})
    for ax in [c,d]:
        ax.set_xticks([1,2,3,4,5]);ax.set_xlabel('Participant proxy-event-rate quintile')
    c.set_ylim(0,100);c.set_yticks([0,50,100]);c.set_ylabel('Denied candidacies (%)')
    c.legend(loc='lower right',handlelength=1.5,labelspacing=.25)
    d.set_ylim(0,50);d.set_yticks([0,25,50]);d.set_ylabel('Share of candidacies (%)')
    for ax,title in zip(axes.flat,['(a) Policy score regions','(b) External HGB permission arms','(c) HGB denial (cap 8)','(d) HGB candidacies (cap 8)']):
        fig.text(ax.get_position().x0,.965 if ax in [a,b] else .49,title,fontweight='bold',fontsize=9,ha='left',va='top')
    pd.DataFrame(source).to_csv(out/'fig3_plot_data.csv',index=False,float_format='%.17g')
    return save(fig,out,'fig3')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True);style()
    data={name:pd.read_csv(args.source/name) for name in FILES}
    manifest_path=args.source/'reanalysis_manifest.json'
    if manifest_path.exists():
        original=json.loads(manifest_path.read_text(encoding='utf-8'))
        for name in FILES:assert sha(args.source/name)==original['output_hashes'][name],name
    outputs=fig2(data,args.out)|fig3(data,args.out)
    manifest={'generator':'Matplotlib','script_sha256':sha(Path(__file__)),
        'matplotlib':matplotlib.__version__,'font_path':findfont(FontProperties(family='Arial')),
        'figure_width_inches':6.5,'minimum_font_points':8,'dpi_png':600,'dpi_tiff':1200,
        'observations_hardcoded':False,'models_refitted':False,'intervals_recomputed':False,
        'inputs':{name:sha(args.source/name) for name in FILES},'outputs':outputs,
        'transforms':['A2 contrasts negate and swap archived CI endpoints.',
                      'A3 action overlap is the interval union width, not the largest component width.',
                      'Figure 3d separates cohort candidacy shares into side-by-side bars.']}
    (args.out/'fig2_fig3_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'figures':2,'files':len(outputs),'font':manifest['font_path']},indent=2))

if __name__=='__main__':main()
