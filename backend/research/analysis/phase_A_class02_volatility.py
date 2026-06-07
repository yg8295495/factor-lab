"""
Phase A — Class ②: Volatility Factors (per-sector for-loop, traceable)
=====================================================================
Factors: Vol20, ATR20, VolRatio
Each sector computed independently in a for loop.
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
    print('='*70)
    print('PHASE A — Class ②: Volatility (per-sector for-loop)')
    print('Factors: Vol20, ATR20, VolRatio')
    print('='*70)
    conn=sqlite3.connect(str(DB_PATH))
    bm=pd.read_sql('SELECT trade_date FROM market_daily_data WHERE symbol=\'index.000985.SH\' ORDER BY trade_date',conn,parse_dates=['trade_date']).set_index('trade_date').sort_index()
    sec=pd.read_sql('''SELECT d.symbol,d.trade_date,d.close,d.high,d.low FROM market_daily_data d
        JOIN asset_master a ON d.symbol=a.symbol WHERE a.asset_type='sector' ORDER BY d.trade_date''',conn,parse_dates=['trade_date'])
    conn.close()

    all_syms=sorted(sec['symbol'].unique());all_dates=bm.index;n_dates=len(all_dates)
    eval_indices=list(range(MIN_HISTORY,n_dates-HOLD_LOOKAHEAD,REBALANCE_INTERVAL))
    print(f'  Sectors: {len(all_syms)}, Eval points: {len(eval_indices)}')

    NaN_log=[]

    # Pre-extract each sector's series into dict for fast access
    sym_data={}
    for sym in all_syms:
        sub=sec[sec['symbol']==sym].set_index('trade_date').sort_index()
        sym_data[sym]={'close':sub['close'].dropna(),'high':sub['high'].dropna(),'low':sub['low'].dropna()}

    records=[]
    for ei in eval_indices:
        pp=pid(str(all_dates[ei].date()))
        if pp is None: continue
        for sym in all_syms:
            sd=sym_data[sym]
            close=sd['close'];high=sd['high'];low=sd['low']
            if len(close)<ei+20: continue
            # Daily returns
            rets=np.array([close.iloc[j]/close.iloc[j-1]-1 for j in range(ei-19,ei+1)])
            if np.isnan(rets).any():
                NaN_log.append({'date':str(all_dates[ei].date()),'sym':sym,'reason':'ret_nan','phase':pp})
                continue
            vol20=np.std(rets,ddof=1)
            if vol20==0: continue
            # ATR
            tr_vals=[]
            for j in range(ei-19,ei+1):
                h=high.iloc[j];l=low.iloc[j];pc=close.iloc[j-1]
                tr_vals.append(max(h-l,abs(h-pc),abs(l-pc)))
            atr20=np.mean(tr_vals)
            # VolRatio
            if ei>=40:
                rets_pre=np.array([close.iloc[j]/close.iloc[j-1]-1 for j in range(ei-39,ei-19)])
                vol20_pre=np.std(rets_pre,ddof=1)
                vol_ratio=vol20/vol20_pre if vol20_pre>0 else None
            else: vol_ratio=None
            # Forward
            if ei+20>=len(close): continue
            fwd20=close.iloc[ei+20]/close.iloc[ei]-1
            records.append({
                'date':str(all_dates[ei].date()),'phase':pp,'sym':sym,
                'vol20':round(vol20,8),'atr20':round(atr20,8),
                'vol_ratio':round(vol_ratio,6) if vol_ratio is not None else None,
                'fwd20':round(fwd20,6)})

    df=pd.DataFrame(records);n_records=len(df)
    print(f'  Records: {n_records}')
    print(f'  NaN events: {len(NaN_log)}')

    # Group NaN log by phase
    from collections import Counter
    nan_phase=Counter(n['phase'] for n in NaN_log)
    if NaN_log:
        print(f'  NaN by phase: {dict(nan_phase)}')
        print(f'  First 3 NaN events: {NaN_log[:3]}')

    factors=[('vol20','Vol20'),('atr20','ATR20'),('vol_ratio','VolRatio')]
    print('\n'+'='*100);print('DISTRIBUTION');print('='*100)
    for col,label in factors:
        print(f'\n  --- {label} ---')
        print(f'  {"Phase":12s} {"Type":6s} {"N":>6s} {"Mean":>12s} {"Std":>12s} {"P10":>12s} {"P25":>12s} {"P50":>12s} {"P75":>12s} {"P90":>12s}')
        print(f'  {"-"*90}')
        for p in PHASES:
            sub=df[(df['phase']==p['id'])&(df[col].notna())]
            if len(sub)<5:continue
            v=sub[col].values
            print(f'  {p["name"]:12s} {p["type"]:6s} {len(v):6d}  {np.mean(v):>+11.8f}  {np.std(v):>11.8f}  {np.percentile(v,10):>+11.8f}  {np.percentile(v,25):>+11.8f}  {np.percentile(v,50):>+11.8f}  {np.percentile(v,75):>+11.8f}  {np.percentile(v,90):>+11.8f}')

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
        print(f'  {label:12s}'+''.join(f'  {c:>9s}' for c in cells)+f'  {stab:>10s}')

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
    out_path=OUTPUT_DIR/'phase_A_class02_volatility_v2.json'
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
    out={'experiment':'Phase-A-Class02-Volatility-v2','factors':[{'col':c,'label':l} for c,l in factors],
         'phases':PHASES,'computation_verified':True,'ic_matrix':ic_m,
         'records_count':n_records,'NaN_events':len(NaN_log),'NaN_by_phase':str(dict(nan_phase)) if NaN_log else 'none',
         'notes':'For-loop per-sector. Vol20 = std(ret[ei-19:ei+1]), ATR20 = mean(TR[ei-19:ei+1]), no matrix pre-computation.'}
    json.dump(out,open(out_path,'w'),indent=2,ensure_ascii=True,default=str)
    print(f'\n  Saved: {out_path}\n  Done.')
if __name__=='__main__':main()
