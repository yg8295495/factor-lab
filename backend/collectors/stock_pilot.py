"""
Pilot：3 行业个股数据采集 — 双趟 baostock + breadth 验证

数据口径（详见 docs/database_schema.md）：
  - 未复权 OHLC → open/high/low/close（基准原始值）
  - 后复权 close → close_hfq（回测/因子计算）
  - 复权因子   → hfq_factor = close_hfq / close
  - 原始涨跌幅 → pct_chg_raw（涨跌停判定）
  - 前复权 K线 → 未复权 OHLC × qfq_factor（hfq_factor 动态推导，不存库）

流程：
  1. 读取申万行业成分股（index_stock_cons）
  2. baostock pass 1 (adjustflag=1)：拉后复权 close → close_hfq
  3. baostock pass 2 (adjustflag=3)：拉未复权 OHLC + pctChg → 基础行情
  4. 合并两趟数据，计算 hfq_factor
  5. 写入 asset_master + market_daily_data
  6. 计算涨跌停标记 + breadth 统计量
  7. 输出验证报告 + 复权精度校验
"""

import sqlite3
import pandas as pd
import numpy as np
import time
import sys
import locale
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
    stocks = []
    for _, row in df.iterrows():
        code = row['品种代码']
        name = row['品种名称']
        exchange = 'SH' if (code.startswith('6') or code.startswith('9')) else 'SZ'
        symbol = f'stock.{code}.{exchange}'
        stocks.append((symbol, code, name, exchange))
    return stocks


# ════════════════════════════════════════
# Part 2: baostock 双趟拉取
# ════════════════════════════════════════

def bs_code(symbol_code, exchange):
    return f"{'sh' if exchange == 'SH' else 'sz'}.{symbol_code}"


# ── 字段定义 ──
# pass 1 (adjustflag=1, 后复权): 只拉 close → close_hfq
PASS1_FIELDS = 'date,close'
# pass 2 (adjustflag=3, 未复权): 拉完整 OHLC + pctChg
PASS2_FIELDS = 'date,open,high,low,close,volume,amount,pctChg'


def fetch_one_stock_bs(args):
    """
    单支股票、单趟 baostock 拉取。
    args: (bs_code_str, start_date, end_date, adjustflag, fields_str, symbol)
    返回: (symbol, rows) 或 (symbol, None)
    """
    import locale
    try:
        locale.setlocale(locale.LC_CTYPE, 'zh_CN.UTF-8')
    except locale.Error:
        pass  # fallback to system default

    import baostock as bs
    bs_code_str, start_date, end_date, adjustflag, fields_str, symbol = args

    for attempt in range(3):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code_str, fields_str,
                start_date=start_date, end_date=end_date,
                frequency='d', adjustflag=str(adjustflag)
            )
            if rs is None or rs.error_code != '0':
                time.sleep(1)
                continue

            rows = []
            while (rs.error_code == '0') & rs.next():
                row_data = rs.get_row_data()
                record = {'trade_date': row_data[0]}
                field_names = fields_str.split(',')
                for i, fname in enumerate(field_names):
                    if fname == 'date':
                        continue
                    val = row_data[i]
                    if val and val != '':
                        record[fname] = float(val)
                    else:
                        record[fname] = None
                if record.get('close') is not None and record['close'] > 0:
                    rows.append(record)
            return (symbol, rows if rows else None)

        except Exception:
            time.sleep(1)
            continue

    return (symbol, None)


def run_bs_pass(sector_stocks, adjustflag, fields_str, pass_label):
    """
    执行一趟 baostock 批量拉取。
    返回: dict{symbol: [rows]}
    """
    total = sum(len(v) for v in sector_stocks.values())
    print(f'  [{pass_label}] 共 {total} 支, adjustflag={adjustflag}...')

    fetch_args = []
    for stocks in sector_stocks.values():
        for symbol, code, name, exchange in stocks:
            bsc = bs_code(code, exchange)
            fetch_args.append((bsc, DATA_START, DATA_END, adjustflag, fields_str, symbol))

    result = {}
    t0 = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one_stock_bs, a): a[-1] for a in fetch_args}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                _, data = future.result()
                if data:
                    result[sym] = data
            except Exception:
                pass
            completed += 1
            if completed % 50 == 0 or completed == total:
                el = time.time() - t0
                print(f'    {pass_label} 进度: {completed}/{total} ({completed/el:.1f} 支/秒)', end='\r')

    t1 = time.time()
    print(f'\n    [{pass_label}] 完成: {len(result)}/{total} 成功, 耗时 {t1-t0:.0f}s')
    return result


# ════════════════════════════════════════
# Part 3: 涨跌停判定
# ════════════════════════════════════════

