# PLAN.md — 当前 Sprint

## 当前进度

**Phase A（因子语义映射）已完成。** 21 个因子全部通过 13 阶段 IC 测试，registry/calculator 已冻结为 v2.0。

### 本轮完成

| 阶段 | 内容 | 状态 |
|:----|:-----|:----:|
| Phase A-① 趋势与动量 | RS20(比值), MOM20/60, Accel, RS60 | ✅ |
| Phase A-② 波动率 | Vol20(逐行业), VolRatio | ✅ |
| Phase A-③ 广度扩散 | PartRate, BreadthChg, NewHigh | ✅ |
| Phase A-④ 价量+领导力 | AmtRatio, VolBkOut, CR3, CR5, TopDisp | ✅ |
| Phase A-⑤ 风格 | SCSpread, AdvDecl | ✅ |
| 注册冻结 | registry.py/calculator.py/01_factors.md 全部更新 | ✅ |

### 当前基线

17 因子注册库（12 MAIN + 5 AUX），参见 `docs/agent/01_factors.md`

| 最强因子 | Avg|IC| | 备注 |
|:---------|:-----:|:------|
| CR3 | 0.232 | 行业集中度 — 全场最强 |
| SCSpread | 0.205 | 大小票剪刀差 |
| CR5 | 0.205 | 行业集中度 |
| Mom20 | 0.188 | 20日动量 |
| AdvDecl | 0.181 | 行业涨跌比 |

## 下一步

- [ ] **Phase B** — 17 因子正交性分析 + 阶段权重 + 组合设计
- [ ] **Phase C** — 组合验证（对照 EXP-003 Variant D 基线）
