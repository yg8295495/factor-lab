# 数据架构

## 主数据源：TickFlow（免费 API）

```
采集脚本: backend/collectors/tickflow_collector.py
用法:     --mode full  # 全量（首次）
          --mode daily # 每日增量

特点:
  - 无需注册，TickFlow.free() 直接用
  - 一个接口返回三种复权数据（adjust 参数）
  - 未复权: adjust='none'         → open/high/low/close/volume/amount
  - 后复权: adjust='backward'     → close_hfq
  - 前复权: adjust='forward'      → 动态计算用
  - 速度: ~0.6只/秒（5线程并行，每个股票2次API调用）
```

## 数据落地

```yaml
asset_master:
  全量 A 股 ~5400 只，导入时自动注册

market_daily_data:
  核心字段:
    open/high/low/close:    "未复权"
    close_hfq:              "后复权 close（回测用）"
    hfq_factor:             "= close_hfq / close"
    pct_chg_raw:            "涨跌幅(自算)"
    limit_up/down_flag:     "涨跌停标记"
  pct_chg_raw 计算: (close[t] - close[t-1]) / close[t-1] * 100
  涨跌停判定: 主板≥9.8%, 科创/创业板≥19.5%, ST≥4.8%
```

## 复权口径规范

| 场景 | 用哪个字段 |
|------|-----------|
| 涨跌停判定 | pct_chg_raw |
| 收益回测/RS/Momentum | close_hfq（后复权） |
| K 线展示 | 未复权 OHLC × hfq_factor[t] / hfq_factor[最新日] |
| 技术指标（ATR/布林） | 未复权 high/low × (当前 hfq_factor / 最新 hfq_factor) |
| 成交额/成交量 | volume/amount 原始值 |
| 数据库 close | 未复权（原始收盘价） |

## 备案（应急降级）

```yaml
方案: mootdx（未复权 OHLCV）+ baostock（后复权 close）
脚本: backend/collectors/stock_pilot.py
坑:
  - baostock 每 80 次要重连
  - locale 影响 pandas 日期解析
  - mootdx 只能线程级复用（每次新建 Quotes()）
详情: 极少用到，需要时直接看 stock_pilot.py 代码
```
