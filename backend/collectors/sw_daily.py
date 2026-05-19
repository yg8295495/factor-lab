"""
申万行业数据更新 — 使用 akshare.index_hist_sw()
已确认31个行业全部可通
"""

import akshare as ak
import sqlite3
import time
from datetime import datetime

DB_PATH = 'factor-lab/data/quant_engine.db'

# 申万一级行业代码
SW_CODES = [
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

def update_sw_data():
    print('=' * 50)
    print(f'申万行业数据更新 — {datetime.now()}')
    print('=' * 50)

    db = sqlite3.connect(DB_PATH)
    db.execute('PRAGMA journal_mode=WAL')
    # 抑制 Python 3.12 的 date adapter 警告
    sqlite3.dbapi2.register_adapter(datetime.date, lambda d: d.isoformat())
    total_rows = 0
    success = 0

    for symbol, code, name in SW_CODES:
        print(f'\n{name} ({code}) ...', end=' ', flush=True)
        try:
            df = ak.index_hist_sw(symbol=code)
            if df is None or len(df) == 0:
                print('[FAIL] 空数据')
                continue

            # 删除旧数据
            db.execute('DELETE FROM market_daily_data WHERE symbol = ?', (symbol,))

            # 写入新数据
            batch = []
            for _, row in df.iterrows():
                trade_date = row['日期']
                close_p = float(row['收盘'])
                open_p = float(row['开盘']) if row['开盘'] else close_p
                high_p = float(row['最高']) if row['最高'] else close_p
                low_p = float(row['最低']) if row['最低'] else close_p
                volume = float(row['成交量']) if row['成交量'] else None
                amount = float(row['成交额']) if row['成交额'] else None
                batch.append((symbol, trade_date, open_p, high_p, low_p, close_p, volume, amount))

            db.executemany(
                'INSERT INTO market_daily_data (symbol,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)',
                batch
            )
            db.commit()

            total_rows += len(batch)
            success += 1
            print(f'[OK] {len(batch)}行  {batch[0][1]} ~ {batch[-1][1]}')

        except Exception as e:
            print(f'[FAIL] {str(e)[:50]}')

        time.sleep(0.5)  # 礼貌等待

    print(f'\n{"=" * 50}')
    print(f'完成: {success}/{len(SW_CODES)} 个行业')
    print(f'总行数: {total_rows}')
    print(f'{"=" * 50}')
    db.close()


if __name__ == '__main__':
    update_sw_data()
