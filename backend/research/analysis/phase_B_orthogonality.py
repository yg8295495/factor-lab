"""
Phase B: Factor Orthogonality Analysis (17 factors × 13 phases)
===============================================================
Computes:
  1. Spearman correlation matrix (17×17) for each of 13 phases
  2. Redundant pairs (|ρ| > 0.7 consistently)
  3. Complementary pairs (|ρ| < 0.2, both IC > 0.1)
  4. Factor clusters

Data reliability: reads from DB, computes factors using verified Phase A methods.
"""

import sqlite3, json, numpy as np, pandas as pd
from pathlib import Path; from collections import defaultdict
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

def pid(ds):
    for p in PHASES:
        if p['start'] <= ds <= p['end']: return p['id']
    return None

def main():
    print('=' * 70)
    print('PHASE B: Factor Orthogonality Analysis')
    print('17 factors × 13 phases = 221 correlation matrices')
    print('=' * 70)

    # ── Load data ──
    print('\n[1/3] Loading data...')
    conn = sqlite3.connect(str(DB_PATH))
    bm = pd.read_sql('SELECT trade_date, close FROM market_daily_data WHERE symbol=? ORDER BY trade_date',
                      conn, params=(BM_SYMBOL,), parse_dates=['trade_date']).set_index('trade_date').sort_index()
    sec = pd.read_sql('''SELECT d.symbol, d.trade_date, d.close, d.high, d.low, d.amount,
                         d.above_ma20_ratio, d.new_high_20d_ratio, d.amount_ratio
                         FROM market_daily_data d JOIN asset_master a ON d.symbol=a.symbol
                         WHERE a.asset_type='sector' ORDER BY d.trade_date''',
                      conn, parse_dates=['trade_date'])
    conn.close()

    sec_close = sec.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    sec_high = sec.pivot(index='trade_date', columns='symbol', values='high').sort_index()
    sec_low = sec.pivot(index='trade_date', columns='symbol', values='low').sort_index()
    sec_amount = sec.pivot(index='trade_date', columns='symbol', values='amount').sort_index()
    sec_pr = sec.pivot(index='trade_date', columns='symbol', values='above_ma20_ratio').sort_index()
    sec_nh = sec.pivot(index='trade_date', columns='symbol', values='new_high_20d_ratio').sort_index()
    sec_ar = sec.pivot(index='trade_date', columns='symbol', values='amount_ratio').sort_index()

    all_dates = bm.index; bm_close = bm['close']; sym_list = list(sec_close.columns)
    n_dates = len(all_dates); n_sym = len(sym_list)
    print(f'  Sectors: {n_sym}, Days: {n_dates}')

    # ── Compute factor values for all eval points ──
    print('\n[2/3] Computing 17 factor values for all eval points...')
    eval_indices = list(range(MIN_HISTORY, n_dates - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
    print(f'  Eval points: {len(eval_indices)}')

    # Pre-compute cross-sector metrics: CR3, CR5, TopDisp, AdvDecl
    amt_mat = sec_amount.values; close_mat = sec_close.values
    cr3_arr = np.full(n_dates, np.nan); cr5_arr = np.full(n_dates, np.nan)
    adv_arr = np.full(n_dates, np.nan)

    for i in range(n_dates):
        a = amt_mat[i]; vm = ~np.isnan(a); va = a[vm]; sa = np.sort(va)[::-1]; t = np.nansum(va)
        if t > 0:
            if len(sa) >= 3: cr3_arr[i] = np.sum(sa[:3]) / t
            if len(sa) >= 5: cr5_arr[i] = np.sum(sa[:5]) / t
        # AdvDecl
        if i > 0:
            chg = close_mat[i] - close_mat[i-1]
            valid = ~np.isnan(chg)
            if valid.sum() > 0:
                adv_arr[i] = np.sum(chg[valid] > 0) / valid.sum()

    # Build records: each record has all 17 factor values + phase + fwd20
    records = []
    for ei in eval_indices:
        pp = pid(str(all_dates[ei].date()))
        if pp is None: continue

        bm20 = bm_close.iloc[ei] / bm_close.iloc[ei-20]
        bm60 = bm_close.iloc[ei] / bm_close.iloc[ei-60]
        if pd.isna(bm20) or pd.isna(bm60): continue

        for si, sym in enumerate(sym_list):
            s = sec_close[sym].dropna()
            if len(s) < ei + 20: continue
            p0 = s.iloc[ei]; p20 = s.iloc[ei-20]; p60 = s.iloc[ei-60]
            if pd.isna(p0) or pd.isna(p20): continue

            # ① Trend/Momentum
            rs20 = (p0 / p20) / bm20
            rs60 = (p0 / p60) / bm60
            mom20 = p0 / p20 - 1
            mom60 = p0 / p60 - 1
            accel = mom20 - (s.iloc[ei-5] / s.iloc[ei-25] - 1) if ei >= 25 else None

            # ② Volatility
            rets = np.array([s.iloc[j] / s.iloc[j-1] - 1 for j in range(ei-19, ei+1)])
            if np.isnan(rets).any(): continue
            vol20 = np.std(rets, ddof=1)
            vol_ratio = None
            if ei >= 40:
                rets_pre = np.array([s.iloc[j] / s.iloc[j-1] - 1 for j in range(ei-39, ei-19)])
                vol20_pre = np.std(rets_pre, ddof=1)
                vol_ratio = vol20 / vol20_pre if vol20_pre > 0 else None

            # ③ Breadth
            ar_series = sec_ar[sym]
            pr = sec_pr[sym].iloc[ei] if ei < len(sec_pr) else None
            bc = sec_pr[sym].iloc[ei] - sec_pr[sym].iloc[ei-5] if ei >= 5 and ei < len(sec_pr) else None
            nh = sec_nh[sym].iloc[ei] if ei < len(sec_nh) else None

            if pr is None or pd.isna(pr): continue

            # ④ Price-Volume
            ar_val = ar_series.iloc[ei] if ei < len(ar_series) else None
            if ar_val is None or pd.isna(ar_val): continue
            ar_sma5 = np.mean([ar_series.iloc[ei-j] for j in range(1,6) if ei-j >= 0]) if ei >= 5 else None
            vb = ar_val - ar_sma5 if ar_sma5 is not None else None

            # ⑤ Leadership
            cr3 = cr3_arr[ei]; cr5 = cr5_arr[ei]
            ret20 = close_mat[ei, si] / close_mat[ei-20, si] - 1
            # TopDisp per sector (same for all sectors on same date)
            all_rets = close_mat[ei] / close_mat[ei-20] - 1
            all_rets = all_rets[~np.isnan(all_rets)]
            td = None
            if len(all_rets) >= 6:
                sr = np.sort(all_rets)
                td = np.mean(sr[-3:]) - np.mean(sr[:3])

            # ⑥ Style
            scs = None; adr = adv_arr[ei]

            # Forward return
            if ei + 20 >= len(s): continue
            fwd20 = s.iloc[ei+20] / p0 - 1

            records.append({
                'date': str(all_dates[ei].date()), 'phase': pp, 'sym': sym,
                'rs20': round(rs20, 6) if not pd.isna(rs20) else None,
                'rs60': round(rs60, 6) if not pd.isna(rs60) else None,
                'mom20': round(mom20, 6), 'mom60': round(mom60, 6),
                'accel': round(accel, 6) if accel is not None else None,
                'vol20': round(vol20, 8),
                'vol_ratio': round(vol_ratio, 6) if vol_ratio is not None else None,
                'pr': round(float(pr), 6),
                'bc': round(float(bc), 6) if bc is not None else None,
                'nh': round(float(nh), 6) if nh is not None and not pd.isna(nh) else None,
                'ar': round(float(ar_val), 6),
                'vb': round(float(vb), 6) if vb is not None else None,
                'cr3': round(float(cr3), 6) if not np.isnan(cr3) else None,
                'cr5': round(float(cr5), 6) if not np.isnan(cr5) else None,
                'td': round(float(td), 6) if td is not None else None,
                'adr': round(float(adr), 6) if not np.isnan(adr) else None,
                'scs': None,  # needs index data, skip for now
                'fwd20': round(fwd20, 6),
            })

    print(f'  Records: {len(records)}')
    df = pd.DataFrame(records)

    # Factor columns (excluding scs which needs index data)
    factor_cols = ['rs20','rs60','mom20','mom60','accel','vol20','vol_ratio',
                   'pr','bc','nh','ar','vb','cr3','cr5','td','adr']
    factor_labels = ['RS20','RS60','Mom20','Mom60','Accel','Vol20','VolRatio',
                     'PartRate','BrdthChg','NewHigh','AmtRatio','VolBkOut',
                     'CR3','CR5','TopDisp','AdvDecl']

    # ════════════════════════════════════════════
    # Phase B-1: Per-phase correlation matrix
    # ════════════════════════════════════════════
    print('\n[3/3] Computing per-phase correlation matrices...')
    print('\n' + '=' * 110)
    print('PHASE B-1: AVERAGE CORRELATION MATRIX (mean |ρ| across 13 phases)')
    print('=' * 110)

    # Compute per-phase correlation, then average
    n_f = len(factor_cols)
    corr_sum = np.zeros((n_f, n_f))
    corr_count = np.zeros((n_f, n_f))
    phase_corrs = {}

    for p in PHASES:
        sub = df[df['phase'] == p['id']]
        if len(sub) < 10: continue
        vals = sub[factor_cols].dropna()
        if len(vals) < 10: continue
        cm = vals.corr(method='spearman').values
        phase_corrs[p['id']] = cm
        mask = ~np.isnan(cm)
        corr_sum[mask] += np.abs(cm[mask])
        corr_count[mask] += 1

    avg_corr = corr_sum / np.maximum(corr_count, 1)

    # Print matrix
    print(f'\n  {"":>14s}', end='')
    for label in factor_labels:
        print(f'{label:>10s}', end='')
    print()

    for i in range(n_f):
        print(f'  {factor_labels[i]:>14s}', end='')
        for j in range(n_f):
            v = avg_corr[i, j]
            if i == j:
                print(f'  {"—":>9s}', end='')
            elif corr_count[i, j] < 5:
                print(f'  {"":>9s}', end='')
            else:
                print(f'  {v:>8.3f} ', end='')
        print()

    # ════════════════════════════════════════════
    # Phase B-2: Redundant pairs
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('PHASE B-2: REDUNDANT PAIRS (|ρ| > 0.7 in >50% phases)')
    print('=' * 70)

    redundant = []
    for i in range(n_f):
        for j in range(i+1, n_f):
            high_corr_phases = 0
            total_phases = 0
            for p in PHASES:
                cm = phase_corrs.get(p['id'])
                if cm is not None and not np.isnan(cm[i, j]):
                    total_phases += 1
                    if abs(cm[i, j]) > 0.7:
                        high_corr_phases += 1
            if total_phases > 0 and high_corr_phases / total_phases > 0.5:
                avg_r = np.mean([abs(phase_corrs[pid][i, j])
                                for pid in phase_corrs if not np.isnan(phase_corrs[pid][i, j])])
                redundant.append((factor_labels[i], factor_labels[j], avg_r, high_corr_phases, total_phases))

    redundant.sort(key=lambda x: x[2], reverse=True)
    if redundant:
        print(f'  {"Pair1":14s} {"Pair2":14s} {"Avg|ρ|":>8s} {"HiCorr/Ph":>10s}')
        print(f'  {"-"*50}')
        for r1, r2, r, hc, tp in redundant:
            print(f'  {r1:14s} {r2:14s} {r:>7.3f}   {hc}/{tp}')
    else:
        print('  (No redundant pairs found)')

    # ════════════════════════════════════════════
    # Phase B-3: Complementary pairs
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('PHASE B-3: COMPLEMENTARY PAIRS (|ρ| < 0.2, both IC > 0.1 in >50% phases)')
    print('=' * 70)

    # Load Phase A IC data
    ic_by_factor = defaultdict(dict)
    for fname, cols in [
        ('phase_A_class01_trend_v2.json', ['rs20','rs60','mom20','mom60','accel']),
        ('phase_A_class02_volatility_v2.json', ['vol20','atr20','vol_ratio']),
        ('phase_A_class03_breadth.json', ['pr','bc','nh','nhc']),
        ('phase_A_class04_pricevol_leadership.json', ['ar','vb','pvd','cr3','cr5','td']),
        ('phase_A_class05_style.json', ['scs','adr']),
    ]:
        fp = OUTPUT_DIR / fname
        if not fp.exists(): continue
        d = json.loads(fp.read_text(encoding='gbk'))
        for row in d['ic_matrix']:
            lbl = row['factor']
            for p in PHASES:
                sr = row.get(f'p{p["id"]}_spearman')
                if sr is not None:
                    ic_by_factor[lbl][p['id']] = abs(sr)

    # Map factor labels to their IC data
    label_to_ic = {}
    for lbl in factor_labels:
        if lbl in ic_by_factor:
            label_to_ic[lbl] = ic_by_factor[lbl]

    complementary = []
    for i in range(n_f):
        for j in range(i+1, n_f):
            li, lj = factor_labels[i], factor_labels[j]
            both_strong_phases = 0
            total_phases = 0
            low_corr_phases = 0
            for p in PHASES:
                cm = phase_corrs.get(p['id'])
                if cm is None or np.isnan(cm[i, j]): continue
                total_phases += 1
                ic_i = label_to_ic.get(li, {}).get(p['id'], 0)
                ic_j = label_to_ic.get(lj, {}).get(p['id'], 0)
                if ic_i > 0.10 and ic_j > 0.10:
                    both_strong_phases += 1
                    if abs(cm[i, j]) < 0.2:
                        low_corr_phases += 1
            if both_strong_phases >= 3 and low_corr_phases / both_strong_phases > 0.5:
                complementary.append((li, lj, low_corr_phases, both_strong_phases))

    complementary.sort(key=lambda x: x[2]/max(x[3],1), reverse=True)
    if complementary:
        print(f'  {"Pair1":14s} {"Pair2":14s} {"LowCorr/Both":>12s}')
        print(f'  {"-"*42}')
        for r1, r2, lc, bs in complementary[:10]:
            print(f'  {r1:14s} {r2:14s} {lc}/{bs}')
    else:
        print('  (No strong complementary pairs found)')

    # ════════════════════════════════════════════
    # Phase B-4: Factor clusters
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('PHASE B-4: FACTOR CLUSTERS (hierarchical grouping)')
    print('=' * 70)

    # Simple clustering: if avg|ρ| > 0.5, they're in same cluster
    from collections import defaultdict as dd
    clusters = dd(list)
    assigned = set()
    for i in range(n_f):
        if factor_labels[i] in assigned: continue
        cluster_members = [factor_labels[i]]
        assigned.add(factor_labels[i])
        for j in range(i+1, n_f):
            if factor_labels[j] in assigned: continue
            v = avg_corr[i, j]
            if corr_count[i, j] >= 5 and v > 0.5:
                cluster_members.append(factor_labels[j])
                assigned.add(factor_labels[j])
        if len(cluster_members) > 1:
            clusters[f'Cluster {len(clusters)+1}'].extend(cluster_members)

    if clusters:
        for cname, members in clusters.items():
            print(f'  {cname}: {", ".join(members)}')
    else:
        print('  (No strong factor clusters — all factors are orthogonal)')

    # Unassigned factors
    unassigned = [l for l in factor_labels if l not in assigned]
    if unassigned:
        print(f'\n  Unclustered (orthogonal): {", ".join(unassigned)}')

    # Save
    out_path = OUTPUT_DIR / 'phase_B_orthogonality.json'
    json.dump({
        'experiment': 'Phase-B-Orthogonality',
        'n_factors': n_f,
        'factors': factor_labels,
        'avg_correlation_matrix': avg_corr.tolist(),
        'redundant_pairs': [{'f1': r1, 'f2': r2, 'avg_abs_rho': round(r,4), 'high_corr_phases': hc, 'total_phases': tp}
                           for r1, r2, r, hc, tp in redundant],
        'complementary_pairs': [{'f1': r1, 'f2': r2, 'low_corr_when_both_strong': lc, 'both_strong_phases': bs}
                               for r1, r2, lc, bs in complementary],
    }, open(out_path, 'w'), indent=2, ensure_ascii=True, default=str)
    print(f'\n  Saved: {out_path}')
    print('\n  Done.')

if __name__ == '__main__':
    main()
