"""Lifecycle schematics and complete saved checkpoint/application outcomes.

Run from any working directory: python build_main_figures.py --out rebuilt
Requires Matplotlib; inputs are resolved relative to this script, never network.
"""
from pathlib import Path
import argparse,csv,hashlib,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle,FancyArrowPatch

HERE=Path(__file__).resolve().parent
P=HERE.parent
INK='#263640';TEAL='#176B70';GREY='#677078';AMBER='#896129'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9.5,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','svg.hashsalt':'ecrc-story-20260912'})
texts=[];cards=[]
def canvas(h):
    f=plt.figure(figsize=(6.5,h));a=f.add_axes([0,0,1,1]);a.set(xlim=(0,6.5),ylim=(0,h));a.axis('off');return f,a
def text(a,x,y,s,size=9.5,bold=False,color=INK,ha='center'):
    t=a.text(x,y,s,ha=ha,va='center',fontsize=size,fontweight='bold' if bold else 'normal',color=color,linespacing=1.23);texts.append(t);return t
def rect(a,x,y,w,h,edge=INK,fill='white',dashed=False,lw=.8):
    r=Rectangle((x,y),w,h,linewidth=lw,edgecolor=edge,facecolor=fill,linestyle=(0,(4,3)) if dashed else '-');a.add_patch(r);return r
def card(a,x,y,w,h,title,body='',fill='white',edge=INK,ts=10,bs=9.1):
    r=rect(a,x,y,w,h,edge,fill)
    tt=[text(a,x+w/2,y+h-.17,title,ts,True,edge)]
    if body:tt.append(text(a,x+w/2,y+(h-.28)/2,body,bs))
    cards.append((r,tt));return r
def arrow(a,ps,color=INK,dashed=False):
    if len(ps)>2:
        xs,ys=zip(*ps[:-1]);a.plot(xs,ys,color=color,lw=.95,ls=(0,(3,2)) if dashed else '-')
    a.add_patch(FancyArrowPatch(ps[-2],ps[-1],arrowstyle='-|>',mutation_scale=9,linewidth=.95,color=color,linestyle=(0,(3,2)) if dashed else '-',shrinkA=0,shrinkB=0))
def save(f,out,n):
    f.canvas.draw();r=f.canvas.get_renderer()
    for t in texts:
        if t.figure is f:
            b=t.get_window_extent(r);assert f.bbox.contains(b.x0,b.y0) and f.bbox.contains(b.x1,b.y1),t.get_text()
    for box,tt in cards:
        if box.figure is f:
            b=box.get_window_extent(r)
            for t in tt:
                z=t.get_window_extent(r);assert b.contains(z.x0,z.y0) and b.contains(z.x1,z.y1),t.get_text()
    for ext in ['pdf','svg','png']:
        args={'dpi':240} if ext=='png' else {}
        if ext=='pdf':args['metadata']={'CreationDate':None,'ModDate':None,'Creator':'Local vector plotting from specification or archived S9 cells'}
        if ext=='svg':args['metadata']={'Date':None}
        f.savefig(out/f'fig{n}.{ext}',**args)
    plt.close(f)
def fig1(out):
    f,a=canvas(2.65);rect(a,.07,.07,6.36,2.51,GREY,dashed=True)
    xs=[.20,1.79,3.38,4.97];w=1.33
    for y,head,col,items in [
      (1.52,'(a) Release on timeout','#923E2C',[('Unknown A','1 held / 1 effect'),('Release unit','0 held / 1 effect'),('Admit B','One more effect'),('Budget exceeded','2 effects / 1 unit')]),
      (.34,'(b) Retain until reconciled',TEAL,[('Unknown A','1 held / 1 effect'),('Retain unit','B not admitted'),('Reconcile A','Held → committed'),('Budget preserved','1 effect / 1 unit')])]:
        text(a,.20,y+.84,head,10,True,col,ha='left')
        for x,(title,body) in zip(xs,items):card(a,x,y,w,.60,title,body,fill='white',edge=col,ts=9.1,bs=8.8)
        for x,z in zip(xs,xs[1:]):arrow(a,[(x+w+.025,y+.30),(z-.03,y+.30)],col)
    save(f,out,1)
