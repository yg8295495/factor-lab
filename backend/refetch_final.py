"""
[已弃用] 最终版补采脚本 — Playwright + chromium-1200

⚠️ 此脚本使用东财接口 fqt=1（前复权），与当前 DB close 字段（未复权）口径不一致。
⚠️ 东财 push2his.eastmoney.com 在本网络永久不通。

如需复用，必须改造为双趟写入（未复权 close + 后复权 close_hfq），
或仅用此脚本拉取数据后自行转换。
"""

import sqlite3, os, time, json
from datetime import datetime
from playwright.sync_api import sync_playwright

DB_PATH = 'factor-lab/data/quant_engine.db'
CHROME_PATH = os.path.expanduser('~') + '/AppData/Local/ms-playwright/chromium-1200/chrome-win64/chrome.exe'

# 55个资产: (symbol, secid)
ASSETS = [
    ('index.000001.SH','1.000001'),('index.000300.SH','1.000300'),
    ('index.000905.SH','1.000905'),('index.000852.SH','1.000852'),
    ('index.932000.SH','1.932000'),('index.000688.SH','1.000688'),
    ('index.399006.SZ','0.399006'),('index.000016.SH','1.000016'),
    ('index.000985.SH','1.000985'),('index.000510.SH','1.000510'),
    ('sector.801010.SW','0.801010'),('sector.801030.SW','0.801030'),
    ('sector.801040.SW','0.801040'),('sector.801050.SW','0.801050'),
    ('sector.801080.SW','0.801080'),('sector.801110.SW','0.801110'),
    ('sector.801120.SW','0.801120'),('sector.801130.SW','0.801130'),
    ('sector.801140.SW','0.801140'),('sector.801150.SW','0.801150'),
    ('sector.801160.SW','0.801160'),('sector.801170.SW','0.801170'),
    ('sector.801180.SW','0.801180'),('sector.801200.SW','0.801200'),
    ('sector.801210.SW','0.801210'),('sector.801710.SW','0.801710'),
    ('sector.801720.SW','0.801720'),('sector.801730.SW','0.801730'),
    ('sector.801740.SW','0.801740'),('sector.801750.SW','0.801750'),
    ('sector.801760.SW','0.801760'),('sector.801770.SW','0.801770'),
    ('sector.801780.SW','0.801780'),('sector.801790.SW','0.801790'),
    ('sector.801880.SW','0.801880'),('sector.801890.SW','0.801890'),
    ('sector.801950.SW','0.801950'),('sector.801960.SW','0.801960'),
    ('sector.801970.SW','0.801970'),('sector.801980.SW','0.801980'),
    ('index.399997.SZ','0.399997'),('index.399967.SZ','0.399967'),
    ('index.399986.SZ','0.399986'),('index.H30590.SH','1.H30590'),
    ('index.000941.SH','1.000941'),('index.399989.SZ','0.399989'),
    ('index.931152.SZ','0.931152'),('index.399975.SZ','0.399975'),
    ('index.990001.SH','1.990001'),('index.930713.SH','1.930713'),
    ('index.930651.SH','1.930651'),('index.399976.SZ','0.399976'),
    ('index.931719.SZ','0.931719'),('index.931151.SZ','0.931151'),
    ('index.000819.SH','1.000819'),
]

def fetch_all():
    print('='*60)
    print('最终补采 — Playwright + chromium-1200')
    print(f'开始: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'共 {len(ASSETS)} 个资产')
    print('='*60)

    db = sqlite3.connect(DB_PATH)

    with sync_playwright() as p:
        # 启动浏览器（非headless + 1200版本）
        browser = p.chromium.launch(
            executable_path=CHROME_PATH,
            headless=False,
            args=['--no-sandbox']
        )
        context = browser.new_context()
        page = context.new_page()

        # 先访问东财主站拿Cookie
        print('\n[Step 0] 访问东财主站获取Cookie...')
        page.goto('https://www.eastmoney.com', wait_until='domcontentloaded', timeout=20000)
        time.sleep(1)
        cookies = context.cookies()
        print(f'  ✅ 获取到 {len(cookies)} 个Cookie')

        total_ok = 0
        total_rows = 0
        total_fail = 0

        for i, (symbol, secid) in enumerate(ASSETS, 1):
            url = (f'https://push2his.eastmoney.com/api/qt/stock/kline/get'
                   f'?secid={secid}'
                   f'&fields1=f1,f2,f3,f4,f5,f6'
                   f'&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
                   f'&klt=101&fqt=1&end=20500101&lmt=5000')

            print(f'\n[{i}/{len(ASSETS)}] {symbol} ', end='', flush=True)

            try:
                resp = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                text = page.locator('body').inner_text()

                if resp and resp.status == 200 and text.startswith('{'):
                    data = json.loads(text)
                    if data.get('data') and data['data'].get('klines'):
                        klines = data['data']['klines']
                        
                        # 解析
                        rows = []
                        for line in klines:
                            parts = line.split(',')
                            if len(parts) >= 11:
                                try:
                                    rows.append((
                                        symbol,
                                        parts[0],
                                        float(parts[1]), float(parts[2]),
                                        float(parts[3]), float(parts[4]),
                                        float(parts[5]) if parts[5] else None,
                                        float(parts[6]) if parts[6] else None,
                                    ))
                                except ValueError:
                                    continue

                        if rows:
                            db.execute('DELETE FROM market_daily_data WHERE symbol = ?', (symbol,))
                            db.executemany(
                                'INSERT INTO market_daily_data (symbol,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)',
                                rows
                            )
                            db.commit()
                            total_rows += len(rows)
                            total_ok += 1
                            print(f'✅ {len(rows)}行  {rows[0][1]} ~ {rows[-1][1]}')
                        else:
                            print(f'⚠️ 解析出0行')
                            total_fail += 1
                    else:
                        print(f'❌ API返回空数据: {text[:80]}')
                        total_fail += 1
                else:
                    status = resp.status if resp else '无响应'
                    print(f'❌ HTTP {status}: {text[:80]}')
                    total_fail += 1

            except Exception as e:
                print(f'❌ 异常: {str(e)[:60]}')
                total_fail += 1

            # 限流: 每2.5秒一个请求
            if i < len(ASSETS):
                time.sleep(2.5)
            
            # 每15个重新拿一次Cookie
            if i % 15 == 0 and i < len(ASSETS) - 1:
                print(f'  ↻ 刷新Cookie...', end=' ', flush=True)
                page.goto('https://www.eastmoney.com', wait_until='domcontentloaded', timeout=15000)
                print('OK')

        browser.close()

    # 汇总
    print('\n' + '='*60)
    print('补采完成')
    print(f'成功: {total_ok}/{len(ASSETS)}')
    print(f'失败: {total_fail}')
    print(f'总行数: {total_rows}')

    # 校验
    cur = db.execute('SELECT COUNT(*) FROM market_daily_data')
    print(f'DB总行数: {cur.fetchone()[0]}')
    cur = db.execute('SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data')
    dr = cur.fetchone()
    print(f'日期范围: {dr[0]} ~ {dr[1]}')
    cur = db.execute('SELECT COUNT(DISTINCT symbol) FROM market_daily_data')
    print(f'有数据的资产: {cur.fetchone()[0]}/{len(ASSETS)}')

    db.close()


if __name__ == '__main__':
    fetch_all()
