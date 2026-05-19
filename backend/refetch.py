"""
从 push2his.eastmoney.com API 重新拉取所有资产的完整日线数据
覆盖 market_daily_data 中的旧数据
"""

import sqlite3
import requests
import time
import sys
from datetime import datetime

DB_PATH = 'factor-lab/data/quant_engine.db'
BATCH_SIZE = 50  # 每次请求间隔，避免被限流

# secid 映射: (symbol, secid)
# 交易所代码: 1=上交所, 0=深交所
ASSETS = [
    # 宽基
    ('index.000001.SH', '1.000001'),
    ('index.000300.SH', '1.000300'),
    ('index.000905.SH', '1.000905'),
    ('index.000852.SH', '1.000852'),
    ('index.932000.SH', '1.932000'),
    ('index.000688.SH', '1.000688'),
    ('index.399006.SZ', '0.399006'),
    ('index.000016.SH', '1.000016'),
    ('index.000985.SH', '1.000985'),
    ('index.000510.SH', '1.000510'),

    # 申万
    ('sector.801010.SW', '0.801010'),
    ('sector.801030.SW', '0.801030'),
    ('sector.801040.SW', '0.801040'),
    ('sector.801050.SW', '0.801050'),
    ('sector.801080.SW', '0.801080'),
    ('sector.801110.SW', '0.801110'),
    ('sector.801120.SW', '0.801120'),
    ('sector.801130.SW', '0.801130'),
    ('sector.801140.SW', '0.801140'),
    ('sector.801150.SW', '0.801150'),
    ('sector.801160.SW', '0.801160'),
    ('sector.801170.SW', '0.801170'),
    ('sector.801180.SW', '0.801180'),
    ('sector.801200.SW', '0.801200'),
    ('sector.801210.SW', '0.801210'),
    ('sector.801710.SW', '0.801710'),
    ('sector.801720.SW', '0.801720'),
    ('sector.801730.SW', '0.801730'),
    ('sector.801740.SW', '0.801740'),
    ('sector.801750.SW', '0.801750'),
    ('sector.801760.SW', '0.801760'),
    ('sector.801770.SW', '0.801770'),
    ('sector.801780.SW', '0.801780'),
    ('sector.801790.SW', '0.801790'),
    ('sector.801880.SW', '0.801880'),
    ('sector.801890.SW', '0.801890'),
    ('sector.801950.SW', '0.801950'),
    ('sector.801960.SW', '0.801960'),
    ('sector.801970.SW', '0.801970'),
    ('sector.801980.SW', '0.801980'),

    # 中证主题
    ('index.399997.SZ', '0.399997'),
    ('index.399967.SZ', '0.399967'),
    ('index.399986.SZ', '0.399986'),
    ('index.H30590.SH', '1.H30590'),
    ('index.000941.SH', '1.000941'),
    ('index.399989.SZ', '0.399989'),
    ('index.931152.SZ', '0.931152'),
    ('index.399975.SZ', '0.399975'),
    ('index.990001.SH', '1.990001'),       # 新增
    ('index.930713.SH', '1.930713'),       # 新增
    ('index.930651.SH', '1.930651'),
    ('index.399976.SZ', '0.399976'),
    ('index.931719.SZ', '0.931719'),       # 新增
    ('index.931151.SZ', '0.931151'),
    ('index.000819.SH', '1.000819'),       # 新增
]


def fetch_klines(secid, retries=3):
    """从 push2his API 拉取完整K线"""
    url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': '101',       # 日K
        'fqt': '1',          # 前复权
        'end': '20500101',   # 拉到未来
        'lmt': '5000',       # 最多5000行
    }
    
    # 使用自定义 Session，不走系统代理
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://www.eastmoney.com/',
    })
    
    for attempt in range(retries):
        try:
            r = sess.get(url, params=params, timeout=30)
            if r.status_code != 200:
                print(f'    HTTP {r.status_code}')
                continue
            data = r.json()
            if data.get('data') and data['data'].get('klines'):
                return data['data']['klines']
            else:
                print(f'    无数据返回')
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f'    失败: {str(e)[:60]}')
            return None
    return None


def parse_klines(klines):
    """解析K线字符串为结构化数据"""
    results = []
    for line in klines:
        parts = line.split(',')
        if len(parts) >= 11:
            trade_date = parts[0]
            try:
                results.append((
                    trade_date,
                    float(parts[1]),   # open
                    float(parts[2]),   # close
                    float(parts[3]),   # high
                    float(parts[4]),   # low
                    float(parts[5]) if parts[5] else None,   # volume
                    float(parts[6]) if parts[6] else None,   # amount
                ))
            except (ValueError, IndexError):
                continue
    return results


def main():
    print('=' * 60)
    print('数据补采 — push2his.eastmoney.com')
    print(f'开始时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)
    
    # 连接数据库
    db = sqlite3.connect(DB_PATH)
    db.execute('PRAGMA journal_mode=WAL')
    
    total_success = 0
    total_rows = 0
    total_fail = 0
    
    for idx, (symbol, secid) in enumerate(ASSETS, 1):
        print(f'\n[{idx}/{len(ASSETS)}] {symbol} (secid={secid})')
        print(f'  请求中...', end=' ', flush=True)
        
        klines = fetch_klines(secid)
        if not klines or len(klines) == 0:
            print('❌ 获取失败')
            total_fail += 1
            continue
        
        rows = parse_klines(klines)
        if not rows:
            print('❌ 解析失败')
            total_fail += 1
            continue
        
        # 删除旧数据，写入新数据
        db.execute('DELETE FROM market_daily_data WHERE symbol = ?', (symbol,))
        
        batch = []
        for r in rows:
            batch.append((symbol, r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
        
        db.executemany(
            'INSERT INTO market_daily_data (symbol, trade_date, open, high, low, close, volume, amount) VALUES (?,?,?,?,?,?,?,?)',
            batch
        )
        db.commit()
        
        total_rows += len(batch)
        total_success += 1
        print(f'✅ {len(batch)}行  {rows[0][0]} ~ {rows[-1][0]}')
        
        # 限流: 每批请求间等待1.5秒，避免被封IP
        if idx < len(ASSETS):
            time.sleep(1.5)
    
    # 汇总
    print('\n' + '=' * 60)
    print(f'补采完成')
    print(f'  成功: {total_success}/{len(ASSETS)}')
    print(f'  失败: {total_fail}')
    print(f'  总行数: {total_rows}')
    print(f'  结束时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    
    # 简单校验
    cur = db.execute('SELECT COUNT(DISTINCT symbol) FROM market_daily_data')
    assets_with_data = cur.fetchone()[0]
    cur = db.execute('SELECT COUNT(*) FROM market_daily_data')
    total = cur.fetchone()[0]
    cur = db.execute('SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data')
    dr = cur.fetchone()
    print(f'  有数据的资产: {assets_with_data}/55')
    print(f'  总行数: {total}')
    print(f'  日期范围: {dr[0]} ~ {dr[1]}')
    
    db.close()


if __name__ == '__main__':
    main()
