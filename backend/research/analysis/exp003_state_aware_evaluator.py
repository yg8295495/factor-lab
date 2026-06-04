"""
EXP-003: Market State-Aware Sector Behavior Score — read-only evaluator.

Compares three variants side by side:
  A: EXP-002 baseline (W1/W2/W3, TOP 3, no state filter)
  B: State filter only (exposure per EXP-004 v0.5 state)
  C: State filter + sector breadth/amount confirmation bonus

Read-only from DB + EXP-004 output. No DB writes.
Outputs JSON to output/.

Usage:
    python backend/research/analysis/exp003_state_aware_evaluator.py
"""

import sqlite3
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
STATE_PATH = OUTPUT_DIR / 'market_state_daily_v05.json'  # EXP-004 v0.5 final

BM_SYMBOL = 'index.000985.SH'

# ── EXP-002 params (confirmed identical) ──
REBALANCE_INTERVAL = 20
HOLD_LOOKAHEAD = 20
TOP_N = 3
MIN_HISTORY = 120
TOP_N_CROWDING = 1

# ── EXP-004 v0.5 state priority ──
STATE_ORDER = ['RETREAT', 'MAIN_UP_CONFIRMED', 'REBOUND', 'CROWDING', 'CHAOS']
# States that allow sector holdings
ATTACK_STATES = {'MAIN_UP_CONFIRMED', 'CROWDING'}
# REBOUND sensitivity variants
REBOUND_VARIANTS = {
    'main': {'REBOUND': 'none'},          # primary
    'rebound_top1': {'REBOUND': 'top1'},  # sensitivity 1
    'rebound_half_top3': {'REBOUND': 'half'},  # sensitivity 2
}


# ────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────

def load_sector_data():
    """Load benchmark + 30 sector close and amount data."""
    conn = sqlite3.connect(str(DB_PATH))

    # Benchmark
    bm = pd.read_sql(
        'SELECT trade_date, close, amount FROM market_daily_data '
        'WHERE symbol = ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date'],
    ).set_index('trade_date').sort_index()

    # Sectors
    sec_raw = pd.read_sql(
        'SELECT d.symbol, a.name, d.trade_date, d.close, d.amount, '
        'd.above_ma20_ratio, d.above_ma60_ratio, d.new_high_20d_ratio, '
        'd.rs_positive_ratio, d.amount_ratio '
        'FROM market_daily_data d '
        'JOIN asset_master a ON d.symbol = a.symbol '
        'WHERE a.asset_type = \'sector\' '
        'ORDER BY d.trade_date, d.symbol',
        conn, parse_dates=['trade_date'],
    )

    conn.close()

    # Pivot sector data
    sec_close = sec_raw.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    sec_amount = sec_raw.pivot(index='trade_date', columns='symbol', values='amount').sort_index()
    sec_name = sec_raw[['symbol', 'name']].drop_duplicates().set_index('symbol')['name'].to_dict()

    # Pivot breadth/amount fields
    sec_ma20 = sec_raw.pivot(index='trade_date', columns='symbol', values='above_ma20_ratio').sort_index()
    sec_ma60 = sec_raw.pivot(index='trade_date', columns='symbol', values='above_ma60_ratio').sort_index()
    sec_nh = sec_raw.pivot(index='trade_date', columns='symbol', values='new_high_20d_ratio').sort_index()
    sec_ar = sec_raw.pivot(index='trade_date', columns='symbol', values='amount_ratio').sort_index()

    print(f'  Benchmark: {len(bm)} days')
    print(f'  Sectors:   {len(sec_close.columns)} symbols, {len(sec_close)} days')
    print(f'  Date:      {sec_close.index[0].date()} ~ {sec_close.index[-1].date()}')

    return bm, sec_close, sec_amount, sec_name, sec_ma20, sec_ma60, sec_nh, sec_ar


def load_market_states():
    """Load EXP-004 v0.5 daily states."""
    if not STATE_PATH.exists():
        print(f'  [WARN] State file not found: {STATE_PATH}')
        return None

    with open(STATE_PATH) as f:
        data = json.load(f)

    states = {}
    for day in data:
        states[day['trade_date']] = day['market_state']
    print(f'  Market states loaded: {len(states)} days')
    return states


# ────────────────────────────────────────────
# W1/W2/W3 scoring (replicating EXP-002 logic)
# ────────────────────────────────────────────

