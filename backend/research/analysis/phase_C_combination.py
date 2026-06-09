"""
Phase C: Factor Combination — no-state baseline backtest.
========================================================

Method:
  - 253 rolling windows (same as EXP-003)
  - Score = rank_pct(CR3) + rank_pct(Mom20) + rank_pct(Accel)
  - TOP N equal weight, N = 1/3/5
  - Benchmark: index.000985.SH

Also outputs "ranking order" diagnostic:
  Does TOP1 > TOP2 > TOP3 > ... in forward return?
  If yes, ranking has resolution. If no, selection is random.

Data reliability: for-loop per sector, no matrix shortcuts.
All factor formulas use Phase A verified definitions.
"""

import sqlite3, json, numpy as np, pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
BM_SYMBOL = 'index.000985.SH'

# EXP-003 params (identical)
REBALANCE_INTERVAL = 20
HOLD_LOOKAHEAD = 20
MIN_HISTORY = 120

# Baseline from STATUS.md
BASELINE = {
    'total_return_pct': 985.3,
    'excess_return_pct': 340.6,
    'max_drawdown_pct': -45.9,
    'description': 'EXP-003 Variant D: state=position, CHAOS>=6, TOP1-3',
}


def main():
    print('=' * 70)
    print('PHASE C: Factor Combination — No-State Baseline')
    print('Score = rank(CR3) + rank(Mom20) + rank(Accel)')
    print('=' * 70)

    # ── 1. Load ──
    print('\n[1/4] Loading data...')
    conn = sqlite3.connect(str(DB_PATH))
    bm = pd.read_sql(
        'SELECT trade_date, close FROM market_daily_data WHERE symbol=? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date']
    ).set_index('trade_date').sort_index()
    sec = pd.read_sql('''SELECT d.symbol, d.trade_date, d.close, d.amount,
                         d.above_ma20_ratio, d.amount_ratio
                         FROM market_daily_data d
                         JOIN asset_master a ON d.symbol=a.symbol
                         WHERE a.asset_type='sector' ORDER BY d.trade_date''',
                      conn, parse_dates=['trade_date'])
    conn.close()

    sec_close = sec.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    sec_amount = sec.pivot(index='trade_date', columns='symbol', values='amount').sort_index()
    sec_pr = sec.pivot(index='trade_date', columns='symbol', values='above_ma20_ratio').sort_index()
    sec_ar = sec.pivot(index='trade_date', columns='symbol', values='amount_ratio').sort_index()

    all_dates = bm.index; bm_close = bm['close']
    sym_list = list(sec_close.columns); n_sym = len(sym_list)
    n_dates = len(all_dates)
    print(f'  Sectors: {n_sym}, Days: {n_dates}')

    # ── 2. Pre-compute cross-sector CR3 ──
    print('\n[2/4] Pre-computing cross-sector CR3...')
    amt_mat = sec_amount.values
    cr3_arr = np.full(n_dates, np.nan)
    for i in range(n_dates):
        a = amt_mat[i]; vm = ~np.isnan(a); va = a[vm]; sa = np.sort(va)[::-1]; t = np.nansum(va)
        if t > 0 and len(sa) >= 3:
            cr3_arr[i] = np.sum(sa[:3]) / t

    # ── 3. Rolling eval ──
    print('\n[3/4] Running rolling backtest...')
    eval_indices = list(range(MIN_HISTORY, n_dates - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
    print(f'  Windows: {len(eval_indices)}')

    trade_log = []
    ranking_diag = []  # per-window TOP1..TOP10 forward returns

    for ei in eval_indices:
        eval_date = all_dates[ei]
        bm20_ratio = bm_close.iloc[ei] / bm_close.iloc[ei - 20]
        bm_fwd = bm_close.iloc[ei + 20] / bm_close.iloc[ei] - 1

        # Score all 30 sectors
        sector_scores = {}
        sector_fwds = {}

        for sym in sym_list:
            s = sec_close[sym].dropna()
            if len(s) < ei + 20:
                continue

            # CR3 (same for all sectors on this date)
            cr3 = cr3_arr[ei]
            if np.isnan(cr3):
                continue

            # Mom20
            p0 = s.iloc[ei]; p20 = s.iloc[ei - 20]
            if pd.isna(p0) or pd.isna(p20):
                continue
            mom20 = p0 / p20 - 1

            # Accel
            if ei >= 25:
                accel = mom20 - (s.iloc[ei - 5] / s.iloc[ei - 25] - 1)
            else:
                accel = 0

            # Forward return (for diagnostic)
            fwd20 = s.iloc[ei + 20] / p0 - 1

            sector_scores[sym] = {'cr3': cr3, 'mom20': mom20, 'accel': accel}
            sector_fwds[sym] = fwd20

        if len(sector_scores) < 5:
            continue

        # Rank each factor to percentile (0-1), sum
        syms = list(sector_scores.keys())
        cr3_vals = np.array([sector_scores[s]['cr3'] for s in syms])
        mom20_vals = np.array([sector_scores[s]['mom20'] for s in syms])
        accel_vals = np.array([sector_scores[s]['accel'] for s in syms])

        def rank_pct(arr):
            r = np.argsort(np.argsort(arr))  # rank 0..n-1
            return r / (len(arr) - 1) if len(arr) > 1 else r

        total_score = rank_pct(cr3_vals) + rank_pct(mom20_vals) + rank_pct(accel_vals)

        # Sort by total_score descending
        order = np.argsort(total_score)[::-1]
        ranked_syms = [syms[i] for i in order]

        # Ranking diagnostic: forward return of TOP1..TOP10
        fwd_by_rank = {}
        for rank_i, rsym in enumerate(ranked_syms[:10]):
            fwd_by_rank[f'rank_{rank_i+1}'] = round(float(sector_fwds.get(rsym, 0)), 6)
        fwd_by_rank['bm_fwd20'] = round(float(bm_fwd), 6)
        fwd_by_rank['date'] = str(eval_date.date())
        ranking_diag.append(fwd_by_rank)

        # Select TOP N
        for top_n in [1, 3, 5]:
            top_syms = ranked_syms[:top_n]
            eq_weight = 1.0 / top_n
            portfolio_ret = sum(sector_fwds.get(s, 0) for s in top_syms) * eq_weight

            trade_log.append({
                'eval_date': str(eval_date.date()),
                'top_n': top_n,
                'portfolio_return_pct': round(portfolio_ret * 100, 4),
                'benchmark_return_pct': round(bm_fwd * 100, 4),
                'excess_return_pct': round((portfolio_ret - bm_fwd) * 100, 4),
                'top_sectors': [str(s) for s in top_syms],
            })

    print(f'  Trades logged: {len(trade_log)}')

    # ── 4. Results ──
    print('\n[4/4] Computing results...')

    df = pd.DataFrame(trade_log)

    for top_n in [1, 3, 5]:
        sub = df[df['top_n'] == top_n]
        n_wins = len(sub)
        cum_portfolio = (sub['portfolio_return_pct'] / 100 + 1).prod()
        cum_bm = (sub['benchmark_return_pct'] / 100 + 1).prod()
        cum_excess = cum_portfolio - cum_bm
        win_rate = (sub['excess_return_pct'] > 0).mean() * 100

        # Max drawdown (on portfolio return, not excess)
        cum_port_series = (1 + sub['portfolio_return_pct'] / 100).cumprod()
        cum_bm_series = (1 + sub['benchmark_return_pct'] / 100).cumprod()
        port_peak = cum_port_series.cummax()
        port_dd = (cum_port_series / port_peak - 1).min() * 100

        print(f'\n  TOP {top_n} results ({n_wins} windows):')
        print(f'    Portfolio return: {cum_portfolio*100-100:>8.1f}%')
        print(f'    Benchmark return: {cum_bm*100-100:>8.1f}%')
        print(f'    Excess return:    {cum_excess*100:>+8.1f}%')
        print(f'    Win rate:         {win_rate:>7.1f}%')
        print(f'    Max DD (port):    {port_dd:>+7.1f}%')

    print(f'\n  {"="*50}')
    print(f'  BASELINE (EXP-003 Variant D):')
    print(f'    Excess return: +{BASELINE["excess_return_pct"]:.1f}%')
    print(f'    Max DD (port): {BASELINE["max_drawdown_pct"]:.1f}%')
    print(f'  {"*WARNING*":^50s}')
    print(f'  Benchmark alignment differs: this run 694% vs EXP-003 645%')
    print(f'  Direct comparison is approximate. See notes in JSON.')
    print(f'  {"="*50}')

    # ── Ranking order diagnostic ──
    print('\n' + '=' * 70)
    print('RANKING ORDER DIAGNOSTIC')
    print('Does TOP1 > TOP2 > TOP3 in forward return?')
    print('=' * 70)

    diag_df = pd.DataFrame(ranking_diag)
    avg_fwd = {}
    for i in range(1, 11):
        col = f'rank_{i}'
        if col in diag_df.columns:
            avg_fwd[f'TOP{i}'] = diag_df[col].mean() * 100

    print(f'\n  {"Rank":>8s}  {"Avg Forward 20D":>18s}')
    print(f'  {"-"*30}')
    for r, v in avg_fwd.items():
        print(f'  {r:>8s}  {v:>+15.2f}%')

    # Ordering check
    ordered = True
    prev_val = 999
    for i in range(1, 11):
        v = diag_df[f'rank_{i}'].mean()
        if v > prev_val:
            ordered = False
        prev_val = v

    print(f'\n  Strictly decreasing (TOP1 > TOP2 > ... > TOP10)? {ordered}')
    if not ordered:
        print('  → Ranking resolution is imperfect. Selection adds noise.')

    # ── Save ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'phase_C_combination.json'

    results_summary = {}
    for top_n in [1, 3, 5]:
        sub = df[df['top_n'] == top_n]
        n_wins = len(sub)
        cum_p = (sub['portfolio_return_pct'] / 100 + 1).prod()
        cum_b = (sub['benchmark_return_pct'] / 100 + 1).prod()
        cum_e = cum_p - cum_b
        wr = (sub['excess_return_pct'] > 0).mean() * 100
        cum_port_s = (1 + sub['portfolio_return_pct'] / 100).cumprod()
        port_peak = cum_port_s.cummax()
        dd = ((cum_port_s / port_peak - 1).min()) * 100
        results_summary[f'TOP{top_n}'] = {
            'windows': n_wins,
            'total_return_pct': round((cum_p - 1) * 100, 1),
            'benchmark_return_pct': round((cum_b - 1) * 100, 1),
            'excess_return_pct': round(cum_e * 100, 1),
            'win_rate_pct': round(wr, 1),
            'max_drawdown_port_pct': round(dd, 1),
        }

    ranking_order = {}
    for i in range(1, 11):
        col = f'rank_{i}'
        if col in diag_df.columns:
            ranking_order[f'TOP{i}'] = round(float(diag_df[col].mean() * 100), 4)

    output = {
        'experiment': 'Phase-C-Combination-v1',
        'method': 'Score = rank_pct(CR3) + rank_pct(Mom20) + rank_pct(Accel), no state filter, equal weight',
        'baseline': BASELINE,
        'results': results_summary,
        'ranking_order_diagnostic': ranking_order,
        'ranking_strictly_decreasing': ordered,
        'params': {
            'rebalance_interval': REBALANCE_INTERVAL,
            'hold_lookahead': HOLD_LOOKAHEAD,
            'asset_pool': '30 Shenwan sectors',
            'benchmark': BM_SYMBOL,
            'transaction_cost': 'none (v1)',
        },
        'notes': 'No-state baseline. Benchmark return differs from EXP-003 (694% vs 645%) due to 20D window alignment. '
                 'Max drawdown is on portfolio return (not excess). '
                 'Do not compare directly without state conditioning.',
    }
    json.dump(output, open(out_path, 'w'), indent=2, ensure_ascii=True, default=str)
    print(f'\n  Saved: {out_path}')
    print('\n  Done.')


if __name__ == '__main__':
    main()
