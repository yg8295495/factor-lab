"""
从现有系统 (backend/financial_data.db) 迁移数据到 factor-lab (quant_engine.db)

迁移步骤:
  1. 清空旧迁移数据
  2. asset_master — 写入 55 个选定的资产
  3. market_daily_data.OHLCV — 从 index_daily 表迁移行情数据（只迁移目标资产）
  4. 输出校验报告

用法:
  python factor-lab/backend/migrate.py
"""

import sqlite3
import sys

OLD_DB = 'backend/financial_data.db'
NEW_DB = 'factor-lab/data/quant_engine.db'

# ─── 目标资产清单 (55个) ───
# (new_symbol, name, asset_type, exchange, old_code_pattern)
# old_code_pattern=None 表示旧系统中无此数据，跳过迁移
ASSETS = [
    # ── 宽基 (10个) ──
    ('index.000001.SH', '上证指数', 'index', 'SH', '000001.SH'),
    ('index.000300.SH', '沪深300', 'index', 'SH', '000300.SH'),
    ('index.000905.SH', '中证500', 'index', 'SH', '000905.SH'),
    ('index.000852.SH', '中证1000', 'index', 'SH', '000852.SH'),
    ('index.932000.SH', '中证2000', 'index', 'SH', '932000.SH'),
    ('index.000688.SH', '科创50', 'index', 'SH', '000688.SH'),
    ('index.399006.SZ', '创业板指', 'index', 'SZ', '399006.SZ'),
    ('index.000016.SH', '上证50', 'index', 'SH', '000016.SH'),
    ('index.000985.SH', '中证全指', 'index', 'SH', '000985.SH'),
    ('index.000510.SH', '中证A500', 'index', 'SH', '000510.SH'),

    # ── 申万一级 (30个，801020采掘已合并到石油石化，旧系统无数据) ──
    ('sector.801010.SW', '农林牧渔', 'sector', 'SW', '801010'),
    ('sector.801030.SW', '化工', 'sector', 'SW', '801030'),
    ('sector.801040.SW', '钢铁', 'sector', 'SW', '801040'),
    ('sector.801050.SW', '有色金属', 'sector', 'SW', '801050'),
    ('sector.801080.SW', '电子', 'sector', 'SW', '801080'),
    ('sector.801110.SW', '家用电器', 'sector', 'SW', '801110'),
    ('sector.801120.SW', '食品饮料', 'sector', 'SW', '801120'),
    ('sector.801130.SW', '纺织服装', 'sector', 'SW', '801130'),
    ('sector.801140.SW', '轻工制造', 'sector', 'SW', '801140'),
    ('sector.801150.SW', '医药生物', 'sector', 'SW', '801150'),
    ('sector.801160.SW', '公用事业', 'sector', 'SW', '801160'),
    ('sector.801170.SW', '交通运输', 'sector', 'SW', '801170'),
    ('sector.801180.SW', '房地产', 'sector', 'SW', '801180'),
    ('sector.801200.SW', '商贸零售', 'sector', 'SW', '801200'),
    ('sector.801210.SW', '社会服务', 'sector', 'SW', '801210'),
    ('sector.801710.SW', '建筑材料', 'sector', 'SW', '801710'),
    ('sector.801720.SW', '建筑装饰', 'sector', 'SW', '801720'),
    ('sector.801730.SW', '电力设备', 'sector', 'SW', '801730'),
    ('sector.801740.SW', '国防军工', 'sector', 'SW', '801740'),
    ('sector.801750.SW', '计算机', 'sector', 'SW', '801750'),
    ('sector.801760.SW', '传媒', 'sector', 'SW', '801760'),
    ('sector.801770.SW', '通信', 'sector', 'SW', '801770'),
    ('sector.801780.SW', '银行', 'sector', 'SW', '801780'),
    ('sector.801790.SW', '非银金融', 'sector', 'SW', '801790'),
    ('sector.801880.SW', '汽车', 'sector', 'SW', '801880'),
    ('sector.801890.SW', '机械设备', 'sector', 'SW', '801890'),
    ('sector.801950.SW', '煤炭', 'sector', 'SW', '801950'),
    ('sector.801960.SW', '石油石化', 'sector', 'SW', '801960'),
    ('sector.801970.SW', '环保', 'sector', 'SW', '801970'),
    ('sector.801980.SW', '美容护理', 'sector', 'SW', '801980'),

    # ── 中证主题 (15个) ──
    ('index.399997.SZ', '中证白酒', 'index', 'SZ', '399997.SZ'),
    ('index.399967.SZ', '中证军工', 'index', 'SZ', '399967.SZ'),
    ('index.399986.SZ', '中证银行', 'index', 'SZ', '399986.SZ'),
    ('index.H30590.SH', '中证机器人', 'index', 'SH', 'H30590.SH'),
    ('index.000941.SH', '中证内地新能源', 'index', 'SH', '000941.SH'),
    ('index.399989.SZ', '中证医疗', 'index', 'SZ', '399989.SZ'),
    ('index.931152.SZ', '中证创新药', 'index', 'SZ', '931152.SH'),       # 旧系统是 .SH
    ('index.399975.SZ', '证券公司', 'index', 'SZ', '399975'),            # 旧系统无后缀
    ('index.930651.SH', 'CS计算机', 'index', 'SH', '930651.SH'),
    ('index.399976.SZ', 'CS新能车', 'index', 'SZ', 'sz399976'),         # 旧系统是 sz 前缀
    ('index.931151.SZ', '中证光伏产业', 'index', 'SZ', '931151.SH'),    # 旧系统是 .SH

    # 以下5个旧系统无数据，标记为待采集
    ('index.990001.SH', '中华半导体芯片', 'index', 'SH', None),
    ('index.930713.SH', 'CS人工智', 'index', 'SH', None),
    ('index.931719.SZ', 'CS电池', 'index', 'SZ', None),
    ('index.000819.SH', '中证申万有色金属', 'index', 'SH', None),
]