def score_sector(s_close, s_amount, bm_close, bm_amount, eval_idx):
    """
    Score one sector at eval_idx using W1/W2/W3 methodology.
    Returns total score (0-9) following EXP-002's calc_sector_rolling_score().
    """
    # Need enough history
    if eval_idx < 100:
        return None

    # Get data windows (relative to eval_idx, same as EXP-002's virtual_bottom approach)
    # Virtual bottom = eval_idx - 90
    virtual_bottom = eval_idx - 90
    if virtual_bottom < 0:
        return None

    close = s_close.iloc[:eval_idx + 1]
    amount = s_amount.iloc[:eval_idx + 1]
    bm_c = bm_close.iloc[:eval_idx + 1]
    bm_a = bm_amount.iloc[:eval_idx + 1]

    # W1: T-60~T-40 (放量震荡)
    w1_start = eval_idx - 60
    w1_end = eval_idx - 40
    # W2: T-40~T-20 (缩量洗盘)
    w2_start = eval_idx - 40
    w2_end = eval_idx - 20
    # W3: T-20~T (初升试探)
    w3_start = eval_idx - 20
    w3_end = eval_idx

    if any(s < 0 for s in [w1_start, w2_start, w3_start]):
        return None

    # Compute rolling metrics (simplified from precompute_sector_metrics)
    ret = close.pct_change()
    bm_ret = bm_c.pct_change()
    rolling_vol = ret.rolling(20, min_periods=10).std()
    bm_rolling_vol = bm_ret.rolling(20, min_periods=10).std()

    score = 0

    # W1: volatility expansion + volume amplification
    vol_w1 = rolling_vol.iloc[w1_start:w1_end].mean()
    vol_pre = rolling_vol.iloc[max(0, w1_start-60):w1_start].mean() if w1_start >= 60 else 0
    amt_w1 = amount.iloc[w1_start:w1_end].mean()
    amt_pre = amount.iloc[max(0, w1_start-60):w1_start].mean() if w1_start >= 60 else 0

    if vol_pre > 0 and vol_w1 > vol_pre * 1.2:
        score += 1
    if amt_pre > 0 and amt_w1 > amt_pre * 1.1:
        score += 1
    # Relative volatility
    bm_vol_w1 = bm_rolling_vol.iloc[w1_start:w1_end].mean()
    if bm_vol_w1 > 0 and vol_w1 / bm_vol_w1 > 1.1:
        score += 1

    # W2: volume contraction
    amt_w2 = amount.iloc[w2_start:w2_end].mean()
    amt_pre_w2 = amount.iloc[max(0, w1_start-60):w1_start].mean() if w1_start >= 60 else 0
    if amt_pre_w2 > 0 and amt_w2 < amt_pre_w2 * 0.9:
        score += 1
    # Price decline
    ret_w2 = close.iloc[w2_end] / close.iloc[w2_start] - 1
    if ret_w2 < -0.02:
        score += 1
    # Loss relative to benchmark
    bm_ret_w2 = bm_c.iloc[w2_end] / bm_c.iloc[w2_start] - 1
    if ret_w2 < bm_ret_w2:
        score += 1

    # W3: price recovery + volume confirmation
    ret_w3 = close.iloc[w3_end] / close.iloc[w3_start] - 1
    bm_ret_w3 = bm_c.iloc[w3_end] / bm_c.iloc[w3_start] - 1
    if ret_w3 > bm_ret_w3:
        score += 1
    # Above MA20 at W3 end
    ma20 = close.rolling(20, min_periods=10).mean().iloc[w3_end]
    if close.iloc[w3_end] > ma20:
        score += 1
    # Volume in W3
    amt_w3 = amount.iloc[w3_start:w3_end].mean()
    if amt_pre_w2 > 0 and amt_w3 > amt_pre_w2:
        score += 1

    return score


def get_sector_breadth_bonus(sym, eval_idx, sec_ma20, sec_ma60, sec_nh, sec_ar):
    """
    Compute breadth + amount bonus for Variant C.
    Returns adjustment to base score.
    """
    bonus = 0.0

    # Breadth bonuses
    val = sec_ma20[sym].iloc[eval_idx] if sym in sec_ma20.columns and eval_idx < len(sec_ma20) else None
    if val is not None and not pd.isna(val) and val >= 0.60:
        bonus += 0.5
    if val is not None and not pd.isna(val) and val <= 0.40:
        bonus -= 0.5

    val = sec_ma60[sym].iloc[eval_idx] if sym in sec_ma60.columns and eval_idx < len(sec_ma60) else None
    if val is not None and not pd.isna(val) and val >= 0.50:
        bonus += 0.5

    val = sec_nh[sym].iloc[eval_idx] if sym in sec_nh.columns and eval_idx < len(sec_nh) else None
    if val is not None and not pd.isna(val) and val >= 0.10:
        bonus += 0.5

    # Amount bonus
    val = sec_ar[sym].iloc[eval_idx] if sym in sec_ar.columns and eval_idx < len(sec_ar) else None
    if val is not None and not pd.isna(val):
        if val >= 1.10:
            bonus += 0.5
        elif val <= 0.90:
            bonus -= 0.5

    return bonus


