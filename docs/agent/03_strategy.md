# 03_strategy.md — Strategy Boundary

> This repo is not yet building the final AI-DMS strategy layer.

Current scope:

- factor research
- multi-factor scoring
- Layer 3 structure evidence
- rolling validation
- signal output prototypes

Not current scope:

- final portfolio construction
- execution engine
- macro/NLP/capex expectation layer
- final AI explanation layer

When discussing "strategy" in this repo, treat it as:

```text
factor combination -> ranked signal -> rolling validation
```

Default benchmark:

```text
index.000985.SH
```

Default evaluation should report:

- total return
- excess return
- window win rate
- max drawdown
- phase-level performance
