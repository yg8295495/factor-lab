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
    components = _score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx)
    return components['total'] if components else None


def score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx):
    """
    Score one sector and return full W1/W2/W3 component breakdown.
    Returns dict {w1, w2, w3, total} or None.
    """
    return _score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx)


def _score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx):
    """
    Core scoring: returns dict with w1/w2/w3/total scores, or None if insufficient data.
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
    w1_score = 0
    w2_score = 0
    w3_score = 0

    # W1: volatility expansion + volume amplification
    vol_w1 = rolling_vol.iloc[w1_start:w1_end].mean()
    vol_pre = rolling_vol.iloc[max(0, w1_start-60):w1_start].mean() if w1_start >= 60 else 0
    amt_w1 = amount.iloc[w1_start:w1_end].mean()
    amt_pre = amount.iloc[max(0, w1_start-60):w1_start].mean() if w1_start >= 60 else 0

    if vol_pre > 0 and vol_w1 > vol_pre * 1.2:
        score += 1; w1_score += 1
    if amt_pre > 0 and amt_w1 > amt_pre * 1.1:
        score += 1; w1_score += 1
    # Relative volatility
    bm_vol_w1 = bm_rolling_vol.iloc[w1_start:w1_end].mean()
    if bm_vol_w1 > 0 and vol_w1 / bm_vol_w1 > 1.1:
        score += 1; w1_score += 1

    # W2: volume contraction
    amt_w2 = amount.iloc[w2_start:w2_end].mean()
    amt_pre_w2 = amount.iloc[max(0, w1_start-60):w1_start].mean() if w1_start >= 60 else 0
    if amt_pre_w2 > 0 and amt_w2 < amt_pre_w2 * 0.9:
        score += 1; w2_score += 1
    # Price decline
    ret_w2 = close.iloc[w2_end] / close.iloc[w2_start] - 1
    if ret_w2 < -0.02:
        score += 1; w2_score += 1
    # Loss relative to benchmark
    bm_ret_w2 = bm_c.iloc[w2_end] / bm_c.iloc[w2_start] - 1
    if ret_w2 < bm_ret_w2:
        score += 1; w2_score += 1

    # W3: price recovery + volume confirmation
    ret_w3 = close.iloc[w3_end] / close.iloc[w3_start] - 1
    bm_ret_w3 = bm_c.iloc[w3_end] / bm_c.iloc[w3_start] - 1
    if ret_w3 > bm_ret_w3:
        score += 1; w3_score += 1
    # Above MA20 at W3 end
    ma20 = close.rolling(20, min_periods=10).mean().iloc[w3_end]
    if close.iloc[w3_end] > ma20:
        score += 1; w3_score += 1
    # Volume in W3
    amt_w3 = amount.iloc[w3_start:w3_end].mean()
    if amt_pre_w2 > 0 and amt_w3 > amt_pre_w2:
        score += 1; w3_score += 1

    return {'total': score, 'w1': w1_score, 'w2': w2_score, 'w3': w3_score}


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


def compute_variant_d(variant_name, scores_df, sec_close, bm_close, sec_name,
                      chaos_threshold=6):
    """
    Variant D: state = position size, industry score = direction.

    Rules:
      MAIN_UP_CONFIRMED → TOP 3, equal weight
      REBOUND           → TOP 2, equal weight
      CHAOS             → TOP 1, equal weight (only if top score >= chaos_threshold)
      CROWDING          → TOP 1, equal weight
      RETREAT           → no holdings
    """
    STATE_ACTION = {
        'MAIN_UP_CONFIRMED': (3, 1.0),
        'REBOUND':           (2, 1.0),
        'CHAOS':             (1, 1.0),
        'CROWDING':          (1, 1.0),
        'RETREAT':           (0, 0.0),
    }

    trade_log = []

    for i in range(len(scores_df)):
        row = scores_df.iloc[i]
        eval_date = row.name
        state = row['state']
        top_n, weight_factor = STATE_ACTION.get(state, (0, 0.0))

        if top_n == 0:
            continue  # no holdings (RETREAT or unknown)

        # Get sorted sectors
        scores = sorted(row['sector_scores'].items(), key=lambda x: x[1], reverse=True)

        # CHAOS threshold gate
        if state == 'CHAOS':
            if not scores or scores[0][1] < chaos_threshold:
                continue  # skip this window — no sector meets minimum bar
            top_n = 1  # CHAOS always TOP 1 (already set above, but explicit for clarity)
            top_syms = [scores[0][0]]
            top_scores = [scores[0][1]]
        else:
            top_syms = [s[0] for s in scores[:top_n]]
            top_scores = [s[1] for s in scores[:top_n]]

        top_names = [sec_name.get(s, s) for s in top_syms]
        weight = round(1.0 / top_n * weight_factor, 4)

        trade_log.append({
            'eval_date': str(eval_date.date()),
            'state': state,
            'top_sectors': top_names,
            'top_scores': [round(s, 2) for s in top_scores],
            'weight': weight,
        })

    return trade_log


def compute_variant_e(variant_name, scores_df, sec_close, bm_close, sec_name,
                      chaos_threshold=6, chaos_delta_min=0.0, crowding_delta_max=2.0):
    """
    EXP-007 Variant E: State × Lifecycle fusion.

    Extends Variant D by adding Delta(W2-W3) refinement:
    - CHAOS: prefer Delta >= chaos_delta_min (default 0.0 = W2 >= W3)
    - CROWDING: avoid Delta >= crowding_delta_max (default 2.0 = Wash >> Launch)

    Uses sector_components stored in scores_records for Delta computation.
    Falls back to total-score-only selection when components unavailable.
    """
    trade_log = []

    STATE_ACTION = {
        'MAIN_UP_CONFIRMED': (3, 1.0),
        'REBOUND':           (2, 1.0),
        'CHAOS':             (1, 1.0),
        'CROWDING':          (1, 1.0),
        'RETREAT':           (0, 0.0),
    }

    for i in range(len(scores_df)):
        row = scores_df.iloc[i]
        eval_date = row.name
        state = row['state']
        top_n, weight_factor = STATE_ACTION.get(state, (0, 0.0))

        if top_n == 0:
            continue  # no holdings (RETREAT)

        sector_scores_raw = row['sector_scores']
        if not sector_scores_raw:
            continue

        # Get sector scores with optional Delta component
        # Build list of (sym, total_score, delta)
        scored_sectors = []
        for sym, score in sector_scores_raw.items():
            delta = None
            # Try to get Delta from components
            try:
                comps = row.get('sector_components', {})
                if sym in comps:
                    c = comps[sym]
                    if isinstance(c, dict) and 'w2' in c and 'w3' in c:
                        delta = c['w2'] - c['w3']
            except (TypeError, KeyError):
                pass
            scored_sectors.append((sym, score, delta))

        # Sort by total score descending
        scored_sectors.sort(key=lambda x: x[1], reverse=True)

        # Apply Delta rules per state
        if state == 'CHAOS':
            # Prefer Delta >= chaos_delta_min; fallback to top score if no sector qualifies
            eligible = [(s, sc, d) for s, sc, d in scored_sectors
                        if d is not None and d >= chaos_delta_min]
            if eligible:
                selected = eligible[:top_n]
            else:
                selected = scored_sectors[:top_n]  # fallback to pure score

            # CHAOS threshold: top selected score must be >= chaos_threshold
            if not selected or selected[0][1] < chaos_threshold:
                continue
            top_n = 1  # CHAOS always TOP 1
            selected = selected[:1]

        elif state == 'CROWDING':
            # Avoid Delta >= crowding_delta_max (Wash >> Launch is negative in CROWDING)
            eligible = [(s, sc, d) for s, sc, d in scored_sectors
                        if d is None or d < crowding_delta_max]
            if eligible:
                selected = eligible[:top_n]
            else:
                selected = scored_sectors[:top_n]  # fallback

        else:
            # MAIN_UP, REBOUND: no Delta filter
            selected = scored_sectors[:top_n]

        top_syms = [s[0] for s in selected]
        top_scores = [s[1] for s in selected]
        top_names = [sec_name.get(s, s) for s in top_syms]
        weight = round(1.0 / top_n * weight_factor, 4)

        trade_log.append({
            'eval_date': str(eval_date.date()),
            'state': state,
            'top_sectors': top_names,
            'top_scores': [round(s, 2) for s in top_scores],
            'weight': weight,
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
# Per-window return analysis
# ────────────────────────────────────────────

def compute_per_window_returns(trade_log, sec_close, bm_close, eval_dates, sec_name):
    """
    Compute per-window return for each entry in trade_log.
    Returns list of dicts: {date, state, sector_return, bm_return, excess_return, win}.
    """
    holdings_map = {}
    sym_by_name = {v: k for k, v in sec_name.items()}

    for log_entry in trade_log:
        eval_date = pd.Timestamp(log_entry['eval_date'])
        top_names = log_entry['top_sectors']
        weight = log_entry['weight']
        state = log_entry['state']
        holdings = []
        for name in top_names:
            sym = sym_by_name.get(name)
            if sym and sym in sec_close.columns:
                holdings.append((sym, weight))
        holdings_map[eval_date] = (state, holdings)

    window_results = []
    for i in range(len(eval_dates) - 1):
        start = eval_dates[i]
        end = eval_dates[i + 1]

        entry = holdings_map.get(start)
        if entry is None:
            continue  # no holdings this window

        state, holdings = entry
        if not holdings:
            continue

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

        bm_series = bm_close.dropna()
        try:
            bm_start = bm_series.loc[bm_series.index >= start].iloc[0] if any(bm_series.index >= start) else None
            bm_end = bm_series.loc[bm_series.index <= end].iloc[-1] if any(bm_series.index <= end) else None
            if bm_start and bm_end and bm_start > 0:
                bm_ret = (bm_end / bm_start - 1) * 100
            else:
                bm_ret = 0.0
        except (IndexError, KeyError):
            bm_ret = 0.0

        window_results.append({
            'date': str(start.date()),
            'state': state,
            'sector_return': round(sec_ret, 2),
            'benchmark_return': round(bm_ret, 2),
            'excess_return': round(sec_ret - bm_ret, 2),
            'win': 1 if sec_ret > bm_ret else 0,
        })

    return window_results


def compute_yearly_breakdown(trade_log, sec_close, bm_close, eval_dates, sec_name):
    """
    Group per-window returns by calendar year.
    Returns dict: year -> {trades, total_return, bm_return, excess_return, win_rate}.
    """
    windows = compute_per_window_returns(trade_log, sec_close, bm_close, eval_dates, sec_name)

    from collections import OrderedDict
    yearly = OrderedDict()

    for w in windows:
        year = w['date'][:4]
        if year not in yearly:
            yearly[year] = {
                'trades': 0,
                'total_ret': 0.0,
                'total_sector_ret': 0.0,
                'total_bm_ret': 0.0,
                'wins': 0,
            }
        yearly[year]['trades'] += 1
        yearly[year]['total_sector_ret'] += w['sector_return']
        yearly[year]['total_bm_ret'] += w['benchmark_return']
        yearly[year]['wins'] += w['win']

    # Convert to readable stats
    result = {}
    cum_sector = 0.0
    cum_bm = 0.0
    # Strategy annual return = compound of per-window returns within that year
    # (simple sum for now — consistent with total_ret additive across windows)
    for year, d in yearly.items():
        win_rate = d['wins'] / max(d['trades'], 1) * 100
        result[year] = {
            'trades': d['trades'],
            'avg_sector_return_pct': round(d['total_sector_ret'] / max(d['trades'], 1), 2),
            'cumulative_sector_pct': round(d['total_sector_ret'], 2),
            'cumulative_bm_pct': round(d['total_bm_ret'], 2),
            'cumulative_excess_pct': round(d['total_sector_ret'] - d['total_bm_ret'], 2),
            'win_rate_pct': round(win_rate, 1),
        }
    return result


def compute_state_contribution(trade_log, sec_close, bm_close, eval_dates, sec_name):
    """
    Group per-window returns by entry market state.
    Returns dict: state -> {trades, total_return, avg_return, win_rate}.
    """
    windows = compute_per_window_returns(trade_log, sec_close, bm_close, eval_dates, sec_name)

    from collections import OrderedDict
    state_data = OrderedDict()

    for w in windows:
        st = w['state']
        if st not in state_data:
            state_data[st] = {
                'trades': 0,
                'total_sector_ret': 0.0,
                'total_bm_ret': 0.0,
                'wins': 0,
            }
        state_data[st]['trades'] += 1
        state_data[st]['total_sector_ret'] += w['sector_return']
        state_data[st]['total_bm_ret'] += w['benchmark_return']
        state_data[st]['wins'] += w['win']

    result = {}
    for st, d in state_data.items():
        win_rate = d['wins'] / max(d['trades'], 1) * 100
        result[st] = {
            'trades': d['trades'],
            'avg_return_pct': round(d['total_sector_ret'] / max(d['trades'], 1), 2),
            'total_return_pct': round(d['total_sector_ret'], 2),
            'total_benchmark_pct': round(d['total_bm_ret'], 2),
            'excess_return_pct': round(d['total_sector_ret'] - d['total_bm_ret'], 2),
            'win_rate_pct': round(win_rate, 1),
        }
    return result


def compute_leader_capture_analysis(trade_log, scores_records, sec_close, eval_dates, sec_name):
    """
    For each rebalance window, measure how well the strategy captures the true market leader.

    Returns:
        overall: dict of aggregate metrics
        per_window: list of detailed per-window records
        by_state: breakdown by market state
    """
    sym_by_name = {v: k for k, v in sec_name.items()}
    name_by_sym = sec_name

    # Build holdings map from trade_log
    holdings_map = {}  # eval_date -> list of (sym, weight)
    for entry in trade_log:
        eval_date = pd.Timestamp(entry['eval_date'])
        top_names = entry['top_sectors']
        weight = entry['weight']
        holdings = []
        for name in top_names:
            sym = sym_by_name.get(name)
            if sym and sym in sec_close.columns:
                holdings.append((sym, weight))
        holdings_map[eval_date] = (entry['state'], holdings)

    per_window = []
    for i in range(len(eval_dates) - 1):
        start = eval_dates[i]
        end = eval_dates[i + 1]

        # Compute forward 20D return for ALL sectors
        sector_returns = {}  # sym -> return_pct
        for sym in sec_close.columns:
            series = sec_close[sym].dropna()
            try:
                p_start = series.loc[series.index >= start].iloc[0] if any(series.index >= start) else None
                p_end = series.loc[series.index <= end].iloc[-1] if any(series.index <= end) else None
                if p_start and p_end and p_start > 0:
                    ret = (p_end / p_start - 1) * 100
                    sector_returns[sym] = ret
            except (IndexError, KeyError):
                continue

        if not sector_returns:
            continue

        # Rank sectors by forward return
        ranked = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
        true_leader_sym = ranked[0][0]
        true_leader_ret = ranked[0][1]
        true_top3_syms = {s[0] for s in ranked[:3]}

        # Strategy's picks
        entry = holdings_map.get(start)
        if entry is None:
            # No holdings this window — capture is 0
            per_window.append({
                'date': str(start.date()),
                'state': 'NONE',
                'has_holdings': False,
                'top1_capture': 0.0,
                'top3_hit': False,
                'top1_hit': False,
                'picked_sectors': [],
                'picked_return': 0.0,
                'true_leader': name_by_sym.get(true_leader_sym, true_leader_sym),
                'true_leader_return': round(true_leader_ret, 2),
            })
            continue

        state, holdings = entry
        picked_syms = [s[0] for s in holdings]
        picked_names = [name_by_sym.get(s, s) for s in picked_syms]

        # Compute strategy return for this window
        strat_ret = 0.0
        for sym, w in holdings:
            ret = sector_returns.get(sym, 0.0)
            strat_ret += w * ret

        # Capture ratio
        cap_ratio = (strat_ret / true_leader_ret * 100) if true_leader_ret > 0 else 0.0
        cap_ratio = max(0.0, min(100.0, cap_ratio))  # clamp 0~100

        # Hits
        top1_hit = (picked_syms[0] == true_leader_sym) if picked_syms else False
        top3_hit = any(s in true_top3_syms for s in picked_syms)

        per_window.append({
            'date': str(start.date()),
            'state': state,
            'has_holdings': True,
            'top1_capture': round(cap_ratio, 1),
            'top3_hit': top3_hit,
            'top1_hit': top1_hit,
            'top1_pick': picked_names[0] if picked_names else '',
            'top1_pick_return': round(sector_returns.get(picked_syms[0], 0), 2) if picked_syms else 0,
            'picked_sectors': picked_names,
            'picked_return': round(strat_ret, 2),
            'true_leader': name_by_sym.get(true_leader_sym, true_leader_sym),
            'true_leader_return': round(true_leader_ret, 2),
            'true_top3': [name_by_sym.get(s, s) for s in true_top3_syms],
        })

    # Aggregate
    total = len(per_window)
    with_holdings = [w for w in per_window if w['has_holdings']]

    overall = {
        'total_windows': total,
        'windows_with_holdings': len(with_holdings),
        'top1_hit_rate_pct': round(sum(1 for w in with_holdings if w['top1_hit']) / max(len(with_holdings), 1) * 100, 1),
        'top3_coverage_rate_pct': round(sum(1 for w in with_holdings if w['top3_hit']) / max(len(with_holdings), 1) * 100, 1),
        'avg_top1_capture_pct': round(sum(w['top1_capture'] for w in with_holdings) / max(len(with_holdings), 1), 1),
    }

    # By state
    from collections import defaultdict
    by_state = defaultdict(lambda: {'windows': 0, 'top1_hits': 0, 'top3_hits': 0, 'capture_sum': 0.0})
    for w in with_holdings:
        st = w['state']
        by_state[st]['windows'] += 1
        by_state[st]['top1_hits'] += 1 if w['top1_hit'] else 0
        by_state[st]['top3_hits'] += 1 if w['top3_hit'] else 0
        by_state[st]['capture_sum'] += w['top1_capture']

    state_result = {}
    for st, d in by_state.items():
        state_result[st] = {
            'windows': d['windows'],
            'top1_hit_rate_pct': round(d['top1_hits'] / max(d['windows'], 1) * 100, 1),
            'top3_coverage_pct': round(d['top3_hits'] / max(d['windows'], 1) * 100, 1),
            'avg_capture_pct': round(d['capture_sum'] / max(d['windows'], 1), 1),
        }

    return overall, per_window, state_result


# ────────────────────────────────────────────
# EXP-006: Signal Lifecycle Analysis
# ────────────────────────────────────────────

HORIZONS = [5, 10, 20, 40, 60]


def compute_lifecycle(scores_records, sec_close, bm_close, eval_dates, sec_name, top_n_list=None):
    """
    EXP-006: Lifecycle analysis for both TOP1 and TOP3 equal-weight selection.

    For each rebalance window, pick top_n sectors by W1/W2/W3 score (pure signal,
    no state filter, no threshold) and measure forward Return / Excess /
    WinRate / Capture at 5/10/20/40/60 *trading day* horizons.

    Also records return distributions (P10/P25/P50/P75/P90) per horizon.

    top_n_list: which N's to compute (default [1, 3])
    """
    if top_n_list is None:
        top_n_list = [1, 3]
    name_by_sym = sec_name

    # Build rebalance date lookup: date -> sector_scores dict
    window_map = {}
    for rec in scores_records:
        d = rec['eval_date']
        if hasattr(d, 'date'):
            d_ts = pd.Timestamp(d)
        else:
            d_ts = pd.Timestamp(rec['date_str'])
        window_map[d_ts] = rec

    # Store per-window results for distribution analysis
    # {n: {h: [returns_list]}}
    dist_returns = {n: {h: [] for h in HORIZONS} for n in top_n_list}

    horizon_data = {n: {h: {'returns': [], 'excess': [], 'wins': [], 'captures': []}
                        for h in HORIZONS} for n in top_n_list}

    for start in eval_dates:
        rec = window_map.get(start)
        if not rec or not rec['sector_scores']:
            continue

        # Rank all sectors by score
        ranked = sorted(rec['sector_scores'].items(), key=lambda x: x[1], reverse=True)

        # Pre-compute start prices in all series
        def closest_before(series, dt):
            mask = series.index <= dt
            if not mask.any():
                return None
            idx = mask.sum() - 1
            if idx < len(series):
                return series.iloc[idx], idx
            return None

        bm_series = bm_close.dropna()
        bm_entry = closest_before(bm_series, start)
        if bm_entry is None:
            continue
        bm_p0, bm_i0 = bm_entry

        # All sector start prices
        all_p0 = {}
        all_i0 = {}
        for sym in sec_close.columns:
            entry = closest_before(sec_close[sym].dropna(), start)
            if entry:
                all_p0[sym], all_i0[sym] = entry

        for n in top_n_list:
            top_syms = [s[0] for s in ranked[:n]]

            for h in HORIZONS:
                # Equal-weight portfolio return
                ret_sum = 0.0
                valid_count = 0
                for sym in top_syms:
                    if sym not in all_p0:
                        continue
                    sym_series = sec_close[sym].dropna()
                    end_idx = all_i0[sym] + h
                    if end_idx >= len(sym_series):
                        continue
                    p1 = sym_series.iloc[end_idx]
                    ret_sum += p1 / all_p0[sym] - 1
                    valid_count += 1

                if valid_count == 0:
                    continue
                sec_ret = ret_sum / valid_count  # equal weight

                # Benchmark forward return
                bm_end_idx = bm_i0 + h
                if bm_end_idx >= len(bm_series):
                    continue
                bm_ret = bm_series.iloc[bm_end_idx] / bm_p0 - 1

                excess = sec_ret - bm_ret
                win = 1 if sec_ret > bm_ret else 0

                # Leader capture: best single-sector forward return at same horizon
                best_ret = None
                for sym in sec_close.columns:
                    if sym not in all_p0:
                        continue
                    sym_series = sec_close[sym].dropna()
                    end_idx = all_i0[sym] + h
                    if end_idx >= len(sym_series):
                        continue
                    fr = sym_series.iloc[end_idx] / all_p0[sym] - 1
                    if best_ret is None or fr > best_ret:
                        best_ret = fr

                capture = (sec_ret / best_ret * 100) if (best_ret is not None and best_ret > 0) else 0.0
                capture = max(0.0, min(100.0, capture))

                horizon_data[n][h]['returns'].append(sec_ret * 100)
                horizon_data[n][h]['excess'].append(excess * 100)
                horizon_data[n][h]['wins'].append(win)
                horizon_data[n][h]['captures'].append(capture)
                dist_returns[n][h].append(sec_ret * 100)

    # Aggregate
    result = {}
    for n in top_n_list:
        result[f'TOP{n}'] = {}
        for h in HORIZONS:
            d = horizon_data[n][h]
            n_windows = len(d['returns'])
            if n_windows == 0:
                continue

            rets = sorted(dist_returns[n][h])
            n_ret = len(rets)

            def percentile(sorted_list, p):
                import math
                idx = max(0, min(n_ret - 1, int(math.ceil(p / 100.0 * n_ret) - 1)))
                return round(sorted_list[idx], 2)

            result[f'TOP{n}'][f'{h}D'] = {
                'windows': n_windows,
                'avg_return_pct': round(sum(d['returns']) / n_windows, 2),
                'avg_excess_pct': round(sum(d['excess']) / n_windows, 2),
                'win_rate_pct': round(sum(d['wins']) / n_windows * 100, 1),
                'avg_capture_pct': round(sum(d['captures']) / n_windows, 1),
                'dist_p10': percentile(rets, 10),
                'dist_p25': percentile(rets, 25),
                'dist_p50': percentile(rets, 50),
                'dist_p75': percentile(rets, 75),
                'dist_p90': percentile(rets, 90),
            }

    return result


# ────────────────────────────────────────────
# EXP-006A: Winner Window Profile Analysis
# ────────────────────────────────────────────

WINNER_GROUPS = [
    ('Super Winner', 0.0, 0.1),
    ('Winner',       0.1, 0.3),
    ('Neutral',      0.3, 0.7),
    ('Loser',        0.7, 0.9),
    ('Disaster',     0.9, 1.0),
]


def main_exp006a():
    print('=' * 60)
    print('EXP-006A: Winner Window Profile Analysis')
    print('=' * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print('\n[1/4] Loading sector data...')
    bm, sec_close, sec_amount, sec_name, sec_ma20, sec_ma60, sec_nh, sec_ar = load_sector_data()
    bm_close = bm['close']
    bm_amount = bm['amount']

    print('\n[2/4] Loading market states...')
    states = load_market_states()

    print('\n[3/4] Scoring and collecting window data...')
    all_dates = bm.index
    sym_list = list(sec_close.columns)
    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))

    def closest_before(series, dt):
        mask = series.index <= dt
        if not mask.any():
            return None, None
        idx = mask.sum() - 1
        if idx < len(series):
            return series.iloc[idx], idx
        return None, None

    windows = []
    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        date_str = str(eval_date.date())
        sector_components = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue
            comp = score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx)
            if comp and 0 < comp['total'] <= 9:
                sector_components[sym] = comp
        if not sector_components:
            continue

        ranked = sorted(sector_components.items(), key=lambda x: x[1]['total'], reverse=True)
        top3_syms = [s[0] for s in ranked[:3]]
        top3_comps = [s[1] for s in ranked[:3]]

        ret_sum, valid = 0.0, 0
        for sym in top3_syms:
            series = sec_close[sym].dropna()
            p0, i0 = closest_before(series, eval_date)
            if p0 is None:
                continue
            end_idx = i0 + 20
            if end_idx >= len(series):
                continue
            ret_sum += series.iloc[end_idx] / p0 - 1
            valid += 1
        if valid == 0:
            continue
        fwd_return = ret_sum / valid * 100

        bm_p0, bm_i0 = closest_before(bm_close, eval_date)
        if bm_p0 is None or bm_i0 + 20 >= len(bm_close):
            continue
        bm_fwd = (bm_close.iloc[bm_i0 + 20] / bm_p0 - 1) * 100

        state = states.get(date_str, 'CHAOS') if states else 'UNKNOWN'
        avg_w1 = sum(c['w1'] for c in top3_comps) / len(top3_comps)
        avg_w2 = sum(c['w2'] for c in top3_comps) / len(top3_comps)
        avg_w3 = sum(c['w3'] for c in top3_comps) / len(top3_comps)
        avg_total = sum(c['total'] for c in top3_comps) / len(top3_comps)

        ma20_vals, ar_vals = [], []
        for sym in top3_syms:
            if sym in sec_ma20.columns and eval_idx < len(sec_ma20):
                v = sec_ma20[sym].iloc[eval_idx]
                if not pd.isna(v):
                    ma20_vals.append(v)
            if sym in sec_ar.columns and eval_idx < len(sec_ar):
                v = sec_ar[sym].iloc[eval_idx]
                if not pd.isna(v):
                    ar_vals.append(v)

        windows.append({
            'date': date_str,
            'state': state,
            'return_pct': round(fwd_return, 2),
            'excess_pct': round(fwd_return - bm_fwd, 2),
            'top3_avg_w1': round(avg_w1, 2),
            'top3_avg_w2': round(avg_w2, 2),
            'top3_avg_w3': round(avg_w3, 2),
            'top3_avg_total': round(avg_total, 2),
            'top3_avg_ma20': round(sum(ma20_vals) / max(len(ma20_vals), 1), 4) if ma20_vals else None,
            'top3_avg_amount_ratio': round(sum(ar_vals) / max(len(ar_vals), 1), 4) if ar_vals else None,
        })

    print(f'  Collected {len(windows)} windows')

    print('\n[4/4] Profiling...')
    windows.sort(key=lambda w: w['return_pct'], reverse=True)
    n = len(windows)
    groups = []
    for label, p_low, p_high in WINNER_GROUPS:
        lo, hi = int(n * p_low), int(n * p_high)
        members = windows[lo:hi]
        if not members:
            continue
        avg_ret = sum(w['return_pct'] for w in members) / len(members)
        avg_exc = sum(w['excess_pct'] for w in members) / len(members)
        avg_w1 = sum(w['top3_avg_w1'] for w in members) / len(members)
        avg_w2 = sum(w['top3_avg_w2'] for w in members) / len(members)
        avg_w3 = sum(w['top3_avg_w3'] for w in members) / len(members)
        avg_total = sum(w['top3_avg_total'] for w in members) / len(members)
        ma20_vals = [w['top3_avg_ma20'] for w in members if w['top3_avg_ma20'] is not None]
        ar_vals = [w['top3_avg_amount_ratio'] for w in members if w['top3_avg_amount_ratio'] is not None]
        state_dist = {}
        for w in members:
            state_dist[w['state']] = state_dist.get(w['state'], 0) + 1

        groups.append({
            'label': label,
            'count': len(members),
            'range': f'{lo/n*100:.0f}%-{hi/n*100:.0f}%' if hi < n else f'{lo/n*100:.0f}%-100%',
            'avg_return': round(avg_ret, 2),
            'avg_excess': round(avg_exc, 2),
            'avg_w1': round(avg_w1, 2),
            'avg_w2': round(avg_w2, 2),
            'avg_w3': round(avg_w3, 2),
            'avg_total': round(avg_total, 2),
            'avg_ma20': round(sum(ma20_vals) / max(len(ma20_vals), 1), 4) if ma20_vals else None,
            'avg_ar': round(sum(ar_vals) / max(len(ar_vals), 1), 4) if ar_vals else None,
            'state_dist': state_dist,
        })

    print(f'\n{"="*120}')
    print('WINNER WINDOW PROFILES')
    print(f'{"="*120}')
    for g in groups:
        ma20_str = f'{g["avg_ma20"]*100:.0f}%' if g["avg_ma20"] is not None else 'N/A'
        ar_str = f'{g["avg_ar"]*100:.0f}%' if g["avg_ar"] is not None else 'N/A'
        states_str = ', '.join(f'{st}={cnt}' for st, cnt in sorted(g['state_dist'].items(), key=lambda x: -x[1]))
        print(f'\n  {g["label"]} (n={g["count"]}, {g["range"]})')
        print(f'    Return={g["avg_return"]:>6.1f}%  Excess={g["avg_excess"]:>6.1f}%  '
              f'W1={g["avg_w1"]}  W2={g["avg_w2"]}  W3={g["avg_w3"]}  Total={g["avg_total"]}')
        print(f'    MA20={ma20_str}  AmtRatio={ar_str}')
        print(f'    States: {states_str}')

    out_path = OUTPUT_DIR / 'exp006a_winner_window_profiles.json'
    with open(out_path, 'w') as f:
        json.dump({
            'experiment': 'EXP-006A',
            'description': 'Winner window profile analysis',
            'total_windows': n,
            'groups': groups,
            'windows': windows,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Output: {out_path}')
    print('\nEXP-006A complete')



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
        sector_components = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue

            comp = score_sector_components(
                s_close, s_amount, bm_close, bm_amount, eval_idx
            )
            if comp and 0 < comp['total'] <= 9:
                sector_scores[sym] = comp['total']
                sector_components[sym] = comp

        if not sector_scores:
            continue

        # Determine state for this eval_date
        state = states.get(date_str, 'CHAOS')
        scores_records.append({
            'eval_date': eval_date,
            'date_str': date_str,
            'state': state,
            'sector_scores': sector_scores,
            'sector_components': sector_components,
            'eval_idx': eval_idx,
        })

    print(f'  Scored {len(scores_records)} rebalance windows')

    print(f'  Scored {len(scores_records)} rebalance windows')

    # ── 2b. CHAOS Top1 score + forward return diagnostics ──
    print('\n[3b/4] CHAOS Top1 score vs future return analysis...')
    scores_df = pd.DataFrame(scores_records)
    scores_df = scores_df.set_index('eval_date')

    # Collect per-window diagnostics
    chaos_window_records = []
    for idx, row in scores_df.iterrows():
        if row['state'] != 'CHAOS':
            continue
        scores = sorted(row['sector_scores'].items(), key=lambda x: x[1], reverse=True)
        if not scores:
            continue

        top_sym, top_score = scores[0]
        eval_idx = row['eval_idx']
        hold_end = eval_idx + HOLD_LOOKAHEAD

        # Forward 20D return for top sector
        sec_series = sec_close[top_sym].dropna()
        bm_series = bm_close.dropna()

        if (hold_end < len(sec_series) and hold_end < len(bm_series)
                and eval_idx < len(sec_series) and eval_idx < len(bm_series)):
            sec_ret = sec_series.iloc[hold_end] / sec_series.iloc[eval_idx] - 1
            bm_ret = bm_series.iloc[hold_end] / bm_series.iloc[eval_idx] - 1
        else:
            continue

        chaos_window_records.append({
            'date': str(row['date_str']),
            'top_sector': top_sym,
            'top_score': top_score,
            'sector_return': round(sec_ret * 100, 2),
            'benchmark_return': round(bm_ret * 100, 2),
            'excess_return': round((sec_ret - bm_ret) * 100, 2),
            'win': int(sec_ret > bm_ret),
        })

    n_chaos = len(chaos_window_records)
    print(f'  CHAOS windows with full data: {n_chaos}')

    # Score distribution
    all_scores = [r['top_score'] for r in chaos_window_records]
    thresholds = [8, 7, 6, 5, 4, 3]
    print(f'\n  {"Threshold":>10s} {"Count":>6s} {"AvgRet":>8s} {"WinRate":>8s} {"AvgExc":>8s}')
    print(f'  {"-"*44}')

    threshold_stats = {}
    for t in thresholds:
        subset = [r for r in chaos_window_records if r['top_score'] >= t]
        if not subset:
            continue
        avg_ret = sum(r['sector_return'] for r in subset) / len(subset)
        win_rate = sum(r['win'] for r in subset) / len(subset) * 100
        avg_exc = sum(r['excess_return'] for r in subset) / len(subset)
        print(f'  >= {t:5d}  {len(subset):5d}  {avg_ret:>7.1f}%  {win_rate:>6.1f}%  {avg_exc:>7.1f}%')
        threshold_stats[f'>= {t}'] = {
            'count': len(subset),
            'avg_sector_return_pct': round(avg_ret, 2),
            'win_rate_pct': round(win_rate, 1),
            'avg_excess_return_pct': round(avg_exc, 2),
        }

    # Also print per-score level for finer granularity
    print(f'\n  Per-score level detail:')
    print(f'  {"Score":>6s} {"Count":>6s} {"AvgRet":>8s} {"WinRate":>8s}')
    print(f'  {"-"*32}')
    for score_val in range(9, 1, -1):
        subset = [r for r in chaos_window_records if r['top_score'] == score_val]
        if not subset:
            continue
        avg_ret = sum(r['sector_return'] for r in subset) / len(subset)
        win_rate = sum(r['win'] for r in subset) / len(subset) * 100
        print(f'  {score_val:5d}  {len(subset):5d}  {avg_ret:>7.1f}%  {win_rate:>6.1f}%')

    # Save full diagnostics
    chaos_diag = {
        'total_chaos_windows': n_chaos,
        'threshold_performance': threshold_stats,
        'per_window_detail': chaos_window_records,
    }
    chaos_diag_path = OUTPUT_DIR / 'exp003_chaos_top1_diagnostics.json'
    with open(chaos_diag_path, 'w') as f:
        json.dump(chaos_diag, f, indent=2, ensure_ascii=False)
    print(f'\n  Full diagnostics: {chaos_diag_path}')

    # ── 3. Compute variants ──
    print('\n[4/4] Computing variants and NAV...')

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

    # Variant D: state = position, industry = direction
    # D_primary: CHAOS >= 6 (Aggressive-leaning)
    trade_log_d1 = compute_variant_d(
        'D_primary', scores_df, sec_close, bm_close, sec_name,
        chaos_threshold=6,
    )
    results['D_state_position_ge6'] = trade_log_d1

    # D_sensitivity: CHAOS >= 7 (Conservative preview)
    trade_log_d2 = compute_variant_d(
        'D_sens_ge7', scores_df, sec_close, bm_close, sec_name,
        chaos_threshold=7,
    )
    results['D_sens_ge7'] = trade_log_d2

    # D_sensitivity: CHAOS >= 8 (further conservative)
    trade_log_d3 = compute_variant_d(
        'D_sens_ge8', scores_df, sec_close, bm_close, sec_name,
        chaos_threshold=8,
    )
    results['D_sens_ge8'] = trade_log_d3

    # ── Variant E: State × Lifecycle fusion (EXP-007) ──
    trade_log_e = compute_variant_e(
        'E_primary', scores_df, sec_close, bm_close, sec_name,
        chaos_threshold=6, chaos_delta_min=0.0, crowding_delta_max=2.0,
    )
    results['E_state_lifecycle'] = trade_log_e

    # E_sensitivity: hard filter CHAOS (Delta < 0 → skip window entirely)
    trade_log_e_hard = compute_variant_e(
        'E_sens_hard', scores_df, sec_close, bm_close, sec_name,
        chaos_threshold=6, chaos_delta_min=999,  # impossible threshold = hard skip
        crowding_delta_max=2.0,
    )
    results['E_sens_hard'] = trade_log_e_hard

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
            'REBOUND': 'TOP 2 equal weight (Variant D) / none (Variant B/C)',
            'CROWDING': 'TOP 1 equal weight',
            'CHAOS': 'TOP 1 >=6 (Variant D primary) / no holdings (Variant B/C)',
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
                   'D_state_position_ge6', 'D_sens_ge7', 'D_sens_ge8',
                   'E_state_lifecycle', 'E_sens_hard',
                   'B_sens_rebound_top1', 'C_sens_rebound_top1']:
        n = nav_results.get(v_name)
        if n:
            print(f'  {v_name:30s} {n["total_return"]:>7.1f}% {n["bm_return"]:>7.1f}% {n["excess_return"]:>7.1f}% {n["max_drawdown_pct"]:>7.1f}%')

    # ── State contribution analysis (Variant D primary only) ──
    print(f'\n{"="*60}')
    print('VARIANT D: STATE CONTRIBUTION ANALYSIS')
    print(f'{"="*60}')

    d_trade_log = results['D_state_position_ge6']
    state_contrib = compute_state_contribution(
        d_trade_log, sec_close, bm_close, scores_df.index, sec_name)

    state_order_d = ['MAIN_UP_CONFIRMED', 'REBOUND', 'CHAOS', 'CROWDING', 'RETREAT']
    total_d_ret = sum(v['total_return_pct'] for v in state_contrib.values())

    print(f'  {"State":22s} {"Trades":>6s} {"AvgRet":>8s} {"WinRate":>8s} '
          f'{"TotalRet":>9s} {"Excess":>8s} {"Contrib":>8s}')
    print(f'  {"-"*73}')
    for st in state_order_d:
        d = state_contrib.get(st)
        if not d:
            continue
        contrib_pct = d['total_return_pct'] / max(total_d_ret, 0.01) * 100
        print(f'  {st:22s} {d["trades"]:5d}  {d["avg_return_pct"]:>7.1f}% {d["win_rate_pct"]:>6.1f}% '
              f'{d["total_return_pct"]:>8.1f}% {d["excess_return_pct"]:>7.1f}% {contrib_pct:>7.1f}%')
    print(f'  {"-"*73}')
    print(f'  {"TOTAL":22s} {"":>6s} {"":>8s} {"":>8s} {total_d_ret:>8.1f}%')

    # ── Yearly breakdown (Variant D primary) ──
    print(f'\n{"="*60}')
    print('VARIANT D: YEARLY BREAKDOWN')
    print(f'{"="*60}')

    yearly = compute_yearly_breakdown(
        d_trade_log, sec_close, bm_close, scores_df.index, sec_name)

    print(f'  {"Year":6s} {"Trades":>6s} {"AvgRet":>8s} {"CumSec":>9s} '
          f'{"CumBM":>9s} {"CumExc":>9s} {"WinRate":>8s}')
    print(f'  {"-"*59}')
    for year, d in yearly.items():
        print(f'  {year:6s} {d["trades"]:5d}  {d["avg_sector_return_pct"]:>7.1f}% '
              f'{d["cumulative_sector_pct"]:>8.1f}% {d["cumulative_bm_pct"]:>8.1f}% '
              f'{d["cumulative_excess_pct"]:>8.1f}% {d["win_rate_pct"]:>6.1f}%')

    # Also print multi-year periods
    periods = [
        ('2000~2005', '2000', '2005'),
        ('2006~2010', '2006', '2010'),
        ('2011~2015', '2011', '2015'),
        ('2016~2020', '2016', '2020'),
        ('2021~2026', '2021', '2026'),
    ]
    print(f'\n  Multi-year periods:')
    print(f'  {"Period":12s} {"Trades":>6s} {"CumSec":>9s} {"CumBM":>9s} {"CumExc":>9s} {"WinRate":>8s}')
    print(f'  {"-"*56}')
    for p_label, y_start, y_end in periods:
        p_trades = 0
        p_sec = 0.0
        p_bm = 0.0
        p_wins = 0
        for year, d in yearly.items():
            if y_start <= year <= y_end:
                p_trades += d['trades']
                p_sec += d['cumulative_sector_pct']
                p_bm += d['cumulative_bm_pct']
                p_wins += int(d['win_rate_pct'] * d['trades'] / 100) if d['trades'] > 0 else 0

        if p_trades > 0:
            win_rate = p_wins / max(p_trades, 1) * 100
            exc = p_sec - p_bm
            print(f'  {p_label:12s} {p_trades:5d}  {p_sec:>8.1f}% {p_bm:>8.1f}% {exc:>8.1f}% {win_rate:>6.1f}%')

    # ── Leader Capture Analysis (Variant D primary) ──
    print(f'\n{"="*60}')
    print('VARIANT D: LEADER CAPTURE ANALYSIS')
    print(f'{"="*60}')

    leader_overall, leader_windows, leader_by_state = compute_leader_capture_analysis(
        d_trade_log, scores_records, sec_close, scores_df.index, sec_name)

    print(f'\n  Overall (among {leader_overall["windows_with_holdings"]} windows with holdings):')
    print(f'  {"Metric":30s} {"Value":>10s}')
    print(f'  {"-"*42}')
    print(f'  {"Top1 Hit Rate":30s} {leader_overall["top1_hit_rate_pct"]:>9.1f}%')
    print(f'  {"Top3 Coverage Rate":30s} {leader_overall["top3_coverage_rate_pct"]:>9.1f}%')
    print(f'  {"Avg Top1 Capture Ratio":30s} {leader_overall["avg_top1_capture_pct"]:>9.1f}%')

    print(f'\n  By state:')
    print(f'  {"State":22s} {"Windows":>7s} {"Top1Hit":>8s} {"Top3Cov":>8s} {"CapRat":>8s}')
    print(f'  {"-"*55}')
    for st in ['MAIN_UP_CONFIRMED', 'REBOUND', 'CHAOS', 'CROWDING']:
        d = leader_by_state.get(st)
        if d:
            print(f'  {st:22s} {d["windows"]:5d}   {d["top1_hit_rate_pct"]:>6.1f}% {d["top3_coverage_pct"]:>6.1f}% {d["avg_capture_pct"]:>6.1f}%')

    # Also compute for A_baseline for comparison
    print(f'\n  Comparison: Variant A (baseline) Top1 Hit Rate')
    leader_a_overall, _, _ = compute_leader_capture_analysis(
        results['A_baseline'], scores_records, sec_close, scores_df.index, sec_name)
    print(f'    A_baseline top1_hit_rate:  {leader_a_overall["top1_hit_rate_pct"]:>5.1f}%')
    print(f'    A_baseline top3_coverage:  {leader_a_overall["top3_coverage_rate_pct"]:>5.1f}%')
    print(f'    A_baseline avg_capture:    {leader_a_overall["avg_top1_capture_pct"]:>5.1f}%')

    # Save leader capture data to output
    output['leader_capture'] = {
        'Variant_D': {
            'overall': leader_overall,
            'by_state': leader_by_state,
        },
        'Variant_A': {
            'overall': leader_a_overall,
        },
    }
    output['detailed_results']['leader_capture_windows'] = leader_windows[:50]  # limit detail size

    print(f'\n  Output: {out_path}')
    print('\nEXP-003 evaluator complete')


def main_exp006():
    """EXP-006: Signal Lifecycle Analysis — standalone mode."""
    print('=' * 60)
    print('EXP-006: W1/W2/W3 Signal Lifecycle Analysis')
    print('=' * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ──
    print('\n[1/3] Loading sector data...')
    bm, sec_close, sec_amount, sec_name, _, _, _, _ = load_sector_data()
    bm_close = bm['close']
    bm_amount = bm['amount']

    # ── 2. Run scoring ──
    print('\n[2/3] Computing W1/W2/W3 scores (TOP 1, no filter)...')
    all_dates = bm.index
    sym_list = list(sec_close.columns)

    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
    scores_records = []
    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        sector_scores = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue
            score = score_sector(s_close, s_amount, bm_close, bm_amount, eval_idx)
            if score is not None and 0 < score <= 9:
                sector_scores[sym] = score
        if sector_scores:
            scores_records.append({
                'eval_date': eval_date,
                'date_str': str(eval_date.date()),
                'sector_scores': sector_scores,
            })

    print(f'  Scored {len(scores_records)} rebalance windows')

    # Build eval_dates from scores_records
    eval_dates = pd.DatetimeIndex([r['eval_date'] for r in scores_records])

    # ── 3. Lifecycle analysis ──
    print('\n[3/3] Computing lifecycle curves...')
    lifecycle = compute_lifecycle(scores_records, sec_close, bm_close, eval_dates, sec_name, top_n_list=[1, 3])

    def print_lifecycle_section(label, prefix, horizon_prefix=''):
        """Print a lifecycle table section. prefix is 'TOP1' or 'TOP3'."""
        print(f'\n  {label}')
        print(f'  {"Horizon":8s} {"Windows":>7s} {"Return":>8s} {"Excess":>8s} {"WinRate":>8s} {"Capture":>8s} '
              f'{"P10":>7s} {"P25":>7s} {"P50":>7s} {"P75":>7s} {"P90":>7s}')
        print(f'  {"-"*88}')
        for h in HORIZONS:
            d = lifecycle.get(prefix, {}).get(f'{h}D')
            if d:
                print(f'  {f"{h}D":8s} {d["windows"]:5d}   {d["avg_return_pct"]:>6.1f}% {d["avg_excess_pct"]:>6.1f}% '
                      f'{d["win_rate_pct"]:>6.1f}% {d["avg_capture_pct"]:>6.1f}% '
                      f'{d["dist_p10"]:>6.1f}% {d["dist_p25"]:>6.1f}% {d["dist_p50"]:>6.1f}% '
                      f'{d["dist_p75"]:>6.1f}% {d["dist_p90"]:>6.1f}%')

    # Print TOP1 table
    print(f'\n{"="*88}')
    print('EXP-006: SIGNAL LIFECYCLE ANALYSIS')
    print(f'{"="*88}')
    print_lifecycle_section('TOP 1 (single-sector signal)', 'TOP1')

    # Print TOP3 table
    print_lifecycle_section('TOP 3 (equal-weight portfolio — matches real strategy)', 'TOP3')

    # Capture peak comparison
    print(f'\n  Capture peak comparison:')
    for prefix, label in [('TOP1', 'TOP 1'), ('TOP3', 'TOP 3')]:
        cands = [(h, lifecycle[prefix][f'{h}D']['avg_capture_pct'])
                 for h in HORIZONS if f'{h}D' in lifecycle.get(prefix, {})]
        if cands:
            peak_h, peak_cap = max(cands, key=lambda x: x[1])
            cap_20 = lifecycle[prefix].get('20D', {}).get('avg_capture_pct', 0)
            print(f'    {label}: capture peak={peak_h}D ({peak_cap:.1f}%), 20D capture={cap_20:.1f}%')

    # Check for venture capital pattern (positive skew)
    print(f'\n  Skew check (20D horizon):')
    for prefix, label in [('TOP1', 'TOP 1'), ('TOP3', 'TOP 3')]:
        d = lifecycle.get(prefix, {}).get('20D')
        if d:
            # Positive skew = median < mean (少数大赢家拉高均值)
            skew_flag = 'Positive skew (VC pattern)' if d['dist_p50'] < d['avg_return_pct'] else 'Approx symmetric'
            print(f'    {label}: median={d["dist_p50"]}% < mean={d["avg_return_pct"]}% -> {skew_flag}')

    # Save
    out_path = OUTPUT_DIR / 'exp006_signal_lifecycle.json'
    with open(out_path, 'w') as f:
        json.dump({
            'experiment': 'EXP-006',
            'description': 'W1/W2/W3 signal lifecycle analysis (TOP1 + TOP3)',
            'method': 'TOP1/TOP3 by W1/W2/W3 score, no state filter, no threshold, equal-weight portfolio',
            'horizons': HORIZONS,
            'lifecycle': lifecycle,
            'parameters': {
                'rebalance_interval': REBALANCE_INTERVAL,
                'min_history': MIN_HISTORY,
                'benchmark': BM_SYMBOL,
            },
        }, f, indent=2, ensure_ascii=False)
    print(f'\n  Output: {out_path}')
    print('\nEXP-006 complete')


# ────────────────────────────────────────────
# EXP-006B: W2-W3 Delta Analysis
# ────────────────────────────────────────────

DELTA_BUCKETS = [
    ('Wash >> Launch',  2.0, 999),
    ('Wash > Launch',   0.5, 2.0),
    ('Balanced',       -0.5, 0.5),
    ('Launch > Wash',  -2.0, -0.5),
    ('Launch >> Wash', -999, -2.0),
]


def main_exp006b():
    """
    EXP-006B: W2-W3 Delta stratification + State × Delta interaction.

    Delta = avg(W2 of TOP3) - avg(W3 of TOP3)

    Groups windows by delta buckets and by state+delta, then compares
    return/win-rate/capture at 20D horizon.
    """
    print('=' * 60)
    print('EXP-006B: W2-W3 Delta Analysis')
    print('=' * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print('\n[1/4] Loading sector data...')
    bm, sec_close, sec_amount, sec_name, sec_ma20, sec_ma60, sec_nh, sec_ar = load_sector_data()
    bm_close = bm['close']
    bm_amount = bm['amount']

    print('\n[2/4] Loading market states...')
    states = load_market_states()

    print('\n[3/4] Scoring windows and computing delta...')
    all_dates = bm.index
    sym_list = list(sec_close.columns)
    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))

    def closest_before(series, dt):
        mask = series.index <= dt
        if not mask.any():
            return None, None
        idx = mask.sum() - 1
        if idx < len(series):
            return series.iloc[idx], idx
        return None, None

    windows = []
    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        date_str = str(eval_date.date())

        sector_components = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue
            comp = score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx)
            if comp and 0 < comp['total'] <= 9:
                sector_components[sym] = comp
        if not sector_components:
            continue

        ranked = sorted(sector_components.items(), key=lambda x: x[1]['total'], reverse=True)
        top3_syms = [s[0] for s in ranked[:3]]
        top3_comps = [s[1] for s in ranked[:3]]

        # TOP3 equal-weight forward 20D return
        ret_sum, valid = 0.0, 0
        for sym in top3_syms:
            series = sec_close[sym].dropna()
            p0, i0 = closest_before(series, eval_date)
            if p0 is None:
                continue
            end_idx = i0 + 20
            if end_idx >= len(series):
                continue
            ret_sum += series.iloc[end_idx] / p0 - 1
            valid += 1
        if valid == 0:
            continue
        fwd_return = ret_sum / valid * 100

        bm_p0, bm_i0 = closest_before(bm_close, eval_date)
        if bm_p0 is None or bm_i0 + 20 >= len(bm_close):
            continue
        bm_fwd = (bm_close.iloc[bm_i0 + 20] / bm_p0 - 1) * 100

        state = states.get(date_str, 'CHAOS') if states else 'UNKNOWN'
        avg_w1 = sum(c['w1'] for c in top3_comps) / len(top3_comps)
        avg_w2 = sum(c['w2'] for c in top3_comps) / len(top3_comps)
        avg_w3 = sum(c['w3'] for c in top3_comps) / len(top3_comps)
        delta = avg_w2 - avg_w3

        windows.append({
            'date': date_str,
            'state': state,
            'return_pct': round(fwd_return, 2),
            'excess_pct': round(fwd_return - bm_fwd, 2),
            'delta': round(delta, 2),
            'avg_w1': round(avg_w1, 2),
            'avg_w2': round(avg_w2, 2),
            'avg_w3': round(avg_w3, 2),
        })

    print(f'  Collected {len(windows)} windows')

    # ── 4a. Delta stratification ──
    print('\n[4a/4] Delta stratification...')

    def delta_bucket_label(d):
        for label, lo, hi in DELTA_BUCKETS:
            if lo <= d < hi:
                return label
        return 'Other'

    bucket_data = {label: [] for label, _, _ in DELTA_BUCKETS}
    for w in windows:
        bl = delta_bucket_label(w['delta'])
        bucket_data[bl].append(w)

    print(f'\n  Delta Buckets:')
    for label, lo, hi in DELTA_BUCKETS:
        members = bucket_data[label]
        if not members:
            continue
        n = len(members)
        avg_ret = sum(w['return_pct'] for w in members) / n
        avg_exc = sum(w['excess_pct'] for w in members) / n
        wins = sum(1 for w in members if w['excess_pct'] > 0)
        win_rate = wins / n * 100
        print(f'  {label:20s}  n={n:3d}  Return={avg_ret:>6.1f}%  Excess={avg_exc:>6.1f}%  WinRate={win_rate:>5.1f}%')

    # ── 4b. State × Delta interaction ──
    print(f'\n\n  State × Delta Interaction:')
    print(f'  {"State":22s} {"Delta Bucket":20s} {"N":>4s} {"Return":>8s} {"Excess":>8s} {"WinRate":>8s}')
    print(f'  {"-"*74}')

    states_order = ['MAIN_UP_CONFIRMED', 'CROWDING', 'CHAOS', 'REBOUND', 'RETREAT']
    for st in states_order:
        sw = [w for w in windows if w['state'] == st]
        if not sw:
            continue
        for label, lo, hi in DELTA_BUCKETS:
            members = [w for w in sw if lo <= w['delta'] < hi]
            if not members:
                continue
            n = len(members)
            avg_ret = sum(w['return_pct'] for w in members) / n
            avg_exc = sum(w['excess_pct'] for w in members) / n
            wins = sum(1 for w in members if w['excess_pct'] > 0)
            win_rate = wins / n * 100
            print(f'  {st:22s} {label:20s} {n:3d}  {avg_ret:>7.1f}% {avg_exc:>7.1f}% {win_rate:>6.1f}%')

    # Save
    out_path = OUTPUT_DIR / 'exp006b_delta_analysis.json'
    with open(out_path, 'w') as f:
        json.dump({
            'experiment': 'EXP-006B',
            'description': 'W2-W3 delta stratification + State x Delta interaction',
            'total_windows': len(windows),
            'delta_buckets': [
                {'label': label, 'lo': lo, 'hi': hi,
                 'windows': [w for w in windows if lo <= w['delta'] < hi]}
                for label, lo, hi in DELTA_BUCKETS
            ],
            'windows': windows,
        }, f, indent=2, ensure_ascii=False, default=str)

    print(f'\n  Output: {out_path}')
    print('\nEXP-006B complete')


# ────────────────────────────────────────────
# EXP-006C: Delta Lifecycle — Phase Position Analysis
# ────────────────────────────────────────────

DELTA_GROUPS_C = [
    ('Wash >> Launch',  2.0, 999),
    ('Wash > Launch',   0.5, 2.0),
    ('Balanced',       -0.5, 0.5),
    ('Launch > Wash',  -2.0, -0.5),
    ('Launch >> Wash', -999, -2.0),
]


def main_exp006c():
    """
    EXP-006C: For each Delta bucket, compute lifecycle curves (5/10/20/40/60D)
    to answer: does high Delta (Wash >> Launch) produce a "slow then strong"
    return structure?

    If yes, Delta is a Phase Position factor, not just a filter.
    """
    print('=' * 60)
    print('EXP-006C: Delta Lifecycle — Phase Position Analysis')
    print('=' * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print('\n[1/3] Loading sector data...')
    bm, sec_close, sec_amount, sec_name, _, _, _, _ = load_sector_data()
    bm_close = bm['close']
    bm_amount = bm['amount']

    print('\n[2/3] Scoring and computing delta + lifecycle...')
    all_dates = bm.index
    sym_list = list(sec_close.columns)
    eval_indices = list(range(MIN_HISTORY, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))

    def closest_before(series, dt):
        mask = series.index <= dt
        if not mask.any():
            return None, None
        idx = mask.sum() - 1
        if idx < len(series):
            return series.iloc[idx], idx
        return None, None

    # delta_bucket -> horizon -> list of return values
    from collections import defaultdict
    bucket_data = defaultdict(lambda: {h: {'returns': [], 'excess': [], 'wins': []}
                                       for h in HORIZONS})

    def delta_bucket_label(d):
        for label, lo, hi in DELTA_GROUPS_C:
            if lo <= d < hi:
                return label
        return 'Other'

    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]

        sector_components = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue
            comp = score_sector_components(s_close, s_amount, bm_close, bm_amount, eval_idx)
            if comp and 0 < comp['total'] <= 9:
                sector_components[sym] = comp
        if not sector_components:
            continue

        ranked = sorted(sector_components.items(), key=lambda x: x[1]['total'], reverse=True)
        top3_syms = [s[0] for s in ranked[:3]]
        top3_comps = [s[1] for s in ranked[:3]]

        avg_w2 = sum(c['w2'] for c in top3_comps) / len(top3_comps)
        avg_w3 = sum(c['w3'] for c in top3_comps) / len(top3_comps)
        delta = avg_w2 - avg_w3
        bl = delta_bucket_label(delta)

        # Pre-compute start prices for all top3 + benchmark
        p0_map = {}
        i0_map = {}
        for sym in top3_syms:
            p0, i0 = closest_before(sec_close[sym].dropna(), eval_date)
            if p0 is not None:
                p0_map[sym], i0_map[sym] = p0, i0
        if len(p0_map) < 1:
            continue

        bm_p0, bm_i0 = closest_before(bm_close, eval_date)
        if bm_p0 is None:
            continue

        for h in HORIZONS:
            ret_sum = 0.0
            valid = 0
            for sym in top3_syms:
                if sym not in i0_map:
                    continue
                series = sec_close[sym].dropna()
                end_idx = i0_map[sym] + h
                if end_idx >= len(series):
                    continue
                ret_sum += series.iloc[end_idx] / p0_map[sym] - 1
                valid += 1
            if valid == 0:
                continue
            sec_ret = ret_sum / valid

            bm_end_idx = bm_i0 + h
            if bm_end_idx >= len(bm_close):
                continue
            bm_ret = bm_close.iloc[bm_end_idx] / bm_p0 - 1

            excess = sec_ret - bm_ret
            win = 1 if sec_ret > bm_ret else 0

            bucket_data[bl][h]['returns'].append(sec_ret * 100)
            bucket_data[bl][h]['excess'].append(excess * 100)
            bucket_data[bl][h]['wins'].append(win)

    # ── 3. Print lifecycle tables per delta bucket ──
    print('\n[3/3] Delta lifecycle curves...')

    for label, lo, hi in DELTA_GROUPS_C:
        members = bucket_data[label]
        if not members:
            continue
        print(f'\n{"="*70}')
        print(f'  Delta Bucket: {label}  (W2-W3 in [{lo}, {hi}))')
        print(f'{"="*70}')
        print(f'  {"Horizon":8s} {"Windows":>7s} {"Return":>8s} {"Excess":>8s} {"WinRate":>8s}')
        print(f'  {"-"*43}')
        for h in HORIZONS:
            d = members[h]
            n = len(d['returns'])
            if n == 0:
                continue
            avg_ret = sum(d['returns']) / n
            avg_exc = sum(d['excess']) / n
            win_rate = sum(d['wins']) / n * 100
            print(f'  {f"{h}D":8s} {n:5d}   {avg_ret:>6.1f}% {avg_exc:>6.1f}% {win_rate:>6.1f}%')

    # Save
    out_path = OUTPUT_DIR / 'exp006c_delta_lifecycle.json'
    out_json = {'experiment': 'EXP-006C', 'description': 'Delta lifecycle curves',
                'delta_buckets': {}}
    for label, lo, hi in DELTA_GROUPS_C:
        members = bucket_data[label]
        if not members:
            continue
        horizons = {}
        for h in HORIZONS:
            d = members[h]
            n = len(d['returns'])
            if n == 0:
                continue
            horizons[f'{h}D'] = {
                'windows': n,
                'avg_return_pct': round(sum(d['returns']) / n, 2),
                'avg_excess_pct': round(sum(d['excess']) / n, 2),
                'win_rate_pct': round(sum(d['wins']) / n * 100, 1),
            }
        out_json['delta_buckets'][label] = {
            'range': f'[{lo}, {hi})',
            'horizons': horizons,
        }
    with open(out_path, 'w') as f:
        json.dump(out_json, f, indent=2, ensure_ascii=False)
    print(f'\n  Output: {out_path}')
    print('\nEXP-006C complete')


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--exp006':
        main_exp006()
    elif len(sys.argv) > 1 and sys.argv[1] == '--exp006a':
        main_exp006a()
    elif len(sys.argv) > 1 and sys.argv[1] == '--exp006b':
        main_exp006b()
    elif len(sys.argv) > 1 and sys.argv[1] == '--exp006c':
        main_exp006c()
    else:
        main()
