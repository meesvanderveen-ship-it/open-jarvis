# D.6 Cost-Aware Baseline Bundle v1

D.6 Cost-Aware Baseline Bundle v1 packages multiple `D.6 Cost-Aware Split Baseline Report v1` outputs into one compact research artifact.

It is research-only. It does not call Coinbase, fetch data, generate signals, optimize parameters, rank tickers, rank cost scenarios, rank parameters, change live settings or produce live trading recommendations.

## Components

- module: `bot/phase_d6_cost_aware_baseline_bundle.py`
- CLI: `tools/build_phase_d6_cost_aware_baseline_bundle.py`
- tests: `tests/test_phase_d6_cost_aware_baseline_bundle.py`

## Scope

- Input: one or more local normalized D.6 candle JSON files.
- Cost scenarios: one or more explicit scenarios from `D.6 Fee/Slippage Assumption Pack v1`.
- Baseline: `buy_hold` only in v1.
- Split configuration: one split configuration per bundle in v1.
- Output: compact JSON by default, optional Markdown summary.

This bundle preserves existing report semantics by calling the cost-aware split baseline adapter rather than changing it.

## CLI

```bash
python3 tools/build_phase_d6_cost_aware_baseline_bundle.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --cost-scenario zero_cost_reference,standard_fee_only,conservative_slippage \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --json
```

Optional explicit report outputs:

```bash
python3 tools/build_phase_d6_cost_aware_baseline_bundle.py \
  --candles /tmp/d6/BTC-USDC-1D.json,/tmp/d6/ETH-USDC-1D.json \
  --cost-scenario standard_fee_only,conservative_slippage \
  --output reports/d6/cost-aware/bundle.json \
  --markdown-output reports/d6/cost-aware/bundle.md
```

Paths under `state/` and `.env` targets are refused.

## Report Shape

Top-level fields include:

- `phase`
- `generated_at`
- `candle_paths`
- `cost_scenarios`
- split configuration
- `summary`
- compact `reports`
- warnings, limitations and safety flags

Summary fields include:

- `candle_file_count`
- `scenario_count`
- `report_count`
- `products`
- `timeframes`
- `scenario_names`
- `usable_report_count`
- `blocked_report_count`
- `warning_counts`
- `contains_rankings=false`
- `contains_recommendations=false`

Each compact row includes:

- `product_id`
- `timeframe`
- `cost_scenario`
- `round_trip_cost_pct`
- `average_validation_net_return_pct`
- `average_test_net_return_pct`
- `worst_test_max_drawdown_pct`
- `usable_for_future_research`
- warning and blocker counts

## Non-Ranking Rule

The bundle is for side-by-side evidence packaging only.

It must not:

- label a best ticker;
- label a best scenario;
- sort scenarios by performance as a recommendation;
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

## Limitations

- Compact bundle only.
- `buy_hold` only in v1.
- One split configuration per bundle.
- No ticker ranking.
- No cost-scenario ranking.
- No Level-0 signal logic.
- No post-only queue, orderbook depth or partial-fill modeling.
- Not a parameter review or live trading recommendation.

## Next Step

A future separate task may implement a fixed Level-0 Signal Backtest Scaffold v1 using the same dataset quality, walk-forward, metrics and cost-assumption foundations. Do not use this bundle to change live parameters.
