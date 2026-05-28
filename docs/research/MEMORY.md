# Research Memory

> Short navigation memory for future AI sessions.
> Keep this file compact: one line should help locate the right detailed record.

## How To Use

- Read this after `AGENT.md` and `PLAN.md`.
- Use keyword/date clues here to locate detailed files.
- Do not store long analysis here. Put details in `experiments/`, `archive/`, or `LESSONS.md`.
- If a task is not yet a formal experiment, still add a short navigation row when it may need to be resumed later.

## Format

| Date | Keywords / Topic | Type | Summary | Detail Path | Status |
|------|------------------|------|---------|-------------|--------|
| 2026-05-29 | 市场状态机 / 研究记忆 / 实验闸门 | workflow-design | 建立短 memory 导航和正式回测前必须先做数据审计、实验设计、用户确认的 workflow。 | `docs/agent/02_experiments.md` | complete |
| 2026-05-29 | 主升阶段 / 因子组合 / 阈值筛选 | experiment-design | 示例检索行：用于定位“全市场找主线行业回测、主升阶段因子组合和阈值筛选”这类后续实验设计。 | `docs/research/experiments/EXP-xxx.md` | example |
| 2026-05-29 | 市场状态识别 / 主线行业识别 / 因子分工 | reference | 确认 v1 不先扩外部因子；个股层主要用于涨跌、涨跌停、行业扩散和龙头集中度聚合，优先补映射和二次计算。 | `docs/research/factor_scope_v1.md` | complete |
| 2026-05-29 | 全A数据 / 行业映射 / 二次计算 | data-audit | 审计当前数据库：stock 数据已大体存在，但 stock-to-sector 映射为空，sector breadth 仅 3 个试点行业，情绪字段需二次计算。 | `docs/research/data_readiness_v1.md` | running |
| 2026-05-29 | 数据运行规范 / a-stock-data / flash执行SOP | workflow-design | 定义 provider 只做适配器，factor-lab 负责字段契约、SQL落库、二次计算、验证报告和低成本模型执行边界。 | `docs/research/data_runtime_spec_v1.md` | complete |

## Type Guide

- `data-audit`: data coverage, field quality, source checks, schema readiness.
- `experiment-design`: hypothesis and method design before implementation.
- `experiment-result`: confirmed experiment result after the run is accepted.
- `data-source-test`: interface/source evaluation such as akshare, tushare, mootdx, adata.
- `workflow-design`: research process, memory, documentation, or review rules.
- `reference`: background research that supports later experiments.
