# 06_phase_a_master_plan.md — Phase A 完整测试计划与工作流程

> **本文档是 factor-lab 从"因子补课"到"版本冻结"全过程的唯一执行指令。**
>
> 任何 AI 会话在接手本项目的实验工作时，必须先读本文档。
> 禁止跳过本文档自行调整因子定义、计算方式或实验流程。
>
> **最高准则**：数据可靠性优先于一切效率。
> 任何计算逻辑改动必须说明对数据准确性的影响，经确认后方可执行。

---

## 0. 当前进度总览

```
┌─────────────────────────────────────────┐
│         01_factors.md (因子定义)          │  ← 未冻结，Phase A 完成后统一更新
├─────────────────────────────────────────┤
│   06_phase_a_master_plan.md (←本文档)     │  ← 当前唯一执行指令
├─────────────────────────────────────────┤
│       registry.py / calculator.py        │  ← 未冻结，Phase A 结束后统一修改
└─────────────────────────────────────────┘
```

### 执行状态表

| 阶段 | 状态 | 说明 |
|:----|:----|:------|
| 整理 21 因子清单 | ✅ 完成 | 6 维度 21 因子，定义+算法已定稿 |
| Phase A 测试 | ⏸ 待开始 | 等待本文档完成后启动 |
| Phase B 正交性分析 | ⏸ | Phase A 完成后进行 |
| Phase C 组合验证 | ⏸ | Phase B 完成后进行 |
| 统一更新 registry/calculator | ⏸ | Phase A/B/C 全部完成后一次性修改 |
| 冻结 `01_factors.md` | ⏸ | 同上 |
| 升级为 Layer 2 正式库 | ⏸ | 冻结后 |

---

## 1. 核心原则（不可违反）

### 1.1 实验优先于注册

```
Phase A 全量测试 → Phase B 正交分析 → Phase C 组合验证
               ↓                    ↓
         收集能力边界数据        决定因子去留
                                    ↓
                         统一更新 registry.py 和 01_factors.md
                                    ↓
                               版本冻结
```

**禁止**在任何 Phase 完成前修改 `registry.py`、`calculator.py` 或 `01_factors.md` 中的因子定义。

### 1.2 数据可靠性优先

每次计算前逐项检查（来自 `05_factor_experiment_framework.md` 3.2 节）：

```
[ ] RS 类因子：使用复合回报（收盘价相除），不使用日回报累加
[ ] RS 类因子：RS20 = P(t)/P(t-20) / BM(t)/BM(t-20)（比值，非差值）
[ ] Momentum 类因子：使用原始回报（不减 benchmark）
[ ] 比率类因子（CR3/AmountRatio）：分子分母同一日期
[ ] BreadthChange：差分（今日值 − N 日前值），非变化率
[ ] Volatility：滚动标准差（ddof=1），每个行业独立计算
[ ] 未来函数检查：因子只用 eval_idx 及之前的数据
[ ] 异常值处理：不截尾 winsorize，不插值，仅剔除 NaN
[ ] 确认使用 `close` 而非 `close_hfq`（行业指数无复权问题）
```

### 1.3 性能约束

如果脚本运行时间超过可接受范围，**停下来讨论优化方案**。
不允许擅自修改计算逻辑以提高速度。可能的优化方向：
- 预计算公共中间结果（如 sector 日回报矩阵）
- 分批运行
- 只跑有数据的阶段

---

## 2. 21 因子最终清单

### ① 趋势与动量（5 个）

| # | 因子 | 经典定义 | 算法公式 | 类型 |
|:-:|:-----|:---------|:---------|:----:|
| 1 | **RS20** | 相对强度（比值） | `(P(t)/P(t-20)) / (BM(t)/BM(t-20))` | 经典 |
| 2 | **RS60** | 相对强度（比值） | `(P(t)/P(t-60)) / (BM(t)/BM(t-60))` | 经典 |
| 3 | **Momentum20** | N 日绝对收益 | `P(t)/P(t-20) - 1` | 经典 |
| 4 | **Momentum60** | N 日绝对收益 | `P(t)/P(t-60) - 1` | 经典 |
| 5 | **Acceleration** | 动量变化率 | `Mom20(t) - Mom20(t-5)`（可用 SMA3 平滑作为对照） | 扩展 |

