# Data Runtime Spec v1

> Purpose: define how data providers, database writes, second-pass
> calculations, and lower-cost execution agents should work for factor-lab.

## Core Principle

External data tools are provider adapters, not the research core.

`factor-lab` owns:

- symbol conventions
- database contracts
- price-adjustment policy
- stock-to-sector mapping policy
- second-pass aggregation formulas
- validation reports
- experiment workflow

Provider tools such as TickFlow, akshare, mootdx, or `a-stock-data` only answer
"how to fetch data". They do not define what the data means inside this repo.

## Provider Priority

Use the first provider that satisfies the required fields and passes sample
validation:

| Priority | Provider | Role |
|----------|----------|------|
| 1 | local `quant_engine.db` | authoritative source for research and backtests |
| 2 | `a-stock-data` adapter | short-term external fetch helper / interface reference |
| 3 | current TickFlow collector | existing local full-A collection path |
| 4 | direct akshare / mootdx / baostock fallback | fallback when adapter coverage is insufficient |

`a-stock-data` may be used short term because it already integrates several A
share data interfaces. Treat it as an adapter candidate and validate every field
before writing to this repo's database.

## Required Normalization

All providers must normalize into the same internal contract before write:

| Field | Required Meaning |
|-------|------------------|
| `symbol` | canonical format such as `stock.000001.SZ` |
| `trade_date` | `YYYY-MM-DD` trading date |
| `open/high/low/close` | raw unadjusted OHLC |
| `volume` | raw shares/lots unit confirmed in source report |
| `amount` | raw traded amount in CNY |
| `pct_chg_raw` | raw unadjusted close-to-close return, percent |
| `close_hfq` | back-adjusted close |
| `hfq_factor` | `close_hfq / close` |

If a provider returns different symbols or units, normalize before staging.
Never write source-native symbols directly into `market_daily_data`.

## Stock-To-Sector Mapping

For the first version, store the primary Shenwan sector on stock assets:

```text
asset_master.stable_industry = sector symbol, e.g. sector.801080.SW
```

Use `asset_master` sector rows to resolve the Chinese sector name.

This is a current-constituent mapping unless a future experiment explicitly
requires point-in-time historical membership. If point-in-time membership becomes
necessary, add a separate mapping artifact or table after a specific design
review.

## SQL / Storage Policy

Keep the semi-wide database design.

Use `market_daily_data` for daily market, sector, and stock fields:

- raw OHLCV and amount
- adjusted close and adjustment factor
- stock emotion flags
- market emotion aggregates on `index.000985.SH`
- sector breadth and amount aggregates on `sector.*.SW`
- registered Layer 2 factors

Use `asset_master` for static identity and current primary sector mapping.

Avoid adding new tables for v1 unless the data shape cannot fit the existing
contract. Generated CSV/JSON audit artifacts are acceptable for validation
reports, but formal backtests should read persisted database fields once formulas
are confirmed.

## Second-Pass Calculations

These calculations should be deterministic and idempotent.

### Stock-Level Recompute

Input: raw stock `close`, `close_hfq`, `hfq_factor`.

Output on stock rows:

- `pct_chg_raw`
- `limit_up_flag`
- `limit_down_flag`

Limit-up/down v1 may use approximate thresholds:

- normal stocks: `>= 9.8%` / `<= -9.8%`
- ST stocks: `>= 4.8%` / `<= -4.8%` if ST can be identified from name
- STAR / ChiNext 20% rules can be added later after board/date rules are
  explicitly designed

Document this approximation in every experiment that uses it.

### Market Emotion Aggregation

Input: all stock rows by trade date.

Output on `index.000985.SH` rows:

- `adv_count`
- `decl_count`
- `market_adv_ratio = adv_count / (adv_count + decl_count)`
- `limit_up_count`
- `limit_down_count`

### Sector Breadth Aggregation

Input: stock rows plus `asset_master.stable_industry`.

Output on `sector.*.SW` rows:

- sector advance ratio
- `above_ma20_ratio`
- `above_ma60_ratio`
- `new_high_20d_ratio`
- `rs_positive_ratio` only if a later design confirms benchmark-relative stock
  strength is needed
- sector limit-up count / ratio
- sector limit-down count / ratio

### Amount Strength Aggregation

Input: stock, sector, and index amount fields.

Preferred v1 fields:

- market amount ratio: market amount / 20-day market amount average
- sector amount ratio: sector amount / 20-day sector amount average
- sector amount share: sector amount / sum(all sector amount)
- sector amount share change: current share - 20-day average share
- sector amount rank percentile across 30 sectors

If existing columns are insufficient, propose explicit new columns before
implementation.

## Execution SOP

Every data task should follow this order:

```text
scope -> provider check -> sample fetch -> normalize -> validate -> stage/report -> approved write -> coverage report -> memory/archive update
```

Rules:

- Run a small sample before full writes.
- Scripts must be idempotent: rerunning the same date range should not duplicate
  or corrupt rows.
- Use `INSERT OR REPLACE` or deterministic `UPDATE` by `(symbol, trade_date)`.
- Write progress and failure reports outside tracked source unless the report is
  a curated research note.
- After writes, produce coverage by field, asset type, date range, and symbol
  count.

## Flash-Agent Execution Contract

Lower-cost execution agents may run collection or recomputation tasks after the
runtime spec is decided.

They must not change schema, factor formulas, or experiment conclusions.

Required output from every execution task:

- command run
- date range
- provider used
- number of symbols attempted / succeeded / failed
- rows inserted or updated
- field coverage before and after
- failure file path
- whether any approximation was used

Any unexpected provider behavior should be written to `docs/archive/` as a data
source note, then summarized in `docs/research/MEMORY.md`.

## Acceptance Gate Before Backtests

Formal market-state and main-line sector backtests can start only after:

- stock-to-sector mapping covers the target sector universe
- stock `pct_chg_raw` and limit flags are populated for the target date range
- market emotion fields are populated on `index.000985.SH`
- sector breadth fields cover all target sectors
- amount-strength fields are either populated or explicitly excluded
- a data coverage report is linked from `docs/research/MEMORY.md`

