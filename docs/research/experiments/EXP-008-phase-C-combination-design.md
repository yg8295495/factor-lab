# EXP-008: Phase C — Factor Combination Design & Phase Validation

> 基于 Phase A（因子 IC）× Phase B（正交性）设计候选组合，分阶段验证组合 IC。

---

## 一、设计原则

### 数据可靠性
- 所有因子使用 Phase A 已验证的定义和计算公式
- 组合分数使用 rank_pct 等权合并（Phase C 不做权重优化）
- 分阶段计算 IC，不跨阶段平均

### 正交性约束
从 Phase B 平均相关矩阵出发：
- **排除高冗余对**（r ≥ 0.6）：CR3↔CR5(0.89), RS20↔Mom20(0.74), Mom20↔PartRate(0.74), PartRate↔NewHigh(0.74), RS60↔Mom60(0.72)
- **优先互补对**（r < 0.25）：不同因子族的信息增量最大

### 候选组合来源

从 17 注册因子中选 3 个为一组，每个组覆盖 ≥2 个不同因子族。

---

## 二、候选组合（5 组）

### Combo A — 「Leader+Accel+Sentiment」
**因子**: `CR3 + Accel + AdvDecl`
| 条目 | 内容 |
|:----|:------|
| 族 | 领导力 + 动量变化 + 风格/涨跌比 |
| Avg\|IC\| | 0.232 / 0.177 / 0.181 |
| 跨相关 | CR3-Accel 0.20, CR3-AdvDecl 0.26, Accel-AdvDecl 0.21 |
| 考虑 | 三个不同家族，跨相关性均 < 0.27，信息增量独立 |

### Combo B — 「Leader+Vol+Breadth」
**因子**: `CR3 + Vol20 + BreadthChg`
| 条目 | 内容 |
|:----|:------|
| 族 | 领导力 + 波动率 + 广度变化 |
| Avg\|IC\| | 0.232 / 0.154 / 0.140 |
| 跨相关 | CR3-Vol20 0.23, CR3-BreadthChg 0.25, Vol20-BreadthChg 0.11 |
| 考虑 | **全场最低跨相关组合**（最大 r=0.25），三个完全不同的市场维度 |

### Combo C — 「Leader+Momentum+Vol」
**因子**: `CR3 + Mom20 + Vol20`
| 条目 | 内容 |
|:----|:------|
| 族 | 领导力 + 动量 + 波动率 |
| Avg\|IC\| | 0.232 / 0.188 / 0.154 |
| 跨相关 | CR3-Mom20 0.19, CR3-Vol20 0.23, Mom20-Vol20 0.20 |
| 考虑 | 相比 Phase C v1（CR3+Mom20+Accel），用 Vol20 替换 Accel 降低相关性（Accel-Mom20=0.34） |

### Combo D — 「Sentiment+Breadth+VolChange」
**因子**: `AdvDecl + BreadthChg + VolRatio`
| 条目 | 内容 |
|:----|:------|
| 族 | 涨跌比 + 广度变化 + 波动率变化 |
| Avg\|IC\| | 0.181 / 0.140 / 0.114 |
| 跨相关 | AdvDecl-BreadthChg 0.27, AdvDecl-VolRatio 0.16, BreadthChg-VolRatio 0.16 |
| 考虑 | 市场情绪维度组合，不含领导力因子（与 Combo A/B/C 互补对照） |

### Combo E — 「Phase-Specific Adaptive」
**动态组合**：不同阶段类型使用不同因子

| 阶段类型 | 因子 | 选择理由 |
|:--------|:-----|:--------|
| Bull (P1,3,5,7,9,11,13) | **Mom20 + Accel + AdvDecl** | 牛市动量+加速度+涨跌情绪最强 |
| Bear (P2,4,6,8,10,12) | **Vol20 + CR3 + AdvDecl** | 熊市波动率+集中度+避险情绪 |
| 说明 | 将 13 阶段按牛/熊分类，分别计算组合分数后合并结果 |

---

## 三、验证方法

### 3.1 组合 IC 计算

对每个候选组合，在每个阶段内：

1. 对该阶段每一天，对 30 个行业计算各因子 rank_pct（0~1）
2. `ComboScore = mean(rank_pct(f1) + rank_pct(f2) + rank_pct(f3))`
3. 计算 ComboScore 与未来 20 日收益的 Spearman 秩相关 → **组合 IC**
4. 对比组合 IC 与单因子 IC，判断组合是否带来信息增量

### 3.2 输出指标

每个组合 × 每个阶段：

| 指标 | 含义 |
|:----|:-----|
| Composite IC | 组合分数 vs 未来 20D 收益的秩相关 |
| IC 提升 | 组合 IC / max(单因子 IC) — >1 说明有正和效应 |
| 单调性 | TOP1→TOP5 的 forward return 是否严格递减 |
| 胜率 | 组合在每个阶段正 IC 的天数占比 |
| 方向稳定性 | 组合 IC 在阶段内的正/负方向是否一致 |

### 3.3 对照基线

- Phase C v1 无状态组合（CR3+Mom20+Accel）
- EXP-003 Variant D 作为最终框架对照（非直接对比组合 IC）

---

## 四、验收标准

| 指标 | 通过线 |
|:----|:------|
| 最佳组合 Avg\|CompositeIC\| | > 0.20（超过 CR3 单因子） |
| 至少有 1 个组合在 ≥10/13 阶段为正 IC | 方向稳定 |
| 最佳组合在 bull/bear 均有效 | 不偏态 |
| Combo E（自适应）优于 Combo A-D | 分阶段设计有价值 |

---

## 五、运行计划

1. 编写 `phase_C_combo_design.py` — 一次性计算 5 组合 × 13 阶段 IC
2. 运行并输出 `output/phase_C_combo_design.json`
3. 分析结果，得出推荐组合
4. 更新 PLAN.md 和 MEMORY.md
