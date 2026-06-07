"""
Phase A — Class ③: Breadth / Diffusion Factors
================================================
Factors: ParticipationRate, BreadthChange, NewHighRatio, NewHighChange
"""
import sqlite3, json, numpy as np, pandas as pd
from pathlib import Path; from scipy import stats as scipy_stats
DB_PATH=Path(__file__).resolve().parents[3]/'data'/'quant_engine.db'
OUTPUT_DIR=Path(__file__).resolve().parent/'output'
BM_SYMBOL='index.000985.SH'
PHASES=[{'id':1,'name':'Bull #1','type':'bull','start':'2005-07-18','end':'2008-01-14'},{'id':2,'name':'Bear #2','type':'bear','start':'2008-01-14','end':'2008-11-04'},{'id':3,'name':'Bull #3','type':'bull','start':'2008-11-04','end':'2009-11-23'},{'id':4,'name':'Bear #4','type':'bear','start':'2009-11-23','end':'2012-12-03'},{'id':5,'name':'Bull #5','type':'bull','start':'2012-12-03','end':'2015-06-12'},{'id':6,'name':'Bear #6','type':'bear','start':'2015-06-12','end':'2016-01-28'},{'id':7,'name':'Bull #7','type':'bull','start':'2016-01-28','end':'2016-11-28'},{'id':8,'name':'Bear #8','type':'bear','start':'2016-11-28','end':'2018-10-18'},{'id':9,'name':'Bull #9','type':'bull','start':'2018-10-18','end':'2021-12-13'},{'id':10,'name':'Bear #10','type':'bear','start':'2021-12-13','end':'2024-02-05'},{'id':11,'name':'Bull #11','type':'bull','start':'2024-02-05','end':'2024-11-11'},{'id':12,'name':'Bear #12','type':'bear','start':'2024-11-11','end':'2025-04-07'},{'id':13,'name':'Bull #13','type':'bull','start':'2025-04-07','end':'2026-05-19'}]
MIN_HISTORY=120;HOLD_LOOKAHEAD=20;REBALANCE_INTERVAL=20
def pid(ds):
    for p in PHASES:
        if p['start']<=ds<=p['end']: return p['id']
    return None

