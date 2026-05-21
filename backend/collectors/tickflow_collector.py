"""
全量 A 股采集 — TickFlow 单源方案

用法：
  python backend/collectors/tickflow_collector.py --mode full     # 全量
  python backend/collectors/tickflow_collector.py --mode daily    # 每日增量

策略：
  - 同时拉取未复权（none）+ 后复权（backward），一次遍历写入
  - 5 线程并行
  - INSERT OR REPLACE，可断点续跑
"""

import sqlite3
import time
import argparse
import concurrent.futures
import threading
from pathlib import Path
from datetime import datetime
from tickflow import TickFlow

NAS_DB = '/Users/LiYuan/Downloads/stock_data.db'
LOCAL_DB = Path(__file__).resolve().parents[2] / 'data' / 'quant_engine.db'
MAX_WORKERS = 5
BATCH_SIZE = 200

_write_lock = threading.Lock()


def get_stock_list():
    conn = sqlite3.connect(NAS_DB)
    rows = conn.execute("""
        SELECT code, code_name, market FROM stock_basic
        WHERE type = 1 AND market != '未知'
        ORDER BY code
    """).fetchall()
    conn.close()

    stocks = []
    for nas_code, name, market in rows:
        mkt, cd = nas_code.split('.')
        tf_code = f'{cd}.{mkt.upper()}'
        local_sym = f'stock.{cd}.{mkt.upper()}'
        stocks.append((tf_code, local_sym, name))
    return stocks


def fetch_and_write_stock(args):
    """拉取单只股票两种复权口径，写入 DB"""
    tf_code, local_sym, name, max_local_date = args
    tf = TickFlow.free()
    result = {'symbol': local_sym, 'name': name, 'rows': 0, 'status': '成功'}

    try:
        # 需要拉多少条：全量5000，增量按需
        if max_local_date:
            # 增量模式：先拉5条看看最新日期，判断需要补多少
            recent = tf.klines.get(tf_code, period='1d', count=5,
                                    adjust='none', as_dataframe=True)
            if recent.empty:
                return {**result, 'status': '无数据'}
            latest_date = recent['trade_date'].iloc[0]
            if latest_date <= max_local_date:
                return {**result, 'status': '已是最新', 'rows': 0}
            # 还有更新的数据，拉全量然后过滤
            count = 5000
        else:
            count = 5000

        # 拉取未复权
        raw = tf.klines.get(tf_code, period='1d', count=count,
                            adjust='none', as_dataframe=True)
        if raw.empty:
            return {**result, 'status': '无数据'}

        # 拉取后复权
        adj = tf.klines.get(tf_code, period='1d', count=count,
                            adjust='backward', as_dataframe=True)
        if adj.empty:
            return {**result, 'status': '后复权无数据'}

        # 按日期索引
        adj_idx = {r['trade_date']: r for _, r in adj.iterrows()}

        db_rows = []
        for _, r in raw.iterrows():
            dt = r['trade_date']
            a = adj_idx.get(dt)
            if a is None:
                continue
            close_raw = r['close']
            close_hfq = a['close']
            hfq_factor = round(close_hfq / close_raw, 6) if close_raw and close_raw > 0 else None
            db_rows.append((
                local_sym, dt,
                r['open'], r['high'], r['low'], close_raw,
                r['volume'], r['amount'],
                close_hfq, hfq_factor,
            ))

        if max_local_date:
            db_rows = [r for r in db_rows if r[1] > max_local_date]

        if db_rows:
            with _write_lock:
                conn = sqlite3.connect(str(LOCAL_DB))
                conn.execute('PRAGMA synchronous=OFF')
                conn.executemany("""
                    INSERT OR REPLACE INTO market_daily_data
                        (symbol, trade_date, open, high, low, close, volume, amount,
                         close_hfq, hfq_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, db_rows)
                conn.commit()
                conn.close()

        return {**result, 'rows': len(db_rows)}

    except Exception as e:
        return {**result, 'status': str(e)[:60]}


def register_assets(stocks):
    local = sqlite3.connect(str(LOCAL_DB))
    for _, local_sym, name in stocks:
        mkt = local_sym.split('.')[2]
        local.execute("""
            INSERT OR IGNORE INTO asset_master (symbol, name, asset_type, exchange, is_active)
            VALUES (?, ?, 'stock', ?, 1)
        """, (local_sym, name, mkt))
    local.commit()
    local.close()
    print(f'  asset_master: {len(stocks)} 只注册完成')


def run(stocks, is_daily=False):
    mode = '增量' if is_daily else '全量'
    print(f'{mode}采集: {len(stocks)} 只, 并行{MAX_WORKERS}线程')

    # 获取本地最新日期
    max_local_date = None
    if is_daily:
        conn = sqlite3.connect(str(LOCAL_DB))
        max_local_date = conn.execute(
            "SELECT MAX(trade_date) FROM market_daily_data"
        ).fetchone()[0]
        conn.close()
        print(f'  本地最新: {max_local_date}')

    args_list = [(c, s, n, max_local_date) for c, s, n in stocks]
    t0 = time.time()
    total_rows = 0
    ok = fail = skip = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_and_write_stock, a): a for a in args_list}
        for f in concurrent.futures.as_completed(futures):
            r = f.result()
            total_rows += r['rows']
            if r['status'] == '成功':
                ok += 1
            elif r['status'] == '已是最新':
                skip += 1
            else:
                fail += 1

            done = ok + fail + skip
            if done % 500 == 0 or done == len(stocks):
                elapsed = time.time() - t0
                rate = done / elapsed
                print(f'  [{done}/{len(stocks)}  {rate:.1f}只/秒] '
                      f'成功{ok} 失败{fail} 跳过{skip} '
                      f'{total_rows}行  耗时{elapsed:.0f}s')

    elapsed = time.time() - t0
    print(f'\n{mode}完成!')
    print(f'  成功: {ok} / 失败: {fail} / 跳过: {skip}')
    print(f'  总行数: {total_rows}')
    print(f'  耗时: {elapsed:.0f}s ({elapsed/60:.1f}分)')
    print(f'  速度: {ok/elapsed:.1f}只/秒')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['full', 'daily'], default='full')
    args = parser.parse_args()

    print('加载股票列表...')
    stocks = get_stock_list()
    print(f'  A 股共 {len(stocks)} 只')

    register_assets(stocks)
    run(stocks, is_daily=(args.mode == 'daily'))
