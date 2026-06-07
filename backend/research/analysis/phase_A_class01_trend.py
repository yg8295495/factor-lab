"""
Phase A — Class ①: Trend / Momentum Factors (Corrected)
=========================================================
Factors: RS20(ratio), RS60(ratio), MOM20, MOM60, Acceleration

Classic definitions:
  RS20 = (P(t)/P(t-20)) / (BM(t)/BM(t-20))   — ratio, NOT excess return
  RS60 = (P(t)/P(t-60)) / (BM(t)/BM(t-60))
  MOM20 = P(t)/P(t-20) - 1
  MOM60 = P(t)/P(t-60) - 1
  Acceleration = MOM20(t) - MOM20(t-5)         — unsmoothed
"""

import sqlite3, json, numpy as np, pandas as pd
from pathlib import Path
from scipy import stats as scipy_stats

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
BM_SYMBOL = 'index.000985.SH'

PHASES = [
    {'id': 1, 'name': 'Bull #1', 'type': 'bull', 'start': '2005-07-18', 'end': '2008-01-14'},
    {'id': 2, 'name': 'Bear #2', 'type': 'bear', 'start': '2008-01-14', 'end': '2008-11-04'},
    {'id': 3, 'name': 'Bull #3', 'type': 'bull', 'start': '2008-11-04', 'end': '2009-11-23'},
    {'id': 4, 'name': 'Bear #4', 'type': 'bear', 'start': '2009-11-23', 'end': '2012-12-03'},
    {'id': 5, 'name': 'Bull #5', 'type': 'bull', 'start': '2012-12-03', 'end': '2015-06-12'},
    {'id': 6, 'name': 'Bear #6', 'type': 'bear', 'start': '2015-06-12', 'end': '2016-01-28'},
    {'id': 7, 'name': 'Bull #7', 'type': 'bull', 'start': '2016-01-28', 'end': '2016-11-28'},
    {'id': 8, 'name': 'Bear #8', 'type': 'bear', 'start': '2016-11-28', 'end': '2018-10-18'},
    {'id': 9, 'name': 'Bull #9', 'type': 'bull', 'start': '2018-10-18', 'end': '2021-12-13'},
    {'id': 10, 'name': 'Bear #10', 'type': 'bear', 'start': '2021-12-13', 'end': '2024-02-05'},
    {'id': 11, 'name': 'Bull #11', 'type': 'bull', 'start': '2024-02-05', 'end': '2024-11-11'},
    {'id': 12, 'name': 'Bear #12', 'type': 'bear', 'start': '2024-11-11', 'end': '2025-04-07'},
    {'id': 13, 'name': 'Bull #13', 'type': 'bull', 'start': '2025-04-07', 'end': '2026-05-19'},
]

MIN_HISTORY = 120; HOLD_LOOKAHEAD = 20; REBALANCE_INTERVAL = 20

def phase_id(ds):
    for p in PHASES:
        if p['start'] <= ds <= p['end']:
            return p['id']
    return None

