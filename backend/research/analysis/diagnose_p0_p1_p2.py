"""
Diagnostic 2: Three root-cause questions.

P0: Why does Gap>=2 fail?
    — Is high-gap selection actually "already priced in"?
    — Compare: past performance of high-gap sectors vs future performance.

P1: W2 — leader ID or return prediction?
    — W2-only TOP3 portfolio returns vs W3-only vs combined.
    — Does W2 pick a "good cluster" even if it misses the #1 champion?

P2: Leading or lagging indicator?
    — Score vs past N-day return correlation.
    — Score vs future N-day return correlation.
    — If score correlates more with past → trailing indicator.
"""

import sqlite3
import json
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
BM_SYMBOL = 'index.000985.SH'
REBALANCE_INTERVAL = 20
HOLD_LOOKAHEAD = 20
MIN_HISTORY = 120


def load_data():
    conn = sqlite3.connect(str(DB_PATH))
    bm = pd.read_sql(
        'SELECT trade_date, close, amount FROM market_daily_data '
        'WHERE symbol = ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date'],
    ).set_index('trade_date').sort_index()

    sec_raw = pd.read_sql(
        'SELECT d.symbol, a.name, d.trade_date, d.close, d.amount '
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

    print(f'  Benchmark: {len(bm)} days')
    print(f'  Sectors:   {len(sec_close.columns)} symbols, {len(sec_close)} days')
    return bm, sec_close, sec_amount, sec_name


def score_components(s_close, s_amount, bm_close, bm_amount, eval_idx):
    if eval_idx < 100:
        return None
    if eval_idx - 90 < 0:
        return None

    close = s_close.iloc[:eval_idx + 1]
    amount = s_amount.iloc[:eval_idx + 1]
    bm_c = bm_close.iloc[:eval_idx + 1]

    w1_s, w1_e = eval_idx - 60, eval_idx - 40
    w2_s, w2_e = eval_idx - 40, eval_idx - 20
    w3_s, w3_e = eval_idx - 20, eval_idx

    ret = close.pct_change()
    bm_ret = bm_c.pct_change()
    rvol = ret.rolling(20, min_periods=10).std()
    bm_rvol = bm_ret.rolling(20, min_periods=10).std()

    total = w1 = w2 = w3 = 0

    # W1
    vol_w1 = rvol.iloc[w1_s:w1_e].mean()
    vol_pre = rvol.iloc[max(0, w1_s-60):w1_s].mean() if w1_s >= 60 else 0
    amt_w1 = amount.iloc[w1_s:w1_e].mean()
    amt_pre = amount.iloc[max(0, w1_s-60):w1_s].mean() if w1_s >= 60 else 0
    if vol_pre > 0 and vol_w1 > vol_pre * 1.2:
        total += 1; w1 += 1
    if amt_pre > 0 and amt_w1 > amt_pre * 1.1:
        total += 1; w1 += 1
    bm_vol_w1 = bm_rvol.iloc[w1_s:w1_e].mean()
    if bm_vol_w1 > 0 and vol_w1 / bm_vol_w1 > 1.1:
        total += 1; w1 += 1

    # W2
    amt_w2 = amount.iloc[w2_s:w2_e].mean()
    amt_pre_w2 = amount.iloc[max(0, w1_s-60):w1_s].mean() if w1_s >= 60 else 0
    if amt_pre_w2 > 0 and amt_w2 < amt_pre_w2 * 0.9:
        total += 1; w2 += 1
    ret_w2 = close.iloc[w2_e] / close.iloc[w2_s] - 1
    if ret_w2 < -0.02:
        total += 1; w2 += 1
    bm_ret_w2 = bm_c.iloc[w2_e] / bm_c.iloc[w2_s] - 1
    if ret_w2 < bm_ret_w2:
        total += 1; w2 += 1

    # W3
    ret_w3 = close.iloc[w3_e] / close.iloc[w3_s] - 1
    bm_ret_w3 = bm_c.iloc[w3_e] / bm_c.iloc[w3_s] - 1
    if ret_w3 > bm_ret_w3:
        total += 1; w3 += 1
    ma20 = close.rolling(20, min_periods=10).mean().iloc[w3_e]
    if close.iloc[w3_e] > ma20:
        total += 1; w3 += 1
    amt_w3 = amount.iloc[w3_s:w3_e].mean()
    if amt_pre_w2 > 0 and amt_w3 > amt_pre_w2:
        total += 1; w3 += 1

    return {'total': total, 'w1': w1, 'w2': w2, 'w3': w3}


def fwd_ret(series, ix, h):
    if ix + h < 0 or ix + h >= len(series):
        return None
    return series.iloc[ix + h] / series.iloc[ix] - 1


def past_ret(series, ix, h):
    """Return over [ix - h, ix]."""
    if ix - h < 0 or ix >= len(series):
        return None
    return series.iloc[ix] / series.iloc[ix - h] - 1


def main():
    print('=' * 70)
    print('DIAGNOSTIC 2: Three Root-Cause Questions')
    print('=' * 70)

    # ── Load ──
    print('\n[1/5] Loading data...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close, bm_amount = bm['close'], bm['amount']
    all_dates = bm.index
    sym_list = list(sec_close.columns)

    # ── Score all windows ──
    print('\n[2/5] Scoring all windows...')
    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
    print(f'  Eval windows: {len(eval_indices)}')

    windows = []
    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        ds = str(eval_date.date())

        # Score all sectors
        comps = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            sc = sec_close[sym].dropna()
            sa = sec_amount[sym].dropna()
            if len(sc) < eval_idx + 1:
                continue
            c = score_components(sc, sa, bm_close, bm_amount, eval_idx)
            if c and 0 < c['total'] <= 9:
                comps[sym] = c

        if not comps:
            continue

        # For each sector: past returns (20/40/60D) + forward returns (20/40/60D)
        # Also: benchmark forward return
        bm_fwd20 = fwd_ret(bm_close, eval_idx, 20)
        bm_fwd40 = fwd_ret(bm_close, eval_idx, 40)
        bm_fwd60 = fwd_ret(bm_close, eval_idx, 60)

        sector_data = {}
        for sym in comps:
            sc = sec_close[sym].dropna()
            ix = sc.index.get_indexer([eval_date], method='pad')[0]
            if ix < 0:
                continue
            sector_data[sym] = {
                'past20': past_ret(sc, ix, 20),
                'past40': past_ret(sc, ix, 40),
                'past60': past_ret(sc, ix, 60),
                'fwd20': fwd_ret(sc, ix, 20),
                'fwd40': fwd_ret(sc, ix, 40),
                'fwd60': fwd_ret(sc, ix, 60),
            }

        if not sector_data:
            continue

        # Rank by total score
        ranked = sorted(comps.items(), key=lambda x: x[1]['total'], reverse=True)

        # Leader = best fwd20
        fwd20s = {sym: sector_data[sym]['fwd20'] for sym in sector_data if sector_data[sym]['fwd20'] is not None}
        if not fwd20s:
            continue
        leader_sym = max(fwd20s, key=fwd20s.get)

        gap = ranked[0][1]['total'] - ranked[1][1]['total'] if len(ranked) >= 2 else 0

        # Top1 and Top3 by score
        top1_sym = ranked[0][0]
        top3_syms = [s[0] for s in ranked[:3]]
        top5_syms = [s[0] for s in ranked[:5]]

        # Leader rank by score
        leader_rank = next((i+1 for i, (s, _) in enumerate(ranked) if s == leader_sym), None)

        windows.append({
            'date': ds,
            'eval_idx': eval_idx,
            'gap': gap,
            'leader_sym': leader_sym,
            'leader_ret20': fwd20s.get(leader_sym),
            'leader_rank': leader_rank,
            'top1_sym': top1_sym,
            'top1_comp': comps[top1_sym],
            'top3_syms': top3_syms,
            'top5_syms': top5_syms,
            # Components of all sectors (for per-component portfolio analysis)
            'comps': comps,
            'sector_data': sector_data,
            'bm_fwd20': bm_fwd20,
            'bm_fwd40': bm_fwd40,
            'bm_fwd60': bm_fwd60,
        })

    print(f'  Windows: {len(windows)}')

    # ════════════════════════════════════════════
    # P0: Gap>=2 failure analysis
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('P0: WHY DOES GAP>=2 FAIL?')
    print('    -> Is high-gap picking "already priced in" sectors?')
    print('=' * 70)

    gap_buckets = [(0, 0, 'Gap=0'), (1, 1, 'Gap=1'), (2, 2, 'Gap=2'), (3, 99, 'Gap>=3')]

    print(f'\n  {"Bucket":10s} {"N":>4s} {"Top1 past20":>12s} {"Top1 past40":>12s} {"Top1 past60":>12s} '
          f'{"Top1 fwd20":>12s} {"Top1 fwd40":>12s} {"Top1 fwd60":>12s} {"BM fwd20":>10s}')
    print(f'  {"-"*94}')

    for lo, hi, label in gap_buckets:
        subset = [w for w in windows if lo <= w['gap'] <= hi]
        if not subset:
            continue
        n = len(subset)

        top1_sym = [w['top1_sym'] for w in subset]
        top1_past20 = np.mean([w['sector_data'].get(s, {}).get('past20', np.nan) for w, s in zip(subset, top1_sym) if w['sector_data'].get(s, {}).get('past20') is not None])
        top1_past40 = np.mean([w['sector_data'].get(s, {}).get('past40', np.nan) for w, s in zip(subset, top1_sym) if w['sector_data'].get(s, {}).get('past40') is not None])
        top1_past60 = np.mean([w['sector_data'].get(s, {}).get('past60', np.nan) for w, s in zip(subset, top1_sym) if w['sector_data'].get(s, {}).get('past60') is not None])
        top1_fwd20 = np.mean([w['sector_data'].get(s, {}).get('fwd20', np.nan) for w, s in zip(subset, top1_sym) if w['sector_data'].get(s, {}).get('fwd20') is not None])
        top1_fwd40 = np.mean([w['sector_data'].get(s, {}).get('fwd40', np.nan) for w, s in zip(subset, top1_sym) if w['sector_data'].get(s, {}).get('fwd40') is not None])
        top1_fwd60 = np.mean([w['sector_data'].get(s, {}).get('fwd60', np.nan) for w, s in zip(subset, top1_sym) if w['sector_data'].get(s, {}).get('fwd60') is not None])
        bm_fwd20 = np.mean([w['bm_fwd20'] for w in subset if w['bm_fwd20'] is not None])

        def pct(v):
            return f'{v*100:+.1f}%' if not np.isnan(v) else '  N/A'

        print(f'  {label:10s} {n:4d}  {pct(top1_past20):>10s}  {pct(top1_past40):>10s}  {pct(top1_past60):>10s}  '
              f'{pct(top1_fwd20):>10s}  {pct(top1_fwd40):>10s}  {pct(top1_fwd60):>10s}  {pct(bm_fwd20):>10s}')

    # Key comparison: top1 vs top2 vs top3 forward return by gap bucket
    print(f'\n  Gap bucket → Top1 vs Top2 vs Top3 forward returns (20D):')
    print(f'  {"Bucket":10s} {"N":>4s} {"Top1 fwd20":>12s} {"Top2 fwd20":>12s} {"Top3 fwd20":>12s} '
          f'{"Avg(1-3)":>10s} {"Bottom3":>10s}')
    print(f'  {"-"*74}')

    for lo, hi, label in gap_buckets:
        subset = [w for w in windows if lo <= w['gap'] <= hi]
        if not subset:
            continue
        n = len(subset)

        top1_fwd = []
        top2_fwd = []
        top3_fwd = []
        bot3_fwd = []

        for w in subset:
            ranked = sorted(w['comps'].items(), key=lambda x: x[1]['total'], reverse=True)
            syms = [s[0] for s in ranked]
            # Top1/2/3 forward
            t1 = w['sector_data'].get(syms[0], {}).get('fwd20')
            t2 = w['sector_data'].get(syms[1], {}).get('fwd20') if len(syms) >= 2 else None
            t3 = w['sector_data'].get(syms[2], {}).get('fwd20') if len(syms) >= 3 else None
            # Bottom3 forward
            b1 = w['sector_data'].get(syms[-1], {}).get('fwd20') if len(syms) >= 1 else None
            b2 = w['sector_data'].get(syms[-2], {}).get('fwd20') if len(syms) >= 2 else None
            b3 = w['sector_data'].get(syms[-3], {}).get('fwd20') if len(syms) >= 3 else None

            if t1 is not None: top1_fwd.append(t1)
            if t2 is not None: top2_fwd.append(t2)
            if t3 is not None: top3_fwd.append(t3)
            if b1 is not None and b2 is not None and b3 is not None:
                bot3_fwd.append(np.mean([b1, b2, b3]))

        print(f'  {label:10s} {n:4d}  {pct(np.mean(top1_fwd)):>10s}  {pct(np.mean(top2_fwd)):>10s}  '
              f'{pct(np.mean(top3_fwd)):>10s}  {pct(np.mean(top1_fwd)):>10s}  '
              f'{pct(np.mean(bot3_fwd)):>10s}')

    # P0 summary: past return momentum of top1 at decision time
    print(f'\n  P0 CONCLUSION:')
    print(f'  Looking at the above:')
    print(f'  - Does past20/past40/past60 INCREASE as gap increases?')
    print(f'    -> If yes, high-gap sectors have more past momentum => already ran')
    print(f'  - Does fwd20 DECREASE as gap increases?')
    print(f'    -> If yes, high-gap sectors have LESS future upside => mean reversion')
    print(f'  - Does the gap=1 bucket produce the best forward return?')
    print(f'    -> If yes, moderate conviction is ideal, over-conviction means overbought')

    # ════════════════════════════════════════════
    # P1: W2 — leader ID or return prediction?
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('P1: W2 — LEADER ID OR RETURN PREDICTION?')
    print('    -> Compare: per-component portfolio returns vs leader hit rate')
    print('=' * 70)

    print(f'\n  Per-component TOP1, TOP3 portfolio performance (20D forward):')
    print(f'  {"Selector":10s} {"N":>4s} {"Top1 fwd20":>10s} {"Top3 fwd20":>10s} {"Top5 fwd20":>10s} '
          f'{"Top1 Win%":>10s} {"Top3 Win%":>10s} {"Top1=Leader":>12s}')
    print(f'  {"-"*78}')

    for selector, comp in [('Total', 'total'), ('W1', 'w1'), ('W2', 'w2'), ('W3', 'w3')]:
        t1_ret, t3_ret, t5_ret = [], [], []
        t1_win, t3_win, t1_leader = 0, 0, 0
        n = 0

        for w in windows:
            ranked = sorted(w['comps'].items(), key=lambda x: x[1][comp], reverse=True)
            syms = [s[0] for s in ranked]
            top1 = w['sector_data'].get(syms[0], {}).get('fwd20')
            top3 = np.mean([w['sector_data'].get(s, {}).get('fwd20', np.nan) for s in syms[:3] if w['sector_data'].get(s, {}).get('fwd20') is not None])
            top5 = np.mean([w['sector_data'].get(s, {}).get('fwd20', np.nan) for s in syms[:5] if w['sector_data'].get(s, {}).get('fwd20') is not None])
            bm_fwd = w['bm_fwd20']

            if top1 is None:
                continue
            t1_ret.append(top1)
            t1_win += 1 if top1 > bm_fwd else 0

            if not np.isnan(top3):
                t3_ret.append(top3)
                t3_win += 1 if top3 > bm_fwd else 0

            if not np.isnan(top5):
                t5_ret.append(top5)

            if syms[0] == w['leader_sym']:
                t1_leader += 1
            n += 1

        print(f'  {selector:10s} {n:4d}  {np.mean(t1_ret)*100:>+7.1f}%  {np.mean(t3_ret)*100:>+7.1f}%  '
              f'{np.mean(t5_ret)*100:>+7.1f}%  {t1_win/n*100:>6.1f}%  {t3_win/n*100:>6.1f}%  '
              f'{t1_leader/n*100:>8.1f}%')

    # P1 deeper: rank coherence — does W2 select a better "cluster"?
    print(f'\n  W2 vs W3: When they disagree, who wins?')
    print(f'  (Compare: sectors where W2 high but W3 low vs W3 high but W2 low)')

    w2_high_w3_low_ret = []
    w3_high_w2_low_ret = []
    for w in windows:
        ranked_w2 = sorted(w['comps'].items(), key=lambda x: x[1]['w2'], reverse=True)
        ranked_w3 = sorted(w['comps'].items(), key=lambda x: x[1]['w3'], reverse=True)

        w2_top3 = {s[0] for s in ranked_w2[:3]}
        w3_top3 = {s[0] for s in ranked_w3[:3]}

        # W2 exclusive (in W2 top3 but NOT in W3 top3)
        w2_only = w2_top3 - w3_top3
        w3_only = w3_top3 - w2_top3

        if w2_only:
            r = np.mean([w['sector_data'].get(s, {}).get('fwd20', np.nan) for s in w2_only if w['sector_data'].get(s, {}).get('fwd20') is not None])
            if not np.isnan(r):
                w2_high_w3_low_ret.append(r)
        if w3_only:
            r = np.mean([w['sector_data'].get(s, {}).get('fwd20', np.nan) for s in w3_only if w['sector_data'].get(s, {}).get('fwd20') is not None])
            if not np.isnan(r):
                w3_high_w2_low_ret.append(r)

    print(f'    W2-high-but-W3-low sectors (W2 exclusive): avg fwd20 = {np.mean(w2_high_w3_low_ret)*100:+.2f}% (n={len(w2_high_w3_low_ret)})')
    print(f'    W3-high-but-W2-low sectors (W3 exclusive): avg fwd20 = {np.mean(w3_high_w2_low_ret)*100:+.2f}% (n={len(w3_high_w2_low_ret)})')

    # P1: Check if W2-picked sectors are more "clustered" (top3 are close to each other)
    w2_clusters = []
    w3_clusters = []
    for w in windows:
        ranked_w2 = sorted(w['comps'].items(), key=lambda x: x[1]['w2'], reverse=True)
        ranked_w3 = sorted(w['comps'].items(), key=lambda x: x[1]['w3'], reverse=True)

        w2_fwd = [w['sector_data'].get(s[0], {}).get('fwd20') for s in ranked_w2[:3] if w['sector_data'].get(s[0], {}).get('fwd20') is not None]
        w3_fwd = [w['sector_data'].get(s[0], {}).get('fwd20') for s in ranked_w3[:3] if w['sector_data'].get(s[0], {}).get('fwd20') is not None]

        if len(w2_fwd) >= 2:
            w2_clusters.append(np.std(w2_fwd))
        if len(w3_fwd) >= 2:
            w3_clusters.append(np.std(w3_fwd))

    print(f'\n  Cluster coherence (low std = more consistent picks):')
    print(f'    W2 TOP3 fwd20 std: {np.mean(w2_clusters)*100:.2f}%')
    print(f'    W3 TOP3 fwd20 std: {np.mean(w3_clusters)*100:.2f}%')

    # ════════════════════════════════════════════
    # P2: Leading vs lagging indicator
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('P2: LEADING OR LAGGING INDICATOR?')
    print('    -> Correlation: score vs past returns vs future returns')
    print('=' * 70)

    # For each window, for each sector: compute correlation between score and past/future return
    # Aggregated across all windows
    all_pairs_past = []  # (score, past20), (score, past40), (score, past60)
    all_pairs_future = []  # (score, fwd20), (score, fwd40), (score, fwd60)

    for w in windows:
        comps = w['comps']
        sdata = w['sector_data']
        for sym, comp in comps.items():
            sd = sdata.get(sym, {})
            total = comp['total']
            if sd.get('past20') is not None:
                all_pairs_past.append((total, sd['past20'], 'past20'))
            if sd.get('past40') is not None:
                all_pairs_past.append((total, sd['past40'], 'past40'))
            if sd.get('past60') is not None:
                all_pairs_past.append((total, sd['past60'], 'past60'))
            if sd.get('fwd20') is not None:
                all_pairs_future.append((total, sd['fwd20'], 'fwd20'))
            if sd.get('fwd40') is not None:
                all_pairs_future.append((total, sd['fwd40'], 'fwd40'))
            if sd.get('fwd60') is not None:
                all_pairs_future.append((total, sd['fwd60'], 'fwd60'))

    from scipy.stats import pearsonr, spearmanr

    print(f'\n  Score vs Past Return (is the score describing what already happened?):')
    print(f'  {"Horizon":10s} {"Pearson r":>10s} {"p-value":>10s} {"Spearman":>10s} {"Direction":>15s}')
    print(f'  {"-"*60}')
    for h in ['past20', 'past40', 'past60']:
        pairs = [(s, r) for s, r, label in all_pairs_past if label == h]
        if len(pairs) < 10:
            continue
        scores = np.array([p[0] for p in pairs])
        returns = np.array([p[1] for p in pairs])
        pr, pp = pearsonr(scores, returns)
        sr, sp = spearmanr(scores, returns)
        dir_label = 'POSITIVE' if pr > 0 else 'NEGATIVE'
        print(f'  {h:10s}  {pr:>+7.4f}   {pp:.4f}   {sr:>+7.4f}   {dir_label:>15s}')

    print(f'\n  Score vs Forward Return (is the score predicting the future?):')
    print(f'  {"Horizon":10s} {"Pearson r":>10s} {"p-value":>10s} {"Spearman":>10s} {"Direction":>15s}')
    print(f'  {"-"*60}')
    for h in ['fwd20', 'fwd40', 'fwd60']:
        pairs = [(s, r) for s, r, label in all_pairs_future if label == h]
        if len(pairs) < 10:
            continue
        scores = np.array([p[0] for p in pairs])
        returns = np.array([p[1] for p in pairs])
        pr, pp = pearsonr(scores, returns)
        sr, sp = spearmanr(scores, returns)
        dir_label = 'POSITIVE' if pr > 0 else 'NEGATIVE'
        print(f'  {h:10s}  {pr:>+7.4f}   {pp:.4f}   {sr:>+7.4f}   {dir_label:>15s}')

    # Per-window correlation (is it stable or sporadic?)
    print(f'\n  Per-window Spearman: score rank vs fwd20 return rank')
    w_corrs = []
    for w in windows:
        scores = []
        rets = []
        for sym in w['comps']:
            sd = w['sector_data'].get(sym, {})
            r = sd.get('fwd20')
            if r is not None:
                scores.append(w['comps'][sym]['total'])
                rets.append(r)
        if len(scores) >= 10:
            sr, _ = spearmanr(scores, rets)
            w_corrs.append(sr)

    w_corrs = np.array(w_corrs)
    print(f'  Windows with positive rank correlation: {(w_corrs > 0).mean()*100:.1f}%')
    print(f'  Windows with negative rank correlation: {(w_corrs < 0).mean()*100:.1f}%')
    print(f'  Mean Spearman r: {w_corrs.mean():+.4f}')
    print(f'  Median Spearman r: {np.median(w_corrs):+.4f}')

    # ════════════════════════════════════════════
    # P2b: Does Beta (market return) explain the apparent correlation?
    # ════════════════════════════════════════════
    print(f'\n  P2b: Controlling for market — is the score just picking high-beta sectors?')
    print(f'  (In bull markets, high scores may just mean "high beta")')

    # Separate windows by market regime (bull/bear based on benchmark fwd20)
    bull_windows = [w for w in windows if w['bm_fwd20'] and w['bm_fwd20'] > 0]
    bear_windows = [w for w in windows if w['bm_fwd20'] and w['bm_fwd20'] <= 0]

    for regime, subset in [('Bull', bull_windows), ('Bear', bear_windows)]:
        pairs = []
        for w in subset:
            for sym in w['comps']:
                sd = w['sector_data'].get(sym, {})
                r = sd.get('fwd20')
                if r is not None:
                    pairs.append((w['comps'][sym]['total'], r))
        if len(pairs) < 10:
            continue
        scores = np.array([p[0] for p in pairs])
        rets = np.array([p[1] for p in pairs])
        pr, pp = pearsonr(scores, rets)
        print(f'    {regime:5s} windows: n_pairs={len(pairs):>5d}, Pearson r={pr:+.4f} (p={pp:.4f})')

    # ════════════════════════════════════════════
    # INTEGRATION: The three questions together
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('INTEGRATION')
    print('=' * 70)

    print(f'''
  P0 (Gap>=2): 
    -> If past returns INCREASE with gap while fwd returns DECREASE:
       = Strong evidence that W1/W2/W3 totals measure "completed momentum"
    -> If gap=1 is consistently the best forward bucket:
       = Moderate conviction = unfinished momentum = best risk/reward
    -> If gap>=2 is truly dead (not just small sample):
       = The model can identify "perfected patterns" but those don't lead

  P1 (W2 role):
    -> If W2-Top3 portfolio outperforms but W2-Top1 leader hit is low:
       = W2 predicts "cluster quality" not "single champion"
    -> If W3 has higher leader hit AND higher portfolio return:
       = W3 is genuinely better for both tasks
    -> If W2-exclusive picks outperform W3-exclusive picks:
       = W2 contains orthogonal information not captured by W3 alone

  P2 (Leading vs Lagging):
    -> If score correlates positively with past20/past40 but NOT with fwd20:
       = W1/W2/W3 is a trailing indicator (describes what happened)
    -> If score correlates positively with fwd20 (even weakly):
       = W1/W2/W3 has SOME leading predictive power
    -> If correlation is symmetric (~0 for both past and future):
       = W1/W2/W3 measures something orthogonal to momentum entirely
    -> If bull/bear regime changes the correlation sign:
       = W1/W2/W3 works differently in different regimes (state-dependent)
''')

    print('\n  Done.\n')


if __name__ == '__main__':
    main()
