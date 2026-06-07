"""
Phase A: Factor Semantic Mapping — Full Factor Set (F01-F13).
Optimized version: pre-build sector arrays, avoid pandas overhead in inner loop.
"""

import sqlite3
import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from scipy import stats as scipy_stats

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
BM_SYMBOL = 'index.000985.SH'

PHASES = [
    {'id': 1,  'name': 'Bull #1',  'type': 'bull', 'start': '2005-07-18', 'end': '2008-01-14'},
    {'id': 2,  'name': 'Bear #2',   'type': 'bear', 'start': '2008-01-14', 'end': '2008-11-04'},
    {'id': 3,  'name': 'Bull #3',   'type': 'bull', 'start': '2008-11-04', 'end': '2009-11-23'},
    {'id': 4,  'name': 'Bear #4',   'type': 'bear', 'start': '2009-11-23', 'end': '2012-12-03'},
    {'id': 5,  'name': 'Bull #5',   'type': 'bull', 'start': '2012-12-03', 'end': '2015-06-12'},
    {'id': 6,  'name': 'Bear #6',   'type': 'bear', 'start': '2015-06-12', 'end': '2016-01-28'},
    {'id': 7,  'name': 'Bull #7',   'type': 'bull', 'start': '2016-01-28', 'end': '2016-11-28'},
    {'id': 8,  'name': 'Bear #8',   'type': 'bear', 'start': '2016-11-28', 'end': '2018-10-18'},
    {'id': 9,  'name': 'Bull #9',   'type': 'bull', 'start': '2018-10-18', 'end': '2021-12-13'},
    {'id': 10, 'name': 'Bear #10',  'type': 'bear', 'start': '2021-12-13', 'end': '2024-02-05'},
    {'id': 11, 'name': 'Bull #11',  'type': 'bull', 'start': '2024-02-05', 'end': '2024-11-11'},
    {'id': 12, 'name': 'Bear #12',  'type': 'bear', 'start': '2024-11-11', 'end': '2025-04-07'},
    {'id': 13, 'name': 'Bull #13',  'type': 'bull', 'start': '2025-04-07', 'end': '2026-05-19'},
]

HOLD_LOOKAHEAD = 20
MIN_HISTORY = 120
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'


def phase_id_for(ds):
    for p in PHASES:
        if p['start'] <= ds <= p['end']:
            return p['id']
    return None