def main():
    print('=' * 70)
    print('PHASE A — Class ①: Trend / Momentum (Corrected)')
    print('Factors: RS20(ratio), RS60(ratio), MOM20, MOM60, Acceleration')
    print('=' * 70)

    conn = sqlite3.connect(str(DB_PATH))
    bm = pd.read_sql('SELECT trade_date, close FROM market_daily_data WHERE symbol=? ORDER BY trade_date',
                      conn, params=(BM_SYMBOL,), parse_dates=['trade_date']).set_index('trade_date').sort_index()
    sec = pd.read_sql('''SELECT d.symbol, d.trade_date, d.close FROM market_daily_data d
                         JOIN asset_master a ON d.symbol=a.symbol
                         WHERE a.asset_type='sector' ORDER BY d.trade_date''',
                      conn, parse_dates=['trade_date'])
    conn.close()

    sec_close = sec.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    all_dates = bm.index; sym_list = list(sec_close.columns)
    n_dates = len(all_dates); bm_close = bm['close']
    print(f'  Benchmark: {n_dates}d, Sectors: {len(sym_list)}')

    eval_indices = list(range(MIN_HISTORY, n_dates - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
    print(f'  Eval points: {len(eval_indices)}')

    records = []
    for ei in eval_indices:
        pid = phase_id(str(all_dates[ei].date()))
        if pid is None: continue
        bm_20 = bm_close.iloc[ei] / bm_close.iloc[ei-20]
        bm_60 = bm_close.iloc[ei] / bm_close.iloc[ei-60]
        if pd.isna(bm_20) or pd.isna(bm_60): continue

        for sym in sym_list:
            s = sec_close[sym].dropna()
            if len(s) < ei + 20: continue
            p0 = s.iloc[ei]; p20 = s.iloc[ei-20]; p60 = s.iloc[ei-60]
            rs20 = (p0 / p20) / bm_20
            rs60 = (p0 / p60) / bm_60
            mom20 = p0 / p20 - 1
            mom60 = p0 / p60 - 1
            accel = mom20 - (s.iloc[ei-5] / s.iloc[ei-25] - 1) if ei >= 25 else None
            fwd20 = s.iloc[ei+20] / p0 - 1
            records.append({
                'date': str(all_dates[ei].date()), 'phase': pid, 'sym': sym,
                'rs20': round(rs20, 6), 'rs60': round(rs60, 6),
                'mom20': round(mom20, 6), 'mom60': round(mom60, 6),
                'accel': round(accel, 6) if accel is not None else None,
                'fwd20': round(fwd20, 6),
            })

    n_records = len(records)
    print(f'  Records: {n_records}')
    df = pd.DataFrame(records)
    factors = [('rs20','RS20'), ('rs60','RS60'), ('mom20','Mom20'), ('mom60','Mom60'), ('accel','Accel')]

    # Distribution
    print('\n' + '=' * 100)
    print('DISTRIBUTION')
    print('=' * 100)
    for col, label in factors:
        print(f'\n  --- {label} ---')
        print(f'  {"Phase":12s} {"Type":6s} {"N":>6s} {"Mean":>10s} {"Std":>10s} {"P10":>10s} {"P25":>10s} {"P50":>10s} {"P75":>10s} {"P90":>10s}')
        print(f'  {"-"*86}')
        for p in PHASES:
            sub = df[(df['phase']==p['id']) & (df[col].notna())]
            if len(sub) < 5: continue
            v = sub[col].values
            print(f'  {p["name"]:12s} {p["type"]:6s} {len(v):6d}  {np.mean(v):>+9.4f}  {np.std(v):>9.4f}  {np.percentile(v,10):>+9.4f}  {np.percentile(v,25):>+9.4f}  {np.percentile(v,50):>+9.4f}  {np.percentile(v,75):>+9.4f}  {np.percentile(v,90):>+9.4f}')

    # IC table
    print('\n' + '=' * 110)
    print('IC TABLE')
    print('=' * 110)
    line = f'  {"Factor":16s}'
    for p in PHASES: line += f'  {p["name"]:>9s}'
    line += f'  {"Stability":>10s}'
    print(line); print('  ' + '-' * (18 + 11*13 + 12))

    for col, label in factors:
        signs = []; cells = []
        for p in PHASES:
            sub = df[(df['phase']==p['id']) & (df[col].notna())]
            if len(sub) < 5: cells.append(' --'); continue
            v = sub[col].values; f = sub['fwd20'].values
            if np.std(v)==0 or np.std(f)==0: cells.append(' --'); continue
            sr, sp = scipy_stats.spearmanr(v, f)
            sgn = '+' if sr>0.02 else ('-' if sr<-0.02 else '~')
            signs.append(sgn)
            star = '*' if sp<0.10 else ' '
            cells.append(f'{sr:>+7.3f}{star}{sgn}')
        pos=signs.count('+'); neg=signs.count('-'); t=len(signs)
        if t==0: stab='?'
        elif pos/t>=0.7: stab='STABLE+'
        elif neg/t>=0.7: stab='STABLE-'
        elif pos>=t*0.25 and neg>=t*0.25: stab=f'REG({pos}/{neg})'
        else: stab='WEAK'
        print(f'  {label:16s}' + ''.join(f'  {c:>9s}' for c in cells) + f'  {stab:>10s}')

    # Per-phase best
    print('\n' + '=' * 70)
    print('BEST FACTOR PER PHASE')
    print('=' * 70)
    for p in PHASES:
        best_l, best_ic = None, 0
        for col, label in factors:
            sub = df[(df['phase']==p['id']) & (df[col].notna())]
            if len(sub)<5: continue
            v=sub[col].values; f=sub['fwd20'].values
            if np.std(v)==0 or np.std(f)==0: continue
            sr,_=scipy_stats.spearmanr(v,f)
            if abs(sr)>abs(best_ic): best_ic=sr; best_l=label
        if best_l: print(f'  {p["name"]:12s} {p["type"]:6s} -> {best_l:12s} (IC={best_ic:+.4f})')

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'phase_A_class01_trend_v2.json'
    ic_m = []
    for col, label in factors:
        r = {'factor': label}
        for p in PHASES:
            sub = df[(df['phase']==p['id']) & (df[col].notna())]
            if len(sub)<5: r[f'p{p["id"]}_spearman']=None; r[f'p{p["id"]}_n']=0; continue
            v=sub[col].values; f=sub['fwd20'].values
            if np.std(v)==0 or np.std(f)==0: r[f'p{p["id"]}_spearman']=None; r[f'p{p["id"]}_n']=0; continue
            sr,sp=scipy_stats.spearmanr(v,f)
            r[f'p{p["id"]}_spearman']=round(sr,4); r[f'p{p["id"]}_p']=round(sp,4); r[f'p{p["id"]}_n']=len(sub)
        ic_m.append(r)
    json.dump({'experiment':'Phase-A-Class01-Trend-v2','factors':[{'col':c,'label':l} for c,l in factors],
               'phases':PHASES,'computation_verified':False,'ic_matrix':ic_m,'records_count':n_records},
              open(out_path,'w'), indent=2, ensure_ascii=True, default=str)
    print(f'\n  Saved: {out_path}')
    print(f'\n  Done. Cross-verify before setting verified=true.')

if __name__ == '__main__':
    main()
