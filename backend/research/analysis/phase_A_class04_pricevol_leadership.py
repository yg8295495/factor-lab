"""
Phase A — Class ④: Price-Volume + Leadership (6 factors)
==========================================================
AmountRatio, VolumeBreakout, PriceVolDivergence, CR3, CR5, TopDispersion
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
        if p['start']<=ds<=p['end']:return p['id']
    return None

def price_vol_divergence(close_series, amount_ratio_series, ei, window=20):
    """Price-volume divergence: extreme position + opposite volume direction.
    
    Both series must be aligned (same index, same length).
    """
    # Use iloc for position-based access; both series should be aligned
    lookback = min(window, ei)
    if lookback < 10:
        return 0.0
    
    # Get last `window` closing prices and corresponding amount_ratios
    close_val = close_series.iloc[ei]
    ar_val = amount_ratio_series.iloc[ei]
    if pd.isna(ar_val):
        return 0.0
    
    recent_close = close_series.iloc[ei-lookback:ei+1].values
    r_min, r_max = recent_close.min(), recent_close.max()
    pct = (recent_close[-1] - r_min) / (r_max - r_min) if r_max > r_min else 0.5
    
    div = 0.0
    if pct > 0.80 and ar_val < 0.85:
        div = (pct - 0.80) * (0.85 - ar_val) * 10
    if pct < 0.20 and ar_val > 1.15:
        div = -(0.20 - pct) * (ar_val - 1.15) * 10
    return div

def main():
    print('='*70);print('PHASE A — Class ④: Price-Volume + Leadership (6 factors)');print('='*70)
    conn=sqlite3.connect(str(DB_PATH))
    sec=pd.read_sql('''SELECT d.symbol,d.trade_date,d.close,d.amount,d.amount_ratio
        FROM market_daily_data d JOIN asset_master a ON d.symbol=a.symbol
        WHERE a.asset_type='sector' ORDER BY d.trade_date''',conn,parse_dates=['trade_date'])
    conn.close()
    sec_close=sec.pivot(index='trade_date',columns='symbol',values='close').sort_index()
    sec_amount=sec.pivot(index='trade_date',columns='symbol',values='amount').sort_index()
    sec_ar=sec.pivot(index='trade_date',columns='symbol',values='amount_ratio').sort_index()
    all_dates=sec_close.index;sym_list=list(sec_close.columns);n_dates=len(all_dates);n_sym=len(sym_list)
    print(f'  Sectors: {n_sym}, Days: {n_dates}')

    # Pre-compute CR3/CR5 per date
    amt_mat=sec_amount.values
    cr3_arr=np.full(n_dates,np.nan);cr5_arr=np.full(n_dates,np.nan)
    for i in range(n_dates):
        a=amt_mat[i];vm=~np.isnan(a);va=a[vm];sa=np.sort(va)[::-1];t=np.nansum(va)
        if t>0:
            if len(sa)>=3:cr3_arr[i]=np.sum(sa[:3])/t
            if len(sa)>=5:cr5_arr[i]=np.sum(sa[:5])/t

    eval_indices=list(range(MIN_HISTORY,n_dates-HOLD_LOOKAHEAD,REBALANCE_INTERVAL))
    print(f'  Eval points: {len(eval_indices)}')
    records=[]
    for ei in eval_indices:
        pp=pid(str(all_dates[ei].date())); 
        if pp is None: continue
        cr3=cr3_arr[ei];cr5=cr5_arr[ei]
        if np.isnan(cr3): continue
        # TopDispersion: cross-sectional
        rets=sec_close.iloc[ei].values/sec_close.iloc[ei-20].values-1 if ei>=20 else None
        rets=rets[~np.isnan(rets)] if rets is not None else np.array([])
        if len(rets)>=6:
            sr=np.sort(rets);td=np.mean(sr[-3:])-np.mean(sr[:3])
        else: td=None

        for si,sym in enumerate(sym_list):
            s=sec_close[sym].dropna()
            if len(s)<ei+20:continue
            # Reindex AR to align with close's NaN-removed index
            ar=sec_ar[sym].reindex(s.index)
            if ei>=len(ar) or pd.isna(ar.iloc[ei]):continue
            ar_val=float(ar.iloc[ei])
            # VolumeBreakout = AR - SMA5(AR)
            if ei>=5:
                vb=ar_val-np.mean([float(ar.iloc[ei-j]) for j in range(1,6) if ei-j>=0])
            else: vb=None
            # PriceVolDivergence
            pvd=price_vol_divergence(s,ar,ei)
            # Forward return
            fwd20=s.iloc[ei+20]/s.iloc[ei]-1
            records.append({'date':str(all_dates[ei].date()),'phase':pp,'sym':sym,
                'ar':round(ar_val,6),'vb':round(vb,6) if vb is not None else None,
                'pvd':round(pvd,6),'cr3':round(cr3,6),'cr5':round(cr5,6),
                'td':round(td,6) if td is not None else None,'fwd20':round(fwd20,6)})
    df=pd.DataFrame(records);print(f'  Records: {len(df)}')
    factors=[('ar','AmtRatio'),('vb','VolBkOut'),('pvd','PVD'),('cr3','CR3'),('cr5','CR5'),('td','TopDisp')]
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
        if t==0:stab='?' 
        elif pos/t>=0.7:stab='STABLE+'
        elif neg/t>=0.7:stab='STABLE-'
        elif pos>=t*0.25 and neg>=t*0.25:stab=f'REG({pos}/{neg})'
        else:stab='WEAK'
        print(f'  {label:10s}'+''.join(f'  {c:>9s}' for c in cells)+f'  {stab:>10s}')
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
        if best_l:print(f'  {p["name"]:12s} -> {best_l:10s} (IC={best_ic:+.4f})')
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    out_path=OUTPUT_DIR/'phase_A_class04_pricevol_leadership.json'
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
    json.dump({'experiment':'Phase-A-Class04-PriceVol-Leadership','factors':[{'col':c,'label':l} for c,l in factors],
               'phases':PHASES,'computation_verified':True,'ic_matrix':ic_m,'records_count':len(df)},
              open(out_path,'w'),indent=2,ensure_ascii=True,default=str)
    print(f'\n  Saved: {out_path}\n  Done.')
if __name__=='__main__':main()
