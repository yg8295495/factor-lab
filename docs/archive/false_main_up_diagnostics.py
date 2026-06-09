"""
EXP-004: False MAIN_UP diagnostics — compare 3 sample groups.

Reads daily state results + DB to compare feature distributions between:
  A = bear phase MAIN_UP days (false positives)
  B = bull phase MAIN_UP days (true positives)
  C = bear phase RETREAT days (true negatives)

Output: backend/research/analysis/output/market_state_false_main_up_diagnostics.json

Usage:
    python backend/research/analysis/market_state_false_main_up_diagnostics.py
"""

import json
import sqlite3
import numpy as np
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
PHASES_CSV = Path(__file__).resolve().parents[1] / 'labeling' / 'labels' / 'market_phases.csv'
BM_SYMBOL = 'index.000985.SH'
BM2_SYMBOL = 'index.000300.SH'

# Use v0.3 results (latest stable MAIN_UP)
DAILY_PATH = OUTPUT_DIR / 'market_state_daily_v03.json'


def load_phase_labels():
    import pandas as pd
    if not PHASES_CSV.exists():
        return None
    phases = pd.read_csv(PHASES_CSV, comment='#', parse_dates=['start_date', 'end_date'])
    last = phases.iloc[-1]
    if pd.isna(last['end_date']) or str(last['end_date']).strip() == '至今':
        phases.at[phases.index[-1], 'end_date'] = datetime.now().strftime('%Y-%m-%d')
        phases['end_date'] = pd.to_datetime(phases['end_date'])
    return phases


def is_in_bear_phase(date_str, phases):
    """Check if a trade_date falls in a bear phase."""
    import pandas as pd
    dt = pd.to_datetime(date_str)
    for _, p in phases.iterrows():
        if p['phase_type'] == 'bear' and p['start_date'] <= dt <= p['end_date']:
            return True
    return False


def is_in_bull_phase(date_str, phases):
    """Check if a trade_date falls in a bull phase."""
    import pandas as pd
    dt = pd.to_datetime(date_str)
    for _, p in phases.iterrows():
        if p['phase_type'] == 'bull' and p['start_date'] <= dt <= p['end_date']:
            return True
    return False


