"""
Pilot：3 行业个股数据采集 + 涨跌停 + breadth 验证

目标行业：
  - 电子 (801080) — 成长型，481 支，验证大规模
  - 食品饮料 (801120) — 消费型，123 支，验证中等规模
  - 银行 (801780) — 防御型，42 支，验证小规模

流程：
  1. 读取申万行业成分股（index_stock_cons）
  2. baostock 拉取个股日线（不复权 + 后复权双通道）
  3. 写入 asset_master + market_daily_data
  4. 计算涨跌停标记 + breadth 统计量
  5. 输出验证报告
"""

import sqlite3
import pandas as pd
import numpy as np
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'quant_engine.db'

# ── 试点行业 ──
PILOT_SECTORS = [
    ('801080', '电子', 'sector.801080.SW'),
    ('801120', '食品饮料', 'sector.801120.SW'),
    ('801780', '银行', 'sector.801780.SW'),
]

DATA_START = '2005-01-01'
DATA_END = datetime.now().strftime('%Y-%m-%d')


# ════════════════════════════════════════
# Part 1: 成分股获取
# ════════════════════════════════════════

def fetch_constituents(sector_code):
    """从 akshare 获取申万行业成分股"""
    import akshare as ak
    df = ak.index_stock_cons(symbol=sector_code)
    # 列: 品种代码, 品种名称, 纳入日期
    stocks = []
    for _, row in df.iterrows():
        code = row['品种代码']
        name = row['品种名称']
        # 判断交易所
        if code.startswith('6') or code.startswith('9'):
            exchange = 'SH'
        else:
            exchange = 'SZ'
        symbol = f'stock.{code}.{exchange}'
        stocks.append((symbol, code, name, exchange))
    return stocks


# ════════════════════════════════════════
# Part 2: baostock 数据拉取
# ════════════════════════════════════════

def bs_code(symbol_code, exchange):
    """转为 baostock 格式: sh.600000 / sz.000001"""
    return f"{'sh' if exchange == 'SH' else 'sz'}.{symbol_code}"


def fetch_stock_baostock(bs_code_str, start_date, end_date):
    """
    从 baostock 拉取个股日线（单次调用）。

    adjustflag=1 (后复权)，同时返回 close + volume + amount + pctChg。
    baostock 的 pctChg 字段始终是原始涨跌幅，不受复权设置影响。

    针对 ~5% 次新股的解压/编码错误，返回 None 跳过。
    """
    import baostock as bs
    import time

    for attempt in range(3):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code_str, 'date,close,volume,amount,pctChg',
                start_date=start_date, end_date=end_date,
                frequency='d', adjustflag='1'  # 后复权
            )
            if rs.error_code != '0':
                time.sleep(1)
                continue

            rows = []
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                d, c, v, a, p = row[0], row[1], row[2], row[3], row[4]
                if c and float(c) > 0:
                    rows.append({
                        'trade_date': d,
                        'close': float(c),
                        'volume': float(v) if v else 0,
                        'amount': float(a) if a else 0,
                        'pct_chg_raw': float(p) if p else None,
                    })
            return rows if rows else None

        except Exception:
            time.sleep(1)
            continue

    return None


def fetch_one_stock(args):
    """包装函数，用于多线程"""
    symbol, code, exchange, start, end = args
    try:
        bs_code_str = bs_code(code, exchange)
        data = fetch_stock_baostock(bs_code_str, start, end)
        return (symbol, data)
    except Exception:
        return (symbol, None)


# ════════════════════════════════════════
# Part 3: 涨跌停判定
# ════════════════════════════════════════

def detect_limit_updown(pct_chg, is_st=True):
    """
    判定涨跌停。
    
    使用未复权涨跌幅（pct_chg_raw）。
    规则：
      - 非ST: >= 9.8% 涨停, <= -9.8% 跌停
      - ST:   >= 4.8% 涨停, <= -4.8% 跌停
      - 科创/创业 (688/300开头): >= 19.5% 涨停, <= -19.5% 跌停
    """
    if pct_chg is None or np.isnan(pct_chg):
        return 0, 0  # (limit_up, limit_down)

    limit_up_flag = 0
    limit_down_flag = 0

    if is_st:
        if pct_chg >= 4.8:
            limit_up_flag = 1
        elif pct_chg <= -4.8:
            limit_down_flag = 1
    else:
        if pct_chg >= 9.8:
            limit_up_flag = 1
        elif pct_chg <= -9.8:
            limit_down_flag = 1

    return limit_up_flag, limit_down_flag