### ② 波动率（4 个）

| # | 因子 | 经典定义 | 算法公式 | 类型 |
|:-:|:-----|:---------|:---------|:----:|
| 6 | **Vol20** | 20D 收益率标准差 | `std(ret[t-20:t])`，**每个行业独立计算** | 经典 |
| 7 | **ATR20** | 平均真实波幅 | `mean(TR[t-20:t])`, TR=max(H-L,\|H-Cp\|,\|L-Cp\|) | 经典 |
| 8 | **VolExpansion** | 波动扩张 | `Vol20(t) / Vol20(t-20)`（>1.2 扩张） | 扩展 |
| 9 | **VolCompression** | 波动收缩 | `Vol20(t) / Vol20(t-20)`（<0.8 收缩） | 扩展 |

> 注：VolExpansion 和 VolCompression 共用同一原始值 `VolRatio(t)`，不做二值化，保留连续值用于 IC 分析。

### ③ 广度与扩散（4 个）

| # | 因子 | 经典定义 | 算法公式 | 类型 |
|:-:|:-----|:---------|:---------|:----:|
| 10 | **ParticipationRate** | 参与度（绝对水平） | `above_ma20_ratio`（DB 已有字段） | 经典 |
| 11 | **BreadthChange** | 广度变化率 | `above_ma20_ratio(t) - above_ma20_ratio(t-5)` | 扩展 |
| 12 | **NewHighRatio** | 新高比例 | `new_high_20d_ratio`（DB 已有字段） | 经典 |
| 13 | **NewHighChange** | 新高比例变化 | `new_high_20d_ratio(t) - new_high_20d_ratio(t-5)` | 扩展 |

### ④ 价量行为（3 个）

| # | 因子 | 经典定义 | 算法公式 | 类型 |
|:-:|:-----|:---------|:---------|:----:|
| 14 | **AmountRatio** | 量比 | `amount(t) / SMA20(amount)`（DB 已有字段 ✅） | 经典 |
| 15 | **VolumeBreakout** | 放量加速度 | `AmountRatio(t) - SMA5(AmountRatio(t))` | 扩展 |
| 16 | **PriceVolDivergence** | 量价背离 | 三周期极值确认法（详见第 3 节） | 扩展 |

### ⑤ 领导力与结构（3 个）

| # | 因子 | 经典定义 | 算法公式 | 类型 |
|:-:|:-----|:---------|:---------|:----:|
| 17 | **CR3** | 行业集中度 | `sum(Top3_amount) / sum(all_sector_amount)` | 经典 |
| 18 | **CR5** | 行业集中度 | `sum(Top5_amount) / sum(all_sector_amount)` | 经典 |
| 19 | **TopDispersion** | 领导力强度 | `mean(Top3_ret) - mean(Bottom3_ret)`（降级观察） | 扩展 |

### ⑥ 风格与资金流（2 个 — Layer 4 预备）

| # | 因子 | 经典定义 | 算法公式 | 最终归属 |
|:-:|:-----|:---------|:---------|:--------|
| 20 | **SmallCapSpread** | 大小票剪刀差 | `中证2000 收益 − 沪深300 收益` | Layer 4 |
| 21 | **AdvDeclineRatio** | 行业涨跌比 | `30 行业中上涨数 / 有数据行业总数` | 行业级→Layer 2 市场级→Layer 4 |

---

## 3. 扩展因子算法详细说明

### 3.1 PriceVolDivergence（量价背离）

**核心逻辑**：价格在极值位置 + 量能方向相反。

```python
divergence = 0  # 连续信号值，范围无限制（通常 -2 ~ +2）

# Step 1: 价格位置判断
close_20d_pct = percentile(close, window=20)  # 近 20 日百分位 (0~1)

# Step 2: 量比
ar = amount_ratio(t)

# Step 3: 背离判定（仅在极值区间触发）
if close_20d_pct > 0.80 and ar < 0.85:
    # 顶背离：价格在高位，量能收缩
    divergence = (close_20d_pct - 0.80) * (0.85 - ar) * 10

if close_20d_pct < 0.20 and ar > 1.15:
    # 底背离：价格在低位，量能扩张
    divergence = -(0.20 - close_20d_pct) * (ar - 1.15) * 10
```

