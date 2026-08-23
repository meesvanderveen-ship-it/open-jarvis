# D.6 Baseline Backtest Scaffold v1

Timestamp: `2026-05-29T19:45:00Z`

## Purpose

D.6 Baseline Backtest Scaffold v1 is the first research-only backtest layer. It loads normalized D.6 cached or fixture candle JSON files and produces a deterministic report-only baseline result.

It does not call Coinbase, fetch data, optimize parameters, write trading state, mutate live config or touch active orders.

## Components

- module: `bot/phase_d6_baseline_backtest.py`
- CLI: `tools/run_phase_d6_baseline_backtest.py`
- tests: `tests/test_phase_d6_baseline_backtest.py`

## Candle Loader

The loader reads normalized D.6 candle JSON arrays and validates:

- `product_id`
- `timeframe`
- `start`
- `open`
- `high`
- `low`
- `close`
- `volume`

It sorts and deduplicates by `start`, rejects mixed product/timeframe files, detects basic timeframe gaps and refuses paths under `state/`.

## Baselines

`buy_hold`:

- buys at first candle close
- sells at last candle close
- applies fee assumption at entry and exit
- reports one scaffold round trip

`simple_ma`:

- fixed 5/20 moving-average scaffold
- buys when fast MA is above slow MA
- exits when fast MA drops below slow MA
- closes any residual position at final candle
- fixed parameters only; no optimization

Both baselines are intentionally simple and should be treated as scaffolds, not production strategy evidence.

## CLI

Stdout-only:

```bash
python3 tools/run_phase_d6_baseline_backtest.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --baseline buy_hold \
  --initial-quote 1000 \
  --fee-pct 0.0040 \
  --json
```

Explicit report output:

```bash
python3 tools/run_phase_d6_baseline_backtest.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --baseline simple_ma \
  --output reports/d6/baseline/btc-usdc-1d-simple-ma.json
```

Output paths under `state/` are refused.

## Report Fields

Reports include:

- ticker
- timeframe
- candle count
- first/last candle start
- gap count
- baseline type
- initial/final quote
- net return
- max drawdown
- trades count
- exposure/time-in-market
- fees assumption
- warnings/limitations

Safety flags:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Limitations

V1 does not model:

- post-only queue/fill probability
- intrabar execution
- slippage beyond the fee assumption
- partial fills
- cancel/replace behavior
- multi-ticker portfolio allocation
- walk-forward validation
- parameter search

The correct use is smoke-testing the cached candle pipeline and establishing baseline report shape before richer D.6 backtests.

## Next Step

The next safe D.6 task is a fixture/cached-candle baseline report bundle or Level-0 signal backtest scaffold. Do not proceed to parameter search or optimization until baseline reports, fill assumptions and walk-forward validation are explicitly implemented and reviewed.