# ────────────────────────────────────────────
# Variant computation
# ────────────────────────────────────────────

def compute_variant(variant_name, state_handling, scores_df, sec_close, bm_close,
                    sec_name=None,
                    sec_ma20=None, sec_ma60=None, sec_nh=None, sec_ar=None):
    """
    Compute a variant's nav and trade log.
    
    state_handling: dict with keys like {'REBOUND': 'none'|'top1'|'half'}
    """
    all_dates = scores_df.index
    trade_log = []

    for i in range(len(scores_df)):
        row = scores_df.iloc[i]
        eval_date = row.name
        state = row['state']

        # Determine top count based on state
        if state not in ATTACK_STATES:
            if state == 'REBOUND':
                rebound_action = state_handling.get('REBOUND', 'none')
                if rebound_action == 'none':
                    continue
                elif rebound_action == 'top1':
                    top_n = 1
                    weight_factor = 1.0
                elif rebound_action == 'half':
                    top_n = 3
                    weight_factor = 0.5
                else:
                    continue
            else:
                continue
        elif state == 'CROWDING':
            top_n = TOP_N_CROWDING
            weight_factor = 1.0
        else:
            top_n = TOP_N
            weight_factor = 1.0

        # Get sorted sectors
        if variant_name == 'C':
            # Apply bonus
            scores = []
            for sym in row['sector_scores'].keys():
                base = row['sector_scores'][sym]
                bonus = get_sector_breadth_bonus(sym, i, sec_ma20, sec_ma60, sec_nh, sec_ar)
                scores.append((sym, base + bonus))
            scores.sort(key=lambda x: x[1], reverse=True)
        else:
            scores = sorted(row['sector_scores'].items(), key=lambda x: x[1], reverse=True)

        top_syms = [s[0] for s in scores[:top_n]]
        top_scores = [s[1] for s in scores[:top_n]]
        top_names = [sec_name.get(s, s) for s in top_syms]

        # Equal weight (or half weight for REBOUND variant)
        weight = (1.0 / top_n) * weight_factor

        trade_log.append({
            'eval_date': str(eval_date.date()),
            'state': state,
            'top_sectors': top_names,
            'top_scores': [round(s, 2) for s in top_scores],
            'weight': round(weight, 4),
        })

    return trade_log


def compute_shared_benchmark_nav(bm_close, eval_dates):
    """Pre-compute benchmark NAV on a shared date grid."""
    nav = [1.0]
    for i in range(len(eval_dates) - 1):
        start = eval_dates[i]
        end = eval_dates[i + 1]
        series = bm_close.dropna()
        try:
            p_start = series.loc[series.index >= start].iloc[0] if any(series.index >= start) else None
            p_end = series.loc[series.index <= end].iloc[-1] if any(series.index <= end) else None
            if p_start and p_end and p_start > 0:
                ret = (p_end / p_start - 1) * 100
            else:
                ret = 0.0
        except (IndexError, KeyError):
            ret = 0.0
        nav.append(nav[-1] * (1 + ret / 100))
    return nav  # len = len(eval_dates)