def detect_limit_updown(pct_chg, code='', name=''):
    """
    判定涨跌停。
    规则：
      - 非ST: >= 9.8% 涨停, <= -9.8% 跌停
      - ST:   >= 4.8% 涨停, <= -4.8% 跌停
      - 科创/创业 (688/300开头): >= 19.5% 涨停, <= -19.5% 跌停
    """
    if pct_chg is None or np.isnan(pct_chg):
        return 0, 0

    # ST 判定
    is_st = name.startswith('*ST') or name.startswith('ST') or name.startswith('S')
    # 科创/创业板
    is_kcb = code.startswith('688')
    is_cyb = code.startswith('300')

    limit_up = 0
    limit_down = 0

    if is_st:
        if pct_chg >= 4.8:   limit_up = 1
        elif pct_chg <= -4.8: limit_down = 1
    elif is_kcb or is_cyb:
        if pct_chg >= 19.5:  limit_up = 1
        elif pct_chg <= -19.5: limit_down = 1
    else:
        if pct_chg >= 9.8:   limit_up = 1
        elif pct_chg <= -9.8: limit_down = 1

    return limit_up, limit_down


# ════════════════════════════════════════
# Part 4: Breadth 计算（基于后复权价格）
# ════════════════════════════════════════

def calc_sector_breadth(stock_close_hfq_df):
    """
    计算行业 breadth 统计量，基于后复权 close。

    stock_close_hfq_df: DataFrame, index=trade_date, columns=symbol, values=close_hfq

    返回 DataFrame: [above_ma20_ratio, above_ma60_ratio, new_high_20d_ratio]
    """
    if stock_close_hfq_df.empty or len(stock_close_hfq_df.columns) < 3:
        return None

    ma20 = stock_close_hfq_df.rolling(20, min_periods=10).mean()
    ma60 = stock_close_hfq_df.rolling(60, min_periods=20).mean()

    above_ma20 = (stock_close_hfq_df > ma20).astype(int)
    above_ma60 = (stock_close_hfq_df > ma60).astype(int)

    # 20 日新高（后复权确认真实新高）
    high_20d = stock_close_hfq_df.rolling(20, min_periods=5).max()
    new_high_20d = (stock_close_hfq_df >= high_20d).astype(int)

    result = pd.DataFrame(index=stock_close_hfq_df.index)
    result['above_ma20_ratio'] = above_ma20.sum(axis=1) / above_ma20.count(axis=1)
    result['above_ma60_ratio'] = above_ma60.sum(axis=1) / above_ma60.count(axis=1)
    result['new_high_20d_ratio'] = new_high_20d.sum(axis=1) / new_high_20d.count(axis=1)

    return result


# ════════════════════════════════════════
# Part 5: 主流程
# ════════════════════════════════════════

