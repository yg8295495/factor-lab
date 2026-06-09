"""
每日增量更新脚本 — 所有数据源统一入口

用法：
    # 更新 full.db（台式完整版，含个股聚合）
    python backend/collectors/daily_update.py

    # 更新 base.db（随身版，跳过个股聚合）
    python backend/collectors/daily_update.py --db data/quant_engine_base.db

    # 仅更新 801003 K线+派生字段（最快）
    python backend/collectors/daily_update.py --db data/quant_engine_base.db --only-benchmark

工作模式：
  - 全量模式（默认）：更新所有数据
  - base模式（--db base.db）：跳过个股聚合（除非同目录有 full.db 可复制）
  - 仅基准模式（--only-benchmark）：最快，适合日常快速更新

增量原则：
  - K线：只拉取缺失日期，不重写历史
  - PE/PB：只拉取最新年份，COALESCE 合并
  - 派生字段：只重新计算最近 20 个交易日（amount_ratio/volatility/pe_ttm_pct）
  - 个股聚合（新高比/涨跌家数）：仅在 full.db 模式下从个股全量重算
"""

import sys, os, time, sqlite3, argparse
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "quant_engine.db"
BASE_DB_PATH = PROJECT_ROOT / "data" / "quant_engine_base.db"

import akshare as ak
import urllib3, pandas as pd
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── 配置 ──
SW_CODES = [
    ('sector.801010.SW', '801010', '农林牧渔'), ('sector.801030.SW', '801030', '化工'),
    ('sector.801040.SW', '801040', '钢铁'), ('sector.801050.SW', '801050', '有色金属'),
    ('sector.801080.SW', '801080', '电子'), ('sector.801110.SW', '801110', '家用电器'),
    ('sector.801120.SW', '801120', '食品饮料'), ('sector.801130.SW', '801130', '纺织服装'),
    ('sector.801140.SW', '801140', '轻工制造'), ('sector.801150.SW', '801150', '医药生物'),
    ('sector.801160.SW', '801160', '公用事业'), ('sector.801170.SW', '801170', '交通运输'),
    ('sector.801180.SW', '801180', '房地产'), ('sector.801200.SW', '801200', '商贸零售'),
    ('sector.801210.SW', '801210', '社会服务'), ('sector.801710.SW', '801710', '建筑材料'),
    ('sector.801720.SW', '801720', '建筑装饰'), ('sector.801730.SW', '801730', '电力设备'),
    ('sector.801740.SW', '801740', '国防军工'), ('sector.801750.SW', '801750', '计算机'),
    ('sector.801760.SW', '801760', '传媒'), ('sector.801770.SW', '801770', '通信'),
    ('sector.801780.SW', '801780', '银行'), ('sector.801790.SW', '801790', '非银金融'),
    ('sector.801880.SW', '801880', '汽车'), ('sector.801890.SW', '801890', '机械设备'),
    ('sector.801950.SW', '801950', '煤炭'), ('sector.801960.SW', '801960', '石油石化'),
    ('sector.801970.SW', '801970', '环保'), ('sector.801980.SW', '801980', '美容护理'),
]

BM_SYMBOL = 'index.801003.SW'
TRADING_DAYS_CACHE = 20  # amount_ratio/volatility 需要回算的窗口


def log(msg):
    print(f"  {msg}", flush=True)


def get_latest_date(conn, symbol):
    r = conn.execute('SELECT MAX(trade_date) FROM market_daily_data WHERE symbol=?', (symbol,)).fetchone()
    return r[0] if r[0] else None


def get_latest_pe_date(conn, symbol):
    r = conn.execute('SELECT MAX(trade_date) FROM market_daily_data WHERE symbol=? AND pe_ttm IS NOT NULL', (symbol,)).fetchone()
    return r[0] if r[0] else None


# ═══════════════════════════════════════════
# Stage 1: 801003 K线增量
# ═══════════════════════════════════════════