def main():
    import pandas as pd

    print('=' * 70)
    print('PHASE A: Factor Semantic Mapping — Full Set (F01-F13)')
    print('=' * 70)

    # ── Load ──
    print('\n[1/3] Loading data...')
    conn = sqlite3.connect(str(DB_PATH))

    bm = pd.read_sql(
        'SELECT trade_date, close, amount FROM market_daily_data '
        'WHERE symbol = ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date'],
    ).set_index('trade_date').sort_index()

    sec_raw = pd.read_sql(
        'SELECT d.symbol, d.trade_date, d.close, d.amount, '
        'd.above_ma20_ratio, d.amount_ratio, d.price_vol_divergence '
        'FROM market_daily_data d '
        'JOIN asset_master a ON d.symbol = a.symbol '
        'WHERE a.asset_type = \'sector\' '
        'ORDER BY d.trade_date, d.symbol',
        conn, parse_dates=['trade_date'],
    )
    conn.close()

    # Build per-symbol arrays
    close_piv = sec_raw.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    amount_piv = sec_raw.pivot(index='trade_date', columns='symbol', values='amount').sort_index()
    ma20_piv = sec_raw.pivot(index='trade_date', columns='symbol', values='above_ma20_ratio').sort_index()
    ar_piv = sec_raw.pivot(index='trade_date', columns='symbol', values='amount_ratio').sort_index()
    pvd_piv = sec_raw.pivot(index='trade_date', columns='symbol', values='price_vol_divergence').sort_index()

    sym_list = list(close_piv.columns)
    all_dates = bm.index
    n_dates = len(all_dates)
    bm_close = bm['close'].values
    bm_amount = bm['amount'].values
    n_sym = len(sym_list)

    print(f'  Sectors: {n_sym}, Eval days: {n_dates}')

    # Pre-compute phase_id for each date index
    date_phase = {}
    for i, dt in enumerate(all_dates):
        date_phase[i] = phase_id_for(str(dt.date()))

    # ════════════════════════════════════════════
    # Pre-compute factor values per sector per eval date
    # ════════════════════════════════════════════
    print('\n[2/3] Computing factors...')
    eval_indices = list(range(MIN_HISTORY, n_dates - HOLD_LOOKAHEAD, 20))
    print(f'  Eval windows: {len(eval_indices)}')

    # Pre-compute sector returns and volatility
    # close_ret: sector simple returns array (n_dates x n_sym)
    close_mat = close_piv.values  # (n_dates, n_sym)
    amount_mat = amount_piv.values

    # Simple returns
    close_ret = np.full_like(close_mat, np.nan, dtype=float)
    close_ret[1:] = close_mat[1:] / close_mat[:-1] - 1

    # Rolling vol (20D)
    vol20_mat = np.full_like(close_mat, np.nan, dtype=float)
    for i in range(20, n_dates):
        vol20_mat[i] = np.nanstd(close_ret[i-20:i], axis=0)

    # Date-phase map
    eval_phases = [date_phase.get(ix) for ix in eval_indices]

    # CR3/CR5 per date: cross-sector amount concentration
    cr3_per_date = {}
    cr5_per_date = {}
    for i in range(n_dates):
        amts = amount_mat[i]
        valid_mask = ~np.isnan(amts)
        valid_amts = amts[valid_mask]
        sorted_amts = np.sort(valid_amts)[::-1]
        total = np.nansum(amts)
        if total > 0:
            cr3_per_date[i] = np.sum(sorted_amts[:3]) / total if len(sorted_amts) >= 3 else None
            cr5_per_date[i] = np.sum(sorted_amts[:5]) / total if len(sorted_amts) >= 5 else None
        else:
            cr3_per_date[i] = None
            cr5_per_date[i] = None

    # Factor ID -> phase_id -> list of (val, fwd)
    factor_names = {
        'F01_W1': 'W1',
        'F02_W2': 'W2',
        'F03_W3': 'W3',
        'F04_BreadthChange': 'BreadthChg',
        'F05_RS20': 'RS20',
        'F06_RS60': 'RS60',
        'F07_Momentum20': 'Mom20',
        'F08_Momentum60': 'Mom60',
        'F09_Volatility20': 'Vol20',
        'F10_CR3': 'CR3',
        'F11_CR5': 'CR5',
        'F12_AmountRatio': 'AmtRatio',
        'F13_PriceVolDivergence': 'PVD',
    }
    factor_data = {fid: defaultdict(list) for fid in factor_names}
    records = []

    for ei_idx, eval_idx in enumerate(eval_indices):
        phase = eval_phases[ei_idx]
        if phase is None:
            continue
        ds = str(all_dates[eval_idx].date())

        cr3 = cr3_per_date.get(eval_idx)
        cr5 = cr5_per_date.get(eval_idx)

        for sym_idx in range(n_sym):
            # Check data availability
            if np.isnan(close_mat[eval_idx, sym_idx]):
                continue
            if eval_idx + 20 >= n_dates or np.isnan(close_mat[eval_idx + 20, sym_idx]):
                continue

            # Fwd return
            fwd20 = close_mat[eval_idx + 20, sym_idx] / close_mat[eval_idx, sym_idx] - 1

            # ----- Compute all factors -----

            # F09 Volatility20
            vol20 = vol20_mat[eval_idx, sym_idx]
            if np.isnan(vol20) or vol20 == 0:
                continue

            val_w1 = None
            # W1: need volatility expansion check (60-40 days before)
            if eval_idx >= 60:
                w1_s, w1_e = eval_idx - 60, eval_idx - 40
                vol_w1 = np.nanmean(vol20_mat[w1_s:w1_e, sym_idx])
                vol_pre = np.nanmean(vol20_mat[max(0, w1_s-60):w1_s, sym_idx]) if w1_s >= 60 else 0
                amt_w1 = np.nanmean(amount_mat[w1_s:w1_e, sym_idx])
                amt_pre = np.nanmean(amount_mat[max(0, w1_s-60):w1_s, sym_idx]) if w1_s >= 60 else 0

                w1 = 0
                if vol_pre > 0 and vol_w1 > vol_pre * 1.2:
                    w1 += 1
                if amt_pre > 0 and amt_w1 > amt_pre * 1.1:
                    w1 += 1
                # bm volatility comparison
                bm_vol_w1 = np.nanstd(bm_close[w1_s:w1_e] / bm_close[w1_s-1:w1_e-1] - 1) if w1_e < len(bm_close) else 0
                if bm_vol_w1 > 0 and vol_w1 / bm_vol_w1 > 1.1:
                    w1 += 1
                val_w1 = w1
            else:
                continue

            # W2: volume contraction + price decline (40-20 days before)
            val_w2 = None
            if eval_idx >= 60:
                w1_s = eval_idx - 60
                w2_s, w2_e = eval_idx - 40, eval_idx - 20
                amt_pre_w2 = np.nanmean(amount_mat[max(0, w1_s-60):w1_s, sym_idx]) if w1_s >= 60 else 0
                amt_w2 = np.nanmean(amount_mat[w2_s:w2_e, sym_idx])
                w2 = 0
                if amt_pre_w2 > 0 and amt_w2 < amt_pre_w2 * 0.9:
                    w2 += 1
                ret_w2 = close_mat[w2_e, sym_idx] / close_mat[w2_s, sym_idx] - 1
                if ret_w2 < -0.02:
                    w2 += 1
                bm_ret_w2 = bm_close[w2_e] / bm_close[w2_s] - 1 if w2_s >= 0 and w2_e < len(bm_close) else 0
                if ret_w2 < bm_ret_w2:
                    w2 += 1
                val_w2 = w2
            else:
                continue

            # W3: initial launch (20-0 days before)
            val_w3 = None
            if eval_idx >= 20:
                w3_s, w3_e = eval_idx - 20, eval_idx
                w1_s = eval_idx - 60
                amt_pre_w3 = np.nanmean(amount_mat[max(0, w1_s-60):w1_s, sym_idx]) if w1_s >= 60 else np.nanmean(amount_mat[:w3_s, sym_idx])
                amt_w3 = np.nanmean(amount_mat[w3_s:w3_e, sym_idx])
                w3 = 0
                ret_w3 = close_mat[w3_e, sym_idx] / close_mat[w3_s, sym_idx] - 1
                bm_ret_w3 = bm_close[w3_e] / bm_close[w3_s] - 1
                if ret_w3 > bm_ret_w3:
                    w3 += 1
                # MA20 check
                ma20 = np.nanmean(close_mat[w3_e-20:w3_e, sym_idx]) if w3_e >= 20 else close_mat[w3_e, sym_idx]
                if close_mat[w3_e, sym_idx] > ma20:
                    w3 += 1
                if amt_pre_w3 > 0 and amt_w3 > amt_pre_w3:
                    w3 += 1
                val_w3 = w3
            else:
                continue

            # BreadthChange (above_ma20_ratio 5-day slope)
            if eval_idx >= 5:
                v_now = ma20_piv.values[eval_idx, sym_idx]
                v_before = ma20_piv.values[eval_idx - 5, sym_idx]
                bc = v_now - v_before if not (np.isnan(v_now) or np.isnan(v_before)) else None
            else:
                bc = None
            if bc is None:
                continue

            # RS20
            rs20 = close_ret[eval_idx - 20:eval_idx, sym_idx].sum() if eval_idx >= 20 else None
            if rs20 is None:
                continue

            # RS60
            if eval_idx >= 60:
                rs60 = close_ret[eval_idx - 60:eval_idx, sym_idx].sum()
            else:
                continue

            # Momentum20
            mom20 = close_mat[eval_idx, sym_idx] / close_mat[eval_idx - 20, sym_idx] - 1 if eval_idx >= 20 else None
            if mom20 is None:
                continue

            # Momentum60
            mom60 = close_mat[eval_idx, sym_idx] / close_mat[eval_idx - 60, sym_idx] - 1 if eval_idx >= 60 else None
            if mom60 is None:
                continue

            # AmountRatio
            ar = ar_piv.values[eval_idx, sym_idx]
            if np.isnan(ar):
                continue

            # PriceVolumeDivergence
            pvd = pvd_piv.values[eval_idx, sym_idx]
            if np.isnan(pvd):
                continue

            # Store factor values
            vals = {
                'F01_W1': val_w1,
                'F02_W2': val_w2,
                'F03_W3': val_w3,
                'F04_BreadthChange': bc,
                'F05_RS20': rs20,
                'F06_RS60': rs60,
                'F07_Momentum20': mom20,
                'F08_Momentum60': mom60,
                'F09_Volatility20': vol20,
                'F10_CR3': cr3,
                'F11_CR5': cr5,
                'F12_AmountRatio': ar,
                'F13_PriceVolDivergence': pvd,
            }

            for fid, val in vals.items():
                if val is not None and not (isinstance(val, float) and np.isnan(val)):
                    factor_data[fid][phase].append({'val': val, 'fwd': fwd20})

    print(f'  Total records: {sum(len(records) for records in [sum(factor_data[f].values(),[]) for f in factor_data])}')

    # ════════════════════════════════════════════
    # IC Table
    # ════════════════════════════════════════════
    print('\n[3/3] Computing IC table...')
    print('\n' + '=' * 110)
    print('PHASE A: IC TABLE — Spearman Rank Correlation by Factor x Phase')
    print('(sign: + if IC>0.02, - if IC<-0.02, ~ otherwise; * if p<0.10)')
    print('=' * 110)

    # Header
    line = f'  {"ID":12s} {"Name":18s}'
    for p in PHASES:
        line += f'  {p["name"]:>9s}'
    line += f'  {"Stability":>10s}'
    print(line)
    print('  ' + '-' * (14 + 11 * 13 + 12))

    results = {}
    for fid, label in factor_names.items():
        signs = []
        cells = []
        for p in PHASES:
            items = factor_data[fid].get(p['id'], [])
            if len(items) < 5:
                cells.append(' --')
                continue
            vals = np.array([it['val'] for it in items])
            fwds = np.array([it['fwd'] for it in items])
            if np.std(vals) == 0 or np.std(fwds) == 0:
                cells.append(' --')
                continue
            sr, sp = scipy_stats.spearmanr(vals, fwds)
            sgn = '+' if sr > 0.02 else ('-' if sr < -0.02 else '~')
            signs.append(sgn)
            star = '*' if sp < 0.10 else ' '
            cells.append(f'{sr:>+7.3f}{star}{sgn}')

        # Stability
        if signs:
            pos = signs.count('+')
            neg = signs.count('-')
            neu = signs.count('~')
            total = len(signs)
            if pos / total >= 0.7:
                stab = 'STABLE+'
            elif neg / total >= 0.7:
                stab = 'STABLE-'
            elif pos >= total * 0.25 and neg >= total * 0.25:
                stab = f'REGIME({pos}/{neg})'
            else:
                stab = 'WEAK'
        else:
            stab = '?'

        line = f'  {fid:12s} {label:18s}'
        for c in cells:
            line += f'  {c:>9s}'
        line += f'  {stab:>10s}'
        print(line)

    # ════════════════════════════════════════════
    # Summary ranking
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('FACTOR RANKING BY AVERAGE |IC|')
    print('=' * 70)

    factor_scores = []
    for fid, label in factor_names.items():
        ics = []
        for p in PHASES:
            items = factor_data[fid].get(p['id'], [])
            if len(items) < 5:
                continue
            vals = np.array([it['val'] for it in items])
            fwds = np.array([it['fwd'] for it in items])
            if np.std(vals) == 0 or np.std(fwds) == 0:
                continue
            sr, _ = scipy_stats.spearmanr(vals, fwds)
            ics.append(sr)
        if ics:
            avg_ic = np.mean(ics)
            avg_abs_ic = np.mean(np.abs(ics))
            pos_ratio = sum(1 for ic in ics if ic > 0.02) / len(ics)
            neg_ratio = sum(1 for ic in ics if ic < -0.02) / len(ics)
            factor_scores.append({
                'id': fid, 'name': label,
                'avg_ic': avg_ic, 'avg_abs_ic': avg_abs_ic,
                'pos_ratio': pos_ratio, 'neg_ratio': neg_ratio,
                'n_phases': len(ics),
            })

    factor_scores.sort(key=lambda x: x['avg_abs_ic'], reverse=True)
    print(f'  {"Rank":>4s} {"ID":12s} {"Name":18s} {"Avg IC":>8s} {"Avg|IC|":>8s} {"Pos%":>6s} {"Neg%":>6s} {"Phases":>6s}')
    print(f'  {"-"*70}')
    for rank, fs in enumerate(factor_scores, 1):
        print(f'  {rank:4d} {fs["id"]:12s} {fs["name"]:18s} {fs["avg_ic"]:>+7.4f}  {fs["avg_abs_ic"]:>6.4f}  '
              f'{fs["pos_ratio"]*100:>5.0f}% {fs["neg_ratio"]*100:>5.0f}% {fs["n_phases"]:5d}')

    # ════════════════════════════════════════════
    # Key pattern detection
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('PATTERN DETECTION')
    print('=' * 70)

    print('\n  Phase-by-phase factor rank:')
    # Which factor has the highest |IC| in each phase?
    for p in PHASES:
        best_factor = None
        best_abs_ic = 0
        for fid, label in factor_names.items():
            items = factor_data[fid].get(p['id'], [])
            if len(items) < 5:
                continue
            vals = np.array([it['val'] for it in items])
            fwds = np.array([it['fwd'] for it in items])
            if np.std(vals) == 0 or np.std(fwds) == 0:
                continue
            sr, _ = scipy_stats.spearmanr(vals, fwds)
            if abs(sr) > best_abs_ic:
                best_abs_ic = abs(sr)
                best_factor = (label, sr)
        if best_factor:
            print(f'  {p["name"]:12s} {p["type"]:6s} -> Best factor: {best_factor[0]:15s} (IC={best_factor[1]:+.4f})')

    # Save
    print('\n  Saving results...')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # (Saving raw data would be large — we skip it for now)
    print(f'  Done.\n')


if __name__ == '__main__':
    main()