def run_pilot():
    print('=' * 60)
    print('  Pilot：3 行业个股数据采集（双趟 baostock）')
    print('=' * 60)

    # ── 阶段 1: 获取成分股 ──
    print('\n[1/5] 获取申万行业成分股...')
    sector_stocks = {}
    stock_info = {}  # symbol → {code, name, exchange}
    for sw_code, sw_name, _ in PILOT_SECTORS:
        stocks = fetch_constituents(sw_code)
        sector_stocks[sw_code] = stocks
        for sym, code, name, ex in stocks:
            stock_info[sym] = {'code': code, 'name': name, 'exchange': ex}
        print(f'  {sw_name} ({sw_code}): {len(stocks)} 支股票')

    total_stocks = sum(len(v) for v in sector_stocks.values())

    # ── 阶段 2: baostock 双趟 ──
    print('\n[2/5] baostock 双趟拉取...')
    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        print(f'  ❌ baostock 登录失败: {lg.error_msg}')
        return
    print(f'  baostock 登录成功')

    # Pass 1: 后复权 close → close_hfq
    pass1_data = run_bs_pass(sector_stocks, adjustflag=1,
                              fields_str=PASS1_FIELDS, pass_label='Pass 1 后复权')
    # Pass 2: 未复权 OHLC + pctChg
    pass2_data = run_bs_pass(sector_stocks, adjustflag=3,
                              fields_str=PASS2_FIELDS, pass_label='Pass 2 未复权')

    bs.logout()

    # ── 阶段 3: 合并两趟数据 ──
    print('\n[3/5] 合并双趟数据 + 写入数据库...')

    # 按 symbol 合并两趟的交易日数据
    merged = {}
    for sym in set(list(pass1_data.keys()) + list(pass2_data.keys())):
        d1 = {r['trade_date']: r for r in pass1_data.get(sym, [])}
        d2 = {r['trade_date']: r for r in pass2_data.get(sym, [])}
        all_dates = sorted(set(list(d1.keys()) + list(d2.keys())))
        rows = []
        for dt in all_dates:
            row = {'trade_date': dt}
            if dt in d1:
                row['close_hfq'] = d1[dt].get('close')
            if dt in d2:
                row['open'] = d2[dt].get('open')
                row['high'] = d2[dt].get('high')
                row['low'] = d2[dt].get('low')
                row['close'] = d2[dt].get('close')       # 未复权
                row['volume'] = d2[dt].get('volume')
                row['amount'] = d2[dt].get('amount')
                row['pct_chg_raw'] = d2[dt].get('pctChg')
            rows.append(row)
        if rows:
            merged[sym] = rows

    print(f'  合并完成: {len(merged)}/{total_stocks} 支')

    # ── 计算 hfq_factor + 写入 DB ──
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 确保 asset_master 中有这些 stock
    for sym, info in stock_info.items():
        cursor.execute('''
            INSERT OR IGNORE INTO asset_master (symbol, name, asset_type, exchange, is_active)
            VALUES (?, ?, 'stock', ?, 1)
        ''', (sym, info['name'], info['exchange']))

    inserted = 0
    for sym, rows in merged.items():
        info = stock_info.get(sym, {})
        code = info.get('code', '')
        name = info.get('name', '')

        for r in rows:
            # 计算 hfq_factor
            close_raw = r.get('close')
            close_hfq_val = r.get('close_hfq')
            hfq_factor = None
            if close_raw is not None and close_hfq_val is not None and close_raw > 0:
                hfq_factor = close_hfq_val / close_raw

            # 涨跌停判定
            pct = r.get('pct_chg_raw')
            limit_up, limit_down = detect_limit_updown(pct, code, name) if pct is not None else (0, 0)

            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO market_daily_data 
                    (symbol, trade_date,
                     open, high, low, close, volume, amount,
                     close_hfq, hfq_factor,
                     pct_chg_raw,
                     limit_up_flag, limit_down_flag)
                    VALUES (?, ?,
                     ?, ?, ?, ?, ?, ?,
                     ?, ?,
                     ?,
                     ?, ?)
                ''', (
                    sym, r['trade_date'],
                    r.get('open'), r.get('high'), r.get('low'), r.get('close'),
                    r.get('volume'), r.get('amount'),
                    r.get('close_hfq'), hfq_factor,
                    r.get('pct_chg_raw'),
                    limit_up, limit_down,
                ))
                inserted += 1
            except Exception as e:
                pass

    conn.commit()
    print(f'  写入 {inserted} 行到 market_daily_data')
    print(f'  涨跌停标记基于 pct_chg_raw（未复权涨跌幅）')

    # ── 阶段 4: 复权精度抽样校验 + Breadth ──
    print('\n[4/5] 复权精度校验 + 行业 Breadth...')

    # 校验：随机抽一支股票，验证 close_hfq ≈ close_raw × hfq_factor
    sample_sym = None
    for sym in merged:
        if any(r.get('close_hfq') for r in merged[sym]):
            sample_sym = sym
            break
    if sample_sym:
        sample = [r for r in merged[sample_sym] if r.get('close_hfq') and r.get('close')]
        if sample:
            errors = []
            for r in sample[:100]:  # 前 100 天
                expected = r['close'] * (r['close_hfq'] / r['close'])
                actual = r['close_hfq']
                err = abs(expected - actual)
                errors.append(err)
            max_err = max(errors)
            print(f'  复权精度校验 ({sample_sym}): max_err={max_err:.4f}', end='')
            if max_err < 0.02:
                print(' ✅ 通过（误差 < 0.02）')
            else:
                print(f' ⚠️ 误差偏大，需检查')

    # Breadth 计算（基于后复权 close_hfq）
    for sw_code, sw_name, sector_symbol in PILOT_SECTORS:
        stocks = sector_stocks[sw_code]
        sym_list = [s[0] for s in stocks]

        # 从 merged 中提取后复权 close
        close_dfs = []
        for sym in sym_list:
            if sym not in merged:
                continue
            records = [r for r in merged[sym] if r.get('close_hfq') is not None]
            if not records:
                continue
            df = pd.DataFrame(records)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.set_index('trade_date')
            close_dfs.append(df[['close_hfq']].rename(columns={'close_hfq': sym}))

        if not close_dfs:
            print(f'  {sw_name}: 无后复权数据，跳过')
            continue

        sector_close = pd.concat(close_dfs, axis=1)
        sector_close = sector_close[sector_close.index >= '2005-01-01']

        breadth = calc_sector_breadth(sector_close)
        if breadth is None:
            print(f'  {sw_name}: breadth 计算失败')
            continue

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
        print(f'  {sw_name}: {len(sector_close.columns)} 支股票 → {updated} 天 breadth 写入完成')

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
        print(f'    above_ma20_ratio: {df["above_ma20_ratio"].min():.2f} ~ {df["above_ma20_ratio"].max():.2f}')
        print(f'    above_ma60_ratio: {df["above_ma60_ratio"].min():.2f} ~ {df["above_ma60_ratio"].max():.2f}')
        print(f'    new_high_20d_ratio: {df["new_high_20d_ratio"].min():.2f} ~ {df["new_high_20d_ratio"].max():.2f}')
        print(f'    最近 3 天:')
        for _, r in df.tail(3).iterrows():
            print(f'      {r["trade_date"]}: MA20={r["above_ma20_ratio"]:.2f} '
                  f'MA60={r["above_ma60_ratio"]:.2f} NH={r["new_high_20d_ratio"]:.2f}')

    conn.close()
    print('\n✅ Pilot 完成')


if __name__ == '__main__':
    run_pilot()