def stage_benchmark_kline(conn, is_base_mode):
    """增量补充 801003 K线"""
    log('[1/7] 801003 K线增量 ...')
    latest = get_latest_date(conn, BM_SYMBOL)
    log(f'  数据库最新日: {latest}')

    df = ak.index_hist_sw("801003")
    df = df.sort_values(df.columns[1])
    closes = df.iloc[:,5].astype(float)
    pct_chg = closes.pct_change() * 100.0

    inserted = 0
    for i in range(len(df)):
        dt = str(df.iloc[i, 1])
        if latest and dt <= latest:
            continue
        # 检查是否已存在
        exist = conn.execute('SELECT 1 FROM market_daily_data WHERE symbol=? AND trade_date=?', (BM_SYMBOL, dt)).fetchone()
        if exist:
            continue

        close_p = float(df.iloc[i, 5])
        conn.execute(
            'INSERT INTO market_daily_data (symbol, trade_date, open, high, low, close, close_hfq, hfq_factor, volume, amount, pct_chg_raw) '
            'VALUES (?,?,?,?,?,?, ?,?,?,?, ?)',
            (BM_SYMBOL, dt,
             float(df.iloc[i, 2]) if df.iloc[i, 2] else close_p,
             float(df.iloc[i, 4]) if df.iloc[i, 4] else close_p,
             float(df.iloc[i, 3]) if df.iloc[i, 3] else close_p,
             close_p, close_p, 1.0,
             float(df.iloc[i, 6]) if df.iloc[i, 6] else None,
             float(df.iloc[i, 7]) if df.iloc[i, 7] else None,
             float(pct_chg.iloc[i]) if pd.notna(pct_chg.iloc[i]) else None)
        )
        inserted += 1
    conn.commit()
    new_latest = get_latest_date(conn, BM_SYMBOL)
    log(f'  新增 {inserted} 行, 最新: {new_latest}')


# ═══════════════════════════════════════════
# Stage 2: 801003 PE/PB 增量
# ═══════════════════════════════════════════

def stage_pe_pb(conn):
    """增量补充 PE/PB（拉取最新年份）"""
    log('[2/7] 801003 PE/PB 增量 ...')
    latest = get_latest_pe_date(conn, BM_SYMBOL)
    start_year = int(latest[:4]) if latest else 2000
    current_year = datetime.now().year
    total = 0

    for yr in range(max(start_year - 1, 2000), current_year + 1):
        try:
            df = ak.index_analysis_daily_sw('市场表征', start_date=f'{yr}0101', end_date=f'{yr}1231')
            if df is None or len(df) == 0:
                continue
            code_col = df.columns[0]
            d = df[df[code_col] == '801003']
            if len(d) == 0:
                continue

            updated = 0
            for _, row in d.iterrows():
                trade_date = row.iloc[2]
                if latest and str(trade_date) <= latest and yr > start_year - 1:
                    continue
                pe = float(row.iloc[7]) if row.iloc[7] and not pd.isna(row.iloc[7]) else None
                pb = float(row.iloc[8]) if row.iloc[8] and not pd.isna(row.iloc[8]) else None
                if any(v is not None for v in [pe, pb]):
                    conn.execute(
                        'UPDATE market_daily_data SET pe_ttm = COALESCE(?, pe_ttm), pb = COALESCE(?, pb) '
                        'WHERE symbol=? AND trade_date=?',
                        (pe, pb, BM_SYMBOL, trade_date))
                    updated += 1
            conn.commit()
            total += updated
        except Exception as e:
            log(f'    {yr}: {str(e)[:50]}')
    log(f'  更新 {total} 行')



# ═══════════════════════════════════════════
# Stage 3: 行业 K线增量
# ═══════════════════════════════════════════

def stage_industry_kline(conn):
    """增量补充 30 行业 K线"""
    log('[3/7] 行业 K线增量 ...')
    done = 0
    for symbol, code, name in SW_CODES:
        latest = get_latest_date(conn, symbol)
        try:
            df = ak.index_hist_sw(code)
            if df is None or len(df) == 0:
                continue
            df = df.sort_values(df.columns[1])
            inserted = 0
            for i in range(len(df)):
                dt = str(df.iloc[i, 1])
                if latest and dt <= latest:
                    continue
                exist = conn.execute('SELECT 1 FROM market_daily_data WHERE symbol=? AND trade_date=?', (symbol, dt)).fetchone()
                if exist:
                    continue
                close_p = float(df.iloc[i, 5])
                conn.execute(
                    'INSERT INTO market_daily_data (symbol, trade_date, open, high, low, close, volume, amount) '
                    'VALUES (?,?,?,?,?,?,?,?)',
                    (symbol, dt,
                     float(df.iloc[i, 2]) if df.iloc[i, 2] else close_p,
                     float(df.iloc[i, 4]) if df.iloc[i, 4] else close_p,
                     float(df.iloc[i, 3]) if df.iloc[i, 3] else close_p,
                     close_p,
                     float(df.iloc[i, 6]) if df.iloc[i, 6] else None,
                     float(df.iloc[i, 7]) if df.iloc[i, 7] else None))
                inserted += 1
            conn.commit()
            if inserted > 0:
                nl = get_latest_date(conn, symbol)
                log(f'  {name}: +{inserted}行, 最新{nl}')
            done += 1
        except Exception as e:
            log(f'  {name}: FAIL {str(e)[:50]}')
        time.sleep(0.3)
    log(f'  完成: {done}/{len(SW_CODES)}')


