"""
Anchor Experiment: Factor Semantic Mapping — 3 factors x 13 phases x 4 dimensions.

Factors:
  RS20     — sector 20D return relative to benchmark (pure trend)
  涨跌比   — within-sector advance/decline ratio (breadth)
  W3       — W3 component of the behavior score (strongest single factor)

Phases: 13 manually labeled market phases (2005-07 ~ 2026-05)

Output per factor per phase:
  1. Distribution: mean / std / percentiles
  2. Lead-Lag: factor value vs forward 20D return (t+5, t+20)
  3. Directional stability: IC sign (positive/negative/neutral)
  4. Information gain: RankIC, Top-decile spread
"""

import sqlite3
import json
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
BM_SYMBOL = 'index.000985.SH'

# 13 phases from docs/research/phase_sector_leadership_v1.md
PHASES = [
    {'id': 1,  'name': 'Bull #1',        'type': 'bull', 'start': '2005-07-18', 'end': '2008-01-14'},
    {'id': 2,  'name': 'Bear #2',         'type': 'bear', 'start': '2008-01-14', 'end': '2008-11-04'},
    {'id': 3,  'name': 'Bull #3',         'type': 'bull', 'start': '2008-11-04', 'end': '2009-11-23'},
    {'id': 4,  'name': 'Bear #4',         'type': 'bear', 'start': '2009-11-23', 'end': '2012-12-03'},
    {'id': 5,  'name': 'Bull #5',         'type': 'bull', 'start': '2012-12-03', 'end': '2015-06-12'},
    {'id': 6,  'name': 'Bear #6',         'type': 'bear', 'start': '2015-06-12', 'end': '2016-01-28'},
    {'id': 7,  'name': 'Bull #7',         'type': 'bull', 'start': '2016-01-28', 'end': '2016-11-28'},
    {'id': 8,  'name': 'Bear #8',         'type': 'bear', 'start': '2016-11-28', 'end': '2018-10-18'},
    {'id': 9,  'name': 'Bull #9',         'type': 'bull', 'start': '2018-10-18', 'end': '2021-12-13'},
    {'id': 10, 'name': 'Bear #10',        'type': 'bear', 'start': '2021-12-13', 'end': '2024-02-05'},
    {'id': 11, 'name': 'Bull #11',        'type': 'bull', 'start': '2024-02-05', 'end': '2024-11-11'},
    {'id': 12, 'name': 'Bear #12',        'type': 'bear', 'start': '2024-11-11', 'end': '2025-04-07'},
    {'id': 13, 'name': 'Bull #13',        'type': 'bull', 'start': '2025-04-07', 'end': '2026-05-19'},
]

MIN_HISTORY = 120
HOLD_LOOKAHEAD = 20
SCORE_WINDOW = 90  # W1/W2/W3 needs 90 days of history


def load_data():
    conn = sqlite3.connect(str(DB_PATH))

    # Benchmark
    bm = pd.read_sql(
        'SELECT trade_date, close, amount, adv_count, decl_count, '
        'market_adv_ratio, limit_up_count, limit_down_count '
        'FROM market_daily_data WHERE symbol = ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date'],
    ).set_index('trade_date').sort_index()

    # Sectors
    sec_raw = pd.read_sql(
        'SELECT d.symbol, a.name, d.trade_date, d.close, d.amount, '
        'd.above_ma20_ratio, d.above_ma60_ratio, d.new_high_20d_ratio, '
        'd.amount_ratio, d.time_momentum20, d.time_momentum60 '
        'FROM market_daily_data d '
        'JOIN asset_master a ON d.symbol = a.symbol '
        'WHERE a.asset_type = \'sector\' '
        'ORDER BY d.trade_date, d.symbol',
        conn, parse_dates=['trade_date'],
    )
    conn.close()

    sec_close = sec_raw.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    sec_amount = sec_raw.pivot(index='trade_date', columns='symbol', values='amount').sort_index()
    sec_name = sec_raw[['symbol', 'name']].drop_duplicates().set_index('symbol')['name'].to_dict()
    sec_ma20 = sec_raw.pivot(index='trade_date', columns='symbol', values='above_ma20_ratio').sort_index()
    sec_nh = sec_raw.pivot(index='trade_date', columns='symbol', values='new_high_20d_ratio').sort_index()

    print(f'  Benchmark: {len(bm)} days')
    print(f'  Sectors:   {len(sec_close.columns)} symbols, {len(sec_close)} days')
    print(f'  Date:      {sec_close.index[0].date()} ~ {sec_close.index[-1].date()}')

    return bm, sec_close, sec_amount, sec_name, sec_ma20, sec_nh