def main():
    import pandas as pd
    print("=" * 60)
    print("False MAIN_UP Diagnostics")
    print("=" * 60)

    # Load phases
    print("\n[1/4] Loading phase labels...")
    phases = load_phase_labels()
    if phases is None:
        print("  ERROR: no phase labels")
        return

    # Load daily results (v0.3)
    print("\n[2/4] Loading daily states...")
    with open(DAILY_PATH) as f:
        daily = json.load(f)
    print(f"  {len(daily)} days loaded")

    # Classify into 3 groups
    print("\n[3/4] Classifying sample groups...")
    group_a = []  # bear false MAIN_UP
    group_b = []  # bull true MAIN_UP
    group_c = []  # bear RETREAT

    for day in daily:
        if day['market_state'] == 'MAIN_UP':
            if is_in_bear_phase(day['trade_date'], phases):
                group_a.append(day['trade_date'])
            elif is_in_bull_phase(day['trade_date'], phases):
                group_b.append(day['trade_date'])
        elif day['market_state'] == 'RETREAT':
            if is_in_bear_phase(day['trade_date'], phases):
                group_c.append(day['trade_date'])

    print(f"  A: bear false MAIN_UP  = {len(group_a)} days")
    print(f"  B: bull true MAIN_UP   = {len(group_b)} days")
    print(f"  C: bear RETREAT        = {len(group_c)} days")

    # Load feature data from DB
    print("\n[4/4] Loading features from DB...")
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Load benchmark + 000300 data
    cursor.execute(
        "SELECT trade_date, close, time_momentum20, time_momentum60, "
        "trend_strength, breakout_strength, market_adv_ratio, "
        "adv_count, decl_count, limit_up_count, limit_down_count, "
        "amount_ratio "
        "FROM market_daily_data WHERE symbol = ? ORDER BY trade_date",
        (BM_SYMBOL,),
    )
    bm = pd.DataFrame(cursor.fetchall(), columns=[
        'trade_date', 'close', 'mom20', 'mom60', 'trend_str', 'breakout',
        'market_adv_ratio', 'adv_count', 'decl_count', 'lu_count', 'ld_count', 'amount_ratio',
    ])
    bm['trade_date'] = pd.to_datetime(bm['trade_date'])

    cursor.execute(
        "SELECT trade_date, industry_diffusion, market_volatility_20d, small_cap_spread "
        "FROM market_daily_data WHERE symbol = ? ORDER BY trade_date",
        (BM2_SYMBOL,),
    )
    bm2 = pd.DataFrame(cursor.fetchall(), columns=[
        'trade_date', 'industry_diffusion', 'vol_20d', 'small_cap_spread',
    ])
    bm2['trade_date'] = pd.to_datetime(bm2['trade_date'])

    # Load valid stock counts
    cursor.execute(
        "SELECT trade_date, COUNT(*) FROM market_daily_data "
        "WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL "
        "GROUP BY trade_date ORDER BY trade_date",
    )
    vc = pd.DataFrame(cursor.fetchall(), columns=['trade_date', 'valid_cnt'])
    vc['trade_date'] = pd.to_datetime(vc['trade_date'])
    conn.close()

    # Merge
    df = bm.merge(bm2, on='trade_date', how='left')
    df = df.merge(vc, on='trade_date', how='left')
    df = df.set_index('trade_date').sort_index()

    # Compute rolling features (same as the classifier)
    df['adv_20d'] = df['market_adv_ratio'].rolling(20).mean()
    df['diff_chg'] = df['industry_diffusion'].diff(20)
    df['amount_ratio_20d'] = df['amount_ratio'].rolling(20).mean()
    df['vol_percentile'] = df['vol_20d'].rolling(250).rank(pct=True) * 100
    df['dd_20d'] = (df['close'] - df['close'].rolling(20).max()) / df['close'].rolling(20).max() * 100
    df['dd_60d'] = (df['close'] - df['close'].rolling(60).max()) / df['close'].rolling(60).max() * 100
    df['dd_120d'] = (df['close'] - df['close'].rolling(120).max()) / df['close'].rolling(120).max() * 100
    df['ma120_r'] = df['close'] / df['close'].rolling(120).mean()
    df['ma250_r'] = df['close'] / df['close'].rolling(250).mean()
    df['lu_ratio'] = df['lu_count'] / df['valid_cnt'].replace(0, np.nan)
    df['ld_ratio'] = df['ld_count'] / df['valid_cnt'].replace(0, np.nan)
    df['lu_5d'] = df['lu_ratio'].rolling(5).mean()
    df['ld_5d'] = df['ld_ratio'].rolling(5).mean()

    features = [
        'trend_str', 'mom20', 'mom60', 'breakout',
        'ma120_r', 'ma250_r',
        'dd_20d', 'dd_60d', 'dd_120d',
        'adv_20d', 'industry_diffusion', 'diff_chg',
        'amount_ratio_20d',
        'lu_5d', 'ld_5d',
        'small_cap_spread', 'vol_percentile',
    ]

    feature_labels = {
        'trend_str': 'TREND_STR',
        'mom20': 'MOM20',
        'mom60': 'MOM60',
        'breakout': 'BREAKOUT',
        'ma120_r': 'close/MA120',
        'ma250_r': 'close/MA250',
        'dd_20d': 'drawdown_20d',
        'dd_60d': 'drawdown_60d',
        'dd_120d': 'drawdown_120d',
        'adv_20d': 'adv_ratio_20d',
        'industry_diffusion': 'industry_diffusion',
        'diff_chg': 'diffusion_20d_chg',
        'amount_ratio_20d': 'amount_ratio_20d',
        'lu_5d': 'limit_up_ratio_5d',
        'ld_5d': 'limit_down_ratio_5d',
        'small_cap_spread': 'small_cap_spread',
        'vol_percentile': 'volatility_percentile',
    }

    def calc_stats(date_list):
        rows = df.loc[pd.DatetimeIndex([pd.to_datetime(d) for d in date_list if pd.to_datetime(d) in df.index])]
        stats = {}
        for f in features:
            vals = rows[f].dropna().values
            if len(vals) == 0:
                stats[f] = None
            else:
                stats[f] = {
                    'mean': round(float(np.mean(vals)), 3),
                    'median': round(float(np.median(vals)), 3),
                    'p25': round(float(np.percentile(vals, 25)), 3),
                    'p75': round(float(np.percentile(vals, 75)), 3),
                    'min': round(float(np.min(vals)), 3),
                    'max': round(float(np.max(vals)), 3),
                    'n': int(len(vals)),
                }
        return stats

    # Compute
    print("\n  Computing feature distributions...")
    stats_a = calc_stats(group_a)
    stats_b = calc_stats(group_b)
    stats_c = calc_stats(group_c)

    # Print comparison table
    print(f"\n{'Feature':30s} {'False MU (A)':>12s} {'True MU (B)':>12s} {'Bear RET (C)':>12s} {'A vs B':>10s}")
    print("-" * 76)
    for f in features:
        label = feature_labels[f]
        a = stats_a[f]
        b = stats_b[f]
        c = stats_c[f]
        a_m = a['median'] if a else None
        b_m = b['median'] if b else None
        c_m = c['median'] if c else None
        diff = ""
        if a_m is not None and b_m is not None:
            d = a_m - b_m
            diff = f"{d:+.2f}" if abs(d) >= 0.01 else "~0"
        a_s = f"{a_m:>8.2f}" if a_m is not None else "  N/A"
        b_s = f"{b_m:>8.2f}" if b_m is not None else "  N/A"
        c_s = f"{c_m:>8.2f}" if c_m is not None else "  N/A"
        print(f"{label:30s} {a_s:>12s} {b_s:>12s} {c_s:>12s} {diff:>10s}")

    # Candidate rule evaluation
    print(f"\n  Evaluating candidate rules...")
    a_dates = pd.DatetimeIndex([pd.to_datetime(d) for d in group_a if pd.to_datetime(d) in df.index])
    b_dates = pd.DatetimeIndex([pd.to_datetime(d) for d in group_b if pd.to_datetime(d) in df.index])

    candidates = []

    # Rule: close > MA250
    cnt_a = int((df.loc[a_dates, 'close'] > df.loc[a_dates, 'close'].rolling(250).mean()).sum()) if len(a_dates) > 0 else 0
    cnt_b = int((df.loc[b_dates, 'close'] > df.loc[b_dates, 'close'].rolling(250).mean()).sum()) if len(b_dates) > 0 else 0
    candidates.append({
        'rule': 'close > MA250',
        'description': '价格站上250日均线',
        'false_main_up_removed': len(group_a) - cnt_a,
        'true_main_up_lost': len(group_b) - cnt_b,
        'false_removed_pct': round((len(group_a) - cnt_a) / len(group_a) * 100, 1) if group_a else 0,
        'true_lost_pct': round((len(group_b) - cnt_b) / len(group_b) * 100, 1) if group_b else 0,
    })

    # Rule: close > MA120 (already used, for reference)
    cnt_a = int((df.loc[a_dates, 'close'] > df.loc[a_dates, 'close'].rolling(120).mean()).sum()) if len(a_dates) > 0 else 0
    cnt_b = int((df.loc[b_dates, 'close'] > df.loc[b_dates, 'close'].rolling(120).mean()).sum()) if len(b_dates) > 0 else 0
    candidates.append({
        'rule': 'close > MA120',
        'description': '价格站上120日均线（v0.3已有）',
        'false_main_up_removed': len(group_a) - cnt_a,
        'true_main_up_lost': len(group_b) - cnt_b,
        'false_removed_pct': round((len(group_a) - cnt_a) / len(group_a) * 100, 1) if group_a else 0,
        'true_lost_pct': round((len(group_b) - cnt_b) / len(group_b) * 100, 1) if group_b else 0,
    })

    # Rule: diff_chg >= 0 AND adv_20d >= 0.58 (AND version)
    cnt_a = int(((df.loc[a_dates, 'diff_chg'] >= 0) & (df.loc[a_dates, 'adv_20d'] >= 0.58)).sum()) if len(a_dates) > 0 else 0
    cnt_b = int(((df.loc[b_dates, 'diff_chg'] >= 0) & (df.loc[b_dates, 'adv_20d'] >= 0.58)).sum()) if len(b_dates) > 0 else 0
    candidates.append({
        'rule': 'diff_chg >= 0 AND adv_20d >= 0.58',
        'description': '扩散变化不降 + 参与率高位',
        'false_main_up_removed': len(group_a) - cnt_a,
        'true_main_up_lost': len(group_b) - cnt_b,
        'false_removed_pct': round((len(group_a) - cnt_a) / len(group_a) * 100, 1) if group_a else 0,
        'true_lost_pct': round((len(group_b) - cnt_b) / len(group_b) * 100, 1) if group_b else 0,
    })

    # Rule: dd_120d > -10%
    cnt_a = int((df.loc[a_dates, 'dd_120d'] > -10).sum()) if len(a_dates) > 0 else 0
    cnt_b = int((df.loc[b_dates, 'dd_120d'] > -10).sum()) if len(b_dates) > 0 else 0
    candidates.append({
        'rule': 'drawdown_120d > -10%',
        'description': '120日回撤不超过10%',
        'false_main_up_removed': len(group_a) - cnt_a,
        'true_main_up_lost': len(group_b) - cnt_b,
        'false_removed_pct': round((len(group_a) - cnt_a) / len(group_a) * 100, 1) if group_a else 0,
        'true_lost_pct': round((len(group_b) - cnt_b) / len(group_b) * 100, 1) if group_b else 0,
    })

    # Rule: diff_chg >= 0 (standalone)
    cnt_a = int((df.loc[a_dates, 'diff_chg'] >= 0).sum()) if len(a_dates) > 0 else 0
    cnt_b = int((df.loc[b_dates, 'diff_chg'] >= 0).sum()) if len(b_dates) > 0 else 0
    candidates.append({
        'rule': 'diffusion_change >= 0',
        'description': '行业扩散率20日变化不下降',
        'false_main_up_removed': len(group_a) - cnt_a,
        'true_main_up_lost': len(group_b) - cnt_b,
        'false_removed_pct': round((len(group_a) - cnt_a) / len(group_a) * 100, 1) if group_a else 0,
        'true_lost_pct': round((len(group_b) - cnt_b) / len(group_b) * 100, 1) if group_b else 0,
    })

    # Rule: amount_ratio_20d >= 1.0
    cnt_a = int((df.loc[a_dates, 'amount_ratio_20d'] >= 1.0).sum()) if len(a_dates) > 0 else 0
    cnt_b = int((df.loc[b_dates, 'amount_ratio_20d'] >= 1.0).sum()) if len(b_dates) > 0 else 0
    candidates.append({
        'rule': 'amount_ratio_20d >= 1.0',
        'description': '20日均额比不低于1.0',
        'false_main_up_removed': len(group_a) - cnt_a,
        'true_main_up_lost': len(group_b) - cnt_b,
        'false_removed_pct': round((len(group_a) - cnt_a) / len(group_a) * 100, 1) if group_a else 0,
        'true_lost_pct': round((len(group_b) - cnt_b) / len(group_b) * 100, 1) if group_b else 0,
    })

    # Sort by best ratio: most false removed with least true lost
    candidates.sort(key=lambda x: x['true_main_up_lost'])

    print(f"\n  {'Rule':40s} {'False removed':>15s} {'True lost':>12s} {'Ratio':>10s}")
    print("-" * 77)
    for c in candidates:
        ratio = c['false_main_up_removed'] / max(c['true_main_up_lost'], 1)
        print(f"  {c['rule']:40s} {c['false_main_up_removed']:>3d}({c['false_removed_pct']:4.1f}%) {c['true_main_up_lost']:>3d}({c['true_lost_pct']:4.1f}%) {ratio:>8.1f}x")

    # Build output
    output = {
        'sample_counts': {
            'bear_false_main_up': len(group_a),
            'bull_true_main_up': len(group_b),
            'bear_retreat': len(group_c),
        },
        'feature_summary': {},
        'candidate_rules': candidates,
    }

    # Feature summary with readable names
    for f in features:
        label = feature_labels[f]
        entry = {}
        for group_name, stats in [('false_main_up', stats_a), ('true_main_up', stats_b), ('bear_retreat', stats_c)]:
            if stats and stats[f]:
                entry[group_name] = {
                    k: stats[f][k] for k in ['mean', 'median', 'p25', 'p75', 'min', 'max', 'n']
                }
            else:
                entry[group_name] = None
        output['feature_summary'][label] = entry

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'market_state_false_main_up_diagnostics.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  Output: {out_path}")
    print(f"\nDone")


if __name__ == '__main__':
    main()