**信号含义**：
- 正数 → 顶背离（价格偏高且量能在缩，趋势衰竭警示）
- 负数 → 底背离（价格偏低且量能在扩，底部信号）
- 接近 0 → 无显著背离

### 3.2 VolumeBreakout（放量加速度）

**核心逻辑**：量比的短期变化加速度。

```python
ar_sma5 = SMA(amount_ratio, window=5)   # 近 5 日平均量比
volume_breakout = amount_ratio(t) - ar_sma5(t)
```

**信号含义**：
- 正值大 → 量能突然放大（可能是突破或脉冲）
- 连续小幅正值 → 温和持续放量
- 负值 → 量能相对于 5 日均值在收缩

### 3.3 VolRatio（波动率扩张/收缩的连续值）

```python
vol20_t = Vol20(t)           # 当前波动率
vol20_t_minus_20 = Vol20(t-20)  # 20 天前的波动率
vol_ratio = vol20_t / vol20_t_minus_20   # 连续值
```

VolExpansion 和 VolCompression 不另做二值化，IC 分析直接用 `vol_ratio` 的连续值。

### 3.4 Acceleration（可选平滑）

```python
# 无平滑版（Phase A 默认）
acceleration = mom20(t) - mom20(t-5)

# 可选的平滑版（Phase A 后对照用）
acceleration_smooth = mom20(t) - SMA5(mom20)
```

Phase A 先跑无平滑版，拿到结果后如有需要再跑平滑版对比。

### 3.5 TopDispersion（保留降级观察）

```python
rets = cross_sectional_returns(t)  # 30 行业当日涨幅
sorted_rets = sort(rets)
top3 = mean(sorted_rets[:3])      # Top3 行业平均涨幅
bot3 = mean(sorted_rets[-3:])     # Bottom3 行业平均涨幅
top_dispersion = top3 - bot3
```

保留为观察因子，不在 Phase C 组合阶段之前使用。

---

## 4. 因子体系 vs Layer 体系映射

将 21 因子关联到 AI-DMS 各层，明确每类因子在整体架构中的消费位置。

```
Layer 2（特征层）  ← 五类因子全部来源（趋势/波动率/广度/价量/领导力）
  └─ 在 factor-lab 中独立计算、验证、存储

Layer 3（结构层）  ← 价量行为 + 结构领导力 + 广度扩散
  └─ 多特征组合 → 可辨识的市场结构
  └─ 例：主升结构 = 趋势↑ + 放量↑ + 广度↑ + 龙头强化

Layer 4（风格/Regime层） ← 波动率 + 风格资金流
  └─ 宏观市场环境判断（风险偏好、牛熊周期）
  └─ SmallCapSpread / AdvDeclineRatio（市场级）归属此层

Layer 5（预期层）  ← 估值 + NLP
  └─ AI 解释"为什么"，基本面+叙事驱动

W1/W2/W3           ← ❌ 跨类混合因子（Layer 2 内部错误设计）
  └─ 诊断确认：将不同类信号揉合，组件方向互相抵消
```

**核心约束**：Layer 2 只做特征提取，不做市场结论。
Layer 3+ 组合规则在 Phase C 完成后才有资格定义。

---

## 5. 市场阶段定义（13 阶段）

基于基准指数 `index.000985.SH` 收盘价最高/最低点划分。