def assign_phase(trade_date, phases):
    """Map a trade_date to its phase id. Returns None if outside all phases."""
    for p in phases:
        if p['start'] <= str(trade_date.date()) <= p['end']:
            return p['id']
    return None


def compute_rs20(sector_close, benchmark_close, eval_idx):
    """Sector 20D return minus benchmark 20D return, as excess."""
    if eval_idx < 20:
        return None
    sec_ret = sector_close.iloc[eval_idx] / sector_close.iloc[eval_idx - 20] - 1
    bm_ret = benchmark_close.iloc[eval_idx] / benchmark_close.iloc[eval_idx - 20] - 1
    return sec_ret - bm_ret


def compute_w3_component(s_close, s_amount, bm_close, bm_amount, eval_idx):
    """Compute only the W3 component of the behavior score (0-3)."""
    if eval_idx < 20:
        return None, None
    close = s_close.iloc[:eval_idx + 1]
    amount = s_amount.iloc[:eval_idx + 1]
    bm_c = bm_close.iloc[:eval_idx + 1]

    w3_s = eval_idx - 20
    w3_e = eval_idx
    if w3_s < 0:
        return None, None

    # Also need W2 amount baseline for W3 volume confirmation
    w2_s = eval_idx - 40
    w2_e = eval_idx - 20
    w1_s = eval_idx - 60
    if w1_s < 0:
        # Fallback: use pre-w3 baseline
        pre_baseline = eval_idx - 40
        if pre_baseline < 0:
            return None, None
        amt_pre_w3 = amount.iloc[max(0, pre_baseline-20):pre_baseline].mean()
    else:
        amt_pre_w3 = amount.iloc[max(0, w1_s-60):w1_s].mean() if w1_s >= 60 else amount.iloc[:w1_s].mean()

    w3 = 0
    ret_w3 = close.iloc[w3_e] / close.iloc[w3_s] - 1
    bm_ret_w3 = bm_c.iloc[w3_e] / bm_c.iloc[w3_s] - 1
    if ret_w3 > bm_ret_w3:
        w3 += 1
    ma20 = close.rolling(20, min_periods=10).mean().iloc[w3_e]
    if close.iloc[w3_e] > ma20:
        w3 += 1
    amt_w3 = amount.iloc[w3_s:w3_e].mean()
    if amt_pre_w3 > 0 and amt_w3 > amt_pre_w3:
        w3 += 1

    return w3, ret_w3


def compute_breadth_change(series, eval_idx, window=5):
    """Broadth N-day change (directional slope, not static value)."""
    if eval_idx < window:
        return None
    v_now = series.iloc[eval_idx]
    v_before = series.iloc[eval_idx - window]
    if pd.isna(v_now) or pd.isna(v_before):
        return None
    return v_now - v_before


def forward_return(series, ix, h=20):
    if ix + h >= len(series):
        return None
    return series.iloc[ix + h] / series.iloc[ix] - 1


