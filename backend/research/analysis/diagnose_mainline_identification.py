"""
Diagnostic: Why is main-line (Leader) identification near random?

Reads from DB, computes W1/W2/W3 scores for all 30 sectors on each rebalance
window, then compares score-based selections against the actual future leader.

Diagnostic chain:
  1. Score flatness      — can scores differentiate sectors?
  2. Leader rank dist    — where does the true leader rank by score?
  3. Component analysis  — W1/W2/W3 separation: Leader vs Top1
  4. Gap × Leader hit    — does larger gap predict better hit?
  5. Forward rank        — where does score-Top1 rank by forward return?
"""

import sqlite3
import json
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
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
    print(f'  Date:      {sec_close.index[0].date()} ~ {sec_close.index[-1].date()}')
    return bm, sec_close, sec_amount, sec_name


def score_components(s_close, s_amount, bm_close, bm_amount, eval_idx):
    if eval_idx < 100:
        return None
    virtual_bottom = eval_idx - 90
    if virtual_bottom < 0:
        return None
    close = s_close.iloc[:eval_idx + 1]
    amount = s_amount.iloc[:eval_idx + 1]
    bm_c = bm_close.iloc[:eval_idx + 1]

    w1_s, w1_e = eval_idx - 60, eval_idx - 40
    w2_s, w2_e = eval_idx - 40, eval_idx - 20
    w3_s, w3_e = eval_idx - 20, eval_idx

    if any(s < 0 for s in [w1_s, w2_s, w3_s]):
        return None

    ret = close.pct_change()
    bm_ret = bm_c.pct_change()
    rvol = ret.rolling(20, min_periods=10).std()
    bm_rvol = bm_ret.rolling(20, min_periods=10).std()

    total = w1 = w2 = w3 = 0

    # W1: volatility expansion + volume amplification
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

    # W2: volume contraction + price decline
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

    # W3: price recovery + volume confirmation
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


def fwd_ret(series, ix, h=HOLD_LOOKAHEAD):
    if ix + h >= len(series):
        return None
    return series.iloc[ix + h] / series.iloc[ix] - 1


