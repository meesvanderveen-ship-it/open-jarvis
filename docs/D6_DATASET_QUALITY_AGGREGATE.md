# D.6 Dataset Quality Aggregation v1

Timestamp: `2026-05-29T19:36:55Z`

## Purpose

D.6 Dataset Quality Aggregation v1 combines multiple local D.6 candle quality reports into one research-only gate before larger baseline bundles, walk-forward splits or fixed signal scaffolds.

It reads local cached or fixture candle JSON files only. It does not call Coinbase, fetch data, run backtests, optimize parameters, write trading state, mutate config or touch live orders.

## Components

- module: `bot/phase_d6_dataset_quality_aggregate.py`
- CLI: `tools/show_phase_d6_dataset_quality_aggregate.py`
- tests: `tests/test_phase_d6_dataset_quality_aggregate.py`

## Inputs

The aggregate accepts comma-separated or repeated local normalized D.6 candle JSON paths:

```bash
python3 tools/show_phase_d6_dataset_quality_aggregate.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --json
```

Multiple files:

```bash
python3 tools/show_phase_d6_dataset_quality_aggregate.py \
  --candles /tmp/d6/BTC-USDC-1D.json,/tmp/d6/ETH-USDC-1D.json \
  --output reports/d6/quality/dataset-quality-aggregate.json \
  --markdown-output reports/d6/quality/dataset-quality-aggregate.md
```

Input/output paths under `state/` and `.env` targets are refused.

## Report Shape

Top-level fields:

- `generated_at`
- `phase`
- `status`
- `as_of`
- `candle_paths`
- `summary`
- `reports`
- `warnings`
- safety flags

Summary fields:

- `file_count`
- `quality_counts`
- `aggregate_quality_class`
- `tickers`
- `timeframes`
- `total_missing_candle_estimate`
- `total_gap_count`
- `total_duplicate_count`
- `total_invalid_ohlcv_count`
- `warning_counts`
- `fatal_error_counts`
- `blockers`
- `ready_for_baseline_bundle`
- `ready_for_walk_forward_scaffold`

Per-file rows include compact quality fields from `D.6 Dataset Quality Report v1`, including product/timeframe, candle counts, expected/missing count, gaps, duplicates, invalid OHLCV count, warnings and fatal errors.

## Quality Gate

The aggregate class is:

- `good` when all files are good;
- `usable_with_warnings` when at least one file has warnings but none are poor/invalid;
- `poor` when any file is poor;
- `invalid` when any file is invalid.

`ready_for_baseline_bundle=false` when any file is poor or invalid.

`ready_for_walk_forward_scaffold=false` when any file is poor or invalid.

These fields are research gates only. They are not live trading recommendations.

## Safety Flags

Every aggregate includes:

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

This aggregate does not:

- fetch or repair missing data;
- run a backtest;
- compare strategy returns;
- perform walk-forward validation;
- select parameters;
- approve any parameter change.

It exists to decide whether local candle files are clean enough to feed later research-only components.

## Next Step

The next safe D.6 implementation task is `D.6 Walk-Forward Split Scaffold v1` or `D.6 Metrics Foundation v1`. Do not proceed to optimization, parameter search, new Coinbase fetching or live trading from this aggregation task.
