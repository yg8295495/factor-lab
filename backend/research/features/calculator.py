"""
Factor Calculator (v2.0) — 17 factors from registry.py

⚠️ 本文件硬编码 BM = 'index.000985.SH'（旧基准）。
如需在 801003 上使用，改 BM 后重跑。完成后删除本行。

算法已通过 Phase A 交叉验证 (2026-06-08)。
所有 RS/Volatility 使用逐行业 for 循环，不使用矩阵预计算。
"""

import sqlite3, numpy as np, pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
BM = 'index.000985.SH'

# ── 数据加载 ──

def load_asset(symbol, fields=None):
    conn = sqlite3.connect(str(DB_PATH))
    cols = ','.join(fields) if fields else '*'
    df = pd.read_sql(f'SELECT trade_date, {cols} FROM market_daily_data WHERE symbol=? ORDER BY trade_date',
                     conn, params=(symbol,), parse_dates=['trade_date'])
    conn.close()
    return df.set_index('trade_date') if not df.empty else df

# ── ① Trend / Momentum ──

def calc_rs20(asset_df):
    """RS20 = (P(t)/P(t-20)) / (BM(t)/BM(t-20))"""
    close = asset_df['close_hfq'] if 'close_hfq' in asset_df.columns else asset_df['close']
    bm_df = load_asset(BM, fields=['close_hfq', 'close'])
    bc = bm_df['close_hfq'] if 'close_hfq' in bm_df.columns else bm_df['close']
    rs = (close / close.shift(20)) / (bc / bc.shift(20))
    return rs

def calc_mom(asset_df, lookback=20):
    """MOM = P(t)/P(t-N) - 1"""
    close = asset_df['close_hfq'] if 'close_hfq' in asset_df.columns else asset_df['close']
    return close / close.shift(lookback) - 1

def calc_accel(asset_df):
    """Accel = MOM20(t) - MOM20(t-5)"""
    mom20 = calc_mom(asset_df, 20)
    return mom20 - mom20.shift(5)

# ── ② Volatility ──

def calc_vol20(asset_df):
    """Vol20 = std(ret[t-20:t]) per-sector"""
    close = asset_df['close_hfq'] if 'close_hfq' in asset_df.columns else asset_df['close']
    ret = close.pct_change(fill_method=None)
    return ret.rolling(20, min_periods=10).std(ddof=1)

def calc_vol_ratio(asset_df):
    """VolRatio = Vol20(t) / Vol20(t-20)"""
    vol20 = calc_vol20(asset_df)
    return vol20 / vol20.shift(20)

# ── ⑤ Leadership (CR3/CR5 — cross-sector, computed per-date) ──

def calc_cr3(all_amts):
    """CR3 per date. all_amts: (n_dates,) amount array"""
    sorted_amts = np.sort(all_amts)[::-1]
    total = np.nansum(all_amts)
    if total > 0 and len(sorted_amts) >= 3:
        return np.sum(sorted_amts[:3]) / total
    return None

def calc_cr5(all_amts):
    sorted_amts = np.sort(all_amts)[::-1]
    total = np.nansum(all_amts)
    if total > 0 and len(sorted_amts) >= 5:
        return np.sum(sorted_amts[:5]) / total
    return None

# ── ⑥ Style ──

def calc_sc_spread():
    """SCSpread = 中证2000 ret - 沪深300 ret over lookback=20"""
    small = load_asset('index.932000.SH', fields=['close'])
    large = load_asset('index.000300.SH', fields=['close'])
    if small.empty or large.empty:
        return pd.Series(dtype=float)
    sr = small['close'].pct_change(20)
    lr = large['close'].pct_change(20)
    return (sr - lr).reindex(small.index)

def calc_adv_decl(db):
    """AdvDecl: 30 sectors advance / total valid"""
    sw = [r[0] for r in db.execute("SELECT symbol FROM asset_master WHERE asset_type='sector'").fetchall()]
    all_series = {}
    for sym in sw:
        df = load_asset(sym, fields=['close'])
        if not df.empty:
            all_series[sym] = df['close_hfq'] if 'close_hfq' in df.columns else df['close']
    if not all_series:
        return
    piv = pd.DataFrame(all_series)
    direction = piv.diff()
    adv = (direction > 0).sum(axis=1)
    decl = (direction < 0).sum(axis=1)
    ratio = adv / (adv + decl).replace(0, np.nan)
    _write_to_benchmark(db, ratio, 'adv_decline_ratio')

def _write_to_benchmark(db, series, field):
    cursor = db.cursor()
    bm_symbol = BM
    for dt, val in series.items():
        if pd.notna(val):
            cursor.execute(f'UPDATE market_daily_data SET {field}=? WHERE symbol=? AND trade_date=?',
                          (round(float(val), 4), bm_symbol, str(dt.date()) if hasattr(dt, 'date') else str(dt)[:10]))
    db.commit()
