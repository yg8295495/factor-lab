# AGENT.md — AI 工作导航

> 仅记录定位和索引。详细内容在 `docs/agent/` 下按需读取。

## 项目定位

```yaml
name: factor-lab
db: data/quant_engine.db
date_range: 2004-12-31 ~ 当前
stocks: 全量 A 股（~5000+）
indices: 25 | sectors: 30
goal: 行业轮动因子研究 + 行为评分策略
```

## 文档导航

| 路径 | 内容 | AI 何时读 |
|------|------|-----------|
| `docs/agent/00_data.md` | 数据架构：TickFlow 主源、DB schema、复权口径 | 涉及数据/采集时 |
| `docs/agent/01_factors.md` | 因子体系：注册、聚合、回测规范 | 涉及因子/回测时 |
| `docs/agent/02_experiments.md` | 实验方向、方法论、各版本结论 | 涉及实验/分析时 |
| `docs/agent/03_strategy.md` | 策略设计、组合规则、评估框架 | 涉及策略/组合时 |

## 快速命令

```bash
# 数据采集
python3 backend/collectors/tickflow_collector.py --mode daily   # 每日增量

# 因子计算
python3 -m backend.research.features.calculator

# 实验分析
python3 backend/research/analysis/sector_behavior_score.py       # 行为评分
python3 backend/research/analysis/sector_leadership.py            # 行业领涨

# 后端
cd backend && python3 server.py

# 前端
cd frontend && npm run dev
```

## 行为铁律（来自 MEMORY.md）

- 遇到问题 3 次尝试过不去 → 停下和用户沟通
- 修改代码后 → 同步更新 AGENT.md/PLAN.md/相关 agent 文档
- AGENT.md + agent 文档只写精简事实不解释
- 主数据源变更必须先讨论再改