def fig2(out):
    f,a=canvas(4.87)
    # Dashed outer frame groups the schematic, never a distributed transaction.
    rect(a,.07,.07,6.36,4.72,GREY,dashed=True,lw=.9)
    rect(a,.20,.22,3.97,4.40,edge='#CFD5D9',fill='#F5F7F8',lw=.6)
    rect(a,4.38,.22,1.92,4.40,edge='#BBD3D3',fill='#F1F8F8',lw=.6)
    text(a,.38,4.43,'Client: authority + ledger',10.3,True,ha='left')
    text(a,5.34,4.43,'Independent service',10.0,True,TEAL)
    rect(a,.42,3.89,1.99,.34,edge=GREY)
    text(a,1.415,4.06,'Raw request journal',9.1)
    arrow(a,[(1.415,3.89),(1.415,3.61)])
    card(a,.42,3.01,1.99,.60,'1  Issue permit','Permit + unit + registry',ts=10,bs=9.0)
    arrow(a,[(1.415,3.01),(1.415,2.61)])
    text(a,1.56,2.81,'valid permit',8.8,ha='left')
    # Expiry branch is attached to issuance, before the irrevocable arm.
    arrow(a,[(2.41,3.30),(2.80,3.30)],GREY)
    text(a,2.63,3.76,'expired,\nunarmed',8.6,color=GREY)
    card(a,2.80,3.01,1.14,.60,'Cancel','Release unit',edge=GREY,ts=9.7,bs=9.1)
    text(a,3.37,2.83,'No later dispatch',8.3,color=GREY)
    card(a,.42,1.96,1.99,.65,'2  Authorize (arm)','Irrevocable grant + intent',ts=10,bs=8.9)
    arrow(a,[(2.41,2.28),(4.60,2.28)])
    text(a,3.47,2.50,'Execute / retry\nsame key + payload',9.0)
    # Existing keys retrieve the original result; retries do not first act again.
    card(a,4.60,1.13,1.49,1.61,'3  Create / retrieve','New key:\neffect + dedup record\n\nExisting key:\nstored result',edge=TEAL,ts=9.2,bs=8.8)
    arrow(a,[(5.345,1.13),(5.345,.80),(2.41,.80)],TEAL)
    text(a,3.45,.58,'Effect-backed ACK',9.0,color=TEAL)
    card(a,.42,.40,1.99,.80,'4  Reconcile ACK','Receipt + completion\nheld → committed',ts=10,bs=9.0)
    # Recovery retains responsibility; the path rejoins the same dispatch route.
    card(a,2.75,1.28,1.24,.52,'No ACK','Keep unit held',edge=AMBER,fill='#FFFCF4',ts=9.4,bs=9.0)
    arrow(a,[(2.20,1.96),(2.20,1.56),(2.75,1.56)],AMBER,True)
    arrow(a,[(3.99,1.56),(4.13,1.56),(4.13,2.28)],AMBER,True)
    save(f,out,2)
