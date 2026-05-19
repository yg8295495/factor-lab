"""
一键重建数据库 — 统一数据源，统一截止日期

方案:
  - 25个指数 → CSI接口 (stock_zh_index_hist_csindex) 含PE ✅
  - 30个申万 → 申万接口 (index_hist_sw) ✅
  - 1个创业板指 → daily(volume) + 腾讯(amount) 合并

用法: python factor-lab/backend/rebuild_db.py
"""

import akshare as ak
import sqlite3
import time
import pandas as pd
from datetime import datetime

DB_PATH = 'factor-lab/data/quant_engine.db'

# ============================================================
# 资产清单
# ============================================================

# 25个CSI指数 (symbol, csi_code, name)
CSI_ASSETS = [
    # 宽基 (10个)
    ('index.000001.SH', '000001', '上证指数'),
    ('index.000300.SH', '000300', '沪深300'),
    ('index.000905.SH', '000905', '中证500'),
    ('index.000852.SH', '000852', '中证1000'),
    ('index.932000.SH', '932000', '中证2000'),
    ('index.000688.SH', '000688', '科创50'),
    ('index.000016.SH', '000016', '上证50'),
    ('index.000985.SH', '000985', '中证全指'),
    ('index.000510.SH', '000510', '中证A500'),
    # 中证主题 (15个)
    ('index.399997.SZ', '399997', '中证白酒'),
    ('index.399967.SZ', '399967', '中证军工'),
    ('index.399986.SZ', '399986', '中证银行'),
    ('index.H30590.SH', 'H30590', '中证机器人'),
    ('index.000941.SH', '000941', '中证内地新能源'),
    ('index.399989.SZ', '399989', '中证医疗'),
    ('index.931152.SZ', '931152', '中证创新药'),
    ('index.399975.SZ', '399975', '证券公司'),
    ('index.990001.SH', '990001', '中华半导体芯片'),
    ('index.930713.SH', '930713', 'CS人工智'),
    ('index.930651.SH', '930651', 'CS计算机'),
    ('index.399976.SZ', '399976', 'CS新能车'),
    ('index.931719.SZ', '931719', 'CS电池'),
    ('index.931151.SZ', '931151', '中证光伏产业'),
    ('index.000819.SH', '000819', '中证申万有色金属'),
]

# 30个申万行业 (symbol, sw_code, name)
SW_ASSETS = [
    ('sector.801010.SW', '801010', '农林牧渔'),
    ('sector.801030.SW', '801030', '化工'),
    ('sector.801040.SW', '801040', '钢铁'),
    ('sector.801050.SW', '801050', '有色金属'),
    ('sector.801080.SW', '801080', '电子'),
    ('sector.801110.SW', '801110', '家用电器'),
    ('sector.801120.SW', '801120', '食品饮料'),
    ('sector.801130.SW', '801130', '纺织服装'),
    ('sector.801140.SW', '801140', '轻工制造'),
    ('sector.801150.SW', '801150', '医药生物'),
    ('sector.801160.SW', '801160', '公用事业'),
    ('sector.801170.SW', '801170', '交通运输'),
    ('sector.801180.SW', '801180', '房地产'),
    ('sector.801200.SW', '801200', '商贸零售'),
    ('sector.801210.SW', '801210', '社会服务'),
    ('sector.801710.SW', '801710', '建筑材料'),
    ('sector.801720.SW', '801720', '建筑装饰'),
    ('sector.801730.SW', '801730', '电力设备'),
    ('sector.801740.SW', '801740', '国防军工'),
    ('sector.801750.SW', '801750', '计算机'),
    ('sector.801760.SW', '801760', '传媒'),
    ('sector.801770.SW', '801770', '通信'),
    ('sector.801780.SW', '801780', '银行'),
    ('sector.801790.SW', '801790', '非银金融'),
    ('sector.801880.SW', '801880', '汽车'),
    ('sector.801890.SW', '801890', '机械设备'),
    ('sector.801950.SW', '801950', '煤炭'),
    ('sector.801960.SW', '801960', '石油石化'),
    ('sector.801970.SW', '801970', '环保'),
    ('sector.801980.SW', '801980', '美容护理'),
]

# 创业板指 (特殊处理)
GEM = ('index.399006.SZ', 'sz399006', '创业板指')


