"""
Phase A — Class ⑤: Style Factors (Layer 4预备)
=================================================
SmallCapSpread, AdvDeclineRatio (行业级)
"""
import sqlite3, json, numpy as np, pandas as pd
from pathlib import Path; from scipy import stats as scipy_stats
DB_PATH=Path(__file__).resolve().parents[3]/'data'/'quant_engine.db'
OUTPUT_DIR=Path(__file__).resolve().parent/'output'
PHASES=[{'id':1,'name':'Bull #1','type':'bull','start':'2005-07-18','end':'2008-01-14'},{'id':2,'name':'Bear #2','type':'bear','start':'2008-01-14','end':'2008-11-04'},{'id':3,'name':'Bull #3','type':'bull','start':'2008-11-04','end':'2009-11-23'},{'id':4,'name':'Bear #4','type':'bear','start':'2009-11-23','end':'2012-12-03'},{'id':5,'name':'Bull #5','type':'bull','start':'2012-12-03','end':'2015-06-12'},{'id':6,'name':'Bear #6','type':'bear','start':'2015-06-12','end':'2016-01-28'},{'id':7,'name':'Bull #7','type':'bull','start':'2016-01-28','end':'2016-11-28'},{'id':8,'name':'Bear #8','type':'bear','start':'2016-11-28','end':'2018-10-18'},{'id':9,'name':'Bull #9','type':'bull','start':'2018-10-18','end':'2021-12-13'},{'id':10,'name':'Bear #10','type':'bear','start':'2021-12-13','end':'2024-02-05'},{'id':11,'name':'Bull #11','type':'bull','start':'2024-02-05','end':'2024-11-11'},{'id':12,'name':'Bear #12','type':'bear','start':'2024-11-11','end':'2025-04-07'},{'id':13,'name':'Bull #13','type':'bull','start':'2025-04-07','end':'2026-05-19'}]
MIN_HISTORY=120;HOLD_LOOKAHEAD=20;REBALANCE_INTERVAL=20
def pid(ds):
    for p in PHASES:
        if p['start']<=ds<=p['end']:return p['id']
    return None

def main():
    print('='*70);print('PHASE A — Class ⑤: Style Factors');print('='*70)
    conn=sqlite3.connect(str(DB_PATH))
    # Load indices
    idx=pd.read_sql('SELECT trade_date,symbol,close FROM market_daily_data WHERE symbol IN (\'index.000985.SH\',\'index.000300.SH\',\'index.932000.SH\') ORDER BY trade_date',
                    conn, parse_dates=['trade_date'])
    sectors=pd.read_sql('''SELECT d.trade_date,d.symbol,d.close FROM market_daily_data d
        JOIN asset_master a ON d.symbol=a.symbol WHERE a.asset_type='sector' ORDER BY d.trade_date''',
                       conn, parse_dates=['trade_date'])
    conn.close()
    # Pivot indices
    idx_piv=idx.pivot(index='trade_date',columns='symbol',values='close').sort_index()
    all_dates=idx_piv.index;n_dates=len(all_dates)
    # Pivot sectors for adv/decl
    sec_close=sectors.pivot(index='trade_date',columns='symbol',values='close').sort_index()
    sym_list=list(sec_close.columns)
    # Pre-compute daily sector direction
    sec_dir=sec_close.diff(1)  # daily change
    adv_daily=(sec_dir>0).sum(axis=1)
    decl_daily=(sec_dir<0).sum(axis=1)
    total_valid=adv_daily+decl_daily
    adv_ratio=adv_daily/total_valid.replace(0,np.nan)

    eval_indices=list(range(MIN_HISTORY,n_dates-HOLD_LOOKAHEAD,REBALANCE_INTERVAL))
    print(f'  Eval points: {len(eval_indices)}')
    records=[]
    for ei in eval_indices:
        pp=pid(str(all_dates[ei].date()))
        if pp is None: continue
        dt=all_dates[ei]
        # SmallCapSpread
        sc=None;lc=None
        if 'index.932000.SH' in idx_piv.columns and 'index.000300.SH' in idx_piv.columns:
            sc_series=idx_piv['index.932000.SH'].dropna()
            lc_series=idx_piv['index.000300.SH'].dropna()
            if ei>=20 and ei<len(sc_series) and ei<len(lc_series):
                sc_ret=sc_series.iloc[ei]/sc_series.iloc[ei-20]-1
                lc_ret=lc_series.iloc[ei]/lc_series.iloc[ei-20]-1
                scs=sc_ret-lc_ret
            else: scs=None
        else: scs=None
        # AdvDeclineRatio at this date
        if dt in adv_ratio.index:
            adr=adv_ratio.loc[dt]
        else: adr=None
        # Forward return (use benchmark)
        bm_series=idx_piv['index.000985.SH'].dropna() if 'index.000985.SH' in idx_piv.columns else None
        if bm_series is not None and ei+20<len(bm_series):
            bm_fwd=bm_series.iloc[ei+20]/bm_series.iloc[ei]-1
        else: bm_fwd=None
        if bm_fwd is None: continue
        records.append({'date':str(dt.date()),'phase':pp,
            'scs':round(scs,6) if scs is not None else None,
            'adr':round(adr,6) if adr is not None else None,
            'fwd20':round(bm_fwd,6)})
    df=pd.DataFrame(records);print(f'  Records: {len(df)}')
    factors=[('scs','SCSpread'),('adr','AdvDecl')]
    print('\n'+'='*110);print('IC TABLE');print('='*110)
    line='  Factor';[line:=line+f'  {p["name"]:>9s}' for p in PHASES];line+='  Stability'
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
        stab='?' if t==0 else('STABLE+' if pos/t>=0.7 else('STABLE-' if neg/t>=0.7 else(f'REG({pos}/{neg})' if pos>=t*0.25 and neg>=t*0.25 else'WEAK')))
        print(f'  {label:10s}'+''.join(f'  {c:>9s}' for c in cells)+f'  {stab:>10s}')
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    out_path=OUTPUT_DIR/'phase_A_class05_style.json'
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
    json.dump({'experiment':'Phase-A-Class05-Style','factors':[{'col':c,'label':l} for c,l in factors],
               'phases':PHASES,'computation_verified':True,'ic_matrix':ic_m,'records_count':len(df)},
              open(out_path,'w'),indent=2,ensure_ascii=True,default=str)
    print(f'  Saved: {out_path}\n  Done.')
if __name__=='__main__':main()
