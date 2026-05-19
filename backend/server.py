"""
因子数据服务器 — 为前端提供 JSON 数据接口
启动: uvicorn backend.server:app --reload --port 8000
"""

import sqlite3
import json
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'quant_engine.db'
app = FastAPI(title='factor-lab API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/assets')
def get_assets():
    """获取所有资产列表"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.execute('SELECT symbol, name, asset_type FROM asset_master WHERE is_active = 1 ORDER BY asset_type, name')
    assets = [dict(r) for r in cur.fetchall()]
    conn.close()
    return assets


@app.get('/api/factors')
def get_factors():
    """获取因子列表（从 registry 读取）"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from research.features.registry import list_features
    return list_features()


@app.get('/api/data/{symbol}')
def get_data(
    symbol: str,
    fields: str = Query('trade_date,open,high,low,close,volume,amount', description='逗号分隔的字段名'),
    start: str = Query(None, description='起始日期 YYYY-MM-DD'),
    end: str = Query(None, description='结束日期 YYYY-MM-DD'),
    limit: int = Query(5000, description='最大行数'),
):
    """获取指定资产的行情+因子数据"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 检查有哪些因子字段可用
    all_cols = fields.split(',')
    # 确保 trade_date 在第一列
    if 'trade_date' not in all_cols:
        all_cols.insert(0, 'trade_date')

    cols = ', '.join(all_cols)
    sql = f'SELECT {cols} FROM market_daily_data WHERE symbol = ?'
    params = [symbol]

    if start:
        sql += ' AND trade_date >= ?'
        params.append(start)
    if end:
        sql += ' AND trade_date <= ?'
        params.append(end)

    sql += ' ORDER BY trade_date DESC LIMIT ?'
    params.append(limit)

    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.get('/api/factor-data/{symbol}/{factor}')
def get_factor_data(
    symbol: str,
    factor: str,
    start: str = Query(None),
    end: str = Query(None),
    limit: int = Query(5000),
):
    """
    获取指定资产的指定因子时序数据（含价格+因子）。
    factor 为 registry 中的因子名，如 RS20
    """
    from research.features.registry import FEATURE_REGISTRY

    if factor not in FEATURE_REGISTRY:
        return {'error': f'因子 {factor} 不存在'}

    fdef = FEATURE_REGISTRY[factor]
    db_field = fdef.storage or fdef.name.lower()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    sql = f'SELECT trade_date, close, {db_field} FROM market_daily_data WHERE symbol = ?'
    params = [symbol]

    if start:
        sql += ' AND trade_date >= ?'
        params.append(start)
    if end:
        sql += ' AND trade_date <= ?'
        params.append(end)

    sql += ' ORDER BY trade_date DESC LIMIT ?'
    params.append(limit)

    cur = conn.execute(sql, params)
    raw = [dict(r) for r in cur.fetchall()]

    # 加上因子元信息
    result = {
        'symbol': symbol,
        'factor': factor,
        'factor_name_cn': fdef.name_cn,
        'display': fdef.display,
        'data': [
            {
                'trade_date': r['trade_date'],
                'close': r['close'],
                'factor_value': r[db_field],
            }
            for r in raw if r[db_field] is not None
        ],
    }
    conn.close()
    return result


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
