"""
最小化补采 — 只补6个缺失/有问题的资产
每次间隔30秒，避免被封
"""

import sqlite3, os, time, json
from playwright.sync_api import sync_playwright

DB_PATH = 'factor-lab/data/quant_engine.db'
CHROME_PATH = os.path.expanduser('~') + '/AppData/Local/ms-playwright/chromium-1200/chrome-win64/chrome.exe'

# 只补6个: 2个有缺口 + 4个完全缺失
ASSETS = [
    ('index.399967.SZ', '0.399967', '中证军工(补99天缺口)'),
    ('sector.801950.SW', '0.801950', '煤炭(补5年缺口)'),
    ('index.990001.SH', '1.990001', '中华半导体芯片(新)'),
    ('index.930713.SH', '1.930713', 'CS人工智(新)'),
    ('index.931719.SZ', '0.931719', 'CS电池(新)'),
    ('index.000819.SH', '1.000819', '中证申万有色金属(新)'),
]

print('='*60)
print('最小化补采 — 只补6个')
print('重启光猫换IP后再跑！')
print('='*60)

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROME_PATH,
        headless=False,
        args=['--no-sandbox']
    )
    context = browser.new_context()
    page = context.new_page()

    # 拿Cookie
    print('\n[0/6] 拿Cookie...')
    page.goto('https://www.eastmoney.com', wait_until='domcontentloaded', timeout=20000)
    time.sleep(2)

    db = sqlite3.connect(DB_PATH)

    for i, (symbol, secid, desc) in enumerate(ASSETS, 1):
        print(f'\n[{i}/6] {desc} ({symbol})')

        # 先睡30秒，第1个之前也睡
        if i == 1:
            print(f'  等30秒开始第一个请求...')
            time.sleep(30)
        else:
            print(f'  等30秒再拉下一个...')
            time.sleep(30)

        url = (f'https://push2his.eastmoney.com/api/qt/stock/kline/get'
               f'?secid={secid}'
               f'&fields1=f1,f2,f3,f4,f5,f6'
               f'&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
               f'&klt=101&fqt=1&end=20500101&lmt=5000')

        print(f'  请求中...', end=' ', flush=True)
        try:
            resp = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            text = page.locator('body').inner_text()

            if resp and resp.status == 200 and text.startswith('{'):
                data = json.loads(text)
                if data.get('data') and data['data'].get('klines'):
                    klines = data['data']['klines']
                    rows = []
                    for line in klines:
                        parts = line.split(',')
                        if len(parts) >= 11:
                            try:
                                rows.append((
                                    symbol, parts[0],
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
                        print(f'✅ {len(rows)}行  {rows[0][1]} ~ {rows[-1][1]}')
                    else:
                        print(f'⚠️ 解析0行')
                else:
                    print(f'❌ 空数据')
            else:
                print(f'❌ HTTP {resp.status if resp else "无"}')
        except Exception as e:
            print(f'❌ {str(e)[:50]}')

    browser.close()
    db.close()
    print(f'\n✅ 完成')