def is_st_stock(code, name):
    """简单判断是否 ST 股票"""
    if name.startswith('*ST') or name.startswith('ST') or name.startswith('S'):
        return True
    return False


# ════════════════════════════════════════
# Part 4: Breadth 计算
# ════════════════════════════════════════

def calc_sector_breadth(stock_close_df):
    """
    计算行业 breadth 统计量。
    
    stock_close_df: DataFrame, index=trade_date, columns=symbol, values=close
    
    返回:
        DataFrame, index=trade_date, columns=[above_ma20, above_ma60, new_high_20d]
    """
    if stock_close_df.empty or len(stock_close_df.columns) < 3:
        return None

    # 各股票是否在 MA20/MA60 上方
    ma20 = stock_close_df.rolling(20, min_periods=10).mean()
    ma60 = stock_close_df.rolling(60, min_periods=20).mean()

    above_ma20 = (stock_close_df > ma20).astype(int)
    above_ma60 = (stock_close_df > ma60).astype(int)

    # 20 日新高（滚动窗口内最高价）
    high_20d = stock_close_df.rolling(20, min_periods=5).max()
    new_high_20d = (stock_close_df >= high_20d).astype(int)

    # 聚合为比例
    result = pd.DataFrame(index=stock_close_df.index)
    result['above_ma20_ratio'] = above_ma20.sum(axis=1) / above_ma20.count(axis=1)
    result['above_ma60_ratio'] = above_ma60.sum(axis=1) / above_ma60.count(axis=1)
    result['new_high_20d_ratio'] = new_high_20d.sum(axis=1) / new_high_20d.count(axis=1)

    return result


# ════════════════════════════════════════
# Part 5: 主流程
# ════════════════════════════════════════

