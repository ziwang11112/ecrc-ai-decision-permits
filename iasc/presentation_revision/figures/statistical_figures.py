"""Statistical figures use saved point estimates and saved paired intervals only."""
import math
from decimal import Decimal
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle, Patch
from matplotlib.ticker import FuncFormatter
import journal_style as style
import __main__ as builder


def interval(ax, point, low, high, y, marker, color, fill):
    assert low <= point <= high and all(math.isfinite(v) for v in (point, low, high))
    ax.errorbar(point, y, xerr=[[point-low],[high-point]], fmt=marker, mfc=fill, mec=color,
                color=color, ms=4, mew=.8, capsize=2, capthick=.7, elinewidth=.8, zorder=3)


def fig4():
    b=builder; dec,ci,candidate,algebra=b.rows('discrimination.csv'),b.rows('discrimination_ci.csv'),b.rows('candidate.csv'),b.rows('interval_algebra.csv')
    fig=plt.figure(figsize=(style.WIDTH,5.4)); top=fig.add_axes([.285,.47,.69,.41]); bottom=fig.add_axes([.285,.11,.69,.205])
    for ax in (top,bottom):style.clean_axes(ax);ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0)
    ys=[5.4,4.4,3.4,1.8,.8,-.2];top.set(ylim=(-.7,6),xlim=(.4,.85),xticks=[.4,.5,.6,.7,.8],xlabel='AUROC');top.set_yticks(ys);top.set_yticklabels([c+' '+l for _,c in b.COHORTS for _,l in b.MODELS])
    top.axvline(.5,color='#999999',ls=(0,(2,2)),lw=.6,zorder=0);top.axhline(2.6,color='#CCCCCC',lw=.5)
    fig.text(.025,.965,'(a) Prediction evaluation across six cohort-model cells',fontweight='bold',fontsize=10)
    output=[]
    for y,(dataset,cohort,model,label) in zip(ys,[(d,c,m,l) for d,c in b.COHORTS for m,l in b.MODELS]):
        row=b.one(dec,dataset_id=dataset,model_name=model)
        within=b.one(ci,dataset_id=dataset,model_name=model,metric='within_participant_auroc_stratified')
        cand=b.one(candidate,dataset_id=dataset,model_name=model,region='alert_candidates')
        point=float(row['pooled_auroc']);top.plot(point,y+.17,'s',mfc='white',mec='black',ms=4,mew=.8,zorder=4)
        output.append(dict(panel='a',dataset_id=dataset,cohort=cohort,model_name=model,estimand='all_pairs_pooled',estimate=point,ci_low='',ci_high='',n_participants=row['n_participants'],n_eligible='all observations',source='discrimination.csv'))
        point=float(row['within_participant_auroc_stratified']);low,high=float(within['ci_low']),float(within['ci_high'])
        interval(top,point,low,high,y,'o',style.BLUE,style.BLUE)
        output.append(dict(panel='a',dataset_id=dataset,cohort=cohort,model_name=model,estimand='within_participant_pair_weighted',estimate=point,ci_low=low,ci_high=high,n_participants=row['n_participants'],n_eligible=row['n_participants_eligible'],source='discrimination.csv + discrimination_ci.csv'))
        point,low,high=[float(cand[k]) for k in ('within_auroc_pair_weighted','within_auroc_pair_weighted_ci_low','within_auroc_pair_weighted_ci_high')]
        interval(top,point,low,high,y-.17,'D','black','white')
        output.append(dict(panel='a',dataset_id=dataset,cohort=cohort,model_name=model,estimand='alert_candidate_within_participant_pair_weighted',estimate=point,ci_low=low,ci_high=high,n_participants=cand['n_participants'],n_eligible=cand['n_eligible'],source='candidate.csv'))
    handles=[Line2D([],[],marker='s',mfc='white',mec='black',ls='none',label='Pooled (point only)',ms=4),
             Line2D([],[],marker='o',color=style.BLUE,ls='none',label='Within participant',ms=4),
             Line2D([],[],marker='D',mfc='white',mec='black',ls='none',label='Alert candidates',ms=4)]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.941),ncol=3,frameon=False,columnspacing=.9,handletextpad=.35)
    fig.text(.025,.374,'(b) External frozen score regions',fontweight='bold',fontsize=10)
    for i,(model,label) in enumerate(b.MODELS):
        row=b.one(algebra,cohort='external',model_name=model)
        tau=Decimal(str(round(float(row['prompt_threshold']),2))); low=tau-Decimal('.03');high=tau+Decimal('.03');y=2-i
        bottom.add_patch(Rectangle((.45,y-.30),.10,.60,facecolor='#E0E0E0',edgecolor='none',zorder=0))
        bottom.plot([float(low),float(high)],[y,y],color=style.GREY,lw=4,solid_capstyle='butt')
        bottom.plot([float(high),1],[y,y],color=style.BLUE,lw=4,solid_capstyle='butt')
        bottom.plot([float(low),float(high)],[y,y],'o',mfc=style.GREY,mec='black',ms=3,mew=.4)
        bottom.plot(float(high),y,'o',mfc='white',mec=style.BLUE,ms=3,mew=.7,zorder=5)
        if label=='Logistic':bottom.plot(.55,y,'o',color='black',ms=3,zorder=6)
        output.append(dict(panel='b',model_name=model,threshold=str(tau),review_low=str(low),review_high=str(high),gate_low='.45',gate_high='.55',alert_low_exclusive=str(high),alert_high_inclusive='1',action_gate_union_width=str(max(Decimal(0),min(Decimal('.55'),Decimal(1))-max(Decimal('.45'),low))),source='interval_algebra.csv'))
    bottom.set(ylim=(-.5,2.5),xlim=(.35,1.01),xticks=[.4,.5,.6,.7,.8,.9,1.0],xlabel='Proposal score before ambiguity veto')
    bottom.set_yticks([2,1,0]);bottom.set_yticklabels([label+' (τ = '+f"{float(b.one(algebra,cohort='external',model_name=m)['prompt_threshold']):.2f}"+')' for m,label in b.MODELS])
    bottom.legend(handles=[Patch(facecolor='#E0E0E0',label='Gate [0.45, 0.55]'),Line2D([],[],color=style.GREY,lw=4,label='Review'),Line2D([],[],color=style.BLUE,lw=4,label='Alert')],loc='upper left',bbox_to_anchor=(-.02,1.3),frameon=False,ncol=3,columnspacing=1,handlelength=1,handletextpad=.4)
    fig.text(.025,.015,'AUROC populations differ; distances between symbols are not a same-estimand performance loss.',fontsize=9.5)
    b.write_csv(b.DATA/'fig4_plot_data.csv',output)
    for source in ('discrimination.csv','discrimination_ci.csv','candidate.csv'):
        b.evidence(4,'a','data/input/'+source,{'dataset_id':[x[0] for x in b.COHORTS],'model_name':[x[0] for x in b.MODELS],'candidate_region':'alert_candidates'},
                   'Exact stored pooled, pair-weighted within-person and candidate AUROC; saved CIs only; pooled point-only because no corresponding stored CI used. No connecting lines.', 'saved statistical estimates; different evaluation populations')
    b.evidence(4,'b','data/input/interval_algebra.csv',{'cohort':'external','models':[x[0] for x in b.MODELS]},'Decimal endpoint projection from saved tau: review [tau-.03,tau+.03], alert (tau+.03,1], ambiguity gate [.45,.55]; recompute union width, not legacy max-component width.','specified frozen policy regions')
    return style.save(fig,4,'prediction_and_gate')


