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
| 2026-05-29 | 全A数据 / 行业映射 / 二次计算 | data-audit | 审计当前数据库：stock 数据已大体存在，但 stock-to-sector 映射为空，sector breadth 仅 3 个试点行业，情绪字段需二次计算。 | `docs/research/data_readiness_v1.md` | complete |
| 2026-05-29 | 数据运行规范 / a-stock-data / flash执行SOP | workflow-design | 定义 provider 只做适配器，factor-lab 负责字段契约、SQL落库、二次计算、验证报告和低成本模型执行边界。 | `docs/research/data_runtime_spec_v1.md` | complete |
| 2026-05-29 | stock-to-sector 映射 / 30行业全覆盖 | data-audit | 用 akshare index_component_sw 构建5148/5478只股票的行业映射（94%），31行名称对齐。 | `backend/collectors/build_sector_mapping.py` | complete |
| 2026-05-29 | 个股 pct_chg_raw / 涨跌停标记 | data-audit | 从未复权 close 计算 4814/5183 只股票的原始涨跌幅和涨跌停标记，14.58M 行（97.3%）。 | `backend/collectors/compute_stock_fields.py` | complete |
| 2026-05-29 | 市场情绪聚合 / index.000985.SH | data-audit | 统计全 A 股每日涨跌家数、涨跌停家数，写入 index.000985.SH 行。覆盖 5189/5191 行。 | `backend/collectors/aggregate_market_emotion.py` | complete |
| 2026-05-29 | 行业内部宽度 / 30行业全覆盖 | data-audit | 对 30 个行业分别计算 above_ma20/ma60_ratio、new_high_20d_ratio，替换原有 3 个试点行业的旧数据。 | `backend/collectors/aggregate_sector_breadth.py` | complete |
| 2026-05-29 | amount_ratio / 额比写入 | data-audit | 所有 sector 行 + index.000985.SH 写入 amount_ratio = amount/SMA20(amount)。sector 132514/133084 行覆盖。 | `backend/collectors/compute_amount_ratio.py` | complete |
| 2026-05-29 | ETF净申赎 / 量能增强方向 | reference | 评估 tushare etf_share_size 作为未来量能信号增强的数据源。成交额占比和净申赎实时算，不持久化。 | `docs/research/etf_flow_as_signal_v1.md` | reference |
| 2026-06-04 | 市场状态识别 EXP-004 / 五维度分类 | experiment-result | 6轮迭代(v0→v0.5)，最终 bear false MAIN_UP 3.0%, bull MAIN_UP recall 10.5%。诊断确认已到规则边界，剩余模糊窗口交给行业层(EXP-003)。最终规则固化在 v0.5。 | `docs/research/experiments/EXP-004-market-state-recognition-v0.md` | complete |
| 2026-06-05 | EXP-003 / Variant D / 状态=仓位 | experiment-result | D(≥6) 确认为当前基线：+985%收益,+341%超额,-46%回撤。CHAOS贡献46%，方向筛选有效✅ 强识别待验证⚠️ | `docs/research/experiments/EXP-003-breadth-enhanced-behavior-score.md` | complete |
| 2026-06-05 | EXP-006 / 信号生命周期分析 | experiment-result | 5/10/20/40/60D 四条曲线完成。Delta(W2-W3)=生命周期位置因子（解释性，非交易性）。Variant E融合测试失败。 | `output/exp006*/` | complete |
| 2026-06-05 | EXP-007 / State×Lifecycle融合 | experiment-result | Delta作为实时选择过滤器不成立。E_state_lifecycle(377.8%) / E_sens_hard(633.1%) 均不如D(985.3%)。行业层研究收口。 | `docs/research/experiments/EXP-007-state-lifecycle-fusion.md` | complete |


## Type Guide

- `data-audit`: data coverage, field quality, source checks, schema readiness.
- `experiment-design`: hypothesis and method design before implementation.
- `experiment-result`: confirmed experiment result after the run is accepted.
- `data-source-test`: interface/source evaluation such as akshare, tushare, mootdx, adata.
- `workflow-design`: research process, memory, documentation, or review rules.
- `reference`: background research that supports later experiments.
