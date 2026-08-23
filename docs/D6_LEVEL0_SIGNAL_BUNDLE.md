# D.6 Level-0 Signal Bundle v1

D.6 Level-0 Signal Bundle v1 packages one or more fixed Level-0 signal backtest reports into one compact research artifact.

It is research-only. It does not call Coinbase, fetch data, emit live trading signals, optimize parameters, search parameters, rank signals, rank tickers, rank cost scenarios, change live settings or produce live recommendations.

## Components

- module: `bot/phase_d6_level0_signal_bundle.py`
- CLI: `tools/build_phase_d6_level0_signal_bundle.py`
- tests: `tests/test_phase_d6_level0_signal_bundle.py`

## Scope

- Input: one or more local normalized D.6 candle JSON files.
- Cost scenarios: one or more explicit scenarios from `D.6 Fee/Slippage Assumption Pack v1`.
- Signal: `fixed_sma_cross_5_20` only in v1.
- Fixed parameters only.
- One split configuration per bundle.
- Output: compact JSON by default, optional Markdown summary.

This bundle preserves existing report semantics by calling the Level-0 signal backtest scaffold rather than changing it.

## CLI

```bash
python3 tools/build_phase_d6_level0_signal_bundle.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --cost-scenario zero_cost_reference,conservative_slippage \
  --signal fixed_sma_cross_5_20 \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --json
```

Optional explicit report outputs:

```bash
python3 tools/build_phase_d6_level0_signal_bundle.py \
  --candles /tmp/d6/BTC-USDC-1D.json,/tmp/d6/ETH-USDC-1D.json \
  --cost-scenario standard_fee_only,conservative_slippage \
  --output reports/d6/level0/bundle.json \
  --markdown-output reports/d6/level0/bundle.md
```

Paths under `state/` and `.env` targets are refused.

## Report Shape

Summary fields include:

- `candle_file_count`
- `scenario_count`
- `report_count`
- `products`
- `timeframes`
- `scenario_names`
- `signal_names`
- `usable_report_count`
- `blocked_report_count`
- `warning_counts`
- `contains_rankings=false`
- `contains_recommendations=false`

Each compact row includes:

- `product_id`
- `timeframe`
- `candles_path`
- `cost_scenario`
- `signal_name`
- `split_count`
- `average_validation_net_return_pct`
- `average_test_net_return_pct`
- `worst_test_max_drawdown_pct`
- `total_trades_count`
- `usable_for_future_research`
- warning and blocker counts

## Non-Ranking Rule

The bundle is for evidence packaging only.

It must not:

- choose a best ticker;
- choose a best scenario;
- choose a best signal;
- rank parameters;
- propose parameter changes;
- authorize live execution.

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
- `live_recommendation=false`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`
- `fixed_parameters_only=true`
- `strategy_parameter_mutation_allowed=false`
- `runtime_config_mutation_allowed=false`
- `contains_rankings=false`
- `contains_recommendations=false`

## Limitations

- Compact bundle only.
- `fixed_sma_cross_5_20` only in v1.
- One split configuration per bundle.
- No signal, ticker, scenario or parameter ranking.
- No optimization or parameter search.
- No live signal emission.
- Not a live trading recommendation.

## Next Step

A future separate task should add overfitting/trial-accounting guardrails before any broader signal expansion or parameter review.
