# factor-lab 开发计划

> ⚠️ **新人必读**：本文件是 factor-lab 的"任务总纲"。新会话后先读 `AGENT.md`(AI导航) + `README.md`(项目概述) + `PLAN.md`(本文件)。
>
> **核心方法**：所有回测必须用**滚动方式**（每 20 天重评分→调仓→跟踪超额），禁止静态命中率。详见记忆 `workflow_accuracy_first`。
>
> **评分引擎**：以 `sector_behavior_score.py` 的**循环版**为准。向量化版已被验证结果不一致（匹配率仅 34.7%），勿用。

---

## 全局里程碑

```
Phase 1 ─ 骨架搭建 + 数据通道 ───────────────── 已完成
Phase 2 ─ 因子计算 + 基础因子分析 ──────────── 基本完成
Phase 3 ─ 市场结构研究（Layer 3）────────────── 当前阶段
  ├─ 13阶段划分 + 行业轮动分析       ✅ Done
  ├─ 行业强度评分 v1                 ✅ Done (已废弃，见实验文档)
  ├─ 转折期行为评分 v2 v0.1          ✅ Done
  ├─ 结构因子构建                     📝 待做
  └─ 主线识别 → Layer 3 State Machine 📝 待做
Phase 4 ─ 标注系统 + 回测 + qlib ───────────── 📝 待做
```

---

## 当前完成状态

| 模块 | 状态 | 说明 |
|------|:----:|------|
| 数据库 (6表, 23万行) | ✅ | 55资产，schema已冻结 |
| Feature Registry (17因子) | ✅ | 见 `registry.py` |
| regsitry.py CSI→SH 修正 | ✅ | benchmark符号统一 |
| 向量化入口隔离 | ✅ | --daily 已拦截 |
| 涨跌停口径 | ✅ | baostock pctChg 字段 |
| market_daily_data 新字段 | ✅ | 新增10列（breadth+情绪） |
| models.py 更新 | ✅ | 新增字段映射 |
| 个股 Pilot 脚本 | ✅ | baostock，待台式机执行 |
| Tier2 Bug 修复 | ✅ | adv_decline_ratio + volatility 18%→99.7% |
| 行为评分 v2 v0.1 | ✅ | 滚动回测 +60.5%超额/53.1%胜率 |
| 结构因子构建 | 📝 | 待pilot通过后开始 |
| Layer 3 State Machine | 📝 | 下一阶段 |

---

## 实验文档索引

实验结论和详细回测数据已移出 PLAN.md，统一归入：

| 实验 | 文档 |
|:----|:----|
| 阶段划分 + 行业领航分析 | `docs/research/phase_sector_leadership_v1.md` |
| 评分实验合集（v1结论+v2设计+v0.1回测+遗留问题） | `docs/research/behavior_scoring_v1.md` |
| AI 工作导航 | `AGENT.md` |
| 数据源状态 | `docs/data_source_report.md`, `data_collection_manifest.md` |

实验输出 JSON 在 `backend/research/analysis/output/` 目录下。

---

## 下一步任务

### [P0] 个股数据 Pilot → 全量采集
1. 台式机执行 `python3 backend/collectors/stock_pilot.py`（电子/食品饮料/银行）
2. 验证通过后写全量采集脚本
3. 一次性计算：全市场情绪指标 + 30行业 breadth

### [P1] Layer 3 结构因子构建
- RS 加速度（delta RS）
- 波动率扩张因子
- Breadth 聚合（sector_breadth）
- 全在 `backend/research/structures/` 下开发

### [P2] 行为评分 v2 改进 + 回测集成
- 滚动回测加入 breadth 调整因子
- A/B 对比：v0.1（纯行为） vs v0.2（行为 + breadth）

### [P3] 文档收尾 + 笔记本迁移
- 更新 PLAN.md / AGENT.md / behavior_scoring_v1.md
- 笔记本可复现全套分析

---

## 设计决策速查

1. **循环版 > 向量化版** — 各行业交易日历不同，pivot对齐导致窗口偏移
2. **滚动回测 > 静态命中率** — 实战中主线分阶段轮换
3. **schema 已冻结** — 不删不改现有主键，新因子只加字段
4. **符号编码** — `{asset_type}.{ticker}.{exchange}`
5. **Factor Registry** — 所有因子通过 registry.py 注册
6. **先人工标注 → 再结构识别 → 不上 ML**
