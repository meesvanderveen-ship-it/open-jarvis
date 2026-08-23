# D.6 Fixed Level-0 Signal Backtest Scaffold v1

D.6 Fixed Level-0 Signal Backtest Scaffold v1 is the first research-only signal layer for local normalized D.6 candle files.

It does not call Coinbase, fetch market data, emit live trading signals, optimize parameters, search parameters, rank parameters, mutate runtime config, change live settings or produce live recommendations.

## Components

- module: `bot/phase_d6_level0_signal_backtest.py`
- CLI: `tools/show_phase_d6_level0_signal_backtest.py`
- tests: `tests/test_phase_d6_level0_signal_backtest.py`

## Fixed Signal

V1 supports one signal:

- `fixed_sma_cross_5_20`

Fixed parameters:

- `fast_window=5`
- `slow_window=20`
- `position_fraction=1.0`
- entry: fast SMA crosses above slow SMA on candle close
- exit: fast SMA crosses below slow SMA on candle close
- forced exit: any open research position is closed at range end

These constants are scaffold parameters only. They are not live strategy parameters and must not be tuned in this task.

## Backtest Model

The range-level simulation is a deterministic candle-close state machine:

1. Starts flat with `initial_quote`.
2. Enters an all-in research position on a bullish SMA cross.
3. Exits on a bearish SMA cross.
4. Applies one explicit D.6 cost scenario to entry and exit.
5. Forces an exit at range end if still in a research position.

This is not a fill model. It does not model intrabar movement, post-only queue position, orderbook depth, partial fills or live order lifecycle behavior.

## CLI

```bash
python3 tools/show_phase_d6_level0_signal_backtest.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --signal fixed_sma_cross_5_20 \
  --cost-scenario conservative_slippage \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --json
```

Use `--output reports/d6/<name>.json` only when a persisted research report is intentionally needed. Paths under `state/` and `.env` paths are refused.

## Report Shape

Top-level fields include:

- `phase`
- `generated_at`
- `product_id`
- `timeframe`
- `signal_name`
- `signal_version`
- `fixed_parameters`
- `cost_scenario`
- `cost_assumptions`
- split configuration
- dataset quality summary
- per-split train/validation/test metrics
- cost-aware buy-hold `baseline_reference`
- warnings, blockers and limitations
- safety flags

Per-range metrics include:

- return metrics
- drawdown metrics
- exposure metrics
- trade metrics
- cost metrics
- warnings

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

`signal_generation_performed=false` means no live or executable trading signal was emitted. The report contains research-only scaffold observations.

## Limitations

- One fixed signal only in v1.
- No CLI parameters for SMA windows.
- No optimization or parameter search.
- No parameter, ticker or scenario ranking.
- No live recommendation.
- No intrabar fill realism.
- No post-only queue or partial-fill model.

## Next Step

A future separate task may package Level-0 reports into a research bundle or add overfitting/trial-accounting guardrails. Do not use this scaffold to change live parameters.