def fig3(out):
    src=P/'data/fig3_plot_data.csv'
    rows=list(csv.DictReader(src.open(encoding='utf-8')))
    assert len(rows)==36 and all(int(r['n_observations'])==6 and r['min']==r['max']==r['display'] for r in rows)
    by={(r['scenario'],r['phase'],r['metric']):int(r['display']) for r in rows}
    panels=[('expired_unarmed_cleanup','(a) Expiry before authorization',[
      ('issued_unarmed_before_expiry','Permit\nissued'),('expired_unarmed_cancelled','Expiry +\ncancel'),('cancelled_replay_no_dispatch','Retry:\nno dispatch'),('released_budget_reused','Budget\nreused'),('final','Final')]),
      ('accepted_timeout_cleanup_recovery','(b) Timeout after effect commit',[
      ('sink_committed_client_timed_out','Effect stored;\nno ACK'),('cleanup_retained_unknown_grant','Cleanup:\nretain unit'),('after_unknown_recovery_competition','Recovery +\ncompetition'),('final','Final')])]
    metrics=[('held','Held units'),('committed','Committed units'),('effects','Service effects'),('receipts','Local receipts')]
    f,a=canvas(3.95)
    for (scenario,title,phases),top in zip(panels,[3.80,1.85]):
        text(a,.10,top,title,10,True,ha='left')
        x0=1.48;w=(6.35-x0)/len(phases)
        for j,(phase,label) in enumerate(phases):
            x=x0+j*w;text(a,x+w/2,top-.36,label,8.7)
            for i,(metric,mlabel) in enumerate(metrics):
                y=top-.72-i*.30;v=by[scenario,phase,metric]
                rect(a,x+.025,y-.125,w-.05,.25,edge='#CBD3D8',fill={0:'#FFFFFF',1:'#E2EEF0',2:'#B8D5D7'}[v],lw=.6)
                text(a,x+w/2,y,str(v),9.3)
        for i,(metric,label) in enumerate(metrics):text(a,1.36,top-.72-i*.30,label,9.0,ha='right')
    save(f,out,3)
    (out/'fig3_SOURCE.json').write_text(json.dumps({'source':'data/fig3_plot_data.csv','source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'rows':36,'filter':'none','observations_per_cell':6,'values_changed':False,'phase_labels':{s:{p:l.replace('\n',' ') for p,l in ph} for s,t,ph in panels}},indent=2)+'\n')

def fig4(out):
    src=P/'data/S9_cells.csv'
    rows=list(csv.DictReader(src.open(encoding='utf-8')))
    assert len(rows)==8 and all(int(x['batches'])==18 and int(x['eligible_tasks'])==144 for x in rows)
    by={(x['condition'],x['policy'],x['arm']):x for x in rows}
    plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False})
    f,axs=plt.subplots(1,2,figsize=(6.5,2.90),sharey=True)
    colors={'ecrc':TEAL,'ordinary':'#767F86'}
    for ax,cond,panel in zip(axs,['normal','response_loss'],['(a) Normal response','(b) Response loss']):
        for i,arm in enumerate(['ecrc','ordinary']):
            xx=[j+(i-.5)*.32 for j in [0,1]]
            vals=[int(by[cond,policy,arm]['timely_tasks']) for policy in ['depth_first','round_robin']]
            bars=ax.bar(xx,vals,width=.29,color=colors[arm],label='ECRC' if arm=='ecrc' else 'Ordinary',zorder=3)
            for bar,v in zip(bars,vals):ax.text(bar.get_x()+bar.get_width()/2,v+2,str(v),ha='center',va='bottom',fontsize=9)
        ax.set_xticks([0,1],['Depth-first','Round-robin']);ax.set_ylim(0,144);ax.set_yticks([0,36,72,108,144]);ax.grid(axis='y',color='#E4E7EA',lw=.6,zorder=0)
        ax.text(0,1.09,panel,transform=ax.transAxes,ha='left',fontsize=10)
        ax.tick_params(labelsize=9)
    axs[0].set_ylabel('Tasks with timely pass feedback\n(out of 144)',fontsize=9.5)
    axs[1].legend(loc='upper right',frameon=False,ncols=2,fontsize=8.3,handlelength=1,columnspacing=.9)
    f.subplots_adjust(left=.14,right=.985,bottom=.20,top=.85,wspace=.17)
    save(f,out,4)
    (out/'fig4_SOURCE.json').write_text(json.dumps({'source':'data/S9_cells.csv','source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
        'rows':8,'filter':'none','value':'timely_tasks','denominator':144,'intervals':'none; descriptive counts','new_experiments':False},indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=P/'exports');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    fig1(a.out);fig2(a.out);fig3(a.out);fig4(a.out)
    print(json.dumps({'outputs':[{ 'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(a.out.glob('fig*.pdf'))]},indent=2))
