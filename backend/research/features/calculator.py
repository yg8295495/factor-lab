"""
因子计算引擎 — 从 market_daily_data 读取原始数据，计算因子，写回数据库

计算流程:
  1. 读取所有资产数据
  2. 计算 Tier 1 因子（单资产独立计算）
  3. 计算 Tier 2 因子（跨资产横截面聚合）
  4. 写回 market_daily_data

每个因子的 compute_fn 对应 registry.py 中的定义。
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
RS_BENCHMARK = 'index.000985.SH'  # 中证全指

# ────────────────────────────────────────────
# 数据加载
# ────────────────────────────────────────────

def load_asset_data(symbol, fields=None):
    """加载单个资产的全部数据"""
    conn = sqlite3.connect(str(DB_PATH))
    if fields:
        cols = ','.join(fields)
        sql = f'SELECT trade_date, {cols} FROM market_daily_data WHERE symbol = ? ORDER BY trade_date'
    else:
        sql = 'SELECT * FROM market_daily_data WHERE symbol = ? ORDER BY trade_date'
    df = pd.read_sql(sql, conn, params=(symbol,), parse_dates=['trade_date'])
    conn.close()
    return df.set_index('trade_date') if not df.empty else df


def load_all_assets(fields=None):
    """加载所有资产的数据"""
    conn = sqlite3.connect(str(DB_PATH))
    if fields:
        cols = ','.join(fields)
        sql = f'SELECT symbol, trade_date, {cols} FROM market_daily_data ORDER BY symbol, trade_date'
    else:
        sql = 'SELECT symbol, trade_date, close FROM market_daily_data ORDER BY symbol, trade_date'
    df = pd.read_sql(sql, conn, parse_dates=['trade_date'])
    conn.close()

    if df.empty:
        return df
    # 避免 pivot 时 trade_date 重复
    # pivot: symbol 为列, trade_date 为行
    pivot = df.pivot(index='trade_date', columns='symbol', values=fields[0] if fields else 'close')
    return pivot


# ────────────────────────────────────────────
# Tier 1 因子 — 单资产独立计算
# ────────────────────────────────────────────

def calc_rs(asset_df, lookback=20, method='rolling_mean_ratio'):
    """
    相对强度 RS
    RS = (标的收盘 / 标的基准日收盘) / (基准收盘 / 基准基准日收盘) × 1
    method='rolling_mean_ratio': 标的收盘 / 标的20日均值
    method='point_to_point': 标的收盘 / 20天前的收盘
    """
    close = asset_df['close']
    # 获取基准数据
    benchmark_df = load_asset_data(RS_BENCHMARK, fields=['close'])
    if benchmark_df.empty:
        return pd.Series(index=asset_df.index, dtype=float)

    # 对齐日期
    combined = pd.DataFrame({
        'close': close,
        'benchmark_close': benchmark_df['close']
    }).dropna()

    if method == 'rolling_mean_ratio':
        # RS = (标的/基准) / (标的20日均值/基准20日均值)
        rs = (combined['close'] / combined['benchmark_close']) / \
             (combined['close'].rolling(lookback).mean() / combined['benchmark_close'].rolling(lookback).mean())
    elif method == 'point_to_point':
        # RS = 标的20日收益 / 基准20日收益 × 基准当前值
        asset_ret = combined['close'] / combined['close'].shift(lookback)
        bench_ret = combined['benchmark_close'] / combined['benchmark_close'].shift(lookback)
        rs = asset_ret / bench_ret
    else:
        raise ValueError(f'Unknown method: {method}')

    return rs * 100  # 转成百分比风格


def calc_rs_slope(asset_df, lookback=20):
    """RS20 的线性回归斜率"""
    rs20 = calc_rs(asset_df, lookback=20)
    slope = rs20.rolling(lookback).apply(
        lambda x: np.polyfit(range(len(x)), x, 1)[0] if len(x) == lookback else np.nan,
        raw=True
    )
    return slope


def calc_time_momentum(asset_df, lookback=20):
    """时序动量 = 自身涨跌幅"""
    close = asset_df['close']
    mom = close / close.shift(lookback) - 1
    return mom * 100


def calc_trend_strength(asset_df):
    """趋势综合评分 0-100：RS20 + MOM20 + RS_SLOPE 归一化后平均"""
    rs20 = calc_rs(asset_df, lookback=20)
    mom20 = calc_time_momentum(asset_df, lookback=20)
    slope = calc_rs_slope(asset_df)

    # 滚动百分位归一化
    def to_percentile(series, window=250):
        return series.rolling(window).rank(pct=True) * 100

    p_rs = to_percentile(rs20)
    p_mom = to_percentile(mom20)
    p_slope = to_percentile(slope)

    strength = (p_rs + p_mom + p_slope) / 3
    return strength.clip(0, 100)


def calc_percentile_series(series, window=250):
    """滚动百分位"""
    return series.rolling(window).rank(pct=True) * 100


def calc_change_rate(series, lookback=20):
    """变化率"""
    return series.pct_change(periods=lookback, fill_method=None) * 100


def calc_breakout(asset_df, lookback=20):
    """突破强度 = (收盘 - 20日均线) / 20日均线"""
    close = asset_df['close']
    ma = close.rolling(lookback).mean()
    return (close - ma) / ma * 100


def calc_dividend_yield_percentile(asset_df, window=250):
    """股息率百分位"""
    if 'dividend_yield' not in asset_df.columns:
        return pd.Series(index=asset_df.index, dtype=float)
    dy = asset_df['dividend_yield']
    if dy.isna().all():
        return pd.Series(index=asset_df.index, dtype=float)
    return calc_percentile_series(dy, window)


def calc_price_vol_divergence(asset_df, lookback=5):
    """
    量价背离度
    正数 = 价涨量缩（顶背离风险）
    负数 = 价跌量增（底背离机会）
    """
    close = asset_df['close']
    volume = asset_df['volume'] if 'volume' in asset_df.columns else pd.Series(index=asset_df.index, dtype=float)

    if volume.isna().all():
        return pd.Series(index=asset_df.index, dtype=float)

    price_dir = close.diff(lookback)
    vol_dir = volume.diff(lookback)

    # 归一化
    price_z = (price_dir - price_dir.rolling(250).mean()) / price_dir.rolling(250).std()
    vol_z = (vol_dir - vol_dir.rolling(250).mean()) / vol_dir.rolling(250).std()

    # 背离 = 价格方向与成交量方向相反
    divergence = -(price_z * vol_z)  # 价涨量缩→正, 价跌量增→负
    return divergence


def calc_tier1_factors(symbol, db):
    """计算单个资产的所有 Tier 1 因子"""
    asset_df = load_asset_data(symbol)
    if asset_df.empty or 'close' not in asset_df.columns:
        return

    results = {}

    # RS系列
    results['rs20_cross'] = calc_rs(asset_df, lookback=20)
    results['rs60_cross'] = calc_rs(asset_df, lookback=60)
    results['time_momentum20'] = calc_time_momentum(asset_df, lookback=20)
    results['time_momentum60'] = calc_time_momentum(asset_df, lookback=60)
    results['trend_strength'] = calc_trend_strength(asset_df)
    results['breakout_strength'] = calc_breakout(asset_df)

    # PE相关（仅指数有PE数据）
    if 'pe_ttm' in asset_df.columns and asset_df['pe_ttm'].notna().any():
        results['pe_ttm_pct'] = calc_percentile_series(asset_df['pe_ttm'], 250)
        results['pe_change_rate'] = calc_change_rate(asset_df['pe_ttm'], 20)

    # 股息率
    if 'dividend_yield' in asset_df.columns:
        dy_pct = calc_dividend_yield_percentile(asset_df)
        if not dy_pct.isna().all():
            results['dividend_yield_pct'] = dy_pct

    # 量价背离
    if 'volume' in asset_df.columns:
        div = calc_price_vol_divergence(asset_df)
        if not div.isna().all():
            results['price_vol_divergence'] = div

    # 写回数据库
    cursor = db.cursor()
    for date_idx, row in asset_df.iterrows():
        date_str = date_idx.strftime('%Y-%m-%d')
        updates = []
        params = []

        # 遍历每个因子
        field_map = {
            'rs20_cross': 'rs20_cross',
            'rs60_cross': 'rs60_cross',
            'time_momentum20': 'time_momentum20',
            'time_momentum60': 'time_momentum60',
            'trend_strength': 'trend_strength',
            'breakout_strength': 'breakout_strength',
            'pe_ttm_pct': None,  # 暂不写入DB字段，先留着
            'pe_change_rate': None,
            'dividend_yield_pct': None,
            'price_vol_divergence': None,
        }

        for key, db_field in field_map.items():
            if db_field and key in results and date_idx in results[key].index:
                val = results[key].loc[date_idx]
                if pd.notna(val):
                    updates.append(f'{db_field} = ?')
                    params.append(round(float(val), 4))

        if updates:
            sql = f'UPDATE market_daily_data SET {", ".join(updates)} WHERE symbol = ? AND trade_date = ?'
            cursor.execute(sql, params + [symbol, date_str])

    db.commit()


# ────────────────────────────────────────────
# Tier 2 因子 — 横截面聚合
# ────────────────────────────────────────────

def calc_adv_decline_ratio(db):
    """涨跌比：申万30行业中上涨/下跌的比例"""
    sw_symbols = _get_sw_symbols(db)
    if not sw_symbols:
        return

    # 加载所有申万行业收盘价
    all_close = load_all_assets(['close'])
    if all_close.empty:
        return

    # 只保留申万行业
    sw_close = all_close[[c for c in all_close.columns if c in sw_symbols]]
    if sw_close.empty:
        return

    # 每日涨跌方向
    direction = sw_close.diff().dropna()

    # 计算涨跌比
    adv = (direction > 0).sum(axis=1)
    decl = (direction < 0).sum(axis=1)
    ratio = adv / (adv + decl).replace(0, np.nan)

    _write_tier2_factor(db, 'ADV_DECLINE_RATIO', ratio)


def calc_industry_diffusion(db, threshold=50, lookback=20):
    """行业扩散率：RS20 > threshold 的行业占比"""
    sw_symbols = _get_sw_symbols(db)
    if not sw_symbols:
        return

    # 逐个计算申万行业的RS20
    all_rs = {}
    for sym in sw_symbols:
        asset_df = load_asset_data(sym, fields=['close'])
        if not asset_df.empty:
            rs = calc_rs(asset_df, lookback=lookback)
            all_rs[sym] = rs

    if not all_rs:
        return

    rs_df = pd.DataFrame(all_rs)
    diffusion = (rs_df > threshold).sum(axis=1) / len(sw_symbols) * 100

    _write_tier2_factor(db, 'INDUSTRY_DIFFUSION', diffusion)


def calc_market_volatility(db, lookback=20):
    """市场波动率：申万行业平均收益率标准差"""
    sw_symbols = _get_sw_symbols(db)
    all_close = load_all_assets(['close'])
    if all_close.empty:
        return

    sw_close = all_close[[c for c in all_close.columns if c in sw_symbols]]
    if sw_close.empty:
        return

    # 日收益率
    returns = sw_close.pct_change(fill_method=None).dropna()

    # 每个行业的滚动波动率
    vol = returns.rolling(lookback).std() * np.sqrt(252) * 100
    market_vol = vol.mean(axis=1)

    _write_tier2_factor(db, 'VOLATILITY_20D', market_vol)


def calc_small_cap_spread(db, lookback=20):
    """大小票剪刀差 = 中证2000 RS - 沪深300 RS"""
    small_cap = 'index.932000.SH'
    large_cap = 'index.000300.SH'

    small_df = load_asset_data(small_cap, fields=['close'])
    large_df = load_asset_data(large_cap, fields=['close'])

    if small_df.empty or large_df.empty:
        return

    # 直接用收盘涨幅差（相对值），不需要RS
    small_ret = small_df['close'].pct_change(lookback)
    large_ret = large_df['close'].pct_change(lookback)
    spread = (small_ret - large_ret) * 100

    _write_tier2_factor(db, 'SMALL_CAP_SPREAD', spread)


def _get_sw_symbols(db):
    """获取所有申万行业symbol"""
    cursor = db.execute("SELECT symbol FROM asset_master WHERE asset_type = 'sector'")
    return [r[0] for r in cursor.fetchall()]


def _write_tier2_factor(db, factor_name, series):
    """将Tier 2因子写入market_daily_data表对应字段"""
    field_map = {
        'ADV_DECLINE_RATIO': 'adv_decline_ratio',
        'INDUSTRY_DIFFUSION': 'industry_diffusion',
        'VOLATILITY_20D': 'market_volatility_20d',
        'SMALL_CAP_SPREAD': 'small_cap_spread',
    }

    db_field = field_map.get(factor_name)
    if not db_field:
        return

    cursor = db.cursor()
    # 市场级因子写入沪深300（作为市场代表）
    market_symbol = 'index.000300.SH'
    for date_idx, val in series.items():
        if pd.notna(val):
            date_str = date_idx.strftime('%Y-%m-%d') if hasattr(date_idx, 'strftime') else str(date_idx)[:10]
            sql = f'UPDATE market_daily_data SET {db_field} = ? WHERE symbol = ? AND trade_date = ?'
            cursor.execute(sql, (round(float(val), 4), market_symbol, date_str))
    db.commit()


# ────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────

def run_all():
    """计算所有因子"""
    print('=' * 50)
    print(f'因子计算开始 — {datetime.now()}')
    print('=' * 50)

    db = sqlite3.connect(str(DB_PATH))

    # Step 1: Tier 1 因子
    print('\n[Step 1] Tier 1 因子 — 单资产计算...')
    cursor = db.execute('SELECT symbol FROM asset_master WHERE is_active = 1')
    symbols = [r[0] for r in cursor.fetchall()]
    for i, sym in enumerate(symbols, 1):
        if i % 10 == 0:
            print(f'  [{i}/{len(symbols)}] ...')
        calc_tier1_factors(sym, db)

    print(f'  ✅ Tier 1 完成')

    # Step 2: Tier 2 因子
    print('\n[Step 2] Tier 2 因子 — 横截面聚合...')

    print('  ADV_DECLINE_RATIO (涨跌比)...')
    calc_adv_decline_ratio(db)

    print('  INDUSTRY_DIFFUSION (行业扩散率)...')
    calc_industry_diffusion(db)

    print('  VOLATILITY_20D (市场波动率)...')
    calc_market_volatility(db)

    print('  SMALL_CAP_SPREAD (大小票剪刀差)...')
    calc_small_cap_spread(db)

    print('  ✅ Tier 2 完成')

    db.close()
    print(f'\n✅ 因子计算完成 — {datetime.now()}')


if __name__ == '__main__':
    run_all()