# 申万行业在旧系统中是 .SI 后缀
SW_CODE_MAP = {
    '801010': ('801010.SI', '801010.SI'),
    '801030': ('801030.SI', '801030.SI'),
    '801040': ('801040.SI', '801040.SI'),
    '801050': ('801050.SI', '801050.SI'),
    '801080': ('801080.SI', '801080.SI'),
    '801110': ('801110.SI', '801110.SI'),
    '801120': ('801120.SI', '801120.SI'),
    '801130': ('801130.SI', '801130.SI'),
    '801140': ('801140.SI', '801140.SI'),
    '801150': ('801150.SI', '801150.SI'),
    '801160': ('801160.SI', '801160.SI'),
    '801170': ('801170.SI', '801170.SI'),
    '801180': ('801180.SI', '801180.SI'),
    '801200': ('801200.SI', '801200.SI'),
    '801210': ('801210.SI', '801210.SI'),
    '801710': ('801710.SI', '801710.SI'),
    '801720': ('801720.SI', '801720.SI'),
    '801730': ('801730.SI', '801730.SI'),
    '801740': ('801740.SI', '801740.SI'),
    '801750': ('801750.SI', '801750.SI'),
    '801760': ('801760.SI', '801760.SI'),
    '801770': ('801770.SI', '801770.SI'),
    '801780': ('801780.SI', '801780.SI'),
    '801790': ('801790.SI', '801790.SI'),
    '801880': ('801880.SI', '801880.SI'),
    '801890': ('801890.SI', '801890.SI'),
    '801950': ('801950.SI', '801950.SI'),
    '801960': ('801960.SI', '801960.SI'),
    '801970': ('801970.SI', '801970.SI'),
    '801980': ('801980.SI', '801980.SI'),
}


def find_old_code(old, symbol_name, old_code_pattern):
    """在旧系统中查找匹配的代码"""
    if old_code_pattern is None:
        return None

    cur = old.execute('SELECT DISTINCT 代码 FROM index_daily WHERE 代码 = ?', (old_code_pattern,))
    row = cur.fetchone()
    if row:
        return row[0]

    # 申万行业特殊处理
    if old_code_pattern in SW_CODE_MAP:
        for try_code in SW_CODE_MAP[old_code_pattern]:
            cur = old.execute('SELECT DISTINCT 代码 FROM index_daily WHERE 代码 = ?', (try_code,))
            row = cur.fetchone()
            if row:
                return row[0]

    # 尝试 .SH 后缀
    for suffix in ['.SH', '.SZ', '.SI']:
        cur = old.execute('SELECT DISTINCT 代码 FROM index_daily WHERE 代码 = ?', (old_code_pattern + suffix,))
        row = cur.fetchone()
        if row:
            return row[0]

    return None