| ID | 名称 | 类型 | 起始 | 结束 | 基准涨跌 | 天数 |
|:--:|:----|:----:|:----:|:----:|:--------:|:----:|
| 1 | Bull #1 — 大牛市 | bull | 2005-07-18 | 2008-01-14 | +619.0% | 910 |
| 2 | Bear #2 — 金融危机 | bear | 2008-01-14 | 2008-11-04 | −71.5% | 295 |
| 3 | Bull #3 — 四万亿反弹 | bull | 2008-11-04 | 2009-11-23 | +146.7% | 384 |
| 4 | Bear #4 — 漫长熊市 | bear | 2009-11-23 | 2012-12-03 | −40.7% | 1106 |
| 5 | Bull #5 — 创业板→杠杆牛 | bull | 2012-12-03 | 2015-06-12 | +246.6% | 921 |
| 6 | Bear #6 — 股灾+熔断 | bear | 2015-06-12 | 2016-01-28 | −49.7% | 230 |
| 7 | Bull #7 — 超跌反弹 | bull | 2016-01-28 | 2016-11-28 | +27.3% | 305 |
| 8 | Bear #8 — 慢熊 | bear | 2016-11-28 | 2018-10-18 | −34.1% | 689 |
| 9 | Bull #9 — 结构牛 | bull | 2018-10-18 | 2021-12-13 | +79.6% | 1152 |
| 10 | Bear #10 — 大熊市 | bear | 2021-12-13 | 2024-02-05 | −39.3% | 784 |
| 11 | Bull #11 — W底反弹 | bull | 2024-02-05 | 2024-11-11 | +39.6% | 280 |
| 12 | Bear #12 — 2浪回调 | bear | 2024-11-11 | 2025-04-07 | −14.7% | 147 |
| 13 | Bull #13 — 3浪主升中 | bull | 2025-04-07 | 至今 | +49.5% | 进行中 |

详细行业领涨记录见 `docs/research/phase_sector_leadership_v1.md`。

所有 Phase A 测试的 eval 点如落在以上阶段之外则跳过。小样本阶段（Bear #12 仅 147 天）结论标注为参考性。

---

## 6. Phase A 执行顺序（按类逐步推进）

### 执行规则

1. **一次只跑一个类**。跑完输出完整结果+汇报，不跳步。
2. **每个因子的第一次运行必须做交叉验证**：抽 5 个日期 × 5 个行业 = 25 个样本，手动验算。
3. 验算通过后标记 `verified = true`，否则 `false`。
4. 每类跑完后更新本文档的进度总表。

### 类① 趋势与动量（5 个因子）

| 因子 | 数据来源 | 关键改动说明 |
|:-----|:--------|:------------|
| RS20 | sector close | 从 Phase A 第一次跑的"超额收益差值"改为"比值" |
| RS60 | sector close | 同上 |
| Momentum20 | sector close | ✅ 无变化 |
| Momentum60 | sector close | ✅ 无变化 |
| Acceleration | 派生自 Momentum20 | ✅ 无变化 |

### 类② 波动率（4 个因子）

| 因子 | 数据来源 | 关键改动说明 |
|:-----|:--------|:------------|
| Vol20 | sector close（每个行业独立） | 旧实现是"行业平均"，新实现是"每个行业自己的" |
| ATR20 | sector high/low/close | 新实现，需要 high/low 字段 |
| VolExpansion | 派生自 Vol20 | 连续值 |
| VolCompression | 派生自 Vol20 | 连续值 |

### 类③ 广度与扩散（4 个因子）

| 因子 | 数据来源 | 关键改动说明 |
|:-----|:--------|:------------|
| ParticipationRate | sector above_ma20_ratio | ✅ 无变化 |
| BreadthChange | 派生自 above_ma20_ratio | ✅ 无变化 |
| NewHighRatio | sector new_high_20d_ratio | ✅ 无变化 |
| NewHighChange | 派生自 new_high_20d_ratio | ✅ 无变化 |

### 类④ 价量行为 + 领导力（6 个因子）

| 因子 | 数据来源 | 关键改动说明 |
|:-----|:--------|:------------|
| AmountRatio | sector amount_ratio | ✅ 无变化 |
| VolumeBreakout | 派生自 AmountRatio | 新实现 |
| PriceVolDivergence | sector close + amount_ratio | **重写** |
| CR3 | sector amount（横截面） | ✅ 无变化 |
| CR5 | sector amount（横截面） | ✅ 无变化 |
| TopDispersion | sector close（横截面） | ✅ 保留 |

### 类⑤ 风格（2 个因子）

