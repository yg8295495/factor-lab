"""
因子数据服务器 — 为前端提供 JSON 数据接口
启动: uvicorn backend.server:app --reload --port 8000
"""

import sys
import sqlite3
import json
from pathlib import Path

# 确保能导入 research 模块
_sr = Path(__file__).resolve().parent  # backend/
if str(_sr) not in sys.path:
    sys.path.insert(0, str(_sr))
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

# 延迟导入 registry（解决 uvicorn 路径问题）
_registry = None
def get_registry():
    global _registry
    if _registry is None:
        from research.features.registry import FACTOR_REGISTRY
        _registry = FACTOR_REGISTRY
    return _registry

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'quant_engine.db'
app = FastAPI(title='factor-lab API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/benchmark')
def get_benchmark():
    """返回当前基准指数信息（前端从此接口获取，不再硬编码）"""
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT symbol, name FROM asset_master WHERE symbol = 'index.801003.SW'"
    ).fetchone()
    conn.close()
    if not row:
        return {'symbol': 'index.801003.SW', 'name': '申万Ａ指'}
    return {'symbol': row[0], 'name': row[1]}


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
    from research.features.registry import list_factors
    return list_factors()


@app.get('/api/signals')
def get_signals():
    """读取预计算的信号触发点"""
    path = Path(__file__).resolve().parent / 'research' / 'analysis' / 'output' / 'signal_triggers.json'
    if not path.exists():
        return {'error': '信号数据未生成，请先运行 compute_signals.py'}
    return json.load(open(path, 'r', encoding='utf-8'))


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
    FACTOR_REGISTRY = get_registry()

    if factor not in FACTOR_REGISTRY:
        return {'error': f'因子 {factor} 不存在'}

    fdef = FACTOR_REGISTRY[factor]
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
        'display': fdef.name_cn,
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


@app.get('/api/percentiles/{symbol}')
def get_percentiles(symbol: str, window: str = Query('5y', regex='^(5y|10y|all)$')):
    """
    计算 PE/EY/ERP 百分位时序。
    window: 5y / 10y / all
    返回每日的 pe_pct / ey_pct / erp_pct
    """
    import numpy as np

    ndays = {'5y': 1250, '10y': 2500, 'all': 0}[window]
    conn = sqlite3.connect(str(DB_PATH))

    rows = conn.execute(
        "SELECT trade_date, close, pe_ttm FROM market_daily_data "
        "WHERE symbol=? AND pe_ttm IS NOT NULL AND pe_ttm>0 ORDER BY trade_date",
        (symbol,)
    ).fetchall()

    if not rows:
        conn.close()
        return []

    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]
    pes = np.array([float(r[2]) for r in rows])
    eys = 1.0 / pes

    # 国债收益率
    brows = conn.execute(
        "SELECT trade_date, close FROM market_daily_data "
        "WHERE symbol='macro.CN10Y' AND close IS NOT NULL ORDER BY trade_date"
    ).fetchall()
    bond_map = {r[0]: float(r[1])/100 for r in brows}
    conn.close()

    def pct(arr, idx, n):
        if n == 0: start = 0
        else: start = max(0, idx - n + 1)
        w = arr[start:idx+1]
        return float(np.sum(w <= arr[idx]) / len(w)) if len(w) >= 30 else None

    result = []
    for i in range(len(dates)):
        pe_p = pct(pes, i, ndays)
        ey_p = pct(eys, i, ndays)
        b = bond_map.get(dates[i])
        erp_v = float(eys[i] - b) if b else None
        # ERP 百分位需要单独维护一个 erp 序列
        erp_p = None
        if b:
            # 在 erp 序列中的位置
            erp_series = np.array([eys[j] - bond_map.get(dates[j], 0) for j in range(i+1) if bond_map.get(dates[j])])
            if len(erp_series) >= 30:
                w = erp_series if ndays == 0 else erp_series[-min(ndays, len(erp_series)):]
                erp_p = float(np.sum(w <= erp_series[-1]) / len(w))

        result.append({
            'trade_date': dates[i],
            'close': closes[i],
            'pe': float(pes[i]),
            'pe_pct': round(pe_p, 4) if pe_p is not None else None,
            'ey_pct': round(ey_p, 4) if ey_p is not None else None,
            'erp': round(erp_v, 4) if erp_v is not None else None,
            'erp_pct': round(erp_p, 4) if erp_p is not None else None,
        })

    return result


@app.get('/api/market-structure')
def get_market_structure():
    """读取预计算的市场结构 v1 数据"""
    path = Path(__file__).resolve().parent / 'research' / 'analysis' / 'output' / 'market_structure_v1.json'
    if not path.exists():
        return {'error': '市场结构数据未生成，请先运行 market_structure_v1.py'}
    data = json.load(open(path, 'r', encoding='utf-8'))
    return data


@app.get('/api/market-state')
def get_market_state():
    """⚠️ 已废弃（基于 801001，输出已删除）。待 market_structure_v1/v2 切 801003 重跑后恢复。"""
    return {'error': '基准已切换为801003，需重跑分析脚本后恢复此接口'}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