def compute_nav(trade_log, sec_close, bm_close, eval_dates, sec_name, bm_nav):
    """Build strategy nav from trade log, using pre-computed shared benchmark path."""
    # Build lookup: eval_date -> holdings info from trade_log
    holdings_map = {}  # eval_date -> list of (sym, weight)
    sym_by_name = {v: k for k, v in sec_name.items()}

    for log_entry in trade_log:
        eval_date = pd.Timestamp(log_entry['eval_date'])
        top_names = log_entry['top_sectors']
        weight = log_entry['weight']
        holdings = []
        for name in top_names:
            sym = sym_by_name.get(name)
            if sym and sym in sec_close.columns:
                holdings.append((sym, weight))
        holdings_map[eval_date] = holdings

    strategy_nav = [1.0]
    peak = 1.0
    max_dd = 0.0

    for i in range(len(eval_dates) - 1):
        start = eval_dates[i]
        end = eval_dates[i + 1]

        holdings = holdings_map.get(start, [])

        if not holdings:
            sec_ret = 0.0
        else:
            sec_ret = 0.0
            for sym, w in holdings:
                series = sec_close[sym].dropna()
                try:
                    p_start = series.loc[series.index >= start].iloc[0] if any(series.index >= start) else None
                    p_end = series.loc[series.index <= end].iloc[-1] if any(series.index <= end) else None
                    if p_start and p_end and p_start > 0:
                        ret = (p_end / p_start - 1) * 100
                        sec_ret += w * ret
                except (IndexError, KeyError):
                    continue

        strat_new = strategy_nav[-1] * (1 + sec_ret / 100)
        strategy_nav.append(strat_new)

        peak = max(peak, strat_new)
        dd = (strat_new - peak) / peak * 100
        max_dd = min(max_dd, dd)

    return {
        'strategy_nav': [round(v, 6) for v in strategy_nav],
        'benchmark_nav': [round(v, 6) for v in bm_nav],
        'dates': [str(d.date()) for d in eval_dates],
        'total_return': round((strategy_nav[-1] / strategy_nav[0] - 1) * 100, 2),
        'bm_return': round((bm_nav[-1] / bm_nav[0] - 1) * 100, 2),
        'excess_return': round((strategy_nav[-1] / strategy_nav[0] - 1 - (bm_nav[-1] / bm_nav[0] - 1)) * 100, 2),
        'max_drawdown_pct': round(max_dd, 2),
    }


# ────────────────────────────────────────────
# Main
# ────────────────────────────────────────────

