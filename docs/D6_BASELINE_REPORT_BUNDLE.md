# D.6 Baseline Report Bundle v1

Timestamp: `2026-05-29T20:05:00Z`

## Purpose

D.6 Baseline Report Bundle v1 creates compact JSON and Markdown summaries from one or more local D.6 candle files using the existing baseline backtest scaffold.

It is research-only. It does not fetch data, call Coinbase, optimize parameters, write trading state, mutate config or touch live orders.

## Components

- module: `bot/phase_d6_baseline_report_bundle.py`
- CLI: `tools/build_phase_d6_baseline_report_bundle.py`
- tests: `tests/test_phase_d6_baseline_report_bundle.py`

## Inputs

The bundle accepts local normalized D.6 candle JSON files, for example:

```text
research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json
```

Input paths under `state/` are refused through the shared D.6 research path guard.

## Baselines

Default baselines:

- `buy_hold`
- `simple_ma`

The bundle does not add a new strategy. It runs existing fixed scaffold baselines from `D.6 Baseline Backtest Scaffold v1` and aggregates compact results.

## CLI

Stdout JSON:

```bash
python3 tools/build_phase_d6_baseline_report_bundle.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --json
```

Explicit JSON and Markdown output:

```bash
python3 tools/build_phase_d6_baseline_report_bundle.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --baseline buy_hold,simple_ma \
  --output reports/d6/baseline/btc-usdc-1d-baseline-bundle.json \
  --markdown-output reports/d6/baseline/btc-usdc-1d-baseline-bundle.md \
  --json
```

Output paths under `state/` and `.env` targets are refused.

## Report Contents

Top-level summary:

- candle file count
- baseline count
- report count
- tickers
- timeframes
- baseline types
- min/max/average net return
- worst max drawdown
- best/worst compact result

Per-run compact rows:

- ticker
- timeframe
- baseline type
- candle count
- first/last candle
- gap count
- net return
- max drawdown
- trades/round trips
- exposure
- fee assumption
- warnings

Safety flags:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `parameter_search_performed=false`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Limitations

The bundle is a reporting layer only:

- no parameter search
- no optimization
- no walk-forward validation
- no portfolio simulation
- no post-only fill model
- no new Coinbase data fetch

Use it to package baseline scaffold outputs before a later Level-0 signal backtest or richer validation task.

## Next Step

The next safe D.6 step is either:

- produce a small checked-in/report-path baseline bundle from cached candles, or
- implement `D.6 Level-0 Signal Backtest Scaffold v1` using fixture/cached candles only.

Do not proceed to full multi-ticker backtesting, optimization or parameter review without a separate prompt.