def main():
    print('=' * 60)
    print('数据迁移')
    print(f'源: {OLD_DB}')
    print(f'目标: {NEW_DB}')
    print('=' * 60)

    old = sqlite3.connect(OLD_DB)
    new = sqlite3.connect(NEW_DB)
    old.row_factory = sqlite3.Row

    # ─── Step 1: 清空 ───
    print('\n[Step 1] 清空目标表 ...')
    new.execute('DELETE FROM market_daily_data')
    new.execute('DELETE FROM asset_master')
    new.commit()
    print('  ✅ 已清空')

    # ─── Step 2: 写入 asset_master ───
    print('\n[Step 2] 写入 asset_master ...')
    for symbol, name, atype, exchange, _ in ASSETS:
        new.execute(
            'INSERT OR IGNORE INTO asset_master (symbol, name, asset_type, exchange, is_active) VALUES (?, ?, ?, ?, 1)',
            (symbol, name, atype, exchange)
        )
    new.commit()
    cur = new.execute('SELECT COUNT(*) FROM asset_master')
    print(f'  ✅ asset_master: {cur.fetchone()[0]} 条')

    # ─── Step 3: 迁移行情数据 ───
    print('\n[Step 3] 迁移行情数据 (index_daily → market_daily_data) ...')

    total_inserted = 0
    migrated = 0
    skipped = 0
    no_data = []

    for symbol, name, atype, exchange, old_pattern in ASSETS:
        if old_pattern is None:
            print(f'  ⏭️  {symbol:30s} {name} — 旧系统无数据，待采集')
            no_data.append(name)
            skipped += 1
            continue

        old_code = find_old_code(old, name, old_pattern)
        if old_code is None:
            print(f'  ❌ {symbol:30s} {name} — 旧系统未找到代码')
            no_data.append(name)
            skipped += 1
            continue

        rows = old.execute(
            'SELECT 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额 FROM index_daily WHERE 代码 = ? ORDER BY 日期',
            (old_code,)
        ).fetchall()

        if not rows:
            print(f'  ⚠️  {symbol:30s} {name} — 找到代码但无数据行')
            skipped += 1
            continue

        batch = []
        for r in rows:
            trade_date = r['日期']
            o = r['开盘'] if r['开盘'] is not None else r['收盘']
            c = r['收盘']
            h = r['最高'] if r['最高'] is not None else r['收盘']
            l = r['最低'] if r['最低'] is not None else r['收盘']
            v = r['成交量']
            a = r['成交额']
            batch.append((symbol, trade_date, o, h, l, c, v, a))

        new.executemany(
            'INSERT OR IGNORE INTO market_daily_data (symbol, trade_date, open, high, low, close, volume, amount) VALUES (?,?,?,?,?,?,?,?)',
            batch
        )
        total_inserted += len(batch)
        migrated += 1
        print(f'  ✅ {symbol:30s} {len(batch):>5}行  {rows[0]["日期"]} ~ {rows[-1]["日期"]}')

    new.commit()

    print(f'\n  迁移完成: {migrated} 个资产成功, {skipped} 个跳过')
    if no_data:
        print(f'  待采集 ({len(no_data)}个): {", ".join(no_data)}')

    # ─── Step 4: 校验 ───
    print('\n' + '=' * 60)
    print('校验报告')
    print('=' * 60)

    cur = new.execute('SELECT COUNT(*) FROM asset_master')
    print(f'asset_master: {cur.fetchone()[0]} 条')

    cur = new.execute('SELECT COUNT(*) FROM market_daily_data')
    data_cnt = cur.fetchone()[0]
    print(f'market_daily_data: {data_cnt} 行')

    # 每个资产的数据范围
    print('\n各资产数据范围:')
    cur = new.execute('''
        SELECT symbol, COUNT(*) as cnt,
               MIN(trade_date) as start, MAX(trade_date) as end
        FROM market_daily_data
        GROUP BY symbol
        ORDER BY symbol
    ''')
    for r in cur.fetchall():
        print(f'  {r[0]:35s} {r[1]:>5}行  {r[2]} ~ {r[3]}')

    # 空值检查
    print('\n空值检查:')
    for col in ['open', 'close', 'high', 'low', 'volume', 'amount']:
        cur = new.execute(f'SELECT COUNT(*) FROM market_daily_data WHERE {col} IS NULL')
        n = cur.fetchone()[0]
        status = '✅' if n == 0 else f'⚠️  {n}行'
        print(f'  {status} {col}')

    old.close()
    new.close()
    print('\n✅ 迁移完成')


if __name__ == '__main__':
    main()
