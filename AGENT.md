# AGENT.md — AI Startup Router

> Purpose: fast orientation for a new AI session. Keep this file short.
> Default startup should read only this file, `PLAN.md`, and `docs/research/MEMORY.md`.

## Module Scope

`factor-lab` is the lightweight factor research submodule of the broader AI-DMS / Market State Engine.

This repo only focuses on script-verifiable work:

- Layer 1: raw market data needed by factors
- Layer 2: single factors and cross-section features
- Layer 3: factor combinations / structure evidence
- Layer 9: lightweight chart inspection

Out of scope for this repo for now:

- macro research
- capex / fundamentals narrative research
- reports / news / NLP expectation layer
- final AI-DMS state explanation layer

## Hard Rules

- Use the semi-wide SQLite design. Prefer appending daily fields to `market_daily_data`; do not split tables unless the data shape truly requires it.
- Benchmark symbol is `index.801003.SW`（申万Ａ指，唯一真正的全A指数）。
- 801003 替代了此前误用的 801001（实为申万50，仅50只大盘股）。
- 随身版数据库: `data/quant_engine_base.db`（~64MB，不含个股行，适合移动研究）。
- Vectorized sector behavior scoring is forbidden for research conclusions.
- Backtests must use rolling evaluation. Static hit rate is not accepted as evidence.
- Keep experiments narrow: change one main variable, run loop-based rolling backtest, record the result.
- Do not read `docs/archive/` or `docs/human/` unless the user explicitly asks or the current task needs it.

## What To Read

| Task | Read |
|------|------|
| **Current priority / next work** | `PLAN.md`, then `docs/research/MEMORY.md` |
| **Phase A master plan (experiment instruction)** | `docs/agent/06_phase_a_master_plan.md` |
| Data fields, sources, adjustment policy | `docs/agent/00_data.md` |
| Factor definitions, Layer 2/3 boundaries, backtest rules | `docs/agent/01_factors.md` |
| Experiment workflow and known conclusions | `docs/agent/02_experiments.md`, then `docs/research/INDEX.md` / `LESSONS.md` |
| Strategy/portfolio discussion | `docs/agent/03_strategy.md` |
| Exact schema details | `docs/database_schema.md` |

Use `docs/research/MEMORY.md` as a short navigation index. Only read long reports,
experiment records, or archive files when a memory row points to them or the current
task specifically needs that detail.

## Core Commands

### 每日更新（首选）
```bash
# 更新 base.db（随身版）— 只更新801003 K线+派生字段，最快
python3 backend/collectors/daily_update.py --db data/quant_engine_base.db --only-benchmark

# 更新 base.db 全部（含行业+宏观）
python3 backend/collectors/daily_update.py --db data/quant_engine_base.db

# 更新 full.db 全部（含个股聚合重算）
python3 backend/collectors/daily_update.py
```

### 一次性/初始化
```bash
python3 backend/collectors/build_sector_mapping.py     # 行业映射
python3 backend/collectors/compute_stock_fields.py     # 个股涨跌幅/涨跌停
python3 backend/collectors/aggregate_sector_breadth.py # 行业内部宽度
python3 backend/collectors/sw_daily.py                 # 行业日线采集（全量）
python3 backend/collectors/tickflow_collector.py       # 个股日线采集（全量）
python3 backend/collectors/fetch_macro_data.py         # 宏观数据(国债/两融)
```

# Factor calculation
python3 -m backend.research.features.calculator

# Phase A — Factor semantic mapping
python3 backend/research/analysis/phase_A_class01_trend.py
python3 backend/research/analysis/phase_A_class02_volatility.py
python3 backend/research/analysis/phase_A_class03_breadth.py
python3 backend/research/analysis/phase_A_class04_pricevol_leadership.py
python3 backend/research/analysis/phase_A_class05_style.py

# Historical sector leadership analysis
python3 backend/research/analysis/sector_leadership.py

# Local app
./start.sh
```

## Databases

| 文件 | 大小 | 说明 |
|:----|:----:|:-----|
| `data/quant_engine.db` | ~2.8GB | 完整版：含全部个股行，台式研究用 |
| `data/quant_engine_base.db` | ~64MB | 随身版：仅行业+指数+宏观+801003，无个股行 |

## Documentation Workflow

For each resumable task or experiment:

1. Add a short retrieval row in `docs/research/MEMORY.md`.
2. For formal experiments, add or update one row in `docs/research/INDEX.md`.
3. Write full experiment records under `docs/research/experiments/EXP-xxx-*.md`.
4. Put one-off source tests and troubleshooting under `docs/archive/`.
5. Promote only durable conclusions to `docs/research/LESSONS.md`.
6. Keep `PLAN.md` focused on the current sprint, not historical detail.
