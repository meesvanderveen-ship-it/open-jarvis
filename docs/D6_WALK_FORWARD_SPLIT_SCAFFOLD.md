# D.6 Walk-Forward Split Scaffold v1

Timestamp: `2026-05-29T19:43:20Z`

## Purpose

D.6 Walk-Forward Split Scaffold v1 creates deterministic chronological train/validation/test split reports from local normalized D.6 candle JSON files.

It is research-only. It does not fetch data, call Coinbase, run a strategy, optimize parameters, select parameters, write trading state, mutate config or touch live orders.

## Components

- module: `bot/phase_d6_walk_forward_splits.py`
- CLI: `tools/show_phase_d6_walk_forward_splits.py`
- tests: `tests/test_phase_d6_walk_forward_splits.py`

## Inputs

One local normalized D.6 candle JSON file:

```text
research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json
```

Input and output paths under `state/` are refused. `.env` targets are refused.

## Split Modes

Supported modes:

- `holdout`: one train/validation/test split.
- `rolling`: fixed-size train/validation/test windows that move forward by `step_count`.
- `expanding`: training starts at the first candle and expands by `step_count`; validation/test windows move forward.

All counts are candle counts. Defaults are scaffold defaults:

- `train_count=210`
- `validation_count=70`
- `test_count=70`
- `step_count=70`
- `max_splits=12`

These are not strategy parameters and do not mutate live configuration.

## CLI

Stdout JSON:

```bash
python3 tools/show_phase_d6_walk_forward_splits.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --split-mode holdout \
  --json
```

Explicit report output:

```bash
python3 tools/show_phase_d6_walk_forward_splits.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --split-mode rolling \
  --train-count 180 \
  --validation-count 60 \
  --test-count 60 \
  --step-count 60 \
  --output reports/d6/walk_forward/btc-usdc-1d-rolling-splits.json
```

## Report Fields

Top-level fields include:

- `product_id`
- `timeframe`
- `candle_count`
- `first_candle_start`
- `last_candle_start`
- `gap_count`
- `split_mode`
- `train_count`
- `validation_count`
- `test_count`
- `step_count`
- `max_splits`
- `split_count`
- `splits`
- `split_coverage`
- `dataset_quality`
- `usable_for_future_research`
- `warnings`
- `blockers`
- safety flags

Each split contains:

- `split_index`
- `train`
- `validation`
- `test`

Each range includes start/end indices, candle count and first/last candle timestamps.

## Dataset Quality Gate

The scaffold calls `D.6 Dataset Quality Aggregation v1` for the input file and blocks when the aggregate is not ready for walk-forward research.

This gate is research-only. It is not a live trading recommendation and does not authorize any strategy or parameter change.

## Safety Flags

Every report includes:

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

This scaffold does not:

- run a backtest;
- generate signals;
- score strategy performance;
- optimize anything;
- select or rank parameters;
- model fees, slippage or fills;
- emit D.5 learning events.

It only defines chronological split windows for later research-only tasks.

## Next Step

The next safe D.6 task is either:

- `D.6 Metrics Foundation v1`, to standardize reusable return/drawdown/exposure/trade metrics; or
- a future fixed-parameter Level-0 signal scaffold that consumes these splits without optimization.

Do not proceed to optimization, parameter search, new Coinbase fetching or live trading from this scaffold.
