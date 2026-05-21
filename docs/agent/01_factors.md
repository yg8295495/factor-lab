# 因子体系

## 注册系统

所有因子通过 FeatureRegistry 注册，不散落各处。

```
模块: backend/research/features/registry.py
入口: backend/research/features/calculator.py（--daily 已禁用）
```

## 因子维度

| 维度 | 因子 | 数据源/计算方式 |
|------|------|----------------|
| 趋势 | rs20_cross, rs60_cross, rs_slope | 后复权 close × 基准指数 |
| 动量 | time_momentum20, time_momentum60, trend_strength | 后复权 close |
| 量价 | volume_ratio, amount_ratio, price_volume_divergence | 未复权 volume/amount |
| 突破 | breakout_strength, price_vol_divergence | 后复权 close + volume |
| 估值 | pe_ttm, pb, ps, peg, dividend_yield | baostock/a股财务数据 |
| 成长 | roe, gross_margin, revenue_growth, profit_growth | 财报数据 |
| Breadth | above_ma20_ratio, above_ma60_ratio, new_high_20d_ratio | 后复权 close，行业维度 |
| 情绪 | limit_up_count, limit_down_count, market_adv_ratio | 涨跌停统计，全市场维度 |
| 风格 | growth_score, dividend_score, small_cap_score | 因子聚合 |

## 因子聚合思路

```
个股因子 → 行业聚合（中位数/均值） → 风格因子
行业因子 × 权重 → 全市场特征
```

回测使用后复权 close，禁止静态命中率评估。

## 回测规范

- 滚动窗口每 20 天调仓
- 使用循环版（非向量化），各行业独立做 dropna() 定位窗口
- 原因：不同行业交易日历不同，向量化 pivot 导致窗口偏移（匹配率仅 34.7%）
