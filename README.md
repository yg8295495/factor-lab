# factor-lab — 因子研究实验室

> 因子发现 → 行业行为评分 → 市场状态分析 → 主线识别的轻量研究流水线。
> AI-DMS / 市场状态机体系的因子研究子模块。

---

## 研究链路

```
 因子筛选 ──→ 行业行为层 ──→ 市场状态层 ──→ 主线识别层
(12+5因子)   (W1/W2/W3)    (四概率/失速)   (待解决)
    |            |              |             |
  Phase A/B/C   基线D        当前焦点      Top1命中率≈随机
  已冻结        +985%超额     调试中        方向筛选3×有效
```

## 当前基准

`index.801003.SW` — **申万Ａ指**（唯一真正全A指数，~4119只成分股）

> ⚠️ 此前误用 `index.801001.SW`（实为申万50，仅50只大盘股），已于 2026-06-09 完成切换。

## 数据库

| 文件 | 大小 | 说明 |
|:----|:----:|:------|
| `data/quant_engine.db` | ~2.8GB | 完整版（含个股行），台式研究用 |
| `data/quant_engine_base.db` | ~64MB | 随身版（仅行业+指数+宏观），适合移动研究 |

## 快速开始

### 每日更新

```bash
# 更新 base.db 仅801003（最快，日常推荐）
python backend/collectors/daily_update.py --db data/quant_engine_base.db --only-benchmark

# 更新 base.db 全部（含行业+宏观）
python backend/collectors/daily_update.py --db data/quant_engine_base.db

# 更新 full.db 全部（含个股聚合重算）
python backend/collectors/daily_update.py
```

### 一次性初始化

```bash
python backend/collectors/build_sector_mapping.py     # 行业映射
python backend/collectors/aggregate_sector_breadth.py # 行业宽度
python backend/collectors/sw_daily.py                 # 行业K线（全量）
python backend/collectors/tickflow_collector.py       # 个股K线（全量）
```

### 启动前端

```bash
./start.sh
```

## 核心实验结论

| 实验 | 结论 | 状态 |
|:----|:-----|:----:|
| EXP-003 Variant D | 状态=仓位框架，+985%收益，+341%超额 | ✅ 基线 |
| EXP-004 市场状态v0 | 5维度分类→5状态，规则已达边界 | ✅ 定型 |
| EXP-006 生命周期 | Delta(W2-W3)是位置因子非强弱因子 | ✅ 完成 |
| EXP-007 融合测试 | Delta不可用于事前筛选 | ✅ 负结果 |
| Phase A/B/C | 17因子(12MAIN+5AUX)已注册冻结 | ✅ 完成 |

> **注意：** 以上量化结论基于切换前的旧基准（000985/801001）跑出。引用前需改 `BM_SYMBOL` 为 801003 重跑验证。相关脚本 docstring 中均标注了提醒。

## 项目结构

```
backend/
├── collectors/         # 数据采集（daily_update.py 统一入口）
├── research/
│   ├── analysis/       # 分析脚本（状态/结构/因子/行为评分）
│   ├── features/       # 因子注册表 + 计算器
│   ├── labeling/       # 市场阶段人工标注
│   └── structures/     # 结构研究（预留）
├── data/               # Schema + models
└── server.py           # 后端API（待切801003后恢复）

docs/
├── agent/              # AI会话入口文档
├── research/           # 实验报告 + 研究记忆
└── archive/            # 归档（仅保留参考价值的旧脚本）

frontend/               # React前端（待更新801003硬编码）
```

## 关键文档入口

| 文件 | 阅读场景 |
|:-----|:---------|
| `AGENT.md` | 新会话第一站 — 硬规则、命令、文档地图 |
| `PLAN.md` | 当前 sprint — 进度和优先级 |
| `STATUS.md` | 全量现状报告 — 实验记录、数据状态 |
| `docs/research/INDEX.md` | 实验索引 |
| `docs/research/LESSONS.md` | 已验证的持久结论 |
| `docs/agent/00_data.md` | 数据字段、来源、采集规则 |
| `docs/agent/01_factors.md` | 因子定义 |