def fig5():
    b=builder; intervals=b.rows('online_intervals.csv'); estimates=b.rows('online_estimates.csv'); macro=b.rows('participant_equal.csv')
    fig=plt.figure(figsize=(style.WIDTH,6.4))
    axes=[fig.add_axes([x,.18,.213,.68]) for x in (.295,.53,.765)]
    cells=[(d,c,m,l,basis,bl) for d,c in b.COHORTS for m,l in b.MODELS for basis,bl in b.BASES]
    # Two budget rows per cohort/model, with a gap only between cohorts.
    ys=[12-i-(.55 if i>=6 else 0) for i in range(12)]
    metrics=[('alert_precision','(a) Alert precision'),('alert_coverage','(b) Alert coverage'),('budget_utilization','(c) Budget use')]
    output=[]
    for ax,(metric,title) in zip(axes,metrics):
        style.clean_axes(ax);ax.spines['left'].set_visible(False);ax.set_ylim(.05,12.6);ax.set_yticks([])
        ax.axvline(0,color='#999999',ls=(0,(2,2)),lw=.6);ax.axhline(6.725,color='#CCCCCC',lw=.6)
        ax.set_title(title,loc='left',fontweight='bold',pad=12,fontsize=10)
        bounds=[]
        for y,(dataset,cohort,model,label,basis,bl) in zip(ys,cells):
            r=b.one(intervals,dataset_id=dataset,model_name=model,capacity_basis=basis,quantity='delta_paced_minus_fifo__'+metric)
            point,low,high=[float(r[k]) for k in ('estimate','ci_low','ci_high')]
            e0=b.one(estimates,dataset_id=dataset,model_name=model,capacity_basis=basis,allocator='fifo')
            e1=b.one(estimates,dataset_id=dataset,model_name=model,capacity_basis=basis,allocator='paced')
            assert abs(float(r['estimate'])-(float(e1[metric])-float(e0[metric])))<1e-12
            interval(ax,point,low,high,y+.13 if metric!='budget_utilization' else y,'o',style.BLUE,style.BLUE)
            bounds.extend([low,high])
            output.append(dict(panel=metric,dataset_id=dataset,cohort=cohort,model_name=model,capacity_basis=basis,estimand='pooled',estimate=point,ci_low=low,ci_high=high,units='proportion difference',n_participants=e0['n_participants'],finite_replicates=r['finite_replicates'],source='online_intervals.csv',quantity=r['quantity']))
            if metric!='budget_utilization':
                s=b.one(macro,analysis='online',dataset_id=dataset,model_name=model,capacity_basis=basis,reference='fifo',comparison='paced',metric=metric)
                assert abs(float(s['pooled_difference'])-point)<1e-12
                point,low,high=[float(s[k]) for k in ('common_macro_difference','common_macro_difference_ci_low','common_macro_difference_ci_high')]
                interval(ax,point,low,high,y-.13,'D','black','white');bounds.extend([low,high])
                output.append(dict(panel=metric,dataset_id=dataset,cohort=cohort,model_name=model,capacity_basis=basis,estimand='participant_equal_common_valid',estimate=point,ci_low=low,ci_high=high,units='proportion difference',n_participants=s['n_participants'],n_common_valid=s['n_common_valid'],n_reference_only=s['n_reference_only'],n_comparison_only=s['n_comparison_only'],finite_replicates=s['common_macro_difference_finite_replicates'],source='participant_equal.csv',quantity='common_macro_difference'))
        span=max(bounds)-min(bounds);low=min(0,min(bounds))-.10*span;high=max(0,max(bounds))+.10*span
        ax.set_xlim(low,high)
        ax.set_xticks({'alert_precision':[0,.10,.20], 'alert_coverage':[-.04,-.02,0],
                      'budget_utilization':[-.30,-.20,-.10,0]}[metric])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, position: '0' if abs(value)<1e-12 else f'{value:.2f}'))
    for i,(y,(dataset,cohort,model,label,basis,bl)) in enumerate(zip(ys,cells)):
        axes[0].text(-.08,y,bl,ha='right',va='center',transform=axes[0].get_yaxis_transform(),fontsize=9.5)
        if i%2==0:
            axes[0].text(-.44,y-.5,label,ha='right',va='center',transform=axes[0].get_yaxis_transform(),fontsize=9.5)
    fig.text(.025,.948,'Same-ceiling online comparison: all 12 cohort-model-budget cells',fontsize=10,fontweight='bold')
    fig.text(.20,.875,'Model',fontsize=9.5,va='top',ha='right')
    fig.text(.278,.875,'Budget',fontsize=9.5,va='top',ha='right')
    for y,label in [(9.5,'Development'),(2.95,'External')]:
        # Cohort printed beside a bracket covering the three model pairs.
        yy=.18+.68*((y-.05)/(12.6-.05))
        fig.text(.014,yy,label,rotation=90,va='center',ha='left',fontsize=9.5)
    handles=[Line2D([],[],marker='o',color=style.BLUE,ls='none',label='Pooled',ms=4),Line2D([],[],marker='D',mfc='white',mec='black',ls='none',label='Participant-equal (common valid)',ms=4)]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.055),frameon=False,ncol=2,columnspacing=1.2,handletextpad=.4)
    fig.text(.54,.116,'Pacing - FIFO (proportion difference)',ha='center',fontsize=10)
    fig.text(.025,.018,'Saved paired 95% participant-bootstrap intervals; utilization is pooled (saved intervals).',fontsize=9.5)
    assert len(output)==60
    b.write_csv(b.DATA/'fig5_plot_data.csv',output)
    for source in ('online_intervals.csv','online_estimates.csv'):
        b.evidence(5,'a/b/c','data/input/'+source,{'quantity':'delta_paced_minus_fifo__{alert_precision,alert_coverage,budget_utilization}','cells':'2 cohorts x 3 models x 2 budgets'},'Use all 12 stored pooled contrasts and paired intervals per metric in their native proportion-difference units, without rescaling; validate against paced-minus-fifo saved points. No new bootstrap.','saved paired statistical estimates')
    b.evidence(5,'a/b','data/input/participant_equal.csv',{'analysis':'online','reference':'fifo','comparison':'paced','metric':['alert_precision','alert_coverage'],'estimand':'common_macro_difference'},'Use all 24 common-valid participant-equal paired contrasts and saved intervals in their native proportion-difference units, without rescaling or a new bootstrap. Preserve valid-denominator fields in export.','saved paired participant-equal estimates')
    return style.save(fig,5,'online_tradeoffs')
