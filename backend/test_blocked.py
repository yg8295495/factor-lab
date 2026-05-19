"""
快速验证：IP到底被封了没有？
拉一个确定能通的 + 一个刚才报错的
"""
import time, json
from playwright.sync_api import sync_playwright
import os

CHROME_PATH = os.path.expanduser('~') + '/AppData/Local/ms-playwright/chromium-1200/chrome-win64/chrome.exe'

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME_PATH, headless=False, args=['--no-sandbox'])
    context = browser.new_context()
    page = context.new_page()

    # 拿Cookie
    page.goto('https://www.eastmoney.com', wait_until='domcontentloaded', timeout=20000)
    time.sleep(2)

    # 测试1: 确定之前能通的
    print('测试1: 沪深300 (之前✅)')
    page.goto('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1,f2&fields2=f51,f52&klt=101&fqt=1&end=20500101&lmt=3', wait_until='domcontentloaded')
    t1 = page.locator('body').inner_text()
    print(f'  {"✅" if "rc\":0" in t1 else "❌"} {t1[:80]}')

    # 测试2: 申万行业
    print('\n测试2: 申万银行 (之前❌rc=100)')
    page.goto('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.801780&fields1=f1,f2&fields2=f51,f52&klt=101&fqt=1&end=20500101&lmt=3', wait_until='domcontentloaded')
    t2 = page.locator('body').inner_text()
    print(f'  {"✅" if "rc\":0" in t2 else "❌"} {t2[:80]}')

    # 测试3: 中证2000
    print('\n测试3: 中证2000 (之前❌rc=100)')
    page.goto('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.932000&fields1=f1,f2&fields2=f51,f52&klt=101&fqt=1&end=20500101&lmt=3', wait_until='domcontentloaded')
    t3 = page.locator('body').inner_text()
    print(f'  {"✅" if "rc\":0" in t3 else "❌"} {t3[:80]}')

    print('\n结论:')
    if 'rc":0' in t1:
        print('- IP没被封 (沪深300还能通)')
    else:
        print('- IP被封了 (连沪深300都断了)')
    if 'rc":100' in t2:
        print('- 申万行业在push2his确实不存在 (不是封IP)')
    if 'rc":100' in t3:
        print('- 中证2000在push2his不存在')

    browser.close()