# ═══════════════════════════════════════════
# Stage 4: 宏观数据（国债+两融）
# ═══════════════════════════════════════════

def stage_macro(conn):
    """增量补充国债收益率 + 两融余额"""
    log('[4/7] 宏观数据增量 ...')

    # 国债
    log('  10Y国债收益率 ...')
    df = ak.bond_zh_us_rate()
    df = df[['日期', '中国国债收益率10年']].dropna()
    df['日期'] = df['日期'].astype(str)

    latest_bond = get_latest_date(conn, 'macro.CN10Y')
    inserted = 0
    for _, row in df.iterrows():
        dt = str(row['日期'])
        if latest_bond and dt <= latest_bond:
            continue
        val = float(row['中国国债收益率10年'])
        conn.execute(
            'INSERT OR REPLACE INTO market_daily_data (symbol, trade_date, open, high, low, close, close_hfq, hfq_factor) '
            'VALUES (?,?,?,?,?,?,?,?)',
            ('macro.CN10Y', dt, val, val, val, val, val, 1.0))
        inserted += 1
    conn.commit()
    log(f'    新增 {inserted} 行')

    # 两融
    log('  两融余额 ...')
    try:
        df_sh = ak.macro_china_market_margin_sh()
        df_sz = ak.macro_china_market_margin_sz()
        df_sh = df_sh[['日期', '融资融券余额']].rename(columns={'融资融券余额': 'sh'})
        df_sz = df_sz[['日期', '融资融券余额']].rename(columns={'融资融券余额': 'sz'})
        df_sh['日期'] = df_sh['日期'].astype(str)
        df_sz['日期'] = df_sz['日期'].astype(str)
        merged = df_sh.merge(df_sz, on='日期', how='outer')
        merged['total'] = merged['sh'].fillna(0).astype(float) + merged['sz'].fillna(0).astype(float)
        merged = merged.dropna(subset=['total'])
        merged = merged[merged['total'] > 0]

        latest_margin = get_latest_date(conn, 'macro.MARGIN_TOTAL')
        inserted = 0
        for _, row in merged.iterrows():
            dt = str(row['日期'])
            if latest_margin and dt <= latest_margin:
                continue
            val = float(row['total'])
            conn.execute(
                'INSERT OR REPLACE INTO market_daily_data (symbol, trade_date, open, high, low, close, close_hfq, hfq_factor) '
                'VALUES (?,?,?,?,?,?,?,?)',
                ('macro.MARGIN_TOTAL', dt, val, val, val, val, val, 1.0))
            inserted += 1
        conn.commit()
        log(f'    新增 {inserted} 行')
    except Exception as e:
        log(f'    FAIL: {str(e)[:60]}')


# ═══════════════════════════════════════════
# Stage 5: 801003 派生字段（amount_ratio/volatility/pe_ttm_pct）
# ═══════════════════════════════════════════