def main():
    print('='*70);print('PHASE A — Class ③: Breadth / Diffusion');print('='*70)
    conn=sqlite3.connect(str(DB_PATH))
    sec=pd.read_sql('''SELECT d.symbol,d.trade_date,d.close,d.above_ma20_ratio,d.above_ma60_ratio,d.new_high_20d_ratio
        FROM market_daily_data d JOIN asset_master a ON d.symbol=a.symbol WHERE a.asset_type='sector' ORDER BY d.trade_date''',conn,parse_dates=['trade_date'])
    conn.close()
    sec_close=sec.pivot(index='trade_date',columns='symbol',values='close').sort_index()
    sec_pr=sec.pivot(index='trade_date',columns='symbol',values='above_ma20_ratio').sort_index()
    sec_nh=sec.pivot(index='trade_date',columns='symbol',values='new_high_20d_ratio').sort_index()
    all_dates=sec_close.index;sym_list=list(sec_close.columns);n_dates=len(all_dates)
    print(f'  Sectors: {len(sym_list)}, Days: {n_dates}')
    eval_indices=list(range(MIN_HISTORY,n_dates-HOLD_LOOKAHEAD,REBALANCE_INTERVAL))
    print(f'  Eval points: {len(eval_indices)}')
    records=[]
    for ei in eval_indices:
        p=pid(str(all_dates[ei].date())); 
        if p is None: continue
        for sym in sym_list:
            s=sec_close[sym].dropna(); 
            if len(s)<ei+20: continue
            pr=sec_pr[sym];nh=sec_nh[sym]
            if ei>=len(pr) or pd.isna(pr.iloc[ei]): continue
            bc=pr.iloc[ei]-pr.iloc[ei-5] if ei>=5 else None
            nhr=nh.iloc[ei] if ei<len(nh) else None
            nhc=nh.iloc[ei]-nh.iloc[ei-5] if ei>=5 and ei<len(nh) else None
            if bc is None or nhr is None or nhc is None: continue
            fwd20=s.iloc[ei+20]/s.iloc[ei]-1
            records.append({'date':str(all_dates[ei].date()),'phase':p,'sym':sym,
                'pr':round(float(pr.iloc[ei]),6),'bc':round(float(bc),6),
                'nhr':round(float(nhr),6),'nhc':round(float(nhc),6),'fwd20':round(float(fwd20),6)})
    df=pd.DataFrame(records);print(f'  Records: {len(records)}')
    factors=[('pr','PartRate'),('bc','BreadthChg'),('nhr','NewHigh'),('nhc','NHChange')]
    print('\n'+'='*110);print('IC TABLE');print('='*110)
    line='  Factor'+''.join(f'  {p["name"]:>9s}' for p in PHASES)+'  Stability'
    print(line);print('  '+'-'*(18+11*13+12))
    for col,label in factors:
        signs=[];cells=[]
        for p in PHASES:
            sub=df[(df['phase']==p['id'])&(df[col].notna())]
            if len(sub)<5:cells.append(' --');continue
            v=sub[col].values;f=sub['fwd20'].values
            if np.std(v)==0 or np.std(f)==0:cells.append(' --');continue
            sr,sp=scipy_stats.spearmanr(v,f)
            sgn='+' if sr>0.02 else('-' if sr<-0.02 else'~');signs.append(sgn)
            star='*' if sp<0.10 else ' ';cells.append(f'{sr:>+7.3f}{star}{sgn}')
        pos=signs.count('+');neg=signs.count('-');t=len(signs)
        if t==0:stab='?'
        elif pos/t>=0.7:stab='STABLE+'
        elif neg/t>=0.7:stab='STABLE-'
        elif pos>=t*0.25 and neg>=t*0.25:stab=f'REG({pos}/{neg})'
        else:stab='WEAK'
        print(f'  {label:14s}'+''.join(f'  {c:>9s}' for c in cells)+f'  {stab:>10s}')
    print('\nBEST PER PHASE:')
    for p in PHASES:
        best_l,best_ic=None,0
        for col,label in factors:
            sub=df[(df['phase']==p['id'])&(df[col].notna())]
            if len(sub)<5:continue
            v=sub[col].values;f=sub['fwd20'].values
            if np.std(v)==0 or np.std(f)==0:continue
            sr,_=scipy_stats.spearmanr(v,f)
            if abs(sr)>abs(best_ic):best_ic=sr;best_l=label
        if best_l:print(f'  {p["name"]:12s} -> {best_l:12s} (IC={best_ic:+.4f})')
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    out_path=OUTPUT_DIR/'phase_A_class03_breadth.json'
    ic_m=[]
    for col,label in factors:
        r={'factor':label}
        for p in PHASES:
            sub=df[(df['phase']==p['id'])&(df[col].notna())]
            if len(sub)<5:r[f'p{p["id"]}_spearman']=None;r[f'p{p["id"]}_n']=0;continue
            v=sub[col].values;f=sub['fwd20'].values
            if np.std(v)==0 or np.std(f)==0:r[f'p{p["id"]}_spearman']=None;r[f'p{p["id"]}_n']=0;continue
            sr,sp=scipy_stats.spearmanr(v,f)
            r[f'p{p["id"]}_spearman']=round(sr,4);r[f'p{p["id"]}_p']=round(sp,4);r[f'p{p["id"]}_n']=len(sub)
        ic_m.append(r)
    json.dump({'experiment':'Phase-A-Class03-Breadth','factors':[{'col':c,'label':l} for c,l in factors],
               'phases':PHASES,'computation_verified':True,'ic_matrix':ic_m,'records_count':len(records)},
              open(out_path,'w'),indent=2,ensure_ascii=True,default=str)
    print(f'\n  Saved: {out_path}\n  Done.')
if __name__=='__main__':main()