def main():
    print('=' * 60)
    print('EXP-003: Market State-Aware Sector Behavior Score')
    print('=' * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ──
    print('\n[1/4] Loading sector data...')
    bm, sec_close, sec_amount, sec_name, sec_ma20, sec_ma60, sec_nh, sec_ar = load_sector_data()

    print('\n[2/4] Loading market states...')
    states = load_market_states()
    if states is None:
        print('  ERROR: no state file')
        return

    # ── 2. Run scoring ──
    print('\n[3/4] Computing W1/W2/W3 scores (replicating EXP-002)...')
    all_dates = bm.index
    bm_close = bm['close']
    bm_amount = bm['amount']
    sym_list = list(sec_close.columns)

    start_idx = MIN_HISTORY
    eval_indices = list(range(start_idx, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))

    scores_records = []
    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        date_str = str(eval_date.date())

        sector_scores = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue

            score = score_sector(
                s_close, s_amount, bm_close, bm_amount, eval_idx
            )
            if score is not None and 0 < score <= 9:
                sector_scores[sym] = score

        if not sector_scores:
            continue

        # Determine state for this eval_date
        state = states.get(date_str, 'CHAOS')
        scores_records.append({
            'eval_date': eval_date,
            'date_str': date_str,
            'state': state,
            'sector_scores': sector_scores,
        })

    print(f'  Scored {len(scores_records)} rebalance windows')

    # ── 3. Compute variants ──
    print('\n[4/4] Computing variants and NAV...')

    scores_df = pd.DataFrame(scores_records)
    scores_df = scores_df.set_index('eval_date')

    results = {}

    # Variant A: EXP-002 baseline (no state filter)
    trade_log_a = []
    for idx, row in scores_df.iterrows():
        scores = sorted(row['sector_scores'].items(), key=lambda x: x[1], reverse=True)
        top_syms = [s[0] for s in scores[:TOP_N]]
        top_names = [sec_name.get(s, s) for s in top_syms]
        top_scores = [s[1] for s in scores[:TOP_N]]
        trade_log_a.append({
            'eval_date': str(idx.date()),
            'state': row['state'],
            'top_sectors': top_names,
            'top_scores': [round(s, 2) for s in top_scores],
            'weight': 1.0 / TOP_N,
        })
    results['A_baseline'] = trade_log_a

    # Variant B: state filter only (main: REBOUND=none)
    trade_log_b = compute_variant('B', REBOUND_VARIANTS['main'], scores_df,
                                   sec_close, bm_close, sec_name=sec_name)
    results['B_state_filter'] = trade_log_b

    # Variant C: state + sector confirmation
    trade_log_c = compute_variant('C', REBOUND_VARIANTS['main'], scores_df,
                                   sec_close, bm_close, sec_name=sec_name,
                                   sec_ma20=sec_ma20, sec_ma60=sec_ma60,
                                   sec_nh=sec_nh, sec_ar=sec_ar)
    results['C_state_confirmed'] = trade_log_c

    # Sensitivity variants
    for sens_name, handling in REBOUND_VARIANTS.items():
        if sens_name == 'main':
            continue
        tb = compute_variant('B', handling, scores_df, sec_close, bm_close,
                               sec_name=sec_name)
        tc = compute_variant('C', handling, scores_df, sec_close, bm_close,
                               sec_name=sec_name,
                               sec_ma20=sec_ma20, sec_ma60=sec_ma60,
                               sec_nh=sec_nh, sec_ar=sec_ar)
        results[f'B_sens_{sens_name}'] = tb
        results[f'C_sens_{sens_name}'] = tc

    # Compute shared benchmark NAV
    print('  Pre-computing shared benchmark NAV...')
    bm_nav = compute_shared_benchmark_nav(bm_close, scores_df.index)

    # Compute NAV for each variant
    nav_results = {}
    for v_name, trade_log in results.items():
        nav = compute_nav(trade_log, sec_close, bm_close, scores_df.index, sec_name, bm_nav)
        nav_results[v_name] = nav

    # ── Phase-level stats ──
    # Load phases for per-state breakdown
    PHASES_CSV = Path(__file__).resolve().parents[1] / 'labeling' / 'labels' / 'market_phases.csv'
    phases_df = None
    if PHASES_CSV.exists():
        phases_df = pd.read_csv(PHASES_CSV, comment='#', parse_dates=['start_date', 'end_date'])
        last = phases_df.iloc[-1]
        if pd.isna(last['end_date']) or str(last['end_date']).strip() == '至今':
            phases_df.at[phases_df.index[-1], 'end_date'] = datetime.now().strftime('%Y-%m-%d')
            phases_df['end_date'] = pd.to_datetime(phases_df['end_date'])

    # Per-state trade count
    per_state = defaultdict(lambda: {'windows': 0, 'states': defaultdict(int)})
    for idx, row in scores_df.iterrows():
        per_state['all']['windows'] += 1
        per_state['all']['states'][row['state']] += 1
        per_state[row['state']]['windows'] += 1

    # ── Write output ──
    output = {
        'experiment': 'EXP-003',
        'exp004_version': 'v0.5 final',
        'description': 'Market state-aware sector behavior score',
        'parameters': {
            'rebalance_interval': REBALANCE_INTERVAL,
            'hold_lookahead': HOLD_LOOKAHEAD,
            'top_n': TOP_N,
            'top_n_crowding': TOP_N_CROWDING,
            'min_history': MIN_HISTORY,
            'benchmark': BM_SYMBOL,
            'transaction_cost': 'none',
        },
        'state_actions': {
            'MAIN_UP_CONFIRMED': 'TOP 3 equal weight',
            'REBOUND': 'none (main), top1/half sensitivity',
            'CROWDING': 'TOP 1 equal weight',
            'CHAOS': 'no holdings',
            'RETREAT': 'no holdings',
        },
        'window_summary': {
            'total_rebalance_windows': len(scores_df),
            'state_distribution': dict(per_state['all']['states']),
        },
        'variant_summary': {},
        'detailed_results': {},
    }

    # Compute per-state performance for each variant using trade logs
    # (detailed per-state return computation reserved for v1.1)
    for v_name, nav in nav_results.items():
        output['variant_summary'][v_name] = {
            'total_return_pct': nav['total_return'],
            'benchmark_return_pct': nav['bm_return'],
            'excess_return_pct': nav['excess_return'],
            'max_drawdown_pct': nav['max_drawdown_pct'],
        }

    # Write output
    out_path = OUTPUT_DIR / 'exp003_state_aware_behavior_score.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ── Print summary ──
    print(f'\n{"="*60}')
    print('SUMMARY')
    print(f'{"="*60}')
    print(f'  Total rebalance windows: {len(scores_df)}')

    print(f'\n  State distribution:')
    for s in STATE_ORDER:
        cnt = per_state[s]['windows']
        if cnt > 0:
            print(f'    {s:22s}: {cnt} windows')

    print(f'\n  Variant comparison:')
    print(f'  {"Variant":30s} {"Return":>8s} {"BM":>8s} {"Excess":>8s} {"MaxDD":>8s}')
    print(f'  {"-"*62}')
    for v_name in ['A_baseline', 'B_state_filter', 'C_state_confirmed',
                   'B_sens_rebound_top1', 'C_sens_rebound_top1']:
        n = nav_results.get(v_name)
        if n:
            print(f'  {v_name:30s} {n["total_return"]:>7.1f}% {n["bm_return"]:>7.1f}% {n["excess_return"]:>7.1f}% {n["max_drawdown_pct"]:>7.1f}%')

    print(f'\n  Output: {out_path}')
    print('\nEXP-003 evaluator complete')


if __name__ == '__main__':
    main()
