"""Plot only the complete, audited S9 cell table; no synthetic observations."""
from pathlib import Path
import argparse,csv,sys

ROOT=Path(__file__).resolve().parents[2]
deps=ROOT/'qa/iasc_conversion_2026-09-11/python_deps'
if deps.exists():sys.path.insert(0,str(deps))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--cells',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader(a.cells.open(encoding='utf-8')))
    assert len(rows)==8 and all(int(r['batches'])==18 and int(r['eligible_tasks'])==144 for r in rows)
    by={(r['condition'],r['policy'],r['arm']):r for r in rows}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
        'axes.labelcolor':'#27333c','text.color':'#27333c','axes.edgecolor':'#71808a','pdf.fonttype':42,'ps.fonttype':42})
    fig,axes=plt.subplots(1,2,figsize=(10.5,4.5),sharey=True)
    colors={'ecrc':'#315d82','ordinary':'#91999e'}
    for ax,condition,title in zip(axes,['normal','response_loss'],['A  Normal response','B  Post-commit response loss']):
        xs=np.arange(2);width=.34
        for i,arm in enumerate(['ecrc','ordinary']):
            values=[100*int(by[condition,policy,arm]['timely_tasks'])/144 for policy in ['depth_first','round_robin']]
            bars=ax.bar(xs+(i-.5)*width,values,width,color=colors[arm],label='ECRC' if arm=='ecrc' else 'Ordinary',zorder=3)
            for bar,policy in zip(bars,['depth_first','round_robin']):
                count=int(by[condition,policy,arm]['timely_tasks'])
                ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+1.3,f'{count}/144',ha='center',va='bottom',fontsize=9)
        ax.set_xticks(xs,['Depth-first','Round-robin']);ax.set_title(title,loc='left',fontsize=12,pad=12)
        ax.set_ylim(0,100);ax.set_yticks([0,25,50,75,100]);ax.grid(axis='y',color='#e7ebee',zorder=0)
    axes[0].set_ylabel('Tasks with suite-pass feedback by 5 s (%)')
    axes[1].legend(frameon=False,loc='upper right',ncols=2,fontsize=9)
    fig.subplots_adjust(left=.075,right=.99,top=.86,bottom=.22,wspace=.16)
    fig.text(.075,.075,'18 fixed batches × 8 tasks per cell · 16 verification units per batch\nAll tasks included; descriptive observed counts, without inferential error bars.',fontsize=9,color='#53616b')
    fig.savefig(a.out/'S9_application_results.pdf',metadata={'Title':'Observed application verification results','Creator':'Matplotlib; complete S9 cell CSV'})
    fig.savefig(a.out/'S9_application_results.png',dpi=180)
    plt.close(fig)

if __name__=='__main__':main()
