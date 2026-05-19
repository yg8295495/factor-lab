# 数据源踩坑记录

> 遇到数据问题了先看这个文件，不要从零开始排查。

---

## 环境信息

| 项目 | 值 |
|------|-----|
| 机器 | Windows，翻墙（Clash Verge TUN 模式） |
| Python | conda env `quart_trader`，requests/httpx/curl_cffi 均受影响 |
| 浏览器 | Chrome 148（系统）/ Chromium 1200（Playwright 自带） |
| akshare | 1.18.59 |

---

## 东财 API 状态（2026-05-19 测试）

### push2his.eastmoney.com（历史K线）

| 方法 | 结果 | 原因 |
|------|------|------|
| 浏览器手动打开 | ✅ 通 | 真实浏览器 TLS 指纹 + Cookie |
| Python requests | ❌ `RemoteDisconnected` | 检测到非浏览器客户端，主动断开 |
| Python httpx (HTTP/2) | ❌ 同上 | 无关协议版本 |
| curl_cffi (模拟 Chrome) | ❌ 同上 | JA3 指纹仍然不像真实浏览器 |
| curl.exe | ❌ exit 56 | 非浏览器一律拒绝 |
| **Playwright + chromium-1200** | ✅ **通** | **真实浏览器内核，先访问东财主站拿 Cookie** |

**关键发现**：必须先 `page.goto('https://www.eastmoney.com')` 拿到 Cookie，再调 API。

### push2.eastmoney.com（实时列表）

**所有方法均不通。** 这个域名本身在你的网络上被屏蔽了，与客户端无关。

### 各代码类型在 push2his 上的可用性

| 代码类型 | secid 格式 | push2his 可用？ | 替代方案 |
|---------|-----------|----------------|---------|
| 宽基 (000001, 000300...) | `1.000001` | ✅ 通 | — |
| 上证系列 (000016...) | `1.000016` | ✅ 通 | — |
| 深交所系列 (399006...) | `0.399006` | ✅ 通 | — |
| 中证主题 (399997...) | `0.399997` | ✅ 通 | — |
| **申万行业 (801010...)** | **`0.801010`** | **❌ rc=100 不存在** | **akshare.index_hist_sw()** |
| 中证2000 (932000) | `1.932000` | ❌ rc=100 不存在 | 旧系统迁移 |
| 新代码 (93xxxx, 99xxxx) | `1.990001` | ❌ rc=100 不存在 | 旧系统迁移/待补 |

---

## 已确认可用的替代数据源

| 接口 | 覆盖范围 | 测试结果 |
|------|---------|---------|
| **akshare.stock_zh_index_daily_tx(symbol)** | 宽基 + 深交所 + 部分中证 | ✅ 全通（腾讯源） |
| **akshare.index_hist_sw(symbol)** | **申万31行业** | ✅ **全通，字段齐全** |
| **akshare.index_zh_a_hist(symbol)** | 全部指数 | ❌ 本机被封，沙箱被屏蔽 |

---

## 数据迁移注意事项

从 `backend/financial_data.db`（旧系统）迁移到 `factor-lab/data/quant_engine.db`：

1. **申万代码后缀差异**：旧系统用 `.SI`（如 `801780.SI`），新系统用 `.SW`（`sector.801780.SW`）
2. **旧系统缺数据**：中华半导体芯片(990001)、CS人工智(930713)、CS电池(931719)、中证申万有色金属(000819) 在旧系统中无数据
3. **煤炭(801950)缺5年**：2017-01 → 2021-12 数据断裂（旧系统问题）
4. **中证军工(399967)缺99天**：2013-12 → 2014-04 数据断裂

---

## 推荐的采集策略

```python
def fetch_asset_data(symbol, code):
    """按优先级尝试多个数据源"""
    # 1. 申万行业 → 用 akshare 申万接口
    if symbol.startswith('sector.'):
        return akshare.index_hist_sw(code)
    
    # 2. 宽基/中证 → 用 Playwright + chromium-1200 + push2his
    #    （需要先访问 eastmoney.com 拿 Cookie）
    return playwright_fetch_from_push2his(secid)
```

## Playwright 注意事项

- 必须用 **chromium-1200**（系统 Chrome 148 会被检测）
- 先访问 `https://www.eastmoney.com` 拿 Cookie
- 每批请求间隔 ≥ 2.5 秒，每 15 个重新拿 Cookie
- 申万行业不在 push2his 上，不要浪费时间尝试

---

## 最终统一方案（2026-05-19 定稿）

### 数据源分工

| 数据源 | 覆盖 | 原因 |
|--------|------|------|
| **CSI接口** `stock_zh_index_hist_csindex` | 25个指数（宽基+中证主题） | 全量历史(1990~今)、含PE_TTM、Python直连可通 |
| **申万接口** `index_hist_sw` | 30个申万行业 | 全量历史(1999~今)、字段齐全、Python直连可通 |
| **Daily+腾讯合并** | 创业板指 399006 | 国证指数，CSI不覆盖；daily有volume，腾讯有amount |

### 一键重建

```bash
python factor-lab/backend/rebuild_db.py
```

清除旧数据、重新拉取全部资产、统一截止日期。

### CSI接口注意

- 必须传 `start_date='19900101'` 和 `end_date='20260519'` 参数，否则默认只返回2018~2024
- 覆盖所有中证/上证/科创指数，**不覆盖国证指数**（如创业板指399006）
- 返回字段含 `滚动市盈率`（PE_TTM）

### 已解决

- [x] 4个缺失资产（990001, 930713, 931719, 000819）→ CSI接口全部可拉 ✅
- [x] 煤炭5年缺口 → CSI/申万接口覆盖 ✅
- [x] 中证军工99天缺口 → CSI接口覆盖 ✅
- [x] 截止日期不统一 → 全部统一为2026-05-19 ✅

### 未解决

东财 `push2.eastmoney.com` 本机永久不通（非代理问题，是 ISP/路由封禁）

---

*最后更新: 2026-05-20*