def write_asset_master(db):
    """写入 asset_master"""
    db.execute('DELETE FROM asset_master')
    for symbol, _, name in CSI_ASSETS:
        asset_type = 'index'
        exchange = symbol.split('.')[-1]
        db.execute('INSERT INTO asset_master (symbol,name,asset_type,exchange,is_active) VALUES (?,?,?,?,1)',
                   (symbol, name, asset_type, exchange))
    for symbol, _, name in SW_ASSETS:
        db.execute('INSERT INTO asset_master (symbol,name,asset_type,exchange,is_active) VALUES (?,?,?,?,1)',
                   (symbol, name, 'sector', 'SW'))
    # 创业板指
    db.execute('INSERT INTO asset_master (symbol,name,asset_type,exchange,is_active) VALUES (?,?,?,?,1)',
               (GEM[0], GEM[2], 'index', 'SZ'))
    db.commit()


def fetch_csi(symbol, code, name):
    """从CSI接口拉指数数据"""
    df = ak.stock_zh_index_hist_csindex(symbol=code, start_date='19900101', end_date='20260519')
    if df is None or len(df) == 0:
        return []

    rows = []
    for _, r in df.iterrows():
        trade_date = r['日期']
        o = float(r['开盘']) if pd.notna(r['开盘']) else None
        h = float(r['最高']) if pd.notna(r['最高']) else None
        l = float(r['最低']) if pd.notna(r['最低']) else None
        c = float(r['收盘']) if pd.notna(r['收盘']) else None
        v = float(r['成交量']) if pd.notna(r['成交量']) else None
        a = float(r['成交金额']) if pd.notna(r['成交金额']) else None
        pe = float(r['滚动市盈率']) if pd.notna(r['滚动市盈率']) else None
        rows.append((symbol, str(trade_date), o, h, l, c, v, a, pe))
    return rows


def fetch_sw(symbol, code, name):
    """从申万接口拉行业数据"""
    df = ak.index_hist_sw(symbol=code)
    if df is None or len(df) == 0:
        return []

    rows = []
    for _, r in df.iterrows():
        trade_date = r['日期']
        c = float(r['收盘']) if pd.notna(r['收盘']) else None
        o = float(r['开盘']) if pd.notna(r['开盘']) else c
        h = float(r['最高']) if pd.notna(r['最高']) else c
        l = float(r['最低']) if pd.notna(r['最低']) else c
        v = float(r['成交量']) if pd.notna(r['成交量']) else None
        a = float(r['成交额']) if pd.notna(r['成交额']) else None
        rows.append((symbol, str(trade_date), o, h, l, c, v, a, None))
    return rows


def fetch_gem(symbol, code, name):
    """创业板指：从 daily(volume) + 腾讯(amount) 合并"""
    df_v = ak.stock_zh_index_daily(symbol=code)
    df_a = ak.stock_zh_index_daily_tx(symbol=code)
    if df_v is None or len(df_v) == 0:
        return []

    # 腾讯源有 amount，按日期合并
    amount_map = {}
    if df_a is not None and len(df_a) > 0:
        for _, r in df_a.iterrows():
            amount_map[str(r['date'])] = float(r['amount']) if pd.notna(r['amount']) else None

    rows = []
    for _, r in df_v.iterrows():
        trade_date = str(r['date'])
        o = float(r['open']) if pd.notna(r['open']) else None
        h = float(r['high']) if pd.notna(r['high']) else None
        l = float(r['low']) if pd.notna(r['low']) else None
        c = float(r['close']) if pd.notna(r['close']) else None
        v = float(r['volume']) if pd.notna(r['volume']) else None
        a = amount_map.get(trade_date, None)
        rows.append((symbol, trade_date, o, h, l, c, v, a, None))
    return rows


