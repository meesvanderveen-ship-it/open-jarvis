# D.6 Metrics Foundation v1

Timestamp: `2026-05-29T19:53:29Z`

## Purpose

D.6 Metrics Foundation v1 provides small, deterministic, reusable research metrics for future D.6 reports.

It is research-only. It does not load live state, call Coinbase, fetch data, generate signals, run optimization, rank parameters, write trading state, mutate config or touch live orders.

## Component

- module: `bot/phase_d6_metrics.py`
- tests: `tests/test_phase_d6_metrics.py`

No CLI is included in v1. The module is intended for reuse by later D.6 reports.

## Helpers

Core helpers:

- `to_decimal`
- `decimal_str`
- `ratio`
- `net_return`
- `max_drawdown`
- `exposure_ratio`

Metric builders:

- `build_return_metrics`
- `build_drawdown_metrics`
- `build_exposure_metrics`
- `build_trade_metrics`
- `build_fee_metrics`
- `build_metric_warnings`
- `build_phase_d6_metrics_report`

Safety helper:

- `d6_metric_safety_flags`

## Report Shape

`build_phase_d6_metrics_report` returns:

- `generated_at`
- `phase`
- `status`
- `metric_inputs_summary`
- `return_metrics`
- `drawdown_metrics`
- `exposure_metrics`
- `trade_metrics`
- `fee_metrics`
- `warnings`
- safety flags

Warnings may include:

- `too_few_trades`
- `high_drawdown`
- `zero_exposure`
- `data_quality_blocked`
- `split_unusable`

## Safety Flags

Reports include:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `parameter_search_performed=false`
- `signal_generation_performed=false`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Compatibility

This v1 does not refactor existing D.6 baseline reports. That keeps existing report semantics stable while making the metrics available for later split-aware reports.

A future compatibility task may migrate baseline internals to these helpers only if existing tests prove identical output semantics.

## Limitations

This module does not:

- run backtests;
- generate strategy signals;
- calculate split-aware performance by itself;
- model fees beyond summary arithmetic;
- model slippage or fills;
- implement overfitting statistics;
- produce parameter recommendations.

## Next Step

The next safe D.6 task is a split-aware baseline or report adapter that uses the walk-forward split scaffold and this metrics foundation without optimization or parameter search.