def main():
    print('=' * 70)
    print('DIAGNOSTIC: Main-Line Identification Analysis')
    print('=' * 70)

    # ── 1. Load ──
    print('\n[1/4] Loading data...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close, bm_amount = bm['close'], bm['amount']
    all_dates = bm.index
    sym_list = list(sec_close.columns)

    # ── 2. Score every sector, every eval window ──
    print('\n[2/4] Scoring all sectors on each rebalance window...')
    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
    print(f'  Total eval windows: {len(eval_indices)}')

    # Per-window storage: store ALL sector components for diagnostic 3
    windows = []          # main list of per-window diagnostics
    all_window_scores = {}  # date -> {sym -> components}   (for D3)

    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        ds = str(eval_date.date())

        # Compute score components for every sector
        comps = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue
            c = score_components(s_close, s_amount, bm_close, bm_amount, eval_idx)
            if c and 0 < c['total'] <= 9:
                comps[sym] = c

        if not comps:
            continue
        all_window_scores[ds] = comps

        # Compute forward 20D return for each sector
        fwdrs = {}
        for sym in comps:
            r = fwd_ret(sec_close[sym].dropna(), eval_idx)
            if r is not None:
                fwdrs[sym] = r
        if not fwdrs:
            continue

        # Actual leader = best forward return
        leader_sym = max(fwdrs, key=fwdrs.get)
        leader_ret = fwdrs[leader_sym]

        # Rank sectors by total score
        ranked = sorted(comps.items(), key=lambda x: x[1]['total'], reverse=True)
        top1_sym, top1_comp = ranked[0]
        top1_score = top1_comp['total']
        top1_ret = fwdrs.get(top1_sym)

        # Top3 avg return
        top3_ret = np.mean([fwdrs.get(s[0], 0) for s in ranked[:3]])

        # Score gap
        gap = ranked[0][1]['total'] - ranked[1][1]['total'] if len(ranked) >= 2 else 0

        # Leader's rank by score
        leader_rank = next((i+1 for i, (s, _) in enumerate(ranked) if s == leader_sym), None)

        # Top1's rank by forward return
        ranked_fwd = sorted(fwdrs.items(), key=lambda x: x[1], reverse=True)
        top1_fwd_rank = next((i+1 for i, (s, _) in enumerate(ranked_fwd) if s == top1_sym), None)

        windows.append({
            'date': ds,
            'eval_idx': eval_idx,
            'n_scored': len(comps),
            'leader_sym': leader_sym,
            'leader_name': sec_name.get(leader_sym, leader_sym),
            'leader_ret_pct': round(leader_ret * 100, 2),
            'leader_total': comps[leader_sym]['total'],
            'leader_w1': comps[leader_sym]['w1'],
            'leader_w2': comps[leader_sym]['w2'],
            'leader_w3': comps[leader_sym]['w3'],
            'leader_rank': leader_rank,
            'top1_sym': top1_sym,
            'top1_name': sec_name.get(top1_sym, top1_sym),
            'top1_score': top1_score,
            'top1_ret_pct': round(top1_ret * 100, 2) if top1_ret is not None else None,
            'top1_fwd_rank': top1_fwd_rank,
            'top1_w1': top1_comp['w1'],
            'top1_w2': top1_comp['w2'],
            'top1_w3': top1_comp['w3'],
            'top3_avg_ret_pct': round(top3_ret * 100, 2),
            'gap': gap,
            'all_scores': [s[1]['total'] for s in ranked],
        })

    print(f'  Windows collected: {len(windows)}')

    # ════════════════════════════════════════════
    # D1: Score flatness
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('D1: SCORE FLATNESS — can scores differentiate sectors?')
    print('=' * 70)

    gaps = np.array([w['gap'] for w in windows])
    unique_scores = [len(set(w['all_scores'])) for w in windows]

    print(f'\n  Top1-Top2 score gap:')
    print(f'    Mean:    {gaps.mean():.2f}')
    print(f'    Median:  {np.median(gaps):.2f}')
    print(f'    Gap=0:   {(gaps==0).mean()*100:.1f}%')
    print(f'    Gap=1:   {(gaps==1).mean()*100:.1f}%')
    print(f'    Gap>=2:  {(gaps>=2).mean()*100:.1f}%')
    print(f'    Gap>=3:  {(gaps>=3).mean()*100:.1f}%')
    print(f'    Gap>=4:  {(gaps>=4).mean()*100:.1f}%')

    print(f'\n  Unique score levels per window:')
    print(f'    Mean: {np.mean(unique_scores):.1f}  Median: {np.median(unique_scores):.0f}')
    print(f'    Min: {min(unique_scores)}  Max: {max(unique_scores)}')
    print(f'    Windows with ≤3 levels: {(np.array(unique_scores)<=3).mean()*100:.1f}%')

    # Global score distribution
    all_scores = []
    for w in windows:
        all_scores.extend(w['all_scores'])
    c = Counter(all_scores)
    total_s = len(all_scores)
    print(f'\n  Global score distribution ({total_s} total):')
    for k in sorted(c):
        p = c[k] / total_s * 100

    # ════════════════════════════════════════════
    # D2: Leader rank distribution
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('D2: LEADER RANK DISTRIBUTION — where does the true leader rank by score?')
    print('=' * 70)

    ranks = [w['leader_rank'] for w in windows]
    rank_c = Counter(ranks)
    n_win = len(windows)

    print(f'\n  Leader score rank distribution (out of ~30 sectors):')
    for r in range(1, 31):
        cnt = rank_c.get(r, 0)
        pct = cnt / n_win * 100
        bar_len = int(cnt / max(rank_c.values()) * 30) if max(rank_c.values()) > 0 else 0
        if cnt > 0:
            print(f'  Rank {r:2d}: {cnt:3d} ({pct:5.1f}%)  {"█" * bar_len}')
        else:
            print(f'  Rank {r:2d}:  0  ( 0.0%)')

    print(f'\n  Cumulative:')
    for top_n in [1, 3, 5, 10, 15, 20, 25]:
        hits = sum(1 for w in windows if w['leader_rank'] <= top_n)
        rand = top_n / 30 * 100
        print(f'  Leader in Top{top_n:<2d}: {hits:3d}/{n_win} ({hits/n_win*100:.1f}%)  [random: {rand:.1f}%]')

    # ════════════════════════════════════════════
    # D3: Component breakdown — Leader vs Top1
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('D3: COMPONENT ANALYSIS — what do Leader and Top1 look like?')
    print('=' * 70)

    fields = [('W1', 'w1'), ('W2', 'w2'), ('W3', 'w3')]
    print(f'\n  {"Comp":8s} {"Leader avg":>10s} {"Top1 avg":>10s} {"Diff":>8s} {"Leader med":>10s}')
    print(f'  {"-"*48}')
    for label, field in fields:
        lvals = [w[f'leader_{field}'] for w in windows]
        tvals = [w[f'top1_{field}'] for w in windows]
        l_mu = np.mean(lvals)
        t_mu = np.mean(tvals)
        l_med = np.median(lvals)
        print(f'  {label:8s} {l_mu:>8.2f}     {t_mu:>8.2f}     {l_mu - t_mu:>+6.2f}    {l_med:>8.2f}')

    # Per-component selection: what if we selected by each component alone?
    print(f'\n  Per-component leader ID (rank-based):')
    for comp in ['w1', 'w2', 'w3']:
        hits = 0
        for w in windows:
            ds = w['date']
            comps = all_window_scores.get(ds, {})
            if not comps:
                continue
            best = max(comps.items(), key=lambda x: x[1][comp])
            if best[0] == w['leader_sym']:
                hits += 1
        pct = hits / len(windows) * 100
        print(f'  Select by {comp.upper():2s} alone: {hits:3d}/{len(windows)} ({pct:.1f}%)  [random: 3.3%]')

    # Leader component distribution (box stats)
    print(f'\n  Leader score components (all windows):')
    for comp in ['w1', 'w2', 'w3']:
        vals = [w[f'leader_{comp}'] for w in windows]
        vals_arr = np.array(vals)
        unique, counts = np.unique(vals_arr, return_counts=True)
        print(f'  {comp.upper():2s}: mean={vals_arr.mean():.2f} median={np.median(vals_arr):.0f} ', end='')
        for u, c in zip(unique, counts):
            print(f'{int(u)}={c}({c/len(windows)*100:.0f}%) ', end='')
        print()

    # ════════════════════════════════════════════
    # D4: Gap vs Leader hit
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('D4: GAP × LEADER HIT — does larger gap predict better leader ID?')
    print('=' * 70)

    gap_buckets = [(0, 0, 'Gap=0'), (1, 1, 'Gap=1'), (2, 2, 'Gap=2'), (3, 99, 'Gap≥3')]
    print(f'\n  {"Bucket":10s} {"N":>4s} {"Top1=Leader":>13s} {"Top3=Leader":>14s} {"Avg Leader Rank":>17s}')
    print(f'  {"-"*60}')
    for lo, hi, label in gap_buckets:
        subset = [w for w in windows if lo <= w['gap'] <= hi]
        if not subset:
            continue
        n = len(subset)
        top1_hit = sum(1 for w in subset if w['leader_rank'] == 1)
        top3_hit = sum(1 for w in subset if w['leader_rank'] <= 3)
        avg_rank = np.mean([w['leader_rank'] for w in subset])
        print(f'  {label:10s} {n:4d}   {top1_hit:3d}/{n} ({top1_hit/n*100:.1f}%)   {top3_hit:3d}/{n} ({top3_hit/n*100:.1f}%)     {avg_rank:.1f}')

    # ════════════════════════════════════════════
    # D5: Top1 forward return rank
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('D5: TOP1 FORWARD RANK — where does score-Top1 rank by future return?')
    print('=' * 70)

    fwd_ranks = np.array([w['top1_fwd_rank'] for w in windows if w['top1_fwd_rank'] is not None])
    n_fwd = len(fwd_ranks)
    rank_d = Counter(fwd_ranks)

    print(f'\n  Score-Top1 forward return rank (1 = best of 30, 30 = worst):')
    for r in range(1, min(16, n_fwd + 1)):
        cnt = rank_d.get(r, 0)
        pct = cnt / n_fwd * 100
        print(f'  Rank {r:2d}: {cnt:3d} ({pct:5.1f}%)')

    for top_n in [1, 3, 5, 10, 15]:
        hits = sum(1 for r in fwd_ranks if r <= top_n)
        rand = top_n / 30 * 100
        print(f'  Score-Top1 in forward Top{top_n:<2d}: {hits:3d}/{n_fwd} ({hits/n_fwd*100:.1f}%)  [random: {rand:.1f}%]')

    # ════════════════════════════════════════════
    # D6: Top3 capture analysis
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('D6: TOP3 BEHAVIOR — how does Top3 capture the leader?')
    print('=' * 70)

    # Compare: Top3 avg return vs Leader return
    cap_ratios = []
    for w in windows:
        lr = w['leader_ret_pct']
        t3 = w['top3_avg_ret_pct']
        if lr > 0:
            cap_ratios.append(min(t3 / lr, 1.0))
        elif lr < 0:
            cap_ratios.append(max(t3 / lr, 1.0))  # losing less is good
        else:
            cap_ratios.append(0)

    cap_arr = np.array(cap_ratios)
    print(f'\n  Capture ratio (Top3 ret / Leader ret):')
    print(f'    Mean:  {cap_arr.mean()*100:.1f}%')
    print(f'    Median: {np.median(cap_arr)*100:.1f}%')
    print(f'    P25:   {np.percentile(cap_arr, 25)*100:.1f}%')
    print(f'    P75:   {np.percentile(cap_arr, 75)*100:.1f}%')

    # When does Top3 beat random chance on capture?
    # Leader rank bucket -> avg capture
    print(f'\n  Capture ratio by Leader score rank bucket:')
    for lo, hi, label in [(1, 3, 'Rank 1-3'), (4, 10, 'Rank 4-10'), (11, 30, 'Rank 11-30')]:
        subset = [w for w in windows if lo <= w['leader_rank'] <= hi]
        if not subset:
            continue
        avg_cap = np.mean([min(w['top3_avg_ret_pct'] / max(w['leader_ret_pct'], 0.01), 1.0) if w['leader_ret_pct'] > 0 else 0 for w in subset]) * 100
        n = len(subset)
        print(f'    Leader {label:15s}: n={n:3d}, avg capture ratio={avg_cap:.1f}%')

    # ════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('SUMMARY: DIAGNOSTIC CONCLUSIONS')
    print('=' * 70)

    top1_hit = rank_c.get(1, 0) / n_win * 100
    top3_hit = sum(rank_c.get(r, 0) for r in [1, 2, 3]) / n_win * 100
    top5_hit = sum(rank_c.get(r, 0) for r in [1, 2, 3, 4, 5]) / n_win * 100

    print(f'\n  Top1 Leader Hit:   {top1_hit:.1f}%  (random: 3.3%)')
    print(f'  Top3 Leader Hit:   {top3_hit:.1f}%  (random: 10.0%)')
    print(f'  Top5 Leader Hit:   {top5_hit:.1f}%  (random: 16.7%)')
    print(f'')
    print(f'  Avg Top1-Top2 gap: {gaps.mean():.2f}')
    print(f'  Tie rate:          {(gaps==0).mean()*100:.1f}%')
    print(f'  Gap>=2 rate:       {(gaps>=2).mean()*100:.1f}%')
    print(f'')
    print(f'  Score-Top1 in forward Top5: ... (see D5)')
    print(f'')
    print(f'  === INTERPRETATION ===')
    print(f'  If Leader rank distribution is flat (~random):')
    print(f'    → W1/W2/W3 scores do NOT contain leader-prediction information')
    print(f'    → Even when scores strongly agree (gap>=2), leader hit is still low')
    print(f'    → This means new factor(s) are needed, not score tuning')
    print(f'')
    print(f'  If Leader is concentrated at rank 1-5 but gap is small:')
    print(f'    → Scores have signal but low resolution; need continuous scoring')
    print(f'')
    print(f'  If gap>=2 gives much higher leader hit than gap=0:')
    print(f'    → Weighting/selection approach is the problem, not the factor')

    print('\n  Done.')


if __name__ == '__main__':
    main()