def recalc_derived_fields(conn, symbol, window=20):
    """重新计算指定 symbol 最近 N 天的派生字段"""
    from statistics import stdev

    # amount_ratio
    rows = conn.execute(
        'SELECT trade_date, amount FROM market_daily_data WHERE symbol=? AND amount IS NOT NULL ORDER BY trade_date',
        (symbol,)).fetchall()
    for i in range(len(rows)):
        if i < window - 1:
            continue
        window_amt = [float(rows[j][1]) for j in range(i - window + 1, i + 1)]
        sma = sum(window_amt) / len(window_amt)
        if sma > 0:
            ar = round(float(rows[i][1]) / sma, 4)
            conn.execute(
                'UPDATE market_daily_data SET amount_ratio=? WHERE symbol=? AND trade_date=?',
                (ar, symbol, rows[i][0]))

    # market_volatility_20d
    rows2 = conn.execute(
        'SELECT trade_date, close FROM market_daily_data WHERE symbol=? AND close IS NOT NULL ORDER BY trade_date',
        (symbol,)).fetchall()
    daily_rets = [None] * len(rows2)
    for i in range(1, len(rows2)):
        prev = float(rows2[i-1][1])
        if prev > 0:
            daily_rets[i] = float(rows2[i][1]) / prev - 1
    for i in range(window, len(rows2)):
        w = [r for r in daily_rets[i-window+1:i+1] if r is not None]
        if len(w) >= 10:
            mu = sum(w) / len(w)
            var = sum((v - mu) ** 2 for v in w) / len(w)
            conn.execute(
                'UPDATE market_daily_data SET market_volatility_20d=? WHERE symbol=? AND trade_date=?',
                (round(var ** 0.5, 6), symbol, rows2[i][0]))

    # pe_ttm_pct
    rows3 = conn.execute(
        'SELECT trade_date, pe_ttm FROM market_daily_data WHERE symbol=? AND pe_ttm IS NOT NULL AND pe_ttm > 0 ORDER BY trade_date',
        (symbol,)).fetchall()
    for i in range(len(rows3)):
        pe = float(rows3[i][1])
        lookback = min(i, 2500)
        if lookback < 100:
            continue
        w = [float(rows3[j][1]) for j in range(i - lookback, i + 1)]
        valid = [v for v in w if v > 0]
        if len(valid) >= 100:
            pct = sum(1 for v in valid if v <= pe) / len(valid)
            conn.execute(
                'UPDATE market_daily_data SET pe_ttm_pct=? WHERE symbol=? AND trade_date=?',
                (pct, symbol, rows3[i][0]))
    conn.commit()

    cnt1 = conn.execute('SELECT COUNT(*) FROM market_daily_data WHERE symbol=? AND amount_ratio IS NOT NULL', (symbol,)).fetchone()[0]
    cnt2 = conn.execute('SELECT COUNT(*) FROM market_daily_data WHERE symbol=? AND market_volatility_20d IS NOT NULL', (symbol,)).fetchone()[0]
    cnt3 = conn.execute('SELECT COUNT(*) FROM market_daily_data WHERE symbol=? AND pe_ttm_pct IS NOT NULL', (symbol,)).fetchone()[0]
    total = conn.execute('SELECT COUNT(*) FROM market_daily_data WHERE symbol=?', (symbol,)).fetchone()[0]
    log(f'  amount_ratio: {cnt1}/{total}, volatility: {cnt2}/{total}, pe_ttm_pct: {cnt3}/{total}')


def stage_benchmark_derived(conn):
    log('[5/7] 801003 派生字段回算 ...')
    recalc_derived_fields(conn, BM_SYMBOL)


# ═══════════════════════════════════════════
# Stage 6: 行业额比回算（增量）
# ═══════════════════════════════════════════

def stage_industry_amount_ratio(conn):
    """行业额比回算（只回算最近窗口）"""
    log('[6/7] 行业额比回算 ...')
    for symbol, code, name in SW_CODES:
        try:
            recalc_derived_fields(conn, symbol)
        except Exception as e:
            log(f'  {name}: {str(e)[:50]}')
    log('  完成')


# ═══════════════════════════════════════════
# Stage 7: 个股聚合字段（new_high_ratios + market_emotion）
# ═══════════════════════════════════════════