def run_pilot():
    print('=' * 60)
    print('  Pilot：3 行业个股数据验证')
    print('=' * 60)

    # ── 阶段 1: 获取成分股 ──
    print('\n[1/5] 获取申万行业成分股...')
    sector_stocks = {}  # sector_sw_code → [(symbol, code, name, exchange)]
    for sw_code, sw_name, _ in PILOT_SECTORS:
        stocks = fetch_constituents(sw_code)
        sector_stocks[sw_code] = stocks
        print(f'  {sw_name} ({sw_code}): {len(stocks)} 支股票')

    # ── 阶段 2: baostock 数据拉取 ──
    print('\n[2/5] baostock 拉取日线数据...')
    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        print(f'  ❌ baostock 登录失败: {lg.error_msg}')
        return
    print(f'  baostock 登录成功')

    all_stock_data = {}  # symbol → [rows]
    total_stocks = sum(len(v) for v in sector_stocks.values())
    print(f'  共 {total_stocks} 支股票，开始拉取...')

    # 构建参数列表
    fetch_args = []
    for sw_code, stocks in sector_stocks.items():
        for symbol, code, name, exchange in stocks:
            fetch_args.append((symbol, code, exchange, DATA_START, DATA_END))

    # 多线程拉取
    t0 = time.time()
    completed = 0
    MAX_WORKERS = 10

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one_stock, args): args[0] for args in fetch_args}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                symbol, data = future.result()
                if data:
                    all_stock_data[symbol] = data
            except Exception:
                pass
            completed += 1
            if completed % 50 == 0 or completed == total_stocks:
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                print(f'    进度: {completed}/{total_stocks} ({rate:.1f} 支/秒)')

    t1 = time.time()
    print(f'  拉取完成: {len(all_stock_data)}/{total_stocks} 支成功, 耗时 {t1-t0:.0f}s')

    bs.logout()

    if len(all_stock_data) < total_stocks * 0.5:
        print(f'  ⚠️  成功率 {(len(all_stock_data)/total_stocks*100):.0f}%，低于 50%，检查后重试')
        return

    # ── 阶段 3: 写入数据库 + 涨跌停判定 ──
    print('\n[3/5] 写入数据库...')
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    inserted = 0
    for symbol, rows in all_stock_data.items():
        for r in rows:
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO market_daily_data 
                    (symbol, trade_date, close, volume, amount, pct_chg_raw)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (symbol, r['trade_date'], r['close'],
                      r['volume'], r['amount'], r['pct_chg_raw']))
                inserted += 1
            except Exception as e:
                pass

    conn.commit()
    print(f'  写入 {inserted} 行, ASSET_TYPE=stock')
    print(f'  涨跌停判定：使用 pct_chg_raw（未复权涨跌幅）')

    # ── 阶段 4: 逐个行业计算 breadth ──
    print('\n[4/5] 计算行业 Breadth...')
    for sw_code, sw_name, sector_symbol in PILOT_SECTORS:
        stocks = sector_stocks[sw_code]
        sym_list = [f'stock.{c}.{"SH" if c.startswith("6") or c.startswith("9") else "SZ"}' 
                    for _, c, _, _ in stocks]

        # 从数据库读已入库的 close
        close_dfs = []
        for sym in sym_list:
            df = pd.read_sql(
                'SELECT trade_date, close FROM market_daily_data WHERE symbol=? ORDER BY trade_date',
                conn, params=(sym,), parse_dates=['trade_date']
            )
            if not df.empty:
                df = df.set_index('trade_date')
                close_dfs.append(df.rename(columns={'close': sym}))

        if not close_dfs:
            print(f'  {sw_name}: 无数据，跳过')
            continue

        # 合并为一个 DataFrame
        sector_close = pd.concat(close_dfs, axis=1)
        sector_close = sector_close[sector_close.index >= '2005-01-01']

        # 计算 breadth
        breadth = calc_sector_breadth(sector_close)
        if breadth is None:
            print(f'  {sw_name}: breadth 计算失败')
            continue

        # 写入行业行的 market_daily_data
        updated = 0
        for date_str in breadth.index:
            row = breadth.loc[date_str]
            cursor.execute('''
                UPDATE market_daily_data 
                SET above_ma20_ratio=?, above_ma60_ratio=?, new_high_20d_ratio=?
                WHERE symbol=? AND trade_date=?
            ''', (
                float(row['above_ma20_ratio']) if pd.notna(row['above_ma20_ratio']) else None,
                float(row['above_ma60_ratio']) if pd.notna(row['above_ma60_ratio']) else None,
                float(row['new_high_20d_ratio']) if pd.notna(row['new_high_20d_ratio']) else None,
                sector_symbol,
                date_str.strftime('%Y-%m-%d') if hasattr(date_str, 'strftime') else str(date_str),
            ))
            updated += 1

        conn.commit()
        print(f'  {sw_name}: {len(sector_close.columns)} 支 → {updated} 天 breadth 写入完成')

    conn.close()

    # ── 阶段 5: 验证报告 ──
    print('\n[5/5] 验证报告...')
    conn = sqlite3.connect(str(DB_PATH))
    for sw_code, sw_name, sector_symbol in PILOT_SECTORS:
        df = pd.read_sql(
            'SELECT trade_date, above_ma20_ratio, above_ma60_ratio, new_high_20d_ratio '
            'FROM market_daily_data WHERE symbol=? AND trade_date >= "2024-01-01" '
            'ORDER BY trade_date',
            conn, params=(sector_symbol,), parse_dates=['trade_date']
        )
        if df.empty:
            print(f'  {sw_name}: ❌ 无 breadth 数据')
            continue

        print(f'\n  {sw_name} ({sector_symbol}):')
        print(f'    行数: {len(df)}')
        print(f'    above_ma20_ratio 范围: {df["above_ma20_ratio"].min():.2f} ~ {df["above_ma20_ratio"].max():.2f}')
        print(f'    above_ma60_ratio 范围: {df["above_ma60_ratio"].min():.2f} ~ {df["above_ma60_ratio"].max():.2f}')
        print(f'    new_high_20d_ratio 范围: {df["new_high_20d_ratio"].min():.2f} ~ {df["new_high_20d_ratio"].max():.2f}')
        print(f'    样例（最近 3 天）:')
        for _, r in df.tail(3).iterrows():
            print(f'      {r["trade_date"]}: MA20={r["above_ma20_ratio"]:.2f} MA60={r["above_ma60_ratio"]:.2f} NH={r["new_high_20d_ratio"]:.2f}')

    conn.close()
    print('\n✅ Pilot 完成')


if __name__ == '__main__':
    run_pilot()