| 因子 | 数据来源 | 关键改动说明 |
|:-----|:--------|:------------|
| SmallCapSpread | index.932000 + index.000300 | 新实现（Layer 4 预备） |
| AdvDeclineRatio | sector close（横截面） | 新实现（行业级→Layer 2，市场级→Layer 4） |

---

## 7. 输出规范

### 每类测试必须记录

```
实验编号：Phase-A-{类名}
因子清单：[因子1, 因子2, ...]
计算脚本：{路径}
验证状态：verified / unverified / cross-checked
运行日期：{日期}
总样本量：{N}
阶段覆盖：1-13（或标注缺失阶段）
备注：{计算逻辑改动说明，数据异常记录}
```

### 输出格式

每类实验输出一个结果 JSON 文件到 `backend/research/analysis/output/`：

```json
{
  "experiment": "Phase-A-{类名}",
  "computation_verified": true,
  "factors": [{"col": "rs20", "label": "RS20"}, ...],
  "phases": [...],
  "ic_matrix": [
    {
      "factor": "RS20",
      "phase_1": {"spearman": 0.1234, "p": 0.001, "n": 227, "sign": "+"},
      ...
    }
  ],
  "records_count": 5539
}
```

### 每类完成后向用户汇报的内容

1. 因子排名（按 Avg|IC|）
2. 每阶段最佳因子
3. 跨类对比（和已跑类的因子一起排名）
4. 异常记录

---

## 8. 后续阶段说明

在 Phase A 全部完成后，再进入以下步骤：

### Phase B：因子正交性分析

- 21 因子的两两相关系数矩阵
- 按阶段分别计算（13 个矩阵）
- 输出：冗余因子对、互补因子对

### Phase C：组合验证

- 基于 Phase A + B 挑选候选组合
- 按阶段分别设计组合规则
- 在 13 阶段上验证（非滚动回测）
- 对照基线：EXP-003 Variant D

### 冻结收尾

Phase A/B/C 完成后，统一修改：

1. `01_factors.md` — 写入所有因子的最终定义和能力边界
2. `registry.py` — 更新因子注册表
3. `calculator.py` — 更新计算引擎（如果需要）
4. `04_factor_capabilities.md` — 更新能力边界
5. `docs/research/LESSONS.md` — 提升已验证的耐久结论

---

## 9. 常见陷阱（每次启动时回顾）

| 陷阱 | 避免方式 |
|:-----|:--------|
| RS20 用差值代替比值 | 每次启动检查 RS20 公式是否为 `(P(t)/P(t-N)) / (BM(t)/BM(t-N))` |
| 效率优化时改了计算逻辑 | 效率优化必须保留 verified 版本做对照，偏差确认后执行 |
| 提前修改 registry.py | Phase 全部完成前不做任何注册表修改 |
| 陷入"再调一个参数"循环 | 每个因子只测一次，不调参。阈值调整留到 Phase C |
| 跨阶段 IC 平均误导 | 只看 Avg|IC| 可能隐藏阶段反转特性，必须同时看阶段符号分布 |
| 忘记未来函数检查 | 每次 eval_idx 计算只用该日期及之前的数据 |

---

## 10. 文件关系

```
docs/agent/
├── 00_data.md                    # 数据字段/来源/复权口径
├── 01_factors.md                 # 因子定义与注册（← Phase 完成后更新）
├── 02_experiments.md             # 实验工作流
├── 03_strategy.md                # 策略讨论范围
└── 06_phase_a_master_plan.md     # ← 唯一执行指令：Phase A 完整执行流程

docs/research/
├── MEMORY.md                     # 导航记录（每类完成后加一行）
├── INDEX.md                      # 实验索引
└── LESSONS.md                    # 耐久结论（Phase 完成后更新）
```

---

## 11. 本文档维护

- 每完成一个类的 Phase A 测试，更新第 0 节的执行状态表
- 每完成一个阶段（Phase A/B/C），在 `docs/research/MEMORY.md` 加一行
- 任何因子定义的调整必须在此更新并标注修改原因和日期
- 本文档不替代 `01_factors.md`——后者是最终冻结版本，前者是执行中的工作指令
