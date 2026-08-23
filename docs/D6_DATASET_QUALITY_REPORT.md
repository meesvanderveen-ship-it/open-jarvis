# D.6 Dataset Quality Report v1

Timestamp: `2026-05-29T19:31:15Z`

## Purpose

D.6 Dataset Quality Report v1 is a local-candle-only quality layer for normalized D.6 candle JSON files. It checks whether a cached or fixture candle file is suitable for later baseline, signal, walk-forward and review-pack research.

It is research-only. It does not call Coinbase, fetch candles, run backtests, optimize parameters, write trading state, mutate config or touch live orders.

## Components

- module: `bot/phase_d6_dataset_quality.py`
- CLI: `tools/show_phase_d6_dataset_quality.py`
- tests: `tests/test_phase_d6_dataset_quality.py`

## Inputs

The report reads one local normalized D.6 candle JSON array, for example:

```text
research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json
```

Input and output paths under `state/` are refused. `.env` targets are refused.

## Report Fields

The report includes:

- `product_id`
- `timeframe`
- `raw_row_count`
- `candle_count`
- `valid_candle_row_count`
- `first_candle_start`
- `last_candle_start`
- `observed_span_seconds`
- `observed_span_days`
- `timeframe_seconds`
- `expected_candle_count`
- `missing_candle_estimate`
- `gap_count`
- `duplicate_count`
- `non_monotonic_count`
- `invalid_ohlcv_count`
- `invalid_reasons`
- `quality_class`
- `warnings`
- `fatal_errors`

Quality classes:

- `good`: no quality warnings.
- `usable_with_warnings`: usable for scaffold research, but warnings must be carried forward.
- `poor`: severe missing coverage, mixed identity or unsupported timeframe.
- `invalid`: no usable candle set or fatal file-level error.

## CLI

Stdout JSON:

```bash
python3 tools/show_phase_d6_dataset_quality.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --json
```

Explicit report output:

```bash
python3 tools/show_phase_d6_dataset_quality.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --as-of 2026-05-29T00:00:00Z \
  --output reports/d6/quality/btc-usdc-1d-3y-quality.json
```

`--as-of` is optional and only controls stale-candle warnings.

## Safety Flags

Every report includes:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Limitations

This report validates candle-file quality only. It does not:

- fetch missing data;
- repair gaps;
- run a backtest;
- model post-only fills;
- estimate slippage;
- select parameters;
- produce live trading recommendations.

## Next Step

Use quality reports as the gate before larger baseline bundles, Level-0 signal scaffolds or walk-forward splits. A later D.6 task can aggregate quality reports across multiple ticker/timeframe files.