def stage_stock_aggregation(conn, db_path):
    """
    全市场个股聚合 → 写入 801003
    需要个股数据，仅 full.db 模式可用。
    base.db 模式会尝试同目录的 full.db，找不到则跳过。
    """
    # 尝试从 full.db 读取聚合
    full_path = None
    if db_path == BASE_DB_PATH:
        if BASE_DB_PATH.parent.joinpath('quant_engine.db').exists():
            full_path = BASE_DB_PATH.parent.joinpath('quant_engine.db')
    elif 'base' in str(db_path).lower():
        p = Path(str(db_path).replace('_base', '').replace('base', ''))
        if p.exists():
            full_path = p

    if full_path and full_path.exists():
        log(f'[7/7] 从 full.db 复制个股聚合字段 ...')
        full_conn = sqlite3.connect(str(full_path))
        # 复制新高比例
        full_conn.execute("ATTACH DATABASE ? AS base", (str(db_path),))
        full_conn.execute('''
            INSERT OR REPLACE INTO base.market_daily_data (symbol, trade_date, new_high_20d_ratio, new_high_60d_ratio, new_high_120d_ratio)
            SELECT ?, trade_date, new_high_20d_ratio, new_high_60d_ratio, new_high_120d_ratio
            FROM market_daily_data
            WHERE symbol=? AND new_high_20d_ratio IS NOT NULL
        ''', (BM_SYMBOL, 'index.801001.SW'))
        full_conn.commit()
        # 复制涨跌家数
        full_conn.execute('''
            INSERT OR REPLACE INTO base.market_daily_data (symbol, trade_date, adv_count, decl_count, market_adv_ratio, limit_up_count, limit_down_count)
            SELECT ?, trade_date, adv_count, decl_count, market_adv_ratio, limit_up_count, limit_down_count
            FROM market_daily_data
            WHERE symbol=? AND adv_count IS NOT NULL
        ''', (BM_SYMBOL, BM_SYMBOL))
        full_conn.commit()
        full_conn.execute("DETACH DATABASE base")
        full_conn.close()

        total = conn.execute('SELECT COUNT(*) FROM market_daily_data WHERE symbol=?', (BM_SYMBOL,)).fetchone()[0]
        nh = conn.execute(f'SELECT COUNT(*) FROM market_daily_data WHERE symbol=? AND new_high_20d_ratio IS NOT NULL', (BM_SYMBOL,)).fetchone()[0]
        ad = conn.execute(f'SELECT COUNT(*) FROM market_daily_data WHERE symbol=? AND adv_count IS NOT NULL', (BM_SYMBOL,)).fetchone()[0]
        log(f'  完成: new_high_20d={nh}/{total}, adv_count={ad}/{total}')
        return

    # 没有 full.db → 从全市场个股直接聚合（full.db模式）
    log('[7/7] 个股聚合字段重算（全量）...')

    conn.execute('DROP TABLE IF EXISTS market_emotion')
    conn.execute('''
        CREATE TEMP TABLE market_emotion AS
        SELECT trade_date,
            SUM(CASE WHEN pct_chg_raw > 0 THEN 1 ELSE 0 END) AS adv_count,
            SUM(CASE WHEN pct_chg_raw < 0 THEN 1 ELSE 0 END) AS decl_count,
            SUM(CASE WHEN limit_up_flag = 1 THEN 1 ELSE 0 END) AS limit_up_count,
            SUM(CASE WHEN limit_down_flag = 1 THEN 1 ELSE 0 END) AS limit_down_count
        FROM market_daily_data
        WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL
        GROUP BY trade_date
    ''')
    conn.commit()
    conn.execute('''
        UPDATE market_daily_data
        SET adv_count = e.adv_count, decl_count = e.decl_count,
            market_adv_ratio = ROUND(CASE WHEN (e.adv_count + e.decl_count) > 0
                THEN e.adv_count * 1.0 / (e.adv_count + e.decl_count)
                ELSE NULL END, 4),
            limit_up_count = e.limit_up_count, limit_down_count = e.limit_down_count
        FROM market_emotion AS e
        WHERE market_daily_data.symbol=? AND market_daily_data.trade_date = e.trade_date
    ''', (BM_SYMBOL,))
    conn.commit()
    conn.execute('DROP TABLE IF EXISTS market_emotion')

    total = conn.execute('SELECT COUNT(*) FROM market_daily_data WHERE symbol=?', (BM_SYMBOL,)).fetchone()[0]
    ad = conn.execute(f'SELECT COUNT(*) FROM market_daily_data WHERE symbol=? AND adv_count IS NOT NULL', (BM_SYMBOL,)).fetchone()[0]
    log(f'  adv_count: {ad}/{total}')


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='每日数据增量更新')
    parser.add_argument('--db', default=str(DB_PATH), help='数据库路径')
    parser.add_argument('--only-benchmark', action='store_true', help='仅更新801003 K线+派生字段')
    args = parser.parse_args()

    db_path = Path(args.db)
    is_base_mode = 'base' in db_path.name.lower()
    only_benchmark = args.only_benchmark

    print('=' * 50)
    print(f'每日数据增量更新 — {datetime.now()}')
    print(f'数据库: {db_path} ({"base" if is_base_mode else "full"}模式)')
    print('=' * 50)

    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=OFF')
    sqlite3.dbapi2.register_adapter(date, lambda d: d.isoformat())

    t_start = time.time()

    try:
        stage_benchmark_kline(conn, is_base_mode)
        stage_pe_pb(conn)

        if not only_benchmark:
            stage_industry_kline(conn)
            stage_macro(conn)

        stage_benchmark_derived(conn)

        if not only_benchmark:
            stage_industry_amount_ratio(conn)
            stage_stock_aggregation(conn, db_path)
    finally:
        conn.close()

    elapsed = time.time() - t_start
    print(f'\n完成 ({elapsed:.1f}s)')


if __name__ == '__main__':
    main()