def main():
    print('=' * 60)
    print('一键重建数据库')
    print(f'开始: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)

    db = sqlite3.connect(DB_PATH)

    # Step 1: 清空
    print('\n[Step 1] 清空数据库...')
    db.execute('DELETE FROM market_daily_data')
    db.execute('DELETE FROM asset_master')
    db.commit()

    # Step 2: 写入 asset_master
    print('[Step 2] 写入 asset_master...')
    write_asset_master(db)
    cnt = db.execute('SELECT COUNT(*) FROM asset_master').fetchone()[0]
    print(f'  asset_master: {cnt} 条')

    # Step 3: CSI指数 (25个)
    print('\n[Step 3] CSI接口 → 25个指数...')
    csi_ok = 0
    csi_rows = 0
    for symbol, code, name in CSI_ASSETS:
        print(f'  {name:12s} ({code}) ...', end=' ', flush=True)
        try:
            rows = fetch_csi(symbol, code, name)
            if rows:
                db.executemany(
                    'INSERT INTO market_daily_data (symbol,trade_date,open,high,low,close,volume,amount,pe_ttm) VALUES (?,?,?,?,?,?,?,?,?)',
                    rows
                )
                db.commit()
                csi_ok += 1
                csi_rows += len(rows)
                print(f'[OK] {len(rows)}行  {rows[0][1]} ~ {rows[-1][1]}')
            else:
                print('[空]')
        except Exception as e:
            print(f'[FAIL] {str(e)[:50]}')
        time.sleep(0.3)
    print(f'  CSI完成: {csi_ok}/25, {csi_rows}行')

    # Step 4: 申万行业 (30个)
    print('\n[Step 4] 申万接口 → 30个行业...')
    sw_ok = 0
    sw_rows = 0
    for symbol, code, name in SW_ASSETS:
        print(f'  {name:12s} ({code}) ...', end=' ', flush=True)
        try:
            rows = fetch_sw(symbol, code, name)
            if rows:
                db.executemany(
                    'INSERT INTO market_daily_data (symbol,trade_date,open,high,low,close,volume,amount,pe_ttm) VALUES (?,?,?,?,?,?,?,?,?)',
                    rows
                )
                db.commit()
                sw_ok += 1
                sw_rows += len(rows)
                print(f'[OK] {len(rows)}行  {rows[0][1]} ~ {rows[-1][1]}')
            else:
                print('[空]')
        except Exception as e:
            print(f'[FAIL] {str(e)[:50]}')
        time.sleep(0.3)
    print(f'  申万完成: {sw_ok}/30, {sw_rows}行')

    # Step 5: 创业板指 (1个)
    print('\n[Step 5] 创业板指 (daily+腾讯合并)...')
    try:
        rows = fetch_gem(GEM[0], GEM[1], GEM[2])
        if rows:
            db.executemany(
                'INSERT INTO market_daily_data (symbol,trade_date,open,high,low,close,volume,amount,pe_ttm) VALUES (?,?,?,?,?,?,?,?,?)',
                rows
            )
            db.commit()
            print(f'  [OK] {len(rows)}行  {rows[0][1]} ~ {rows[-1][1]}')
    except Exception as e:
        print(f'  [FAIL] {str(e)[:50]}')

    # 校验
    print('\n' + '=' * 60)
    print('校验报告')
    print('=' * 60)

    total = db.execute('SELECT COUNT(*) FROM market_daily_data').fetchone()[0]
    assets = db.execute('SELECT COUNT(DISTINCT symbol) FROM market_daily_data').fetchone()[0]
    dr = db.execute('SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data').fetchone()

    print(f'总行数: {total}')
    print(f'有数据资产: {assets}/56')
    print(f'日期范围: {dr[0]} ~ {dr[1]}')

    print('\n截止日期分布:')
    cur = db.execute('SELECT MAX(trade_date) FROM market_daily_data GROUP BY symbol')
    dates = {}
    for r in cur.fetchall():
        dates[r[0]] = dates.get(r[0], 0) + 1
    for d, cnt in sorted(dates.items()):
        print(f'  {d}: {cnt}个资产')

    # PE覆盖
    pe_cnt = db.execute('SELECT COUNT(DISTINCT symbol) FROM market_daily_data WHERE pe_ttm IS NOT NULL').fetchone()[0]
    print(f'\n有PE_TTM数据的资产: {pe_cnt}')

    missing = db.execute('SELECT symbol, name FROM asset_master WHERE symbol NOT IN (SELECT DISTINCT symbol FROM market_daily_data)').fetchall()
    if missing:
        print(f'\n缺失资产 ({len(missing)}个):')
        for r in missing:
            print(f'  {r[0]} {r[1]}')
    else:
        print('\n缺失资产: 0 ✅')

    db.close()
    print(f'\n完成: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')


if __name__ == '__main__':
    main()