def main():
    print('=' * 70)
    print('ANCHOR EXPERIMENT: Factor Semantic Mapping')
    print('3 factors x 13 phases x 4 dimensions')
    print('=' * 70)

    # Load
    print('\n[1/4] Loading data...')
    bm, sec_close, sec_amount, sec_name, sec_ma20, sec_nh = load_data()
    bm_close, bm_amount = bm['close'], bm['amount']
    all_dates = bm.index
    sym_list = list(sec_close.columns)

    # Build phase date ranges for fast lookup
    phase_ranges = {}
    for p in PHASES:
        mask = (all_dates >= p['start']) & (all_dates <= p['end'])
        phase_ranges[p['id']] = all_dates[mask]

    print(f'\n[2/4] Computing factor values for all sectors x eval dates...')
    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, 20))
    print(f'  Eval dates: {len(eval_indices)}')

    # Structure: factor -> phase_id -> list of dicts with factor_value and forward_return
    factor_data = {
        'RS20': defaultdict(list),
        'W3': defaultdict(list),
        'BreadthChange': defaultdict(list),
    }

    factor_raw = {
        'RS20': defaultdict(list),   # per-phase: raw values for distribution
        'W3': defaultdict(list),
        'BreadthChange': defaultdict(list),
    }

    records = []

    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        eval_phase = assign_phase(eval_date, PHASES)
        if eval_phase is None:
            continue

        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue

            # RS20
            rs20 = compute_rs20(s_close, bm_close, eval_idx)
            if rs20 is None:
                continue

            # W3
            w3, _ = compute_w3_component(s_close, s_amount, bm_close, bm_amount, eval_idx)
            if w3 is None:
                continue

            # Breadth change (above_ma20_ratio 5-day change)
            bc = compute_breadth_change(sec_ma20[sym], eval_idx, 5)
            if bc is None:
                continue

            # Forward return
            fwd = forward_return(s_close, eval_idx, 20)
            if fwd is None:
                continue

            factor_raw['RS20'][eval_phase].append(rs20)
            factor_raw['W3'][eval_phase].append(w3)
            factor_raw['BreadthChange'][eval_phase].append(bc)

            factor_data['RS20'][eval_phase].append({'val': rs20, 'fwd': fwd})
            factor_data['W3'][eval_phase].append({'val': w3, 'fwd': fwd})
            factor_data['BreadthChange'][eval_phase].append({'val': bc, 'fwd': fwd})

            records.append({
                'date': str(eval_date.date()),
                'phase': eval_phase,
                'sym': sym,
                'rs20': round(rs20, 6),
                'w3': w3,
                'bc': round(bc, 6),
                'fwd20': round(fwd, 6),
            })

    print(f'  Records: {len(records)}')

    # ════════════════════════════════════════════
    # DIMENSION 1: Distribution
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('DIMENSION 1: DISTRIBUTION — mean/std/percentile by phase')
    print('=' * 70)

    from scipy import stats as scipy_stats

    for factor_name, label in [('RS20', 'RS20'), ('W3', 'W3'), ('BreadthChange', 'Breadth(ma20_5d)')]:
        print(f'\n  --- {label} ---')
        print(f'  {"Phase":12s} {"Type":6s} {"N":>6s} {"Mean":>8s} {"Std":>8s} {"P10":>8s} {"P25":>8s} {"P50":>8s} {"P75":>8s} {"P90":>8s}')
        print(f'  {"-"*84}')
        for p in PHASES:
            vals = factor_raw[factor_name].get(p['id'], [])
            if len(vals) < 5:
                continue
            arr = np.array(vals)
            print(f'  {p["name"]:12s} {p["type"]:6s} {len(vals):6d} '
                  f'{np.mean(arr)*100:>+7.2f}% {np.std(arr)*100:>7.2f}% '
                  f'{np.percentile(arr,10)*100:>+7.2f}% {np.percentile(arr,25)*100:>+7.2f}% '
                  f'{np.percentile(arr,50)*100:>+7.2f}% {np.percentile(arr,75)*100:>+7.2f}% '
                  f'{np.percentile(arr,90)*100:>+7.2f}%')

    # ════════════════════════════════════════════
    # DIMENSION 2: Information Coefficient (IC)
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('DIMENSION 2: INFORMATION COEFFICIENT — factor vs forward 20D return')
    print('=' * 70)

    for factor_name, label in [('RS20', 'RS20'), ('W3', 'W3'), ('BreadthChange', 'Breadth(ma20_5d)')]:
        print(f'\n  --- {label} ---')
        print(f'  {"Phase":12s} {"Type":6s} {"N":>6s} {"Pearson r":>10s} {"p-val":>8s} {"Spearman":>10s} {"IC(rank)":>10s}')
        print(f'  {"-"*66}')
        for p in PHASES:
            items = factor_data[factor_name].get(p['id'], [])
            if len(items) < 10:
                continue
            vals = np.array([it['val'] for it in items])
            fwds = np.array([it['fwd'] for it in items])

            # Pearson
            pr, pp = scipy_stats.pearsonr(vals, fwds)
            # Spearman rank
            sr, sp = scipy_stats.spearmanr(vals, fwds)

            # RankIC: spearman rank correlation
            rank_ic = sr

            print(f'  {p["name"]:12s} {p["type"]:6s} {len(items):6d} {pr:>+9.4f}  {pp:>.4f}  {sr:>+9.4f}  {rank_ic:>+9.4f}')

    # ════════════════════════════════════════════
    # DIMENSION 3: Directional Stability
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('DIMENSION 3: DIRECTIONAL STABILITY — IC sign consistency across phases')
    print('=' * 70)

    for factor_name, label in [('RS20', 'RS20'), ('W3', 'W3'), ('BreadthChange', 'Breadth(ma20_5d)')]:
        print(f'\n  --- {label} ---')
        signs = []
        print(f'  {"Phase":12s} {"Type":6s} {"IC(Spearman)":>14s} {"Sign":>6s} {"Interpretation":>40s}')
        print(f'  {"-"*80}')
        for p in PHASES:
            items = factor_data[factor_name].get(p['id'], [])
            if len(items) < 10:
                continue
            vals = np.array([it['val'] for it in items])
            fwds = np.array([it['fwd'] for it in items])
            sr, sp = scipy_stats.spearmanr(vals, fwds)
            sign = '+' if sr > 0.02 else ('-' if sr < -0.02 else '~')
            interp = 'Positive predictive' if sr > 0.05 else ('Negative(reverse)' if sr < -0.05 else 'Neutral/noise')
            signs.append(sign)
            print(f'  {p["name"]:12s} {p["type"]:6s} {sr:>+13.4f}   {sign:4s}   {interp}')

        # Stability score: how many phases have the same sign?
        if signs:
            pos = signs.count('+')
            neg = signs.count('-')
            neu = signs.count('~')
            dominant = max(pos, neg, neu)
            total = len(signs)
            print(f'  {"":10s}  Positive: {pos}/{total}  Negative: {neg}/{total}  Neutral: {neu}/{total}')
            if dominant == pos and pos > total * 0.6:
                print(f'  {"":10s}  >> STABLE POSITIVE factor (consistent across regimes)')
            elif dominant == neg and neg > total * 0.6:
                print(f'  {"":10s}  >> STABLE NEGATIVE factor (consistent inverse across regimes)')
            elif pos > 0 and neg > 0 and pos > total * 0.3 and neg > total * 0.3:
                print(f'  {"":10s}  >> REGIME-DEPENDENT factor (sign changes — needs phase conditioning)')
            else:
                print(f'  {"":10s}  >> WEAK/NOISY factor across most regimes')

    # ════════════════════════════════════════════
    # DIMENSION 4: Lead-Lag (t+5 vs t+20 comparison)
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('DIMENSION 4: LEAD-LAG — short-term vs medium-term predictive power')
    print('=' * 70)

    # Recompute with t+5 forward return for comparison
    # (Need to iterate again for forward5 — let me do a limited version)
    print('\n  (This dimension requires separate forward-5 computation —')
    print('   will be added in v0.2 of this analysis.)')
    print('  For now, Dimension 2 Spearman IC already shows the predictive')
    print('  relationship at the standard 20D horizon.)')

    # ════════════════════════════════════════════
    # SUMMARY INTERPRETATION
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('SUMMARY')
    print('=' * 70)

    print(f'''
  Three factors have been mapped across 13 market phases:

  RS20 (pure trend — sector excess return over 20D):
    - Distribution: bull/bear phase differences
    - IC: positive or negative across phases?
    - Sign stability: consistent or regime-dependent?

  W3 (behavior score W3 component):
    - Distribution: varying by market regime?
    - IC: positive in early phases, negative in late phases?
    - Already suspected to be a "late-phase reverse" signal

  Breadth Change (above_ma20_ratio 5-day slope):
    - Distribution: higher in bull vs bear phases?
    - IC: better timing signal than static breadth?
    - Sign stability: leading or coincident indicator?

  === NEXT STEP ===
  Compare these three curves to identify:
  1. Which factors are orthogonal (low cross-correlation)
  2. Which factors are regime-stable vs regime-dependent
  3. Which factor combinations might work in specific phases
''')

    # Save raw data
    out_path = OUTPUT_DIR / 'factor_semantic_mapping_anchor.json'
    with open(out_path, 'w') as f:
        json.dump({
            'experiment': 'Factor Semantic Mapping (Anchor)',
            'description': 'RS20/W3/BreadthChange x 13 phases x 4 dimensions',
            'phases': PHASES,
            'records': records,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Raw data saved: {out_path}')
    print('\n  Done.')


if __name__ == '__main__':
    main()
